# Trading Research Platform

Personal systematic equity research and trading platform. Initial focus: medium-term systematic
investing in UK equities, with architecture that extends to US and European markets.

The platform's first job is unglamorous and critical: **reconstruct the information set an investor
genuinely had at any historical date** — no survivorship bias, no look-ahead, corporate actions
handled correctly. Factor research, backtesting, portfolio construction, and execution are built on
top of that foundation, in that order.

## Non-negotiable principles

- **Point-in-time correctness** — a query `as_of` date `t` never returns data whose
  `available_at > t`. See `docs/QUANT_PRINCIPLES.md`.
- **No survivorship bias** — delisted, bankrupt, acquired, and renamed securities stay in the data.
- **Raw is immutable** — provider payloads are stored verbatim; canonical data is derived by
  deterministic, re-runnable transforms.
- **Reproducibility** — every research result records code version, data versions, parameters,
  universe, and assumptions.

## Project memory

The repository, not any chat history, is the durable source of truth:

- `docs/` — vision, architecture, data model, quantitative principles, decision log
  (`DECISIONS.md`), roadmap, research methodology, provider evaluation.
- `tickets/` — the backlog. One markdown file per ticket; `tickets/INDEX.md` is the
  human-readable index. Work proceeds ticket by ticket.

## Development

Requires [uv](https://docs.astral.sh/uv/).

```sh
uv sync          # create venv and install dependencies
make test        # pytest
make lint        # ruff check + format check
make typecheck   # mypy --strict
make check       # all of the above
```

Layout: `src/trp/` (typed Python package), `tests/` (mirrors `src/`, plus `tests/timetravel/`
for information-leakage tests), `data/` (gitignored: `raw/`, `canonical/`, `derived/`).
