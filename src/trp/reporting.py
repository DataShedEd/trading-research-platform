"""Self-contained HTML run reports (QNT-102): evaluation without tool-hopping.

One page per run, generated INTO the immutable run record from its own artefacts plus
the benchmark series: headline metrics, equity vs benchmark (log, indexed), drawdown,
rolling windows, annual excess bars, costs and turnover, and the run's warnings. Every
chart is inline SVG; the file makes zero external requests and opens anywhere.

`comparison_report` overlays several runs' equity and drawdown curves with an aligned
metrics table — the "three variants side by side" view that makes a registry useful.
"""

import io
import json
from datetime import UTC, date, datetime, time
from html import escape
from itertools import pairwise
from pathlib import Path
from typing import Any

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt
import polars as pl

_STYLE = """
body { font-family: -apple-system, 'Segoe UI', sans-serif; margin: 2rem auto; max-width: 70rem;
       color: #1a1a1a; }
h1 { font-size: 1.4rem; } h2 { font-size: 1.1rem; margin-top: 2rem; }
table { border-collapse: collapse; margin: 0.5rem 0; font-size: 0.9rem; }
td, th { border: 1px solid #ddd; padding: 0.3rem 0.7rem; text-align: right; }
th { background: #f5f5f5; } td:first-child, th:first-child { text-align: left; }
figure { margin: 1rem 0; } svg { max-width: 100%; height: auto; }
.warn { color: #8a4b00; font-size: 0.85rem; }
.meta { color: #666; font-size: 0.85rem; }
"""


def _svg(figure: object) -> str:
    buffer = io.StringIO()
    figure.savefig(buffer, format="svg", bbox_inches="tight")  # type: ignore[attr-defined]
    plt.close(figure)  # type: ignore[arg-type]
    svg = buffer.getvalue()
    return svg[svg.index("<svg") :]


def _benchmark_curve(config: dict[str, Any], dates: list[date]) -> list[float] | None:
    """The benchmark's indexed value on the run's dates, or None without a benchmark."""
    name = config.get("benchmark")
    if not isinstance(name, str) or not name:
        return None
    from trp.backtest.benchmark import load_benchmark
    from trp.config import load_settings

    as_of = datetime.combine(dates[-1], time(23, 59, 59), tzinfo=UTC)
    returns = load_benchmark(
        name, load_settings().canonical_dir / "benchmarks", as_of=as_of
    ).returns
    by_date = dict(zip(returns["date"].to_list(), returns["ret"].to_list(), strict=True))
    level, out = 1.0, []
    for day in dates:
        level *= 1 + by_date.get(day, 0.0)
        out.append(level)
    return out


def _drawdown(values: list[float]) -> list[float]:
    peak, out = float("-inf"), []
    for value in values:
        peak = max(peak, value)
        out.append(value / peak - 1)
    return out


def _metric_rows(metrics: dict[str, Any]) -> list[tuple[str, str]]:
    def pct(x: object) -> str:
        return f"{x:+.2%}" if isinstance(x, int | float) else "n/a"

    def num(x: object) -> str:
        return f"{x:.2f}" if isinstance(x, int | float) else "n/a"

    relative = metrics.get("relative") or {}
    rows = [
        ("Total return", pct(metrics.get("total_return"))),
        ("CAGR", pct(metrics.get("cagr"))),
        ("Volatility (ann.)", pct(metrics.get("annualised_volatility"))),
        (f"Sharpe (rf {pct(metrics.get('risk_free_rate'))})", num(metrics.get("sharpe"))),
        ("Sortino", num(metrics.get("sortino"))),
        ("Max drawdown", pct(metrics.get("max_drawdown"))),
        ("Calmar", num(metrics.get("calmar"))),
        ("Hit rate (days)", pct(metrics.get("hit_rate_periods"))),
        ("Hit rate (positions)", pct(metrics.get("hit_rate_positions"))),
    ]
    if metrics.get("beta") is not None:
        rows.append(("Beta vs benchmark", num(metrics.get("beta"))))
    if relative:
        rows += [
            ("Benchmark total return", pct(relative.get("benchmark_total_return"))),
            ("Excess CAGR vs benchmark", pct(relative.get("excess_cagr"))),
            ("Tracking error", pct(relative.get("tracking_error"))),
            ("Information ratio", num(relative.get("information_ratio"))),
        ]
    return rows


def _daily_returns(values: list[float]) -> list[float]:
    return [b / a - 1 for a, b in pairwise(values) if a > 0]


def _beta(strategy: list[float], benchmark: list[float]) -> float | None:
    n = min(len(strategy), len(benchmark))
    if n < 60:
        return None
    s, b = strategy[:n], benchmark[:n]
    mean_s, mean_b = sum(s) / n, sum(b) / n
    var_b = sum((x - mean_b) ** 2 for x in b) / (n - 1)
    if var_b <= 0:
        return None
    cov = sum((x - mean_s) * (y - mean_b) for x, y in zip(s, b, strict=True)) / (n - 1)
    return cov / var_b


def _annual_table(dates: list[date], values: list[float], benchmark: list[float] | None) -> str:
    """Year | Strategy | Benchmark | Excess — computed from the curves themselves."""
    frame = pl.DataFrame({"date": dates, "value": values}).with_columns(
        pl.col("date").dt.year().alias("year")
    )
    if benchmark:
        frame = frame.with_columns(pl.Series("bench", benchmark))
    rows = ""
    previous_value: float | None = None
    previous_bench: float | None = None
    for (year,), group in sorted(frame.partition_by("year", as_dict=True).items()):
        start_value = previous_value if previous_value is not None else group["value"][0]
        strategy_return = group["value"][-1] / start_value - 1
        cells = f"<td>{year}</td><td>{strategy_return:+.1%}</td>"
        if benchmark:
            start_bench = previous_bench if previous_bench is not None else group["bench"][0]
            bench_return = group["bench"][-1] / start_bench - 1
            cells += f"<td>{bench_return:+.1%}</td><td>{strategy_return - bench_return:+.1%}</td>"
            previous_bench = group["bench"][-1]
        rows += f"<tr>{cells}</tr>"
        previous_value = group["value"][-1]
    header = "<th>Year</th><th>Strategy</th>"
    if benchmark:
        header += "<th>Benchmark</th><th>Excess</th>"
    return f"<table><tr>{header}</tr>{rows}</table>"


def _rolling_window_table(
    dates: list[date], values: list[float], benchmark: list[float] | None
) -> str:
    """Rolling 1y/3y/5y annualised returns and excess, sampled at each year end —
    computed from the curves so 3y/5y need no re-run of the record."""

    def annualised(window_years: int, index: int) -> tuple[float | None, float | None]:
        target = dates[index].replace(year=dates[index].year - window_years)
        starts = [i for i, d in enumerate(dates) if d >= target]
        if not starts or (starts[0] == 0 and dates[0] > target):
            return None, None
        start = starts[0]
        if (dates[index] - dates[start]).days < window_years * 360:
            return None, None
        strategy = (values[index] / values[start]) ** (1 / window_years) - 1
        bench = (
            (benchmark[index] / benchmark[start]) ** (1 / window_years) - 1 if benchmark else None
        )
        return strategy, bench

    year_ends = [
        i for i, d in enumerate(dates) if i + 1 == len(dates) or dates[i + 1].year != d.year
    ]
    rows = ""
    for index in year_ends:
        cells = f"<td>{dates[index]}</td>"
        for window in (1, 3, 5):
            strategy, bench = annualised(window, index)
            if strategy is None:
                cells += "<td>—</td><td>—</td>"
            else:
                excess = f"{strategy - bench:+.1%}" if bench is not None else "—"
                cells += f"<td>{strategy:+.1%}</td><td>{excess}</td>"
        rows += f"<tr>{cells}</tr>"
    return (
        "<table><tr><th>As at</th><th>1y</th><th>1y excess</th><th>3y ann.</th>"
        "<th>3y excess</th><th>5y ann.</th><th>5y excess</th></tr>" + rows + "</table>"
    )


def _drawdown_episodes(
    dates: list[date], values: list[float], benchmark: list[float] | None, top: int = 5
) -> str:
    """Largest drawdowns: start (prior peak), trough, recovery, duration, depth, and the
    benchmark's drawdown over the same start→trough window."""
    episodes: list[tuple[int, int, int | None]] = []
    peak_index = 0
    trough_index = 0
    in_drawdown = False
    for i, value in enumerate(values):
        if value >= values[peak_index]:
            if in_drawdown:
                episodes.append((peak_index, trough_index, i))
                in_drawdown = False
            peak_index = i
        else:
            if not in_drawdown or value < values[trough_index]:
                trough_index = i
            in_drawdown = True
    if in_drawdown:
        episodes.append((peak_index, trough_index, None))
    episodes.sort(key=lambda e: values[e[1]] / values[e[0]])
    rows = ""
    for peak, trough, recovery in episodes[:top]:
        depth = values[trough] / values[peak] - 1
        bench_depth = f"{benchmark[trough] / benchmark[peak] - 1:+.1%}" if benchmark else "—"
        recovered = str(dates[recovery]) if recovery is not None else "not recovered"
        duration = (dates[recovery] if recovery is not None else dates[-1]) - dates[peak]
        rows += (
            f"<tr><td>{dates[peak]}</td><td>{dates[trough]}</td><td>{recovered}</td>"
            f"<td>{duration.days}d</td><td>{depth:+.1%}</td><td>{bench_depth}</td></tr>"
        )
    return (
        "<table><tr><th>Peak</th><th>Trough</th><th>Recovered</th><th>Duration</th>"
        "<th>Strategy DD</th><th>Benchmark same window</th></tr>" + rows + "</table>"
    )


def _load_run(run_dir: Path) -> dict[str, Any]:
    out = {
        "name": run_dir.name,
        "config": json.loads((run_dir / "config.json").read_text()),
        "meta": json.loads((run_dir / "meta.json").read_text()),
        "daily": pl.read_parquet(run_dir / "daily.parquet"),
        "rebalances": pl.read_parquet(run_dir / "rebalances.parquet"),
    }
    metrics_path = run_dir / "metrics.json"
    out["metrics"] = json.loads(metrics_path.read_text()) if metrics_path.exists() else {}
    relative_path = run_dir / "relative.json"
    if relative_path.exists():
        out["metrics"]["relative"] = json.loads(relative_path.read_text())
    rolling_path = run_dir / "rolling.parquet"
    out["rolling"] = pl.read_parquet(rolling_path) if rolling_path.exists() else None
    events_path = run_dir / "events.parquet"
    out["events"] = pl.read_parquet(events_path) if events_path.exists() else None
    return out


def _portfolio_behaviour(run: dict[str, Any]) -> str:
    daily, rebalances, events = run["daily"], run["rebalances"], run["events"]
    holdings = daily["positions"].to_list()
    cash_share = [
        float(c) / float(v) for c, v in zip(daily["cash"], daily["value"], strict=True) if v
    ]
    active = rebalances.filter(pl.col("trades") > 0) if rebalances.height else rebalances
    rows = [
        ("Average holdings", f"{sum(holdings) / len(holdings):.1f}"),
        ("Average one-way turnover / rebalance", f"{float(active['turnover'].mean() or 0):.1%}"),
        ("Max one-way turnover", f"{float(active['turnover'].max() or 0):.1%}"),
        ("Average cash drag", f"{sum(cash_share) / len(cash_share):.2%}"),
    ]
    if events is not None:
        kinds = dict(events.group_by("kind").len().iter_rows())
        rows += [
            ("Delisting events (proceeds)", str(kinds.get("delisting_proceeds", 0))),
            ("Delisting events (write-off)", str(kinds.get("delisting_writeoff", 0))),
        ]
    warnings = run["meta"].get("warnings", [])
    forced = sum(1 for w in warnings if "forced exit" in str(w))
    rows.append(("Forced exits (DEC-019 backstop)", str(forced)))
    return (
        "<table>"
        + "".join(f"<tr><td>{escape(k)}</td><td>{escape(v)}</td></tr>" for k, v in rows)
        + "</table>"
    )


_DEC016_NAMES = (
    "SABMiller, Xstrata, ENRC, ICAP, AMEC, TUI Travel, Worldpay, Invensys, "
    "International Power, Autonomy, Friends Life, Cable & Wireless, Home Retail, "
    "African Barrick, Essar, Cadbury (+ Just Eat's 43-day 2019 tail)"
)


def _data_quality(run: dict[str, Any]) -> str:
    config, meta = run["config"], run["meta"]
    events = run["events"]
    approximated = 0
    if events is not None and "note" in (events.columns or []):
        approximated = events.filter(
            (pl.col("kind") == "delisting_proceeds")
            & pl.col("note").str.contains("last traded close")
        ).height
    warnings = meta.get("warnings", [])
    items = [
        f"Research coverage starts {config.get('start')} (DEC-014).",
        "Known survivorship-related missingness, direction unquantified (DEC-016/025): "
        f"{_DEC016_NAMES} — ≈2.5% of member-months; the exclusion list may only shrink.",
        "Prices/dividends/splits: unit-repaired dataset (DEC-020, source eodhd-gbx2); "
        "originals retained for audit.",
        "Fundamental availability is IMPUTED (DEC-007/024) — irrelevant to price-only "
        "factors, disclosed for any fundamental sleeve.",
        f"Delistings without sourced terms resolve at the last traded close (DEC-023): "
        f"{approximated} such approximations in this run.",
        f"Unresolved run warnings: {len(warnings)}.",
    ]
    return "<ul class='meta'>" + "".join(f"<li>{escape(i)}</li>" for i in items) + "</ul>"


def run_report(run_dir: Path) -> Path:
    run = _load_run(run_dir)
    daily, config, metrics = run["daily"], run["config"], run["metrics"]
    dates = daily["date"].to_list()
    values = [float(v) for v in daily["value"]]
    indexed = [v / values[0] for v in values]
    benchmark = _benchmark_curve(config, dates)
    if benchmark and metrics.get("beta") is None:
        metrics["beta"] = _beta(_daily_returns(values), _daily_returns(benchmark))

    figure, (top, bottom) = plt.subplots(2, 1, figsize=(9.5, 6), sharex=True, height_ratios=[3, 1])
    top.plot(dates, indexed, label=run["name"], linewidth=1.2)
    if benchmark:
        top.plot(dates, benchmark, label=config.get("benchmark"), linewidth=1.0, alpha=0.8)
    top.set_yscale("log")
    top.set_ylabel("growth of 1 (log)")
    top.legend(loc="upper left", fontsize=8)
    top.grid(alpha=0.3)
    bottom.fill_between(dates, _drawdown(values), 0, color="#b23b3b", alpha=0.6)
    bottom.set_ylabel("drawdown")
    bottom.grid(alpha=0.3)
    equity_svg = _svg(figure)

    rolling_svg = ""
    rolling = run["rolling"]
    if rolling is not None and rolling.height:
        window = rolling.filter((pl.col("window") == "12m") & pl.col("sharpe").is_not_null())
        if window.height:
            figure, axis = plt.subplots(figsize=(9.5, 2.6))
            axis.plot(window["date"].to_list(), window["sharpe"].to_list(), linewidth=1.0)
            axis.axhline(0, color="#999", linewidth=0.7)
            axis.set_ylabel("rolling 12m Sharpe")
            axis.grid(alpha=0.3)
            rolling_svg = f"<figure>{_svg(figure)}</figure>"

    annual_svg = ""
    annual = metrics.get("annual_returns") or {}
    if annual and benchmark:
        by_year_strategy = {int(k): v for k, v in annual.items()}
        bench_returns = pl.DataFrame({"date": dates, "level": benchmark})
        bench_by_year = {}
        for (year,), group in sorted(
            bench_returns.with_columns(pl.col("date").dt.year().alias("y"))
            .partition_by("y", as_dict=True)
            .items()
        ):
            bench_by_year[year] = group["level"][-1] / group["level"][0] - 1
        years = sorted(set(by_year_strategy) & set(bench_by_year))
        excess = [by_year_strategy[y] - bench_by_year[y] for y in years]
        figure, axis = plt.subplots(figsize=(9.5, 2.6))
        axis.bar(years, excess, color=["#2c7a3f" if e >= 0 else "#b23b3b" for e in excess])
        axis.axhline(0, color="#999", linewidth=0.7)
        axis.set_ylabel("annual excess vs benchmark")
        axis.grid(alpha=0.3, axis="y")
        annual_svg = f"<figure>{_svg(figure)}</figure>"

    rebalances = run["rebalances"]
    costs_row = ""
    if rebalances.height:
        total_costs = float(rebalances["costs"].sum() or 0)
        mean_turnover = rebalances["turnover"].mean()
        costs_row = (
            f"<p class='meta'>{rebalances.height} rebalances, "
            f"{int(rebalances['trades'].sum())} trades, total costs "
            f"£{total_costs / 100:,.0f}, mean one-way turnover "
            f"{float(mean_turnover or 0):.1%}/rebalance</p>"
        )

    metric_table = "".join(
        f"<tr><td>{escape(label)}</td><td>{escape(value)}</td></tr>"
        for label, value in _metric_rows(metrics)
    )
    warnings = run["meta"].get("warnings", [])
    warning_html = (
        f"<p class='warn'>{len(warnings)} run warnings; first: {escape(warnings[0])}</p>"
        if warnings
        else ""
    )
    flags = metrics.get("flags") or []
    flags_html = "".join(f"<p class='warn'>{escape(f)}</p>" for f in flags)

    html = f"""<!DOCTYPE html><html><head><meta charset="utf-8">
<title>{escape(run["name"])}</title><style>{_STYLE}</style></head><body>
<h1>{escape(run["name"])}</h1>
<p class="meta">{escape(config.get("factor", ""))} v{config.get("factor_version")} ·
{escape(config.get("universe", ""))} · {config.get("start")} → {config.get("end")} ·
top {config.get("top_n")} · config <code>{escape(run["meta"].get("config_hash", ""))}</code> ·
commit <code>{escape(str(run["meta"].get("git_commit", ""))[:12])}</code></p>
<h2>Metrics</h2><table>{metric_table}</table>{costs_row}{flags_html}{warning_html}
<h2>Equity and drawdown</h2><figure>{equity_svg}</figure>
<h2>Annual results</h2>{_annual_table(dates, values, benchmark)}
{f"<h2>Annual excess</h2>{annual_svg}" if annual_svg else ""}
{f"<h2>Rolling 12m Sharpe</h2>{rolling_svg}" if rolling_svg else ""}
<h2>Rolling windows (year ends)</h2>{_rolling_window_table(dates, values, benchmark)}
<h2>Largest drawdowns</h2>{_drawdown_episodes(dates, values, benchmark)}
<h2>Portfolio behaviour</h2>{_portfolio_behaviour(run)}
<h2>Data quality</h2>{_data_quality(run)}
<p class="meta">Conventions: DEC-014 coverage, DEC-016/025 gaps, DEC-017 timing/costs,
DEC-019/023 exits, DEC-020 unit repair. Generated from the immutable run record.</p>
</body></html>"""
    target = run_dir / "report.html"
    target.write_text(html)
    return target


def comparison_report(run_dirs: list[Path], target: Path | None = None) -> Path:
    runs = [_load_run(run_dir) for run_dir in run_dirs]
    figure, (top, bottom) = plt.subplots(
        2, 1, figsize=(9.5, 6.5), sharex=True, height_ratios=[3, 1]
    )
    for run in runs:
        dates = run["daily"]["date"].to_list()
        values = [float(v) for v in run["daily"]["value"]]
        top.plot(dates, [v / values[0] for v in values], label=run["name"], linewidth=1.1)
        bottom.plot(dates, _drawdown(values), linewidth=0.9)
    top.set_yscale("log")
    top.set_ylabel("growth of 1 (log)")
    top.legend(loc="upper left", fontsize=8)
    top.grid(alpha=0.3)
    bottom.set_ylabel("drawdown")
    bottom.grid(alpha=0.3)
    overlay_svg = _svg(figure)

    labels = [str(run["name"]) for run in runs]
    header = "".join(f"<th>{escape(label)}</th>" for label in labels)
    rows_html = ""
    extractors: list[tuple[str, Any]] = [
        ("CAGR", lambda m: m.get("cagr")),
        ("Volatility", lambda m: m.get("annualised_volatility")),
        ("Sharpe", lambda m: m.get("sharpe")),
        ("Max drawdown", lambda m: m.get("max_drawdown")),
        ("Excess CAGR", lambda m: (m.get("relative") or {}).get("excess_cagr")),
        ("Information ratio", lambda m: (m.get("relative") or {}).get("information_ratio")),
        ("Tracking error", lambda m: (m.get("relative") or {}).get("tracking_error")),
    ]
    for metric_label, extractor in extractors:
        cells = ""
        for run in runs:
            value = extractor(run["metrics"])
            cells += f"<td>{f'{value:.4f}' if isinstance(value, int | float) else '—'}</td>"
        rows_html += f"<tr><td>{metric_label}</td>{cells}</tr>"

    html = f"""<!DOCTYPE html><html><head><meta charset="utf-8">
<title>comparison</title><style>{_STYLE}</style></head><body>
<h1>Comparison: {escape(", ".join(labels))}</h1>
<table><tr><th>metric</th>{header}</tr>{rows_html}</table>
<h2>Equity and drawdown</h2><figure>{overlay_svg}</figure>
<p class="meta">Metrics from each run's immutable record; missing values shown as —.</p>
</body></html>"""
    if target is None:
        from trp.config import load_settings

        reports = load_settings().derived_dir / "reports"
        reports.mkdir(parents=True, exist_ok=True)
        target = reports / f"comparison-{'-vs-'.join(labels)[:80]}.html"
    target.write_text(html)
    return target
