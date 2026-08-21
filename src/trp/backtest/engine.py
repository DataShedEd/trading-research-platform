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
from bisect import bisect_left, bisect_right
from collections import defaultdict
from collections.abc import Callable, Sequence
from dataclasses import dataclass, field
from datetime import UTC, date, datetime
from decimal import Decimal
from pathlib import Path
from statistics import median

import polars as pl

from trp.backtest.config import BacktestConfig
from trp.backtest.context import BacktestContext
from trp.backtest.costs import (
    IMPACT_WINDOW_SESSIONS,
    CostModel,
    Side,
    StampExemption,
    no_exemptions,
)
from trp.backtest.portfolio import EventKind, LedgerError, Portfolio, replay
from trp.backtest.rebalance import one_way_turnover, rebalance_sessions
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

STALE_EXIT_DAYS = 15
"""Calendar days without a print before a holding is force-exited (DEC-019). Matches the
context's mark-staleness cap."""


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
        self._traded: dict[SecurityId, list[Decimal]] = defaultdict(list)
        by_sid: dict[SecurityId, list[tuple[date, Decimal]]] = defaultdict(list)
        for bar in bars:
            by_sid[bar.security_id].append((bar.trade_date, bar.close * bar.volume))
        for sid, series2 in by_sid.items():
            series2.sort()
            self._traded[sid] = [value for _, value in series2]
        self._bars_by_sid: dict[SecurityId, list[DailyBar]] = defaultdict(list)
        for bar in bars:
            self._bars_by_sid[bar.security_id].append(bar)
        for bar_list in self._bars_by_sid.values():
            bar_list.sort(key=lambda b: b.trade_date)
        self._actions_by_sid: dict[SecurityId, list[CorporateAction]] = defaultdict(list)
        for action in actions:
            self._actions_by_sid[action.security_id].append(action)

    def close_on_or_before(self, security_id: SecurityId, day: date) -> tuple[date, Decimal] | None:
        dates = self._dates.get(security_id)
        if not dates:
            return None
        index = bisect_right(dates, day)
        if index == 0:
            return None
        return self._closes[security_id][index - 1]

    def bars_for(
        self, security_ids: frozenset[SecurityId], start: date, end: date
    ) -> list[DailyBar]:
        """Per-security date slices — what lets factor computation at a rebalance touch a
        lookback window of member bars instead of the full multi-decade panel."""
        out: list[DailyBar] = []
        for security_id in sorted(security_ids):
            series = self._bars_by_sid.get(security_id, [])
            dates = self._dates.get(security_id, [])
            left = bisect_left(dates, start)
            right = bisect_right(dates, end)
            out.extend(series[left:right])
        return out

    def actions_for(self, security_ids: frozenset[SecurityId]) -> list[CorporateAction]:
        out: list[CorporateAction] = []
        for security_id in sorted(security_ids):
            out.extend(self._actions_by_sid.get(security_id, ()))
        return out

    def median_traded_value(
        self, security_id: SecurityId, day: date, window: int = IMPACT_WINDOW_SESSIONS
    ) -> Decimal | None:
        """Median close x volume over the trailing window of bars ON OR BEFORE ``day`` —
        the point-in-time liquidity input to the market-impact term. None with no bars."""
        dates = self._dates.get(security_id)
        if not dates:
            return None
        index = bisect_right(dates, day)
        if index == 0:
            return None
        values = self._traded[security_id][max(0, index - window) : index]
        return Decimal(median(values))


@dataclass
class RunResult:
    config: BacktestConfig
    daily: pl.DataFrame  # date, value, cash, positions
    events: pl.DataFrame
    rebalances: pl.DataFrame  # date, trades, traded_value, turnover, costs
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


class BacktestEngine:
    def __init__(
        self,
        config: BacktestConfig,
        market: MarketData,
        universe_query: UniverseQuery,
        is_stamp_exempt: StampExemption = no_exemptions,
        fundamentals_root: Path | None = None,
        fx_root: Path | None = None,
        shares_root: Path | None = None,
    ) -> None:
        self._config = config
        self._market = market
        self._universe_query = universe_query
        self._costs = CostModel(config, is_stamp_exempt)
        self._fundamentals_root = fundamentals_root
        self._fx_root = fx_root
        self._shares_root = shares_root
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
                if action.reason is DelistingReason.FAILURE:
                    proceeds = Decimal(0)
                else:
                    # DEC-023: without cash terms, the last traded close is the honest
                    # estimate for every non-failure exit — it approximates acquisition
                    # consideration and is what a forced seller would have realised.
                    found = self._market.close_on_or_before(action.security_id, day)
                    proceeds = found[1] if found is not None else None
                portfolio.resolve_delisting(
                    action.security_id,
                    proceeds,
                    day,
                    note=f"delisting ({action.reason.value})",
                )

    def _force_exit_stale(self, portfolio: Portfolio, day: date) -> None:
        """DEC-019: a holding with no print for more than STALE_EXIT_DAYS and no delisting
        record exits at its last traded close (value-neutral). Without this, securities
        whose delisting the vendor never recorded would be held as phantom positions at a
        frozen mark forever."""
        for security_id in list(portfolio.positions()):
            found = self._market.close_on_or_before(security_id, day)
            if found is None:  # pragma: no cover - a fill implies at least one print
                continue
            last_date, last_close = found
            if (day - last_date).days > STALE_EXIT_DAYS:
                portfolio.resolve_delisting(
                    security_id,
                    last_close,
                    day,
                    note=f"forced exit: no prints since {last_date}, no delisting record",
                )
                self._warnings.append(
                    f"{day}: forced exit of {security_id} at {last_close} "
                    f"(stale since {last_date}, no delisting record)"
                )

    def _decision_clock(self, sessions: Sequence[date], index: int) -> date:
        """The PREVIOUS session, even on the run's first day — a same-day clock would let
        the strategy see the fill-day close. Overridden ONLY by the QNT-057 negative
        control, which proves the leakage suite catches an engine that cheats here."""
        if index > 0:
            return sessions[index - 1]
        return self._calendar.previous_trading_day(sessions[index])

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
        rebalance_days = rebalance_sessions(sessions, config.rebalance, config.rebalance_offset)

        portfolio = Portfolio(config.initial_cash, config.start)
        daily_rows: list[dict[str, object]] = []
        rebalance_rows: list[dict[str, object]] = []

        for index, day in enumerate(sessions):
            self._apply_actions(portfolio, day)
            self._force_exit_stale(portfolio, day)

            if day in rebalance_days:
                decision_clock = self._decision_clock(sessions, index)
                context = BacktestContext(
                    clock=decision_clock,
                    market=self._market,
                    universe_query=self._universe_query,
                    universe=config.universe,
                    mic=config.mic,
                    fundamentals_root=self._fundamentals_root,
                    fx_root=self._fx_root,
                    shares_root=self._shares_root,
                )
                pre_trade_value = portfolio.value(self._marks(portfolio, day))
                targets = strategy(context, portfolio.positions(), pre_trade_value)
                events_before = len(portfolio.events())
                self._execute(portfolio, targets, day)
                trade_events = [
                    e
                    for e in portfolio.events()[events_before:]
                    if e.kind in (EventKind.BUY, EventKind.SELL) and e.price is not None
                ]
                fills = [(e.quantity_delta, e.price) for e in trade_events if e.price is not None]
                rebalance_rows.append(
                    {
                        "date": day,
                        "trades": len(fills),
                        "traded_value": float(
                            sum((abs(q) * p for q, p in fills), start=Decimal(0))
                        ),
                        "turnover": one_way_turnover(fills, pre_trade_value),
                        "costs": float(sum((e.costs for e in trade_events), start=Decimal(0))),
                    }
                )

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
        rebalances = pl.DataFrame(
            rebalance_rows,
            schema={
                "date": pl.Date,
                "trades": pl.Int64,
                "traded_value": pl.Float64,
                "turnover": pl.Float64,
                "costs": pl.Float64,
            },
        )
        return RunResult(
            config=config,
            daily=daily,
            events=events,
            rebalances=rebalances,
            git_commit=_git_commit(),
            started_at=started,
            warnings=list(self._warnings),
        )

    def _execute(self, portfolio: Portfolio, targets: dict[SecurityId, int], day: date) -> None:
        """Execute to target share counts at the day's close. Sells first (frees cash).

        Costs come from the QNT-053 ``CostModel`` — commission with a per-trade minimum,
        half-spread on both sides, stamp duty on purchases, market impact against the
        trailing median daily traded value at ``day`` — and are booked as the explicit
        ``costs`` field on each trade event."""
        current = portfolio.positions()
        orders = {
            sid: targets.get(sid, 0) - current.get(sid, 0) for sid in set(current) | set(targets)
        }
        # Sells first (they free cash), and within sells the net-POSITIVE ones first: a
        # dust position whose minimum commission exceeds its proceeds must be absorbed by
        # the cash the other sells raise, not crash a fully-invested book. A dust sell
        # that still cannot be afforded is skipped with a warning and exits later.
        sell_ids = sorted(sid for sid, delta in orders.items() if delta < 0)

        def sell_net(security_id: SecurityId) -> Decimal:
            found = self._market.close_on_or_before(security_id, day)
            if found is None or found[0] != day:
                return Decimal(0)
            price = found[1]
            shares = -orders[security_id]
            liquidity = self._market.median_traded_value(security_id, day)
            return (
                price * shares
                - self._costs.cost(security_id, Side.SELL, price * shares, liquidity).total
            )

        ordered_sells = sorted(sell_ids, key=lambda sid: (-sell_net(sid), sid))
        buy_ids = sorted(sid for sid, delta in orders.items() if delta > 0)
        for _phase, phase_ids in (("sell", ordered_sells), ("buy", buy_ids)):
            for security_id in phase_ids:
                delta = orders[security_id]
                found = self._market.close_on_or_before(security_id, day)
                if found is None or found[0] != day:
                    self._warnings.append(
                        f"{day}: no same-day print for {security_id}; order skipped"
                    )
                    continue
                price = found[1]
                liquidity = self._market.median_traded_value(security_id, day)
                shares = abs(delta)
                if delta < 0:
                    costs = self._costs.cost(security_id, Side.SELL, price * shares, liquidity)
                    if portfolio.cash + price * shares - costs.total < 0:
                        self._warnings.append(
                            f"{day}: dust sale of {security_id} costs more than it raises "
                            "and cash cannot absorb it; deferred"
                        )
                        continue
                    portfolio.sell(security_id, shares, price, costs.total, day)
                else:
                    shares = self._affordable_shares(
                        portfolio.cash, security_id, shares, price, liquidity
                    )
                    if shares <= 0:
                        continue
                    costs = self._costs.cost(security_id, Side.BUY, price * shares, liquidity)
                    portfolio.buy(security_id, shares, price, costs.total, day)

    def _affordable_shares(
        self,
        cash: Decimal,
        security_id: SecurityId,
        shares: int,
        price: Decimal,
        liquidity: Decimal | None,
    ) -> int:
        """Largest whole-share count with notional + costs within cash. Costs are
        monotonic in the share count, so proportional shrinking converges quickly."""
        while shares > 0:
            notional = price * shares
            total = notional + self._costs.cost(security_id, Side.BUY, notional, liquidity).total
            if total <= cash:
                return shares
            shares = min(shares - 1, int(shares * cash / total))
        return 0


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
    result.rebalances.write_parquet(directory / "rebalances.parquet")
    return directory
