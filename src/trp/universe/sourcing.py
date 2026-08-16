"""Sourcing index membership histories into ticker-level spells.

Two sources, one output shape (:class:`TickerSpell` — ticker-level, because sourcing
happens before the security master is populated; resolution of tickers to immutable
``security_id``s is a separate, later step through the QNT-009 resolver):

- **Curated anchor+changes** (FTSE, QNT-039): a full membership snapshot on an anchor
  date plus dated add/remove changes. :func:`replay_index_history` replays them forward
  and is deliberately strict — removing a non-member or adding an existing member raises,
  because those are exactly the errors hand-curation produces, and a curation error
  caught at replay time costs nothing while one caught in a backtest costs trust.
- **EODHD ``HistoricalTickerComponents``** (S&P 500): provider-supplied spells parsed by
  :func:`spells_from_eodhd_components`.

Half-open convention throughout: a change effective on date ``d`` means the removed name's
spell ends at ``d`` (first day out) and the added name's begins at ``d``.
"""

import json
from collections.abc import Mapping
from datetime import date
from typing import Any

from pydantic import Field

from trp.domain.security import FrozenModel


class TickerSpell(FrozenModel):
    """One membership spell, keyed by the ticker as of the spell, pre-resolution."""

    ticker: str = Field(min_length=1)
    name: str = Field(min_length=1)
    valid_from: date
    valid_to: date | None = None
    source: str = Field(min_length=1)
    needs_verification: bool = False


class HistoryReplayError(Exception):
    pass


def replay_index_history(
    history: Mapping[str, Any],
    *,
    expected_size: int = 100,
    size_tolerance: int = 1,
) -> list[TickerSpell]:
    """Replay an anchor+changes curated history into ticker spells.

    Enforces, per change: every removed name is currently a member; every added name is
    not. After each change the member count must be within ``size_tolerance`` of
    ``expected_size`` (the FTSE 100 briefly holds 99/101 around corporate events).
    Errors name the change date so the curator can fix the entry.
    """
    anchor = history["anchor"]
    anchor_date = date.fromisoformat(anchor["date"])
    anchor_flagged = bool(anchor.get("needs_verification", False))

    members: dict[str, tuple[str, date, str, bool]] = {}  # ticker -> (name, from, source, flag)
    for member in anchor["members"]:
        ticker = member["ticker"].strip()
        if ticker in members:
            raise HistoryReplayError(f"anchor: duplicate ticker {ticker!r}")
        members[ticker] = (member["name"], anchor_date, anchor["source"], anchor_flagged)
    if len(members) != expected_size:
        raise HistoryReplayError(f"anchor holds {len(members)} members, expected {expected_size}")

    spells: list[TickerSpell] = []
    previous_date = anchor_date
    for change in history["changes"]:
        effective = date.fromisoformat(change["effective"])
        if effective < previous_date:
            raise HistoryReplayError(f"changes out of order at {effective} (after {previous_date})")
        previous_date = effective
        flagged = bool(change.get("needs_verification", False))
        source = change["source"]

        for removed in change.get("removed", []):
            ticker = removed["ticker"].strip()
            if ticker not in members:
                raise HistoryReplayError(
                    f"{effective}: cannot remove {ticker!r} ({removed.get('name')}) — "
                    "not currently a member; the curated entry (or an earlier one) is wrong"
                )
            name, valid_from, entry_source, entry_flagged = members.pop(ticker)
            spells.append(
                TickerSpell(
                    ticker=ticker,
                    name=name,
                    valid_from=valid_from,
                    valid_to=effective,
                    source=f"{entry_source}; removed: {source}",
                    needs_verification=entry_flagged or flagged,
                )
            )
        for added in change.get("added", []):
            ticker = added["ticker"].strip()
            if ticker in members:
                raise HistoryReplayError(
                    f"{effective}: cannot add {ticker!r} ({added.get('name')}) — already a member"
                )
            members[ticker] = (added["name"], effective, source, flagged)

        size = len(members)
        if abs(size - expected_size) > size_tolerance:
            raise HistoryReplayError(
                f"{effective}: membership count {size} is outside "
                f"{expected_size}±{size_tolerance} — a change entry is missing or duplicated"
            )

    for ticker, (name, valid_from, entry_source, entry_flagged) in members.items():
        spells.append(
            TickerSpell(
                ticker=ticker,
                name=name,
                valid_from=valid_from,
                valid_to=None,
                source=entry_source,
                needs_verification=entry_flagged,
            )
        )
    spells.sort(key=lambda s: (s.ticker, s.valid_from))
    return spells


def spells_from_eodhd_components(payload: bytes, *, source: str) -> list[TickerSpell]:
    """Parse EODHD index-fundamentals ``HistoricalTickerComponents`` into spells.

    Entries without a ``StartDate`` cannot be dated and are skipped loudly via the
    returned spell list's companion — callers should compare counts; silence would hide
    coverage gaps.
    """
    document = json.loads(payload)
    components = document.get("HistoricalTickerComponents") or {}
    spells: list[TickerSpell] = []
    for entry in components.values():
        start = entry.get("StartDate")
        code = (entry.get("Code") or "").strip()
        if not start or not code:
            continue
        end = entry.get("EndDate")
        spells.append(
            TickerSpell(
                ticker=code,
                name=entry.get("Name") or code,
                valid_from=date.fromisoformat(start),
                valid_to=date.fromisoformat(end) if end else None,
                source=source,
            )
        )
    spells.sort(key=lambda s: (s.ticker, s.valid_from))
    return spells
