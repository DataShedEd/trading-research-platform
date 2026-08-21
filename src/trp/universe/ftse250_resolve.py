"""FTSE 250 identity resolution (QNT-111 stage 2): name-spells → securities.

Resolution order per company (canon name key from ftse250_curate):

1. **FTSE 100 security master** — promotions/demotions MUST resolve to the existing
   security_id (a 100↔250 transfer is an index event, never a new identity). Matched
   by canonical name against every master security's name.
2. **Wikipedia end-anchor ticker** — current members carry the wiki EPIC; matched to
   the EODHD LSE listed list by code (dot-form differences tolerated).
3. **EODHD LSE listed+delisted lists** — canonical-name match (exact → unique
   containment → high-margin fuzzy), preferring Common Stock/Fund rows and GBX/GBP.
4. Otherwise: the company lands in the REJECTS report for hand adjudication via
   ``ftse250_ticker_overrides.json`` (code or null=UNRESOLVABLE, each cited).

Output: ``data_sources/ftse/ftse250_resolution.json`` mapping canon → {display,
security_id (existing or freshly minted), eodhd_code, isin, matched_via} plus a
rejects list. The write stage (ftse250_build) consumes this.
"""

import json
from difflib import SequenceMatcher
from pathlib import Path

from trp.canonical.security_store import read_security_master
from trp.config import load_settings
from trp.universe.ftse250_curate import SOURCES, NameMatcher, normalise

FUZZY_ACCEPT = 0.92
FUZZY_MARGIN = 0.05
_EODHD_NOISE = (" plc", " ord", " ordinary")


def name_variants(display: str) -> list[str]:
    """The display name plus an inverted form for '(X)' styles: 'Smith (DS)' ->
    'DS Smith', 'Fisher (James) & Sons' -> 'James Fisher & Sons', 'Wood Group (John)'
    -> 'John Wood Group'."""
    import re as _re

    variants = [display]
    match = _re.search(r"^(.*?)\s*\(([^)]+)\)(.*)$", display)
    if match:
        head, inner, tail = match.groups()
        variants.append(f"{inner} {head}{tail}".strip())
    return variants


def load_eodhd_rows() -> list[dict[str, str]]:
    """Every page of the archived LSE exchange-symbol lists (listed + delisted)."""

    def pages(pattern: str) -> list[dict[str, object]]:
        out: list[dict[str, object]] = []
        for path in sorted(Path("data/raw/eodhd").glob(pattern)):
            if path.name.endswith(".meta.json"):
                continue
            payload = json.load(open(path))
            if isinstance(payload, list):
                out.extend(payload)
        return out

    listed = pages("securities/a7de7a6803aae50e/*.json")
    delisted = pages("delisted_securities/a7de7a6803aae50e/*.json")
    rows = []
    for row, is_delisted in [(r, False) for r in listed] + [(r, True) for r in delisted]:
        rows.append(
            {
                "code": str(row.get("Code", "")),
                "name": str(row.get("Name", "")),
                "isin": str(row.get("Isin") or ""),
                "type": str(row.get("Type", "")),
                "currency": str(row.get("Currency", "")),
                "delisted": is_delisted,
            }
        )
    return rows


def resolve() -> None:
    settings = load_settings()
    draft = json.load(open(SOURCES / "ftse250_membership_draft.json"))
    aliases = json.load(open(SOURCES / "ftse250_name_aliases.json"))
    matcher = NameMatcher(aliases)
    overrides_path = SOURCES / "ftse250_ticker_overrides.json"
    overrides = json.load(open(overrides_path)) if overrides_path.exists() else {}
    override_map = {
        matcher.canon(k): v for k, v in overrides.items() if not k.startswith("_")
    }

    # 1. existing master by canonical name
    master = read_security_master(settings.canonical_dir / "securities")
    master_by_canon: dict[str, str] = {}
    for security in master.securities:
        master_by_canon.setdefault(matcher.canon(security.name), str(security.security_id))

    # 2/3. EODHD corpus
    eodhd = load_eodhd_rows()
    eodhd_by_code: dict[str, dict[str, str]] = {}
    for row in eodhd:
        eodhd_by_code.setdefault(row["code"], row)
    by_canon: dict[str, list[dict[str, str]]] = {}
    for row in eodhd:
        name = row["name"].lower()
        for noise in _EODHD_NOISE:
            name = name.removesuffix(noise)
        by_canon.setdefault(matcher.canon(name), []).append(row)

    wiki_tickers = {
        matcher.canon(m["name"]): m["ticker"]
        for m in json.load(open(SOURCES / "ftse250_end_anchor.json"))["members"]
    }

    def eodhd_by_name(canon_key: str) -> tuple[dict[str, str] | None, str]:
        rows = by_canon.get(canon_key, [])
        equity = [r for r in rows if r["type"] in ("Common Stock", "Fund", "ETF", "")]
        if len(equity) == 1:
            return equity[0], "eodhd-name-exact"
        if len(equity) > 1:
            # prefer listed over delisted, GBX/GBP over foreign
            ranked = sorted(
                equity,
                key=lambda r: (r["delisted"], r["currency"] not in ("GBX", "GBP"), r["code"]),
            )
            return ranked[0], "eodhd-name-ambiguous-ranked"
        # containment / fuzzy over the whole corpus (unique only)
        candidates = [
            (key, rows2)
            for key, rows2 in by_canon.items()
            if key.startswith(canon_key + " ") or canon_key.startswith(key + " ")
        ]
        if len(candidates) == 1:
            return candidates[0][1][0], "eodhd-name-containment"
        scored = sorted(
            ((SequenceMatcher(None, canon_key, key).ratio(), key) for key in by_canon),
            reverse=True,
        )
        if (
            scored
            and scored[0][0] >= FUZZY_ACCEPT
            and (len(scored) == 1 or scored[0][0] - scored[1][0] >= FUZZY_MARGIN)
        ):
            return by_canon[scored[0][1]][0], f"eodhd-name-fuzzy-{scored[0][0]:.2f}"
        return None, "unmatched"

    resolution: dict[str, dict[str, object]] = {}
    rejects: list[dict[str, object]] = []
    for canon_key, spell_list in draft["spells"].items():
        display = draft["display"].get(canon_key, canon_key)
        entry: dict[str, object] = {"display": display, "spells": spell_list}
        if canon_key in override_map:
            override = override_map[canon_key]
            if override is None:
                entry.update(matched_via="override-unresolvable", eodhd_code=None)
                resolution[canon_key] = entry
                continue
            code = str(override)
            row = (
                eodhd_by_code.get(code)
                or eodhd_by_code.get(code + ".")
                or eodhd_by_code.get(code.rstrip("."))
            )
            if row is None:
                entry.update(matched_via="override-NOT-IN-EODHD", eodhd_code=code)
                rejects.append(
                    {
                        "canon": canon_key,
                        "display": display,
                        "spells": spell_list,
                        "reason": f"adjudicated code {code} absent from EODHD LSE lists",
                    }
                )
                resolution[canon_key] = entry
                continue
            entry.update(matched_via="override", eodhd_code=row["code"], isin=row["isin"])
            resolution[canon_key] = entry
            continue
        variant_keys = [matcher.canon(v) for v in name_variants(display)]
        master_hit = next((k for k in variant_keys if k in master_by_canon), None)
        if master_hit is not None:
            entry.update(matched_via="ftse100-master", security_id=master_by_canon[master_hit])
            resolution[canon_key] = entry
            continue
        ticker = wiki_tickers.get(canon_key)
        if ticker:
            row = eodhd_by_code.get(ticker) or eodhd_by_code.get(ticker + ".")
            if row is None and len(ticker) <= 3:
                row = eodhd_by_code.get(ticker.rstrip(".") )
            if row is not None:
                entry.update(
                    matched_via="wiki-ticker", eodhd_code=row["code"], isin=row["isin"]
                )
                resolution[canon_key] = entry
                continue
        row, how = None, "unmatched"
        for variant in variant_keys:
            row, how = eodhd_by_name(variant)
            if row is not None:
                break
        if row is not None:
            entry.update(matched_via=how, eodhd_code=row["code"], isin=row["isin"])
            resolution[canon_key] = entry
            continue
        rejects.append({"canon": canon_key, "display": display, "spells": spell_list})
        entry.update(matched_via="REJECT", eodhd_code=None)
        resolution[canon_key] = entry

    out = {
        "companies": len(resolution),
        "matched_master": sum(
            1 for e in resolution.values() if e["matched_via"] == "ftse100-master"
        ),
        "matched_wiki_ticker": sum(
            1 for e in resolution.values() if e["matched_via"] == "wiki-ticker"
        ),
        "matched_eodhd": sum(
            1 for e in resolution.values() if str(e["matched_via"]).startswith("eodhd")
        ),
        "overrides": sum(
            1 for e in resolution.values() if str(e["matched_via"]).startswith("override")
        ),
        "rejects": len(rejects),
        "resolution": resolution,
    }
    (SOURCES / "ftse250_resolution.json").write_text(json.dumps(out, indent=1))
    (SOURCES / "ftse250_rejects.json").write_text(json.dumps(rejects, indent=1))
    print(
        f"companies {out['companies']}: master {out['matched_master']}, wiki-ticker "
        f"{out['matched_wiki_ticker']}, eodhd {out['matched_eodhd']}, overrides "
        f"{out['overrides']}, REJECTS {out['rejects']}"
    )


if __name__ == "__main__":
    resolve()
