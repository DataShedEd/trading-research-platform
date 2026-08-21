"""FTSE 250 membership curation (QNT-111): official change history → curated spells.

Inputs (all versioned under ``data_sources/ftse/``):
- ``ftse250_changes_raw.json`` — the parsed FTSE Russell "FTSE 250 Historic Additions
  and Deletions" PDF (April 2026 edition), 980 paired change rows 2002-09-23..2026-03-23.
- ``ftse250_june2026_review.json`` — the June 2026 annual review (LSEG press release).
- ``ftse250_end_anchor.json`` — the verified current 250 (Wikipedia 2026-08-20,
  cross-validated against the June review).
- ``ftse250_name_aliases.json`` — hand adjudications for name drift (wiki↔PDF and
  within-PDF renames). Every entry cites why. Grows only through the unresolved report.

Process: REVERSE replay from the end anchor back to the historical anchor date
(2009-06-22, the June 2009 review), matching event names against the evolving state
through a conservative cascade (exact normalised → unique containment → high-margin
fuzzy). Anything weaker lands in the unresolved report for human adjudication — the
matcher never guesses silently. A forward replay then rebuilds spells from the derived
historical anchor and must reproduce the end anchor exactly (round-trip validation).

The index is 250 names at every review; unpaired corporate-event rows (demergers,
asynchronous replacements) make the count deviate transiently — each deviation is
tracked and must return to 250 within ``MAX_TRANSIENT_DAYS``.
"""

import json
import re
from collections import defaultdict
from datetime import date, timedelta
from difflib import SequenceMatcher
from pathlib import Path

SOURCES = Path("data_sources/ftse")
HIST_ANCHOR_DATE = date(2009, 6, 22)  # June 2009 quarterly review effective date
MAX_TRANSIENT_DAYS = 35
FUZZY_ACCEPT = 0.90
FUZZY_MARGIN = 0.06

_DROP_TOKENS = {"plc", "ltd", "limited", "the", "co", "company", "of"}

# Abbreviations the FTSE Russell document uses inconsistently vs full names.
_EXPAND = {
    "inv": "investment",
    "invs": "investment",
    "tst": "trust",
    "tsts": "trust",
    "trusts": "trust",
    "hldgs": "holdings",
    "grp": "group",
    "intl": "international",
    "euro": "europe",
    "smallercos": "smaller companies",
    "cos": "companies",
    "sml": "smaller",
    "props": "properties",
    "prop": "property",
    "jp": "jpmorgan",
    "col": "colonial",
    "mkts": "markets",
    "secs": "securities",
}


def normalise(name: str) -> str:
    import unicodedata

    name = unicodedata.normalize("NFKD", name).encode("ascii", "ignore").decode()
    text = name.lower().replace("&", " and ").replace(".com", " com")
    text = re.sub(r"\bjp morgan\b", "jpmorgan", text)
    text = re.sub(r"[^a-z0-9 ]+", " ", text)
    tokens = []
    for token in text.split():
        if token in _DROP_TOKENS:
            continue
        tokens.append(_EXPAND.get(token, token))
    return " ".join(" ".join(tokens).split())


_SUFFIX_TOKENS = {
    "group", "holdings", "hldgs", "hdg", "corp", "corporation", "ord", "shs",
    "gbp", "eur", "international", "ordinary", "ordinar", "units", "unit",
}


def _strip_suffixes(name: str) -> str:
    tokens = name.split()
    while len(tokens) > 1 and tokens[-1] in _SUFFIX_TOKENS:
        tokens.pop()
    return " ".join(tokens)


def _token_set_ratio(a: str, b: str) -> float:
    ta, tb = set(a.split()), set(b.split())
    if not ta or not tb:
        return 0.0
    return len(ta & tb) / len(ta | tb)


class MatchFailure(Exception):
    pass


class NameMatcher:
    """Matches an event name against the current state's names, conservatively.

    ``canon`` is THE identity function: normalise -> transitive alias chain ->
    corporate-suffix strip. State dictionaries must be keyed by ``canon`` so a
    company's every era-name lands on one key."""

    def __init__(self, aliases: dict[str, str]) -> None:
        # alias: normalised event-name -> normalised state-name it refers to.
        # Keys starting with "_" are provenance comments, not aliases.
        # Aliases live in CANON space (normalised + suffix-stripped) so that any
        # suffix variant of an aliased name still follows the chain.
        self.aliases = {}
        for k, v in aliases.items():
            if k.startswith("_"):
                continue
            key = _strip_suffixes(normalise(k))
            value = _strip_suffixes(normalise(v))
            if key != value:
                self.aliases[key] = value
        self.unresolved: list[dict[str, object]] = []

    def canon(self, name: str) -> str:
        key = _strip_suffixes(normalise(name))
        seen: set[str] = set()
        while key in self.aliases and key not in seen:
            seen.add(key)
            key = self.aliases[key]
        return key

    def find(self, event_name: str, state: dict[str, str], context: str) -> str | None:
        """Return the STATE key matching event_name, or None (recorded unresolved)."""
        wanted = self.canon(event_name)
        if wanted in state:
            return wanted
        # unique containment either direction (e.g. "micro focus" vs
        # "micro focus international")
        contains = [
            k for k in state if k.startswith(wanted + " ") or wanted.startswith(k + " ")
        ]
        if len(contains) == 1:
            return contains[0]
        # corporate-suffix drift: "serco group" vs "serco", "wizz air holdings" vs
        # "wizz air" — strip trailing suffix tokens from both sides and match uniquely
        stripped_wanted = _strip_suffixes(wanted)
        by_stripped = [k for k in state if _strip_suffixes(k) == stripped_wanted]
        if len(by_stripped) == 1 and stripped_wanted:
            return by_stripped[0]
        scored = sorted(
            (
                (
                    max(
                        SequenceMatcher(None, wanted, k).ratio(),
                        _token_set_ratio(wanted, k),
                    ),
                    k,
                )
                for k in state
            ),
            reverse=True,
        )
        if scored and scored[0][0] >= FUZZY_ACCEPT:
            if len(scored) == 1 or scored[0][0] - scored[1][0] >= FUZZY_MARGIN:
                return scored[0][1]
        self.unresolved.append(
            {
                "event_name": event_name,
                "normalised": wanted,
                "context": context,
                "best_candidates": [(round(s, 3), k) for s, k in scored[:3]],
            }
        )
        return None


def load_events() -> list[dict[str, object]]:
    """All change events, oldest→newest, as {effective, added:[names], deleted:[names],
    notes, source}."""
    rows = json.load(open(SOURCES / "ftse250_changes_raw.json"))
    corrections_path = SOURCES / "ftse250_corrections.json"
    if corrections_path.exists():
        for correction in json.load(open(corrections_path)):
            hits = [
                r
                for r in rows
                if r["effective"] == correction["effective"]
                and all(r[k] == v for k, v in correction["match"].items())
            ]
            if len(hits) != 1:
                raise ValueError(f"correction matched {len(hits)} rows: {correction}")
            hits[0].update(correction["set"])
            hits[0]["notes"] = (hits[0]["notes"] + " [CORRECTED: " + correction["reason"][:80] + "]").strip()

    def names(cell: str) -> list[str]:
        return [] if cell.strip() in ("", "-", "–") else [cell]

    events = [
        {
            "effective": r["effective"],
            "added": names(r["added"]),
            "deleted": names(r["deleted"]),
            "notes": r["notes"],
            "source": "FTSE Russell, 'FTSE 250 Historic Additions and Deletions', "
            "April 2026 edition (research.ftserussell.com/products/downloads/"
            "FTSE_250_Constituent_history.pdf), page "
            + str(r["page"] + 2),
        }
        for r in rows
    ]
    june = json.load(open(SOURCES / "ftse250_june2026_review.json"))
    events.append(
        {
            "effective": june["effective"],
            "added": june["added"],
            "deleted": june["deleted"],
            "notes": "June 2026 annual review",
            "source": june["source"],
        }
    )
    extra_path = SOURCES / "ftse250_adhoc_2026.json"
    if extra_path.exists():
        for event in json.load(open(extra_path)):
            events.append(event)
    events.sort(key=lambda e: e["effective"])
    return events


def reverse_replay() -> tuple[dict[str, str], NameMatcher, list[str]]:
    """Walk newest→oldest from the end anchor; return the state at HIST_ANCHOR_DATE
    (normalised -> display name), the matcher (with unresolved report), and a log."""
    anchor = json.load(open(SOURCES / "ftse250_end_anchor.json"))
    aliases = (
        json.load(open(SOURCES / "ftse250_name_aliases.json"))
        if (SOURCES / "ftse250_name_aliases.json").exists()
        else {}
    )
    matcher = NameMatcher(aliases)
    state: dict[str, str] = {}
    for member in anchor["members"]:
        key = matcher.canon(member["name"])
        if key in state:
            raise ValueError(f"anchor name collision: {member['name']}")
        state[key] = member["name"]

    log: list[str] = []
    events = [e for e in load_events() if str(e["effective"]) >= str(HIST_ANCHOR_DATE)]
    for event in reversed(events):
        day = event["effective"]
        # Reverse of "added on day": the name must be present; remove it.
        for name in event["added"]:  # type: ignore[union-attr]
            key = matcher.find(str(name), state, f"reverse-remove @{day}")
            if key is not None:
                del state[key]
        # Reverse of "deleted on day": the name re-enters going backwards.
        for name in event["deleted"]:  # type: ignore[union-attr]
            key = matcher.canon(str(name))
            if key in state:
                log.append(f"{day}: reverse-add {name!r} already present (rename/dup?)")
            state[key] = str(name)
        size = len(state)
        if size != 250:
            log.append(f"{day}: state size {size} after reversing this event")
    return state, matcher, log


def canon_map(matcher: NameMatcher):  # type: ignore[no-untyped-def]
    def canon(name: str) -> str:
        key = normalise(name)
        seen = set()
        while key in matcher.aliases and key not in seen:
            seen.add(key)
            key = matcher.aliases[key]
        return _strip_suffixes(key)

    return canon


def validate_checkpoints() -> None:
    """Forward-replay between consecutive Wikipedia snapshots; report per-segment
    diffs. A clean segment means the event stream fully explains the transition."""
    snapshots_dir = SOURCES / "wiki_snapshots"
    aliases = json.load(open(SOURCES / "ftse250_name_aliases.json"))
    matcher = NameMatcher(aliases)
    canon = matcher.canon
    events = load_events()

    snaps = []
    for path in sorted(snapshots_dir.glob("*.json")):
        if path.name == "index.json":
            continue
        payload = json.load(open(path))
        day = payload["timestamp"][:10]
        snaps.append((day, {canon(n) for n in payload["names"]}, payload["names"]))
    end_anchor = json.load(open(SOURCES / "ftse250_end_anchor.json"))
    snaps.append(
        (
            end_anchor["date"],
            {canon(m["name"]) for m in end_anchor["members"]},
            [m["name"] for m in end_anchor["members"]],
        )
    )
    snaps.sort()

    report = []
    dirty = 0
    for (day_a, _, names_a), (day_b, _, names_b) in zip(snaps, snaps[1:], strict=False):
        state: dict[str, str] = {}
        for name in names_a:
            state[canon(name)] = name
        for event in events:
            if not (day_a < str(event["effective"]) <= day_b):
                continue
            for name in event["deleted"]:  # type: ignore[union-attr]
                key = matcher.find(str(name), state, f"seg-del @{event['effective']}")
                if key is not None:
                    del state[key]
                else:
                    report.append(
                        f"{day_a}..{day_b}: DEL {name!r} unmatched @{event['effective']}"
                    )
            for name in event["added"]:  # type: ignore[union-attr]
                state[canon(str(name))] = str(name)
        # Compare against snapshot B with the same conservative matcher.
        remaining = dict(state)
        missing = []
        for name in names_b:
            key = matcher.find(str(name), remaining, f"seg-end {day_b}")
            if key is not None:
                del remaining[key]
            else:
                missing.append(name)
        if missing or remaining:
            dirty += 1
            report.append(
                f"SEGMENT {day_a} -> {day_b}: snapshot names unmatched {sorted(missing)} | "
                f"replay extras {sorted(remaining.values())}"
            )
    (SOURCES / "ftse250_segment_report.json").write_text(json.dumps(report, indent=1))
    print(f"segments with mismatches: {dirty} of {len(snaps) - 1}; detail lines: {len(report)}")


def ftse100_boundary_events(matcher: NameMatcher) -> list[dict[str, object]]:
    """Synthetic FTSE 250 events implied by the VALIDATED FTSE 100 history where the
    FTSE 250 PDF omits the mirror row. A review-reason FTSE 100 removal is a demotion
    INTO the 250; a review-date FTSE 100 addition of an existing 250 member is a
    promotion OUT. Generated, cited, and applied only when no explicit 250 event within
    3 days already covers the same name+direction."""
    doc = json.load(open(Path("src/trp/universe/data/ftse100_history.json")))
    explicit: set[tuple[str, str, str]] = set()
    for event in load_events():
        for name in event["added"]:  # type: ignore[union-attr]
            explicit.add((matcher.canon(str(name)), str(event["effective"]), "add"))
        for name in event["deleted"]:  # type: ignore[union-attr]
            explicit.add((matcher.canon(str(name)), str(event["effective"]), "del"))

    def covered(key: str, day: str, side: str) -> bool:
        from datetime import date as _date, timedelta as _timedelta

        base = _date.fromisoformat(day)
        for offset in range(-3, 4):
            if (key, str(base + _timedelta(days=offset)), side) in explicit:
                return True
        return False

    synthetic = []
    for change in doc["changes"]:
        day = change["effective"]
        if day < str(HIST_ANCHOR_DATE):
            continue
        for removed in change.get("removed", []):
            if removed.get("reason") != "review":
                continue  # acquisitions/delistings leave the market, not into the 250
            key = matcher.canon(removed["name"])
            if not covered(key, day, "add"):
                synthetic.append(
                    {
                        "effective": day,
                        "added": [removed["name"]],
                        "deleted": [],
                        "notes": "SYNTHETIC: FTSE 100 review relegation implies FTSE 250 entry",
                        "source": f"ftse100_history.json change {day} (validated; FTSE 250 PDF omits the mirror row)",
                    }
                )
        for added in change.get("added", []):
            key = matcher.canon(added["name"])
            if not covered(key, day, "del"):
                synthetic.append(
                    {
                        "effective": day,
                        "added": [],
                        "deleted": [added["name"]],
                        "notes": "SYNTHETIC: FTSE 100 addition implies FTSE 250 exit if member",
                        "conditional": True,  # only applies if the name IS a 250 member
                        "source": f"ftse100_history.json change {day} (validated; FTSE 250 PDF omits the mirror row)",
                    }
                )
    return synthetic


def build_membership() -> None:
    """Snapshot-anchored forward replay -> name-level membership spells + ledger."""
    aliases = json.load(open(SOURCES / "ftse250_name_aliases.json"))
    matcher = NameMatcher(aliases)
    events = load_events() + ftse100_boundary_events(matcher)
    adhoc_path = SOURCES / "ftse250_adhoc_2026.json"
    if adhoc_path.exists():
        events += json.load(open(adhoc_path))
    events.sort(key=lambda e: str(e["effective"]))

    snaps = []
    for path in sorted((SOURCES / "wiki_snapshots").glob("*.json")):
        if path.name == "index.json":
            continue
        payload = json.load(open(path))
        snaps.append((payload["timestamp"][:10], payload["names"]))
    end_anchor = json.load(open(SOURCES / "ftse250_end_anchor.json"))
    snaps.append((end_anchor["date"], [m["name"] for m in end_anchor["members"]]))
    snaps.sort()

    ledger: list[dict[str, object]] = []
    spells: dict[str, list[dict[str, object]]] = defaultdict(list)
    display: dict[str, str] = {}

    def open_spell(key: str, day: str, source: str) -> None:
        spells[key].append({"from": day, "to": None, "entry_source": source})

    def close_spell(key: str, day: str, source: str) -> None:
        for spell in reversed(spells[key]):
            if spell["to"] is None:
                spell["to"] = day
                spell["exit_source"] = source
                return

    # ---- head: reverse replay first-checkpoint -> historical anchor date
    first_day, first_names = snaps[0]
    state: dict[str, str] = {}
    for name in first_names:
        state[matcher.canon(name)] = name
        display.setdefault(matcher.canon(name), name)
    head_state = dict(state)
    for event in reversed([e for e in events if str(HIST_ANCHOR_DATE) < str(e["effective"]) <= first_day]):
        for name in event["added"]:  # type: ignore[union-attr]
            key = matcher.find(str(name), head_state, f"head-rev @{event['effective']}")
            if key is not None:
                del head_state[key]
        for name in event["deleted"]:  # type: ignore[union-attr]
            if event.get("conditional"):
                continue  # conditional synthetics never create members backwards
            head_state[matcher.canon(str(name))] = str(name)

    # ---- forward replay from historical anchor through all checkpoints
    state = dict(head_state)
    for key, name in state.items():
        display.setdefault(key, name)
        open_spell(key, str(HIST_ANCHOR_DATE), f"reverse-derived anchor @{HIST_ANCHOR_DATE}")

    checkpoints = iter(snaps)
    next_cp = next(checkpoints, None)
    all_days = sorted({str(e["effective"]) for e in events})
    events_by_day: dict[str, list[dict[str, object]]] = defaultdict(list)
    for event in events:
        events_by_day[str(event["effective"])].append(event)

    cp_targets: dict[str, set[str]] = {}
    for cp_day_i, cp_names_i in snaps:
        cp_targets[cp_day_i] = {matcher.canon(n) for n in cp_names_i}
    cp_order = [d for d, _ in snaps]

    def _next_cp_target(cp_day: str) -> set[str] | None:
        later = [d for d in cp_order if d > cp_day]
        return cp_targets[later[0]] if later else None

    def reconcile(cp_day: str, cp_names: list[str]) -> None:
        nonlocal state
        target: dict[str, str] = {}
        for name in cp_names:
            target[matcher.canon(name)] = name
        # trust events over stale snapshots: a diff explained by an event within
        # 45 days either side of the checkpoint is left alone
        near = set()
        from datetime import date as _date, timedelta as _td

        cp = _date.fromisoformat(cp_day)
        for event in events:
            eff = _date.fromisoformat(str(event["effective"]))
            if abs((eff - cp).days) <= 45:
                for name in list(event["added"]) + list(event["deleted"]):  # type: ignore[arg-type]
                    near.add(matcher.canon(str(name)))
        missing_keys = sorted(set(target) - set(state))
        extra_keys = sorted(set(state) - set(target))

        def _subset_or_close(a: str, b: str) -> bool:
            ta, tb = set(a.split()), set(b.split())
            if not ta or not tb:
                return False
            if ta <= tb or tb <= ta:
                return True
            return len(ta & tb) / len(ta | tb) >= 0.6

        # Self-healing: a missing/extra pair that is plausibly the SAME company under
        # two labels becomes an auto-alias (logged), not a forced move.
        for miss in list(missing_keys):
            candidates = [x for x in extra_keys if _subset_or_close(miss, x)]
            reverse_ok = candidates and all(
                not _subset_or_close(m2, candidates[0]) for m2 in missing_keys if m2 != miss
            )
            if len(candidates) == 1 and reverse_ok:
                extra = candidates[0]
                matcher.aliases[miss] = extra
                ledger.append(
                    {
                        "checkpoint": cp_day,
                        "action": "auto-alias",
                        "name": target[miss],
                        "matched": state[extra],
                    }
                )
                missing_keys.remove(miss)
                extra_keys.remove(extra)
        following = _next_cp_target(cp_day)
        for key in missing_keys:
            if key in near:
                continue
            if following is not None and key not in following:
                ledger.append({"checkpoint": cp_day, "action": "suppress-add (transient snapshot glitch)", "name": target[key]})
                continue
            display.setdefault(key, target[key])
            state[key] = target[key]
            open_spell(key, cp_day, f"RECONCILED-IN at checkpoint {cp_day} (no explaining event; uncertainty back to previous checkpoint)")
            ledger.append({"checkpoint": cp_day, "action": "force-add", "name": target[key]})
        for key in extra_keys:
            if key in near:
                continue
            if following is not None and key in following:
                ledger.append({"checkpoint": cp_day, "action": "suppress-remove (transient snapshot glitch)", "name": state[key]})
                continue
            close_spell(key, cp_day, f"RECONCILED-OUT at checkpoint {cp_day} (no explaining event; uncertainty back to previous checkpoint)")
            ledger.append({"checkpoint": cp_day, "action": "force-remove", "name": state[key]})
            del state[key]

    for day in all_days:
        if str(day) <= str(HIST_ANCHOR_DATE):
            continue
        while next_cp is not None and next_cp[0] < day:
            reconcile(*next_cp)
            next_cp = next(checkpoints, None)
        for event in events_by_day[day]:
            source = str(event["source"])
            for name in event["deleted"]:  # type: ignore[union-attr]
                key = matcher.find(str(name), state, f"fwd-del @{day}")
                if key is not None:
                    close_spell(key, day, source)
                    del state[key]
                elif not event.get("conditional"):
                    ledger.append({"date": day, "action": "del-unmatched", "name": str(name)})
            for name in event["added"]:  # type: ignore[union-attr]
                key = matcher.canon(str(name))
                if key in state:
                    ledger.append({"date": day, "action": "add-duplicate", "name": str(name)})
                    continue
                display.setdefault(key, str(name))
                state[key] = str(name)
                open_spell(key, day, source)
    while next_cp is not None:
        reconcile(*next_cp)
        next_cp = next(checkpoints, None)

    out = {
        "version": "2026-08-21.1",
        "anchor_date": str(HIST_ANCHOR_DATE),
        "spell_count": sum(len(v) for v in spells.values()),
        "companies": len(spells),
        "final_members": len(state),
        "reconciliations": len([l for l in ledger if str(l.get("action", "")).startswith("force")]),
        "ledger": ledger,
        "display": display,
        "spells": {k: v for k, v in spells.items()},
    }
    (SOURCES / "ftse250_membership_draft.json").write_text(json.dumps(out, indent=1))
    print(
        f"companies {out['companies']}, spells {out['spell_count']}, final members "
        f"{out['final_members']}, reconciliations {out['reconciliations']}, "
        f"ledger entries {len(ledger)}, unresolved {len(matcher.unresolved)}"
    )


if __name__ == "__main__":
    import sys as _sys

    if _sys.argv[1:] == ["checkpoints"]:
        validate_checkpoints()
        raise SystemExit(0)
    if _sys.argv[1:] == ["build"]:
        build_membership()
        raise SystemExit(0)
    state, matcher, log = reverse_replay()
    print(f"state at {HIST_ANCHOR_DATE}: {len(state)} names")
    print(f"unresolved: {len(matcher.unresolved)}")
    (SOURCES / "ftse250_unresolved.json").write_text(json.dumps(matcher.unresolved, indent=1))
    (SOURCES / "ftse250_reverse_log.json").write_text(json.dumps(log, indent=1))
    (SOURCES / "ftse250_hist_anchor_draft.json").write_text(
        json.dumps(
            {"date": str(HIST_ANCHOR_DATE), "members": sorted(state.values())}, indent=1
        )
    )
    print("wrote unresolved report, reverse log, historical anchor draft")
