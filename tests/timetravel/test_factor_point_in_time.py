"""QNT-049: the Epic 7 acceptance gate — every shipped definition, differentially.

One synthetic canonical store (three securities, two+ years of bars, dividends,
five annual reporting periods, one restatement); every factor and composite in the
registry is computed at t against the restricted store and against a future-extended
store, asserting byte-identical panels. No expected values needed: the differential form
catches leaks in components nobody thought to test individually.
"""

# ruff: noqa: F811 - pytest fixtures are imported by name and reused as parameters

from datetime import UTC, date, datetime, timedelta

import pytest

from tests.factors.test_quality import SNAPSHOT, records
from tests.factors.test_returns import daily_bars
from tests.factors.test_value import fx_root, store  # noqa: F401
from trp.canonical.fundamentals.storage import write_fundamentals
from trp.domain.corporate_actions import Dividend
from trp.domain.identifiers import new_security_id
from trp.factors.compute import ComputeContext, compute_factor
from trp.factors.registry import FactorRegistry

pytestmark = pytest.mark.timetravel

REGISTRY = FactorRegistry.load()
T = date(2021, 6, 30)
AS_OF = datetime(2021, 7, 1, tzinfo=UTC)


def build_world(store):  # type: ignore[no-untyped-def]
    """Three securities, five annual periods each, dividends, distinct price paths."""
    ids = sorted(new_security_id() for _ in range(3))
    incomes = {ids[0]: 80, ids[1]: 120, ids[2]: 200}
    for sid in ids:
        for year in range(2016, 2021):
            write_fundamentals(
                records(
                    sid,
                    {
                        **SNAPSHOT,
                        "net_income": str(incomes[sid] + year - 2016),
                        "shares_outstanding": "1000",
                        "dividends_paid": "-40",
                        "share_buybacks": "-10",
                    },
                    date(year, 12, 31),
                    datetime(year + 1, 4, 30, tzinfo=UTC),
                ),
                store,
                source="fixture",
            )
    bars = []
    for offset, sid in enumerate(ids):
        base = str(300 + 100 * offset)
        wiggle = {date(2020, 9, 1): str(350 + 100 * offset)}
        bars.extend(daily_bars(sid, date(2019, 12, 2), T, base, wiggle))
    actions = [
        Dividend(
            security_id=ids[0],
            ex_date=date(2021, 2, 1),
            source="t",
            available_at=datetime(2021, 2, 1, tzinfo=UTC),
            amount=Decimal("5"),
            currency="GBX",
        )
    ]
    return ids, bars, actions


from decimal import Decimal  # noqa: E402


def context_of(store, fx_root, ids, bars, actions, end=T, as_of=AS_OF):  # type: ignore[no-untyped-def]
    return ComputeContext(
        security_ids=list(ids),
        end=end,
        as_of=as_of,
        bars=bars,
        actions=actions,
        fundamentals_root=store,
        fx_root=fx_root,
    )


def extended(store, ids, bars, actions):  # type: ignore[no-untyped-def]
    """The same store plus everything a leaky implementation would love: future bars,
    a filing knowable after t, a restatement knowable after t, a late-published action."""
    future_bars = []
    for sid in ids:
        future_bars.extend(daily_bars(sid, T + timedelta(days=1), date(2021, 12, 31), "9"))
    for sid in ids:
        write_fundamentals(
            records(
                sid,
                {**SNAPSHOT, "net_income": "9999", "shares_outstanding": "1"},
                date(2021, 12, 31),
                datetime(2022, 4, 30, tzinfo=UTC),
            ),
            store,
            source="fixture",
        )
        write_fundamentals(
            records(
                sid,
                {"net_income": "1"},
                date(2020, 12, 31),
                datetime(2021, 9, 30, tzinfo=UTC),
                revision=1,
            ),
            store,
            source="fixture",
        )
    late_action = Dividend(
        security_id=ids[0],
        ex_date=date(2021, 5, 4),
        source="t",
        available_at=datetime(2021, 8, 1, tzinfo=UTC),
        amount=Decimal("50"),
        currency="GBX",
    )
    return bars + future_bars, [*actions, late_action]


def panel(context) -> list[tuple]:  # type: ignore[no-untyped-def, type-arg]
    rows = []
    for definition in REGISTRY.definitions():
        frame = compute_factor(definition, context)
        for row in frame.select("security_id", "status", "value").to_dicts():
            rows.append((definition.name, definition.version, *row.values()))
    return rows


def test_every_shipped_definition_is_invariant_to_future_data(store, fx_root) -> None:  # type: ignore[no-untyped-def]
    ids, bars, actions = build_world(store)
    clean = panel(context_of(store, fx_root, ids, bars, actions))
    assert sum(1 for row in clean if row[3] == "ok") > len(clean) / 2  # a real panel
    bars2, actions2 = extended(store, ids, bars, actions)
    polluted = panel(context_of(store, fx_root, ids, bars2, actions2))
    assert clean == polluted


def test_restatement_boundary_for_quality_and_value(store, fx_root) -> None:  # type: ignore[no-untyped-def]
    ids, bars, actions = build_world(store)
    restated_at = datetime(2021, 9, 30, tzinfo=UTC)
    write_fundamentals(
        records(ids[0], {"net_income": "1"}, date(2020, 12, 31), restated_at, revision=1),
        store,
        source="fixture",
    )
    for factor in ("roe", "earnings_yield"):
        before = compute_factor(
            REGISTRY.get(factor),
            context_of(
                store,
                fx_root,
                ids,
                bars,
                actions,
                end=restated_at.date() - timedelta(days=1),
                as_of=restated_at - timedelta(days=1),
            ),
        ).to_dicts()[0]
        after = compute_factor(
            REGISTRY.get(factor),
            context_of(
                store,
                fx_root,
                ids,
                bars,
                actions,
                end=restated_at.date() + timedelta(days=1),
                as_of=restated_at + timedelta(days=1),
            ),
        ).to_dicts()[0]
        assert before["value"] != after["value"], factor
        assert before["value"] == pytest.approx(
            {"roe": (80 + 4) / 500, "earnings_yield": 84 / (1000 * 3.5)}[factor]
        )


def test_availability_lag_boundary(store, fx_root) -> None:  # type: ignore[no-untyped-def]
    ids, bars, actions = build_world(store)
    available = datetime(2021, 4, 30, tzinfo=UTC)  # FY2020 filings become knowable
    day_before = compute_factor(
        REGISTRY.get("roe"),
        context_of(
            store,
            fx_root,
            ids,
            bars,
            actions,
            end=available.date() - timedelta(days=1),
            as_of=available - timedelta(days=1),
        ),
    ).to_dicts()[0]
    day_after = compute_factor(
        REGISTRY.get("roe"),
        context_of(
            store,
            fx_root,
            ids,
            bars,
            actions,
            end=available.date() + timedelta(days=1),
            as_of=available + timedelta(days=1),
        ),
    ).to_dicts()[0]
    assert day_before["value"] == pytest.approx((80 + 3) / 500)  # FY2019: 83
    assert day_after["value"] == pytest.approx((80 + 4) / 500)  # FY2020: 84


def test_universe_membership_bounds_the_cross_section(store, fx_root) -> None:  # type: ignore[no-untyped-def]
    """A security whose data sits in the store but who is NOT in the passed universe
    cannot influence anyone's standardised score."""
    ids, bars, actions = build_world(store)
    pair = ids[:2]
    with_bystander_data = compute_factor(
        REGISTRY.get("qvm_equal"), context_of(store, fx_root, pair, bars, actions)
    ).to_dicts()
    # remove the third security's bars entirely: if it influenced anything, this differs
    pair_bars = [bar for bar in bars if bar.security_id in set(pair)]
    without = compute_factor(
        REGISTRY.get("qvm_equal"), context_of(store, fx_root, pair, pair_bars, actions)
    ).to_dicts()
    assert with_bystander_data == without


def test_negative_control_a_period_end_join_fails_the_suite(store, fx_root, monkeypatch) -> None:  # type: ignore[no-untyped-def]
    """The classic leak: resolving fundamentals by period end, ignoring available_at.
    Under it, at least three of the suite's core assertions break."""
    import trp.factors.fundamental as fundamental_module

    honest = fundamental_module.fundamentals

    def leaky(root, security_ids, line_items, *, as_of, **kwargs):  # type: ignore[no-untyped-def]
        return honest(
            root, security_ids, line_items, as_of=datetime(2099, 1, 1, tzinfo=UTC), **kwargs
        )

    ids, bars, actions = build_world(store)
    clean_roe = compute_factor(
        REGISTRY.get("roe"), context_of(store, fx_root, ids, bars, actions)
    ).to_dicts()

    monkeypatch.setattr(fundamental_module, "fundamentals", leaky)
    failures = 0
    # 1. Future filings are no longer inert.
    write_fundamentals(
        records(
            ids[0],
            {**SNAPSHOT, "net_income": "9999", "shares_outstanding": "1000"},
            date(2021, 12, 31),
            datetime(2022, 4, 30, tzinfo=UTC),
        ),
        store,
        source="fixture",
    )
    leaked_roe = compute_factor(
        REGISTRY.get("roe"), context_of(store, fx_root, ids, bars, actions)
    ).to_dicts()
    if leaked_roe != clean_roe:
        failures += 1
    # 2. The availability boundary vanishes: the day-before value already uses FY2020.
    early = compute_factor(
        REGISTRY.get("roe"),
        context_of(
            store,
            fx_root,
            ids,
            bars,
            actions,
            end=date(2021, 4, 29),
            as_of=datetime(2021, 4, 29, tzinfo=UTC),
        ),
    ).to_dicts()[0]
    if early["value"] != pytest.approx((80 + 3) / 500):
        failures += 1
    # 3. A restatement knowable later already rewrites today.
    write_fundamentals(
        records(
            ids[1],
            {"net_income": "1"},
            date(2020, 12, 31),
            datetime(2021, 9, 30, tzinfo=UTC),
            revision=1,
        ),
        store,
        source="fixture",
    )
    restated_now = compute_factor(
        REGISTRY.get("roe"), context_of(store, fx_root, ids, bars, actions)
    ).to_dicts()[1]
    if restated_now["value"] == pytest.approx(1 / 500):
        failures += 1
    assert failures >= 3, "the leaky implementation slipped past the suite"
