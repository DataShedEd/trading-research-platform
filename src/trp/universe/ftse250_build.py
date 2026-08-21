"""FTSE 250 dataset build (QNT-111 stage 3): resolution → master/membership/backfill.

``uv run python -m trp.universe.ftse250_build <step>``:

- ``master`` — mint securities for resolved companies not already in the master
  (FTSE 100 overlap names keep their existing ids — a 100↔250 transfer is never a new
  identity) and extend ``data/canonical/securities/``. Provider-absent names (the
  QNT-112 exception candidates) are minted WITHOUT an EODHD code: their membership is
  real, their price coverage is a measured gap, never a silent drop.
- ``membership`` — write FTSE250 spells through the QNT-037 store (wholesale rewrite of
  ``universe=FTSE250`` only). Companies with no resolvable identity (all pre-2013-only)
  are logged and skipped — the coverage report counts them.
- ``backfill`` / ``canonicalise`` — reuse the QNT-091 pipeline over the extended
  master (resumable; canonicalise appends only new bars). The FTSE 100 subset of every
  regenerated file must be byte-stable — asserted by ``tests/gate``.
"""

# ruff: noqa: SIM115 - curation tooling reads dozens of small JSON files; json.load(open(...)) keeps the provenance one-liners readable

import json
import sys
from datetime import date
from typing import Any

from trp.canonical.security_store import read_security_master, write_security_master
from trp.config import load_settings
from trp.domain.identifier_map import IdentifierRecord
from trp.domain.identifier_validation import validate_isin
from trp.domain.identifiers import IdentifierKind, SecurityId, new_entity_id, new_security_id
from trp.domain.master import SecurityMaster
from trp.domain.security import Entity, Listing, Security, SecurityType
from trp.universe.ftse250_curate import SOURCES
from trp.universe.membership import UniverseMembership
from trp.universe.storage import write_universe

RESOLUTION = SOURCES / "ftse250_resolution.json"
ASSIGNMENTS = SOURCES / "ftse250_security_ids.json"


def _spell_window(spells: list[dict[str, Any]]) -> tuple[date, date | None]:
    start = min(date.fromisoformat(str(s["from"])) for s in spells)
    ends = [s.get("to") for s in spells]
    end = None if any(e is None for e in ends) else max(date.fromisoformat(str(e)) for e in ends)
    return start, end


def build_master() -> None:
    settings = load_settings()
    resolution = json.load(open(RESOLUTION))["resolution"]
    master = read_security_master(settings.canonical_dir / "securities")
    existing_ids = {str(s.security_id) for s in master.securities}
    taken_provider_codes = {
        r.value for r in master.identifiers if r.kind is IdentifierKind.PROVIDER
    }
    assignments: dict[str, str] = json.load(open(ASSIGNMENTS)) if ASSIGNMENTS.exists() else {}

    entities = list(master.entities)
    securities = list(master.securities)
    listings = list(master.listings)
    identifiers = list(master.identifiers)
    log: list[str] = []
    minted = reused = 0

    for canon_key, entry in sorted(resolution.items()):
        if entry.get("security_id"):
            reused += 1
            continue  # FTSE 100 master owns this company
        via = str(entry["matched_via"])
        if via in ("REJECT",):
            continue  # unresolved (pre-2013 tail) — counted by coverage, not minted
        display = str(entry["display"])
        code = entry.get("eodhd_code")
        spells = entry["spells"]
        start, end = _spell_window(spells)

        if canon_key in assignments:
            security_id = SecurityId(assignments[canon_key])
        else:
            security_id = new_security_id()
            assignments[canon_key] = str(security_id)
        if str(security_id) in existing_ids:
            reused += 1
            continue

        entity_id = new_entity_id()
        entities.append(Entity(entity_id=entity_id, name=display, country="GB"))
        securities.append(
            Security(
                security_id=security_id,
                entity_id=entity_id,
                security_type=SecurityType.ORDINARY,
                name=f"{display} ordinary",
            )
        )
        listings.append(
            Listing(security_id=security_id, mic="XLON", currency="GBX", valid_from=start)
        )
        if code:
            provider_value = (
                f"{str(code).partition('.')[0].rstrip('.')}."
                if str(code).endswith(".")
                else str(code)
            )
            provider_value = f"{code!s}.LSE" if not str(code).endswith(".LSE") else str(code)
            if provider_value in taken_provider_codes:
                log.append(
                    f"{display}: EODHD code {provider_value} already attached to another "
                    "security (recycled code) — NOT attached, no backfill"
                )
            else:
                taken_provider_codes.add(provider_value)
                identifiers.append(
                    IdentifierRecord(
                        security_id=security_id,
                        kind=IdentifierKind.PROVIDER,
                        value=provider_value,
                        provider="eodhd",
                        valid_from=start,
                        valid_to=end,
                        source=f"qnt-111 resolution ({entry['matched_via']})",
                    )
                )
                try:
                    identifiers.append(
                        IdentifierRecord(
                            security_id=security_id,
                            kind=IdentifierKind.TICKER,
                            value=str(code).partition(".")[0],
                            mic="XLON",
                            valid_from=start,
                            valid_to=end,
                            source="qnt-111 resolution",
                        )
                    )
                except ValueError:
                    log.append(
                        f"{display}: EODHD code {code!r} is not a valid ticker form "
                        "(recycled-code suffix); provider identifier attached only"
                    )
        else:
            log.append(f"{display}: minted WITHOUT provider code ({via}) — exception candidate")
        isin = entry.get("isin")
        isin_valid = False
        if isin:
            try:
                validate_isin(str(isin))
                isin_valid = True
            except ValueError:
                log.append(f"{display}: ISIN {isin!r} fails checksum — not attached")
        if isin_valid:
            identifiers.append(
                IdentifierRecord(
                    security_id=security_id,
                    kind=IdentifierKind.ISIN,
                    value=str(isin),
                    valid_from=start,
                    valid_to=end,
                    source="eodhd LSE symbol list (qnt-111)",
                )
            )
        minted += 1

    try:
        extended = SecurityMaster(
            entities=tuple(entities),
            securities=tuple(securities),
            listings=tuple(listings),
            status_periods=master.status_periods,
            identifiers=tuple(identifiers),
        )
    except Exception:
        from trp.domain.identifier_map import find_mapping_conflicts

        for conflict in find_mapping_conflicts(tuple(identifiers)):
            print(
                "CONFLICT:",
                conflict.reason,
                conflict.first.kind,
                conflict.first.value,
                conflict.first.valid_from,
                conflict.first.valid_to,
                "vs",
                conflict.second.valid_from,
                conflict.second.valid_to,
            )
        raise
    write_security_master(extended, settings.canonical_dir / "securities")
    ASSIGNMENTS.write_text(json.dumps(assignments, indent=1, sort_keys=True))
    (SOURCES / "ftse250_master_log.json").write_text(json.dumps(log, indent=1))
    print(
        f"master: minted {minted} new securities (reused {reused} existing); "
        f"{len(log)} log lines; total securities {len(securities)}"
    )


def build_membership() -> None:
    settings = load_settings()
    resolution = json.load(open(RESOLUTION))["resolution"]
    assignments = json.load(open(ASSIGNMENTS))
    master = read_security_master(settings.canonical_dir / "securities")
    known = {str(s.security_id) for s in master.securities}

    records: list[UniverseMembership] = []
    skipped: list[str] = []
    for canon_key, entry in sorted(resolution.items()):
        security_id = entry.get("security_id") or assignments.get(canon_key)
        if not security_id or str(security_id) not in known:
            skipped.append(str(entry["display"]))
            continue
        for spell in entry["spells"]:
            source = str(spell["entry_source"])[:150]
            flagged = "RECONCILED" in source or "reverse-derived" in source
            records.append(
                UniverseMembership(
                    universe="FTSE250",
                    security_id=SecurityId(str(security_id)),
                    valid_from=date.fromisoformat(str(spell["from"])),
                    valid_to=(date.fromisoformat(str(spell["to"])) if spell.get("to") else None),
                    source=("[unverified] " if flagged else "") + source[:160],
                )
            )
    write_universe(records, settings.canonical_dir / "universes", known_security_ids=known)
    (SOURCES / "ftse250_membership_skipped.json").write_text(json.dumps(skipped, indent=1))
    print(
        f"membership: {len(records)} spells written for FTSE250; "
        f"{len(skipped)} unresolved companies skipped (logged)"
    )


if __name__ == "__main__":
    step = sys.argv[1] if len(sys.argv) > 1 else ""
    if step == "master":
        build_master()
    elif step == "membership":
        build_membership()
    elif step == "backfill":
        from trp.universe.ftse_build import backfill

        backfill(load_settings())
    elif step == "canonicalise":
        from trp.universe.ftse_build import canonicalise

        canonicalise(load_settings())
    else:
        print("usage: ftse250_build master|membership|backfill|canonicalise")
        raise SystemExit(2)
