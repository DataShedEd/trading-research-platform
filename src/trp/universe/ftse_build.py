"""Build the FTSE 100 dataset: curated membership + EODHD reference data + backfill.

``uv run python -m trp.universe.ftse_build <step>`` where step is one of:

- ``master`` — construct security-master entries for every company the curated history
  references (rename chains collapse to one security with effective-dated tickers; ISINs
  attached from EODHD's LSE listed/delisted lists where the checksum validates) and write
  them to ``data/canonical/securities/``.
- ``membership`` — resolve the curated ticker spells to security ids, write the FTSE100
  membership through the QNT-037 store, and demonstrate ``members("FTSE100", 2012-08-15)``.
- ``backfill`` — fetch prices, splits and dividends for every member security from EODHD
  (raw-first, resumable: securities with archived payloads are skipped), canonicalise via
  QNT-091 transforms into the price store and a corporate-actions Parquet.
- ``report`` — coverage summary per security (bars, span, actions, rejects).

Documented approximations (deliberate, revisit with better data):
- Ticker identifier validity is bounded by membership spells — resolution is guaranteed
  inside membership windows only, which is what universe queries need.
- Listings are recorded open-ended with ``valid_from`` at first observed membership;
  true listing/delisting dates await lifecycle enrichment from price-history ends.
- Two disjoint spells sharing a ticker merge into one security only when the company
  name matches after normalisation; otherwise they are separate securities (ticker reuse)
  and are flagged in the build log.
"""

import argparse
import json
import sys
import time
from collections import defaultdict
from datetime import UTC, date, datetime
from difflib import SequenceMatcher
from pathlib import Path

import polars as pl

from trp.canonical.ingest_eodhd import bars_from_eodhd, dividends_from_eodhd, splits_from_eodhd
from trp.canonical.price_store import write_prices
from trp.canonical.security_store import read_security_master, write_security_master
from trp.config import Settings, load_settings
from trp.domain.corporate_actions import Dividend, Split
from trp.domain.identifier_map import IdentifierRecord
from trp.domain.identifier_validation import validate_isin
from trp.domain.identifiers import IdentifierKind, SecurityId, new_entity_id, new_security_id
from trp.domain.master import SecurityMaster
from trp.domain.prices import DailyBar
from trp.domain.security import Entity, Listing, Security, SecurityType
from trp.ingestion.raw import RawStore
from trp.providers.adapters.eodhd import EodhdProvider
from trp.providers.base import Dataset
from trp.universe.membership import UniverseMembership
from trp.universe.query import UniverseQuery
from trp.universe.sourcing import TickerSpell, replay_index_history
from trp.universe.storage import write_universe

HISTORY_PATH = Path(__file__).parent / "data" / "ftse100_history.json"

# Codes adjudicated by hand as recycled by an unrelated company, where fuzzy name
# matching cannot tell (Home Retail Group vs Home REIT scores 0.89). Add here with a
# note, never by weakening the matcher.
_ADJUDICATED_RECYCLED = {
    "HOME",  # curated member: Home Retail Group (FTSE 100 to 2011); current holder: Home REIT
}
_HISTORY_START = date(1990, 1, 1)


def _normalise_name(name: str) -> str:
    text = name.lower()
    for noise in (" plc", " group", " holdings", " limited", " ltd", ".", ","):
        text = text.replace(noise, "")
    return " ".join(text.split())


def _eodhd_code(ticker: str) -> str:
    return ticker.rstrip(".").replace(".", "-")


def _rename_chains(history: dict[str, object]) -> dict[str, str]:
    """ticker -> chain root, via union of the curated ``renamed`` entries."""
    parent: dict[str, str] = {}

    def find(t: str) -> str:
        parent.setdefault(t, t)
        while parent[t] != t:
            parent[t] = parent[parent[t]]
            t = parent[t]
        return t

    changes: list[dict[str, object]] = history["changes"]  # type: ignore[assignment]
    for change in changes:
        renames: list[dict[str, str]] = change.get("renamed", [])  # type: ignore[assignment]
        for rename in renames:
            a, b = find(rename["from_ticker"].strip()), find(rename["to_ticker"].strip())
            if a != b:
                parent[b] = a
    return {t: find(t) for t in parent}


def load_reference_lists(store: RawStore) -> tuple[dict[str, dict[str, str]], set[str]]:
    """EODHD LSE rows keyed by code, and the set of codes that are delisted."""
    by_code: dict[str, dict[str, str]] = {}
    delisted_codes: set[str] = set()
    for dataset in (Dataset.SECURITIES, Dataset.DELISTED_SECURITIES):
        for meta in store.records(provider="eodhd", dataset=dataset):
            record, content = store.read(meta)
            if content is None or "/exchange-symbol-list/LSE" not in record.endpoint:
                continue
            for row in json.loads(content):
                code = (row.get("Code") or "").strip()
                if code and code not in by_code:
                    by_code[code] = {k: str(v) for k, v in row.items() if v is not None}
                if code and dataset is Dataset.DELISTED_SECURITIES:
                    delisted_codes.add(code)
    return by_code, delisted_codes


def build_master(
    spells: list[TickerSpell],
    history: dict[str, object],
    reference: dict[str, dict[str, str]],
    delisted_codes: set[str],
) -> tuple[SecurityMaster, dict[str, SecurityId], list[str]]:
    """One security per company; returns (master, ticker->security_id, build log)."""
    chains = _rename_chains(history)
    log: list[str] = []

    by_root: dict[str, list[TickerSpell]] = defaultdict(list)
    for spell in spells:
        by_root[chains.get(spell.ticker, spell.ticker)].append(spell)

    # Partition each rename chain into securities. A ticker change at a contiguous
    # boundary is a rename (chain evidence: same company). Within one ticker, a GAP
    # followed by a token-disjoint name is suspected reuse by an unrelated company and
    # starts a new security; contiguity or any shared name token keeps the company.
    grouped: dict[tuple[str, int], list[TickerSpell]] = {}
    for root, root_spells in by_root.items():
        root_spells.sort(key=lambda s: s.valid_from)
        part = 0
        current: list[TickerSpell] = []
        for spell in root_spells:
            if current:
                prev = current[-1]
                contiguous = prev.valid_to == spell.valid_from
                same_ticker = prev.ticker == spell.ticker
                tokens_prev = set(_normalise_name(prev.name).split())
                tokens_next = set(_normalise_name(spell.name).split())
                similar = (
                    SequenceMatcher(
                        None,
                        "".join(sorted(tokens_prev)),
                        "".join(sorted(tokens_next)),
                    ).ratio()
                    >= 0.75
                )  # abrdn/aberdeen are one company; token sets miss it
                if (
                    same_ticker
                    and not contiguous
                    and not (tokens_prev & tokens_next)
                    and not similar
                ):
                    log.append(
                        f"ticker {spell.ticker!r}: gap + unrelated names "
                        f"({prev.name!r} -> {spell.name!r}) — treated as reuse, split"
                    )
                    grouped[(root, part)] = current
                    part += 1
                    current = []
            current.append(spell)
        grouped[(root, part)] = current

    # Per-partition metadata: the EODHD code its latest ticker maps to. A code's
    # reference row (name, ISIN) belongs only to the code's LATEST holder among the
    # partitions; earlier holders of a reused code get no EODHD identifiers.
    part_keys = sorted(grouped)
    part_latest = {key: max(s.valid_from for s in grouped[key]) for key in part_keys}
    part_code = {
        key: _eodhd_code(max(grouped[key], key=lambda s: s.valid_from).ticker) for key in part_keys
    }
    holder_of_code: dict[str, tuple[str, int]] = {}
    for key in part_keys:
        code = part_code[key]
        if code not in holder_of_code or part_latest[key] > part_latest[holder_of_code[code]]:
            holder_of_code[code] = key

    # Merge partitions whose reference ISINs are equal: an ISIN survives renames that
    # happen OUTSIDE the index (Sports Direct->Frasers, Alliance Trust->Alliance Witan),
    # which the curated in-index rename chains cannot see.
    def _names_compatible(key: tuple[str, int]) -> bool:
        """Is EODHD's reference row for this partition's code describing OUR company?

        Three cases (the Home REIT / Aston Martin lesson vs the GSK / SSE lesson):
        - the partition's last spell is OPEN — a current member owns its ticker: trust;
        - the code is in the DELISTED list — dead data lines are not recycled: trust
          (this also covers our member renamed-then-delisted, e.g. SPD -> Frasers);
        - closed spell but the code is still LISTED — either our member relegated and
          still trading (Renishaw) or an unrelated company recycled the code (Aston
          Martin on Amlin's AML, Gusbourne on GUS): decide by fuzzy name similarity.
        """
        code = part_code[key]
        if code not in reference:
            return False
        if code in _ADJUDICATED_RECYCLED:
            return False
        if any(s.valid_to is None for s in grouped[key]):
            return True
        if code in delisted_codes:
            return True
        row_name = reference[code].get("Name")
        if not row_name:
            return False

        def squash(name: str) -> str:
            text = "".join(_normalise_name(name).split())
            for noise in ("group", "holdings", "international"):
                text = text.replace(noise, "")
            return text

        squash_row = squash(row_name)
        ratios = [SequenceMatcher(None, squash_row, squash(s.name)).ratio() for s in grouped[key]]
        return max(ratios) >= 0.75

    def part_isin(key: tuple[str, int]) -> str | None:
        if holder_of_code.get(part_code[key]) != key:
            return None
        if not _names_compatible(key):
            return None
        isin = reference.get(part_code[key], {}).get("Isin")
        if not isin:
            return None
        try:
            validate_isin(isin)
        except ValueError as exc:
            log.append(f"{part_code[key]}: EODHD ISIN rejected ({exc})")
            return None
        return isin

    merge_parent: dict[tuple[str, int], tuple[str, int]] = {k: k for k in part_keys}

    def find_merge(k: tuple[str, int]) -> tuple[str, int]:
        while merge_parent[k] != k:
            merge_parent[k] = merge_parent[merge_parent[k]]
            k = merge_parent[k]
        return k

    isin_owner: dict[str, tuple[str, int]] = {}
    for key in part_keys:
        isin = part_isin(key)
        if isin is None:
            continue
        if isin in isin_owner:
            a, b = find_merge(isin_owner[isin]), find_merge(key)
            if a != b:
                merge_parent[b] = a
                log.append(
                    f"merged {part_code[key]} with {part_code[isin_owner[isin]]} — "
                    f"same ISIN {isin} (rename outside the index)"
                )
        else:
            isin_owner[isin] = key

    merged: dict[tuple[str, int], list[tuple[str, int]]] = defaultdict(list)
    for key in part_keys:
        merged[find_merge(key)].append(key)

    entities, securities, listings, identifiers = [], [], [], []
    ticker_to_security: dict[str, SecurityId] = {}
    for _rep, member_keys in sorted(merged.items()):
        parts = sorted(member_keys, key=lambda k: part_latest[k])
        all_spells = sorted((s for k in parts for s in grouped[k]), key=lambda s: s.valid_from)
        entity_id, security_id = new_entity_id(), new_security_id()
        newest_part = parts[-1]
        newest_code = part_code[newest_part]
        is_holder = holder_of_code.get(newest_code) == newest_part and _names_compatible(
            newest_part
        )
        row = reference.get(newest_code, {}) if is_holder else {}
        display_name = row.get("Name") or all_spells[-1].name

        entities.append(Entity(entity_id=entity_id, name=display_name, country="GB"))
        securities.append(
            Security(
                security_id=security_id,
                entity_id=entity_id,
                security_type=SecurityType.ORDINARY,
                name=f"{display_name} ordinary",
            )
        )
        listings.append(
            Listing(
                security_id=security_id,
                mic="XLON",
                currency="GBX",
                valid_from=all_spells[0].valid_from,
            )
        )
        for spell in all_spells:
            ticker_to_security[spell.ticker] = security_id
            identifiers.append(
                IdentifierRecord(
                    security_id=security_id,
                    kind=IdentifierKind.TICKER,
                    value=spell.ticker,
                    mic="XLON",
                    valid_from=spell.valid_from,
                    valid_to=spell.valid_to,
                    source=f"qnt-039 curated spell; {spell.source[:120]}",
                )
            )
        attached_any_code = False
        for key in parts:
            code = part_code[key]
            if holder_of_code.get(code) != key or code not in reference:
                continue
            if not _names_compatible(key):
                log.append(
                    f"{code}: EODHD row name {reference[code].get('Name')!r} does not "
                    f"match curated member {grouped[key][-1].name!r} — recycled code, "
                    "NOT attached"
                )
                continue
            attached_any_code = True
            group = grouped[key]
            ends = [s.valid_to for s in group]
            identifiers.append(
                IdentifierRecord(
                    security_id=security_id,
                    kind=IdentifierKind.PROVIDER,
                    value=f"{code}.LSE",
                    provider="eodhd",
                    valid_from=min(s.valid_from for s in group),
                    valid_to=None if any(e is None for e in ends) else max(e for e in ends if e),
                    source="eodhd LSE symbol list",
                )
            )
        isin = part_isin(parts[-1]) or next((i for k in parts if (i := part_isin(k))), None)
        if isin:
            identifiers.append(
                IdentifierRecord(
                    security_id=security_id,
                    kind=IdentifierKind.ISIN,
                    value=isin,
                    valid_from=all_spells[0].valid_from,
                    source="eodhd LSE symbol list",
                )
            )
        if not attached_any_code:
            log.append(
                f"{all_spells[-1].ticker} ({display_name}): no EODHD code attached — "
                "no data will backfill (no reference row, or an earlier holder of a reused code)"
            )

    try:
        master = SecurityMaster(
            entities=tuple(entities),
            securities=tuple(securities),
            listings=tuple(listings),
            identifiers=tuple(identifiers),
        )
    except Exception:
        from trp.domain.identifier_map import find_mapping_conflicts

        for conflict in find_mapping_conflicts(identifiers):
            print(
                "CONFLICT:",
                conflict.reason,
                "|",
                conflict.first.kind,
                conflict.first.value,
                conflict.first.valid_from,
                conflict.first.valid_to,
                "| vs |",
                conflict.second.valid_from,
                conflict.second.valid_to,
                "|",
                conflict.first.source[:60],
            )
        raise
    return master, ticker_to_security, log


def membership_records(
    spells: list[TickerSpell], ticker_to_security: dict[str, SecurityId]
) -> list[UniverseMembership]:
    records = []
    for spell in spells:
        records.append(
            UniverseMembership(
                universe="FTSE100",
                security_id=ticker_to_security[spell.ticker],
                valid_from=spell.valid_from,
                valid_to=spell.valid_to,
                source=("[unverified] " if spell.needs_verification else "") + spell.source[:180],
            )
        )
    return records


def _eodhd_code_pairs(master: SecurityMaster) -> list[tuple[SecurityId, str]]:
    """Every (security, EODHD code) pair — a merged security carries several codes and
    ALL of them must backfill (the Frasers lesson: SPD.LSE ends 2019, FRAS.LSE continues)."""
    return sorted(
        (r.security_id, r.value)
        for r in master.identifiers
        if r.kind is IdentifierKind.PROVIDER and r.provider == "eodhd"
    )


def backfill(settings: Settings, *, pace_seconds: float = 0.15) -> None:
    master = read_security_master(settings.canonical_dir / "securities")
    store = RawStore(settings.raw_dir)
    provider = EodhdProvider()
    pairs = _eodhd_code_pairs(master)
    end = datetime.now(UTC).date()
    already_archived = {
        store.read(m)[0].params.get("symbol")
        for m in store.records(provider="eodhd", dataset=Dataset.PRICES)
    }
    done = fetched = 0
    for _security_id, code in pairs:
        ticker = code.partition(".")[0]
        symbol = f"{ticker}:XLON"
        if symbol in already_archived:
            done += 1
            continue
        for page in provider.prices(symbol, _HISTORY_START, end):
            store.write("eodhd", provider.version, Dataset.PRICES, page)
        for page in provider.corporate_actions(symbol, _HISTORY_START, end):
            store.write("eodhd", provider.version, Dataset.CORPORATE_ACTIONS, page)
        fetched += 1
        time.sleep(pace_seconds)
        if fetched % 25 == 0:
            print(f"...fetched {fetched} securities", flush=True)
    print(f"backfill: {fetched} fetched, {done} already archived, {len(pairs)} code-pairs")


def canonicalise(settings: Settings) -> None:
    master = read_security_master(settings.canonical_dir / "securities")
    store = RawStore(settings.raw_dir)
    pairs = _eodhd_code_pairs(master)
    # A security can carry several provider codes over its life (Frasers SPD->FRAS,
    # F&C IT FRCL->FCIT). Each code's bars are attributed ONLY inside its identifier
    # validity window, so overlapping payload histories cannot double-write a day.
    windows = {
        (str(r.security_id), r.value): (r.valid_from, r.valid_to)
        for r in master.identifiers
        if r.kind is IdentifierKind.PROVIDER and r.provider == "eodhd"
    }
    codes_per_sid: dict[str, int] = {}
    for sid, _code in pairs:
        codes_per_sid[str(sid)] = codes_per_sid.get(str(sid), 0) + 1
    by_symbol = {}
    for sid, code in pairs:
        if codes_per_sid[str(sid)] > 1:
            window = windows.get((str(sid), code), (None, None))
        else:
            window = (None, None)  # single-code securities take their full payload
        by_symbol[f"{code.partition('.')[0]}:XLON"] = (sid, window[0], window[1])
    ingested_at = datetime.now(UTC)

    all_bars: list[DailyBar] = []
    multi_candidates: dict[tuple[str, object], list[tuple[bool, str, DailyBar]]] = {}
    all_actions: list[Split | Dividend] = []
    reject_log: list[str] = []
    for dataset in (Dataset.PRICES, Dataset.CORPORATE_ACTIONS):
        for meta in store.records(provider="eodhd", dataset=dataset):
            record, content = store.read(meta)
            symbol = record.params.get("symbol", "")
            mapping = by_symbol.get(symbol)
            if mapping is None or content is None:
                continue
            security_id, window_from, window_to = mapping
            if dataset is Dataset.PRICES:
                bars, rejects = bars_from_eodhd(
                    content, security_id, currency="GBX", ingested_at=ingested_at
                )
                # Multi-code securities: collect candidates per (sid, date); windows
                # only break TIES between codes, never exclude sole coverage (identifier
                # windows are membership-bounded, not listing-bounded).
                if window_from is not None or window_to is not None:
                    for bar in bars:
                        in_window = (window_from is None or bar.trade_date >= window_from) and (
                            window_to is None or bar.trade_date <= window_to
                        )
                        multi_candidates.setdefault((str(security_id), bar.trade_date), []).append(
                            (in_window, symbol, bar)
                        )
                else:
                    all_bars.extend(bars)
            elif "/splits/" in record.endpoint:
                new_splits, rejects = splits_from_eodhd(content, security_id)
                all_actions.extend(new_splits)
            elif "/div/" in record.endpoint:
                new_dividends, rejects = dividends_from_eodhd(content, security_id)
                all_actions.extend(new_dividends)
            else:
                continue
            reject_log.extend(f"{symbol}: {r}" for r in rejects)

    for _key, candidates in multi_candidates.items():
        windowed = [c for c in candidates if c[0]]
        pool = windowed if windowed else candidates
        # deterministic tie-break: symbol order
        chosen = sorted(pool, key=lambda c: c[1])[0]
        all_bars.append(chosen[2])
    written = write_prices(all_bars, settings.canonical_dir / "prices", source="eodhd")
    actions_dir = settings.canonical_dir / "corporate_actions"
    actions_dir.mkdir(parents=True, exist_ok=True)
    splits = [a for a in all_actions if isinstance(a, Split)]
    dividends = [a for a in all_actions if isinstance(a, Dividend)]
    pl.DataFrame(
        [s.model_dump(mode="python") for s in splits],
        schema={
            "security_id": pl.Utf8,
            "action_type": pl.Utf8,
            "ex_date": pl.Date,
            "record_date": pl.Date,
            "pay_date": pl.Date,
            "new_shares": pl.Int64,
            "old_shares": pl.Int64,
            "available_at": pl.Datetime(time_unit="us", time_zone="UTC"),
            "available_at_imputed": pl.Boolean,
            "source": pl.Utf8,
        },
    ).sort(["security_id", "ex_date"]).write_parquet(actions_dir / "eodhd_ftse100_splits.parquet")
    pl.DataFrame(
        [d.model_dump(mode="python") for d in dividends],
        schema={
            "security_id": pl.Utf8,
            "action_type": pl.Utf8,
            "ex_date": pl.Date,
            "record_date": pl.Date,
            "pay_date": pl.Date,
            "amount": pl.Decimal(precision=18, scale=6),
            "currency": pl.Utf8,
            "special": pl.Boolean,
            "available_at": pl.Datetime(time_unit="us", time_zone="UTC"),
            "available_at_imputed": pl.Boolean,
            "source": pl.Utf8,
        },
    ).sort(["security_id", "ex_date"]).write_parquet(
        actions_dir / "eodhd_ftse100_dividends.parquet"
    )
    (settings.derived_dir / "reports").mkdir(parents=True, exist_ok=True)
    (settings.derived_dir / "reports" / "ftse100_canonicalise_rejects.txt").write_text(
        "\n".join(reject_log)
    )
    splits_n = sum(1 for a in all_actions if isinstance(a, Split))
    divs_n = sum(1 for a in all_actions if isinstance(a, Dividend))
    print(
        f"canonicalise: {written} new bars written ({len(all_bars)} parsed), "
        f"{splits_n} splits, {divs_n} dividends, {len(reject_log)} rejects"
    )


def report(settings: Settings) -> None:
    prices = pl.read_parquet(settings.canonical_dir / "prices" / "**/*.parquet")
    master = read_security_master(settings.canonical_dir / "securities")
    names = {s.security_id: s.name for s in master.securities}
    summary = (
        prices.group_by("security_id")
        .agg(
            pl.len().alias("bars"),
            pl.col("trade_date").min().alias("first"),
            pl.col("trade_date").max().alias("last"),
        )
        .sort("bars")
    )
    print(f"securities with bars: {summary.height} / {len(names)}")
    print(f"total bars: {int(summary['bars'].sum())}")
    missing = set(names) - set(summary["security_id"].to_list())
    print(f"securities with NO bars: {len(missing)}")
    for sid in sorted(missing)[:15]:
        print("   ", names[sid])
    print("thinnest coverage:")
    for row in summary.head(10).iter_rows(named=True):
        print(
            f"   {names.get(row['security_id'], '?'):40s} {row['bars']:>6} bars "
            f"{row['first']}..{row['last']}"
        )


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="trp.universe.ftse_build", description=__doc__)
    parser.add_argument(
        "step", choices=["master", "membership", "backfill", "canonicalise", "report"]
    )
    args = parser.parse_args(argv)
    settings = load_settings()
    settings.ensure_data_dirs()

    if args.step == "master":
        history = json.loads(HISTORY_PATH.read_text())
        spells = replay_index_history(history)
        reference, delisted_codes = load_reference_lists(RawStore(settings.raw_dir))
        master, ticker_map, log = build_master(spells, history, reference, delisted_codes)
        write_security_master(master, settings.canonical_dir / "securities")
        (settings.canonical_dir / "securities" / "ftse100_ticker_map.json").write_text(
            json.dumps(ticker_map, indent=2, sort_keys=True)
        )
        print(f"master: {len(master.securities)} securities, {len(master.identifiers)} identifiers")
        for line in log:
            print("  note:", line)
    elif args.step == "membership":
        history = json.loads(HISTORY_PATH.read_text())
        spells = replay_index_history(history)
        ticker_map = {
            t: SecurityId(s)
            for t, s in json.loads(
                (settings.canonical_dir / "securities" / "ftse100_ticker_map.json").read_text()
            ).items()
        }
        master = read_security_master(settings.canonical_dir / "securities")
        records = membership_records(spells, ticker_map)
        write_universe(
            records,
            settings.canonical_dir / "universes",
            known_security_ids={s.security_id for s in master.securities},
        )
        query = UniverseQuery(settings.canonical_dir / "universes")
        for probe in (date(2007, 8, 15), date(2012, 8, 15), date(2020, 3, 20)):
            members = query.members("FTSE100", probe)
            print(f"members('FTSE100', {probe}): {len(members)}")
    elif args.step == "backfill":
        backfill(settings)
    elif args.step == "canonicalise":
        canonicalise(settings)
    elif args.step == "report":
        report(settings)
    return 0


if __name__ == "__main__":
    sys.exit(main())
