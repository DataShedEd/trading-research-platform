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
        ("Hit rate (days)", pct(metrics.get("hit_rate_periods"))),
    ]
    if relative:
        rows += [
            ("Excess CAGR vs benchmark", pct(relative.get("excess_cagr"))),
            ("Tracking error", pct(relative.get("tracking_error"))),
            ("Information ratio", num(relative.get("information_ratio"))),
        ]
    return rows


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
    return out


def run_report(run_dir: Path) -> Path:
    run = _load_run(run_dir)
    daily, config, metrics = run["daily"], run["config"], run["metrics"]
    dates = daily["date"].to_list()
    values = [float(v) for v in daily["value"]]
    indexed = [v / values[0] for v in values]
    benchmark = _benchmark_curve(config, dates)

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
{f"<h2>Rolling</h2>{rolling_svg}" if rolling_svg else ""}
{f"<h2>Annual excess</h2>{annual_svg}" if annual_svg else ""}
<p class="meta">Conventions: DEC-014 coverage, DEC-016 gaps, DEC-017 timing/costs,
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
