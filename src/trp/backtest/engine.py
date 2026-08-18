"""The daily event loop (QNT-050): slow on purpose, honest by construction.

The simulation clock advances session by session over the exchange calendar. Strategy
code runs only on rebalance days and only through a clock-bound ``BacktestContext``
whose knowledge instant is the PREVIOUS session (decide on yesterday's information,
execute at today's close — the documented timing convention in ``BacktestConfig``).

Corporate actions apply to the ledger on their ex-date, but only once *knowable*
(``available_at <=`` the day's instant): a dividend the vendor published late credits on
the knowledge date, and a delisting resolves when we learn of it — never retroactively.

Every run persists its full reproducibility record (config, config hash, git commit,
data versions, daily series, event log) under ``data/derived/backtests/<name>/`` and is
never overwritten. Two runs of one config over one dataset are identical; that is a
tested property, not an aspiration.
"""

import json
import subprocess
from bisect import bisect_right
from collections import defaultdict
from collections.abc import Callable, Sequence
from dataclasses import dataclass, field
from datetime import UTC, date, datetime
from decimal import Decimal
from pathlib import Path

import polars as pl

from trp.backtest.config import BacktestConfig, RebalanceSchedule
from trp.backtest.context import BacktestContext
from trp.backtest.portfolio import LedgerError, Portfolio, replay
from trp.canonical.calendars import get_trading_calendar
from trp.domain.corporate_actions import (
    CorporateAction,
    DelistingAction,
    Dividend,
    Merger,
    Split,
)
from trp.domain.identifiers import SecurityId
from trp.domain.prices import DailyBar
from trp.domain.reference import ReferenceDataError, default_reference_data
from trp.domain.security import DelistingReason
from trp.universe.query import UniverseQuery

Strategy = Callable[[BacktestContext, dict[SecurityId, int], Decimal], dict[SecurityId, int]]
"""(context, current positions, portfolio value) -> target share counts per security."""


class MarketData:
    """The engine's full dataset. Only the context and the engine read it; the context
    filters everything to its clock."""

    def __init__(
        self,
        bars: Sequence[DailyBar],
        actions: Sequence[CorporateAction],
        input_versions: dict[str, str],
    ) -> None:
        self.bars = tuple(bars)
        self.actions = tuple(actions)
        self.input_versions = dict(input_versions)
        self._closes: dict[SecurityId, list[tuple[date, Decimal]]] = defaultdict(list)
        for bar in bars:
            self._closes[bar.security_id].append((bar.trade_date, bar.close))
        for series in self._closes.values():
            series.sort()
        self._dates: dict[SecurityId, list[date]] = {
            sid: [d for d, _ in series] for sid, series in self._closes.items()
        }

    def close_on_or_before(self, security_id: SecurityId, day: date) -> tuple[date, Decimal] | None:
        dates = self._dates.get(security_id)
        if not dates:
            return None
        index = bisect_right(dates, day)
        if index == 0:
            return None
        return self._closes[security_id][index - 1]


@dataclass
class RunResult:
    config: BacktestConfig
    daily: pl.DataFrame  # date, value, cash, positions
    events: pl.DataFrame
    git_commit: str
    started_at: datetime
    warnings: list[str] = field(default_factory=list)


def _git_commit() -> str:
    try:
        return subprocess.run(
            ["git", "rev-parse", "HEAD"], capture_output=True, text=True, check=True
        ).stdout.strip()
    except (subprocess.CalledProcessError, FileNotFoundError):
        return "unknown"


def _rebalance_days(config: BacktestConfig, sessions: Sequence[date]) -> set[date]:
    months = {1, 4, 7, 10} if config.rebalance is RebalanceSchedule.QUARTERLY else set(range(1, 13))
    days: set[date] = set()
    seen: set[tuple[int, int]] = set()
    for session in sessions:
        key = (session.year, session.month)
        if session.month in months and key not in seen:
            seen.add(key)
            days.add(session)
    return days


class BacktestEngine:
    def __init__(
        self,
        config: BacktestConfig,
        market: MarketData,
        universe_query: UniverseQuery,
    ) -> None:
        self._config = config
        self._market = market
        self._universe_query = universe_query
        self._calendar = get_trading_calendar(config.mic)
        self._warnings: list[str] = []
        self._reference = default_reference_data()
        # An action becomes effective on max(ex_date, first-knowable date): index once.
        self._actions_by_effective: dict[date, list[CorporateAction]] = defaultdict(list)
        for action in market.actions:
            effective = max(action.ex_date, action.available_at.date())
            self._actions_by_effective[effective].append(action)

    # ------------------------------------------------------------------ unit help
    def _to_quote_unit(
        self, amount: Decimal, currency: str, security_id: SecurityId
    ) -> Decimal | None:
        if currency == "GBX":
            return amount
        try:
            return self._reference.convert(amount, currency, "GBX")
        except ReferenceDataError:
            self._warnings.append(
                f"{security_id}: {currency} cash amount not convertible to GBX — skipped"
            )
            return None

    # -------------------------------------------------------------- action events
    def _apply_actions(self, portfolio: Portfolio, day: date) -> None:
        """Apply knowable corporate actions to held positions.

        Normal case: the action applies on its ex-date. Late knowledge: it applies on the
        first day it became knowable (never retroactively). The effective-date index
        guarantees available_at <= end of ``day``."""
        for action in self._actions_by_effective.get(day, ()):
            if isinstance(action, Split):
                mark = self._market.close_on_or_before(action.security_id, day)
                if mark is not None and portfolio.quantity(action.security_id) > 0:
                    portfolio.apply_split(
                        action.security_id, action.new_shares, action.old_shares, mark[1], day
                    )
            elif isinstance(action, Dividend):
                per_share = self._to_quote_unit(action.amount, action.currency, action.security_id)
                if per_share is not None:
                    portfolio.credit_dividend(
                        action.security_id, per_share, day, special=action.special
                    )
            elif isinstance(action, Merger) and action.cash_amount is not None:
                proceeds = self._to_quote_unit(
                    action.cash_amount, action.cash_currency or "", action.security_id
                )
                portfolio.resolve_delisting(
                    action.security_id, proceeds, day, note="merger cash consideration"
                )
            elif isinstance(action, DelistingAction):
                proceeds = Decimal(0) if action.reason is DelistingReason.FAILURE else None
                portfolio.resolve_delisting(
                    action.security_id,
                    proceeds,
                    day,
                    note=f"delisting ({action.reason.value})",
                )

    def _marks(self, portfolio: Portfolio, day: date) -> dict[SecurityId, Decimal]:
        marks: dict[SecurityId, Decimal] = {}
        for security_id in portfolio.positions():
            found = self._market.close_on_or_before(security_id, day)
            if found is None:
                raise LedgerError(f"held position {security_id} has no price at all by {day}")
            marks[security_id] = found[1]
        return marks

    # ------------------------------------------------------------------- the loop
    def run(self, strategy: Strategy) -> RunResult:
        config = self._config
        started = datetime.now(UTC)
        sessions = self._calendar.sessions_between(config.start, config.end)
        rebalance_days = _rebalance_days(config, sessions)

        portfolio = Portfolio(config.initial_cash, config.start)
        daily_rows: list[dict[str, object]] = []

        for index, day in enumerate(sessions):
            self._apply_actions(portfolio, day)

            if day in rebalance_days:
                # Decision clock is the PREVIOUS session even on the run's first day —
                # a same-day clock would let the strategy see the fill-day close.
                decision_clock = (
                    sessions[index - 1] if index > 0 else self._calendar.previous_trading_day(day)
                )
                context = BacktestContext(
                    clock=decision_clock,
                    market=self._market,
                    universe_query=self._universe_query,
                    universe=config.universe,
                    mic=config.mic,
                )
                value = portfolio.value(self._marks(portfolio, day))
                targets = strategy(context, portfolio.positions(), value)
                self._execute(portfolio, targets, day)

            marks = self._marks(portfolio, day)
            value = portfolio.value(marks)
            replayed_cash, replayed_positions = replay(portfolio.events())
            if replayed_cash != portfolio.cash or replayed_positions != portfolio.positions():
                raise LedgerError(f"accounting identity broken on {day}")
            daily_rows.append(
                {
                    "date": day,
                    "value": float(value),
                    "cash": float(portfolio.cash),
                    "positions": len(portfolio.positions()),
                }
            )

        events = pl.DataFrame(
            [e.model_dump(mode="json") for e in portfolio.events()],
        )
        daily = pl.DataFrame(daily_rows)
        return RunResult(
            config=config,
            daily=daily,
            events=events,
            git_commit=_git_commit(),
            started_at=started,
            warnings=list(self._warnings),
        )

    def _execute(self, portfolio: Portfolio, targets: dict[SecurityId, int], day: date) -> None:
        """Execute to target share counts at the day's close. Sells first (frees cash).

        Costs (QNT-053 parameters, applied here): commission + half-spread on both sides,
        stamp duty on purchases only."""
        config = self._config
        bps = Decimal("0.0001")
        sell_cost = (config.commission_bps + config.spread_bps / 2) * bps
        buy_cost = (config.commission_bps + config.spread_bps / 2 + config.stamp_duty_bps) * bps

        current = portfolio.positions()
        orders = {
            sid: targets.get(sid, 0) - current.get(sid, 0) for sid in set(current) | set(targets)
        }
        for phase in ("sell", "buy"):
            for security_id in sorted(orders):
                delta = orders[security_id]
                if (phase == "sell" and delta >= 0) or (phase == "buy" and delta <= 0):
                    continue
                found = self._market.close_on_or_before(security_id, day)
                if found is None or found[0] != day:
                    self._warnings.append(
                        f"{day}: no same-day print for {security_id}; order skipped"
                    )
                    continue
                price = found[1]
                shares = abs(delta)
                if delta < 0:
                    portfolio.sell(security_id, shares, price, price * shares * sell_cost, day)
                else:
                    cost_rate = buy_cost
                    notional = price * shares
                    total = notional * (1 + cost_rate)
                    if total > portfolio.cash:  # afford what we can, whole shares only
                        shares = int(portfolio.cash / (price * (1 + cost_rate)))
                        if shares <= 0:
                            continue
                        notional = price * shares
                    portfolio.buy(security_id, shares, price, notional * cost_rate, day)


def write_run(result: RunResult, root: Path) -> Path:
    directory = root / result.config.name
    if directory.exists():
        raise LedgerError(f"{directory} exists; runs are never overwritten — rename the run")
    directory.mkdir(parents=True)
    (directory / "config.json").write_text(result.config.model_dump_json(indent=2))
    (directory / "meta.json").write_text(
        json.dumps(
            {
                "config_hash": result.config.config_hash(),
                "git_commit": result.git_commit,
                "started_at": result.started_at.isoformat(),
                "warnings": result.warnings,
            },
            indent=2,
        )
    )
    result.daily.write_parquet(directory / "daily.parquet")
    result.events.write_parquet(directory / "events.parquet")
    return directory
