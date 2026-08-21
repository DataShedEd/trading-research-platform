# Decision log

Append-only. Never silently change a decision — supersede it with a new entry that references
the old one.

---

DEC-001
Date: 2026-08-16
Decision: uv for dependency and environment management; Python 3.12 pinned; src layout with package name `trp`.
Context: Greenfield repo; need reproducible environments with minimal ceremony.
Alternatives: Poetry (slower, lock friction), pip-tools (manual), conda (heavyweight).
Reason: uv is fast, handles Python installs and lockfiles in one tool. `trp` avoids stdlib name collisions and is short.
Consequences: Contributors need uv installed. `uv.lock` committed; CI uses `uv sync --locked`.

---

DEC-002
Date: 2026-08-16
Decision: ruff (lint + format), mypy --strict, pytest; GitHub Actions running the identical commands as local `make check`.
Context: Correctness-critical quantitative code needs typing and consistent style with low tool sprawl.
Alternatives: black+flake8+isort trio; pyright.
Reason: ruff subsumes the trio; mypy strict catches the silent-coercion class of bugs the brief forbids. The `DTZ` ruff ruleset mechanically bans naive datetimes.
Consequences: Some verbosity (explicit types everywhere). All timestamps must be tz-aware or code fails lint.

---

DEC-003
Date: 2026-08-16
Decision: DuckDB + Parquet is the only analytical store for Milestone 1; Polars is the primary dataframe library.
Context: Single-user, single-machine research workloads on daily-frequency data for a few thousand securities.
Alternatives: PostgreSQL for everything; SQLite; Pandas-first.
Reason: Columnar Parquet + DuckDB gives fast set-based SQL over versionable files with zero server administration. Polars is typed-friendly, fast, and strict about types (no silent coercion).
Consequences: No concurrent-writer story — acceptable for one researcher. Pandas allowed at notebook edges only.

---

DEC-004
Date: 2026-08-16
Decision: PostgreSQL deferred until a component has genuinely transactional state (experiment registry writes, paper-trading orders); not used in Milestone 1.
Context: Brief prefers Postgres "where useful"; Milestone 1 is batch-analytical only.
Alternatives: Stand up Postgres now.
Reason: Avoid operating a database that would hold nothing. Markdown tickets + Parquet cover all M1 state.
Consequences: Epic 10/15 tickets include introducing Postgres (or consciously choosing SQLite) when reached.

---

DEC-005
Date: 2026-08-16
Decision: Pydantic v2 frozen models for domain records; `Decimal` for prices, dividends, and per-share values in canonical stores; timezone-aware UTC timestamps internally; market-local concepts (trading days, period ends) as `date`.
Context: Need validated, immutable, typed domain objects at system boundaries; float rounding must not corrupt corporate-action arithmetic.
Alternatives: dataclasses (no validation), attrs, floats everywhere.
Reason: Validation at the boundary is where provider data quality problems surface; Decimal makes split/dividend adjustment exact and auditable.
Consequences: Explicit Decimal↔float conversion at the derived-analytics boundary; slight verbosity.

---

DEC-006
Date: 2026-08-16
Decision: One QNT-NNN ticket sequence across all epics; tickets are markdown files in `/tickets` with `INDEX.md` as the human-readable source of truth; one git commit per completed ticket, ticket ID first in the message.
Context: Durable project memory must live in the repository, not chat history.
Alternatives: Per-epic prefixes; external tracker.
Reason: Single sequence keeps IDs stable and grep-able; commits-per-ticket make git history a project journal.
Consequences: Ticket files are updated (status, completion notes) as part of the work they describe.

---

DEC-007
Date: 2026-08-16
Decision: When a provider supplies no announcement timestamp for a fundamental record, impute `available_at` conservatively (late) as period end plus a documented per-market reporting lag, and flag the row as imputed.
Context: Point-in-time correctness requires `available_at`; many providers omit true first-publication timestamps.
Alternatives: Use period end (leaks up to months of future information); drop such rows (destroys coverage).
Reason: A late-biased assumption can only understate strategy performance, never flatter it — the safe direction per QUANT_PRINCIPLES.
Consequences: Backtests on imputed data are conservative; the imputed flag lets us measure sensitivity once a provider with real timestamps is available.

---

DEC-008
Date: 2026-08-16
Decision: Security master records are bitemporal. Event time is a half-open date range (`valid_from` inclusive, `valid_to` exclusive, None = open-ended); knowledge time is `recorded_at`/`superseded_at` (UTC timestamps). Lifecycle changes supersede records rather than replacing them, so every historical knowledge state is reconstructable (`pit.known_as_of`). Downstream consumers use `PointInTimeSecurityMaster`, which requires an explicit `as_of` on every query.
Context: A vendor backfilling a 2014 ticker change in 2026 must not make a 2014 backtest smarter than a 2014 investor. Single-axis event dating cannot express this.
Alternatives: Event-time only with documented limitation; full snapshot copies of the master per ingestion run.
Reason: Supersession preserves knowledge history at row granularity with no snapshot storage cost, and revalidation on every change makes inconsistent states unconstructable. `recorded_at=None` (backfill) treated as always-known is the honest-but-lenient default; fundamentals will use conservative imputation instead (DEC-007) because there the leak direction matters more.
Consequences: Storage carries superseded rows forever (small for the master). Uniqueness invariants apply to current records only. `model_copy(update=...)` is banned on domain records in favour of `revalidated_copy`.

---

DEC-009
Date: 2026-08-16
Decision: Rights-issue price adjustment is deferred. The adjustment engine flags any security with a rights issue in its corporate-action history (computation warning + provenance) instead of adjusting for it.
Context: Correct rights adjustment needs the theoretical ex-rights price, which requires reliable subscription terms and cum-rights prices; provider data quality for historical UK rights issues is unproven until the bake-off runs.
Alternatives: Approximate TERP adjustment now; ignore silently.
Reason: A wrong adjustment is worse than a flagged gap — it produces plausible wrong returns. Flagging keeps affected securities visible so research can exclude or hand-check them.
Consequences: Adjusted series for securities with rights issues are wrong before the issue date until this is revisited (post bake-off, when subscription-terms data quality is known). The warning must be surfaced by QNT-019's validation report and respected by the factor engine.

---

DEC-010
Date: 2026-08-16
Decision: Trading calendars come from the `exchange-calendars` library, wrapped by `trp.canonical.calendars`, with a fixed supported range per exchange (2000-01-01 to 2030-12-31 for XLON, XNYS, XNAS) and no committed snapshot for now. The wrapper is the only code allowed to import the library.
Context: QNT-016 needs LSE, NYSE and Nasdaq trading days, holidays and half days. The alternative is curating holiday data files ourselves.
Alternatives: Curated committed data files (stable and auditable, but substantial ongoing work and our own errors to find); the library snapshotted to committed files and treated as canonical (the ticket's suggested middle path).
Reason: The library is mature, actively maintained, and its LSE coverage — including the irregular bank holidays that weekday logic gets wrong — is better than anything we would hand-curate soon. Snapshotting is deferred rather than rejected: it is worth doing once the price bake-off has reconciled calendar days against observed price dates (QNT-019), because a snapshot taken before that reconciliation would just freeze unverified data.
Consequences: Historical holiday data can change between library versions, which would silently change past backtest results and violate reproducibility (QUANT_PRINCIPLES §4). Three things bound that risk: the version is pinned in `uv.lock`, so a change only arrives with a deliberate dependency update; `tests/canonical/test_calendars.py` asserts hand-derived expected values (holidays, half days, session counts) so a changed historical calendar fails tests rather than passing silently; and the supported range is fixed in code rather than anchored to today, so the same historical query is answerable identically in any year. Offline reproducibility is otherwise fine — the library computes calendars locally with no network access. If QNT-019 finds discrepancies against observed price dates, curated overrides can be layered on top of the wrapper, or the snapshot approach adopted, without changing any caller.

---

DEC-011
Date: 2026-08-16
Decision: Canonical fundamentals are stored as Parquet partitioned by period-end year only (`data/canonical/fundamentals/period_year=YYYY/part-N.parquet`), with values as Parquet Decimal(38, 6). Writers append new part-files, never rewrite existing ones; the stable row key is (security, statement, line item, period end, period type, revision sequence).
Context: The dataset is long and narrow, queried as a few line items across many securities filtered by availability. Partitioning by security would produce tens of thousands of tiny files; no partitioning would force full scans for period-bounded queries.
Alternatives: Partition by security (file explosion); by statement+year (more dirs for little pruning benefit at this width); no partitioning.
Reason: A universe-year of statements is tens of thousands of rows — one comfortable file per year (validated by a synthetic-volume test: 900 rows across 3 years produce exactly 3 files). Decimal(38,6) spans per-share pence to trillion-scale balance-sheet lines with six decimal places; out-of-range errors rather than truncating.
Consequences: Changing either choice later means rewriting the dataset (always possible from immutable raw payloads, but expensive). Append-only part-files mean deletion/compaction is a deliberate future operation, never implicit.

---

DEC-012
Date: 2026-08-16
Decision: The bake-off rubric includes veto thresholds: a provider scoring below 0.5 on delisted coverage or below 0.25 on point-in-time fundamental availability is marked unsuitable regardless of its weighted total. Weights and thresholds live in versioned data (src/trp/bakeoff/weights.json, v2026-08-16.1) fixed before any real provider results exist.
Context: QUANT_PRINCIPLES §1 and §2 are non-negotiable; a weighted average can hide a fatal deficiency behind good scores elsewhere.
Alternatives: Weight inflation only (a bad provider can still win); manual judgement (unauditable).
Reason: A provider that cannot serve delisted securities cannot support survivorship-bias-free research at any price. The PIT threshold is set lower (0.25) because QNT-028's research already established that no provider in budget offers true PIT fundamentals — the criterion must be scored honestly without disqualifying every candidate.
Consequences: The report must show veto flags prominently. Revising weights/thresholds later requires a new weights-file version with justification; previously published scores remain attributable to their version.

---

DEC-013
Date: 2026-08-16
Decision: The QNT-028 Phase 1 provider purchase is executed. Owner subscribed to EODHD (paid monthly; 100,000 requests/day and extraLimit 500 observed via /api/user on 2026-08-16) and created a free Tiingo Starter account. Keys live in .env as TRP_EODHD_API_KEY / TRP_TIINGO_API_KEY (SecretStr; never logged — httpx request-URL logging is suppressed since it would print query-parameter tokens).
Context: DATA_PROVIDER_EVALUATION.md recommended EODHD ALL-IN-ONE month-to-month first, Tiingo free as US cross-check. Owner populated both keys on 2026-08-16.
Alternatives: Delay purchase; start with FMP.
Reason: EODHD is the only in-budget candidate covering UK prices, corporate actions, delisted securities and fundamentals in one subscription; the live bake-off run the same day confirmed LSE delisted coverage (all four validation delistings present with matching ISINs).
Consequences: The raw-payload archive is licensed, not owned — cancellation obliges deletion within one month, so the durable bake-off evidence is derived results, not raw payloads. Tier confirmed by the owner 2026-08-16: **ALL-IN-ONE Monthly Subscription, EUR 99.99/month** (month-to-month, as the QNT-028 recommendation advised — no annual commitment until the bake-off verdict is acted on). Live findings: EODHD UK fundamentals carry no usable publication timestamps (filing_date is a period-end default for ~99% of UK/EU rows), so DEC-007 imputation is confirmed load-bearing for UK point-in-time research; the pre-registered PIT veto (DEC-012) correctly marks both providers unsuitable *as PIT-fundamentals sources* while EODHD remains strong for prices/corporate actions/delisted coverage.

---

DEC-014
Date: 2026-08-18
Decision: FTSE 100 research coverage starts 2010-01-01. Membership remains queryable back to the curated anchor (2005-12-19) as event truth, but factor research and backtests must not extend before the coverage start; the universe registry exposes `research_coverage_start` and the QNT-041 gate enforces data completeness only within coverage.
Context: The QNT-091 backfill quantified EODHD's pre-2010 delisted gap — 48 of 240 historical FTSE 100 members (HBOS, Cadbury Schweppes, Xstrata, ICI, …) have no price data, nearly all pre-2010 departures. A backtest over that period would silently exclude ~20% of the then-universe: survivorship bias by data gap.
Alternatives: Patch the gap from another source (cost/effort unknown, deferred not rejected); keep the full span and per-date completeness checks (complex, still biased where incomplete).
Reason: 15+ years (2010–present) with verified full constituent data coverage is ample for medium-term factor research, and an honestly bounded span beats a longer contaminated one (QUANT_PRINCIPLES §2, §5).
Consequences: Backtests report their universe coverage start; results cannot claim pre-2010 UK evidence. Revisit if a source for pre-2010 delisted LSE data is ever acquired — the curated membership already extends to 2005, so only the price/fundamental gap would need filling.

---

DEC-015
Date: 2026-08-18
Decision: Factor definitions are JSON files under config/factors/, one file per immutable (name, version); in-place edits are detected by a declared content hash over the semantic body (description excluded); transforms are named Python implementations registered in trp.factors.compute — configuration parameterises them and can never express logic.
Context: QNT-042 requires versioned, reproducible factor definitions; the risk named in the ticket is an over-general configuration language.
Alternatives: YAML (adds a dependency and implicit typing quirks); Python modules as definitions (unhashable semantics, import-order coupling); a DSL (the trap itself).
Reason: JSON is already the repo's curated-data format, hashes canonically, and the closed transform registry keeps all logic in typed, tested Python.
Consequences: New transform kinds require code (deliberate friction); definition authors must recompute the hash on any semantic change, which is exactly the audit trail wanted. Stored values are tagged name@version + as_of + input dataset versions.

---

DEC-016
Date: 2026-08-18
Decision: Seventeen enumerated data gaps inside the DEC-014 coverage window are accepted and encoded as the QNT-041 gate's exclusion list (tests/gate/test_ftse100_gate.py::KNOWN_DATA_GAPS): sixteen ex-FTSE-100 securities EODHD does not carry at all (SABMiller, Xstrata, ENRC, ICAP, AMEC, TUI Travel, Worldpay, Invensys, International Power, Autonomy, Friends Life, Cable & Wireless, Home Retail, African Barrick, Essar, Cadbury) plus Just Eat's 43-day post-2019 tail. Any coverage hole NOT in the list still fails the gate.
Context: Adjudication of the gate's findings (curated-history fixes v2026-08-16.5 + identity-resolution fixes) reduced the gaps from 3.29% to ~2.5% of member-months 2010–2026; the remainder were verified absent from EODHD's delisted list and price endpoints. Most cluster 2010–2016 exits by acquisition.
Alternatives: Shrink coverage start to ~2016 (loses too much usable history); source the sixteen from another vendor now (deferred, not rejected — the list is the shopping list if ever pursued).
Reason: A quantified, enumerated 2.5% gap with per-name justification is honest and workable; backtests inherit a small, known, conservative-direction bias (missing names are mostly acquisition exits, whose absent final run-ups would generally have HELPED momentum strategies).
Consequences: Backtest reports must cite DEC-016; the exclusion list may only shrink; QNT-041's gate is green under this policy and re-red on any new gap.

---

DEC-017
Date: 2026-08-18
Decision: Backtest simulation conventions (QNT-050/051). Timing: on a rebalance day the strategy's knowledge instant is the END of the PREVIOUS session (its as_of binds at context construction; no method takes a caller-chosen date) and orders fill at the rebalance day's close. Accounting: whole shares only; raw as-traded marks (actions are ledger events — adjusted marks would double-count); dividends credit on the ex-date for the quantity held; split fractions pay cash in lieu at the ex-date mark; a delisting with unknown terms is a conservative write-off to zero. Knowledge: a corporate action applies on max(ex_date, available_at date) — late vendor knowledge acts on the knowledge date, never retroactively.
Context: These are the places a backtest silently flatters itself: same-day information, retroactive action application, adjusted-price marking, vanished delistings.
Alternatives: Fill at next-day open (more conservative timing, needs reliable opens — revisit with QNT-053's slippage work); pay-date dividend crediting (correct but pay-date data quality is unverified; ex-date is documented as slightly favourable on reinvestment timing, weeks at most).
Reason: Each convention picks the honest or conservative side of the ambiguity and is stated in code (BacktestConfig/Portfolio docstrings) and tested, including the flagship invariance test: a run over data extended with future bars and late-announced actions is bit-identical to a run without them.
Consequences: Results are mildly optimistic on execution (close fill with prior-day information) — the QNT-053 cost model is where that optimism is paid for. The daily accounting identity is asserted every session by independent event-log replay; a broken ledger halts the run rather than producing a number.

---

DEC-018
Date: 2026-08-18
Decision: Portfolio-construction rules (QNT-052). Negative scores under score-proportional weighting follow a configured NegativeScorePolicy — RANK (default: weight by ascending rank position, sign-agnostic), SHIFT (score minus minimum), or POSITIVE_ONLY — never an implicit clamp. max_weight capping redistributes excess pro-rata across uncapped names iteratively (water-filling); an infeasible cap (n x max_weight < invested proportion) raises rather than silently under-investing. min_weight then drops below-floor names and redistributes to survivors, re-applying the cap to a fixed point. max_holdings truncates the selection (best scores kept) before weighting. Turnover is one-way: (buy value + sell value) / 2 over pre-trade portfolio value, reported per rebalance.
Context: Score-proportional weighting is undefined for negative scores, which standardised composites produce routinely; capping and flooring interact and need one documented order of operations.
Alternatives: Clamp negatives to zero (silent, distorts the cross-section); long-short weighting (out of scope until shorting exists); optimiser-based construction (deliberately deferred to EPIC 11).
Reason: Every rule is configuration captured in BacktestConfig (and therefore in the config hash and the experiment record); RANK is the default because it is defined for any score distribution and robust to outliers.
Consequences: Sector caps await sector reference data (deferred, noted in QNT-052). Changing any construction rule changes the config hash, so results are never silently comparable across different rules.

---

DEC-019
Date: 2026-08-18
Decision: A held position with no print for more than 15 calendar days and no knowable delisting/merger record is force-exited at its LAST TRADED CLOSE (value-neutral, recorded as delisting proceeds with an explicit "forced exit" note and a run warning). A knowable delisting or merger record always takes precedence because it applies on its effective date, before staleness can accrue.
Context: The canonical store currently holds dividends and splits but no delisting or merger corporate-action records (EODHD's delisted list was used for identity validation, not action ingestion). Without a rule, any FTSE 100 departure by acquisition would remain a phantom position marked at a frozen price for the rest of the backtest.
Alternatives: Write stale positions off to zero (wildly pessimistic — most departures are acquisitions near the last price, not failures); ingest delisting/merger actions first (correct long-term fix, deferred as its own ticket — this convention remains the fallback for vendor gaps even then); exit at the next rebalance only (leaves up to a month of phantom marks and still needs a price to exit at).
Reason: A taken-over company's final traded price sits close to the offer consideration, so exiting at the last close approximates actual proceeds with a small conservative bias (any final run-up between the last print and completion is forgone, consistent with the DEC-016 bias direction). The exit uses only on-or-before-day data, so all timetravel invariants hold.
Consequences: Genuine suspensions longer than 15 days exit and may be re-bought at a later rebalance when prints resume (a round-trip of costs — accepted). Genuine failures with no vendor record exit at the last pre-collapse print, which UNDERSTATES losses; the eventual delisting/merger ingestion ticket shrinks this class. Forced-exit counts appear in every run's warnings and tearsheet.

---

DEC-020
Date: 2026-08-18
Decision: EODHD LSE quotation units are repaired at the canonical layer (QNT-093, trp.canonical.unit_repair) and research consumers read only the repaired datasets: bars under source "eodhd-gbx" (append-only store, originals retained), dividends/splits from *_gbx parquets. Rules: (1) a one-day close ratio within [70, 140] or its inverse is a unit flip and the series is made continuous; (2) whole-series unit decided by dividend-yield evidence (GBX-normalised by each record's currency label) with a price-level fallback, unresolved blocks the write; (3) dividends relabelled GBP->GBX only when the GBP reading implies a >25% single-payment yield AND the amount is >= £2 (pence-scale) — sub-£2 high-yield records are genuine crash-era dividends and are kept and reported; (4) split records whose repaired price series shows no ex-date gap (vendor pre-scaled the surrounding history) are excluded to prevent double-counting, with two 2009 capital-raising records excluded by written adjudication.
Context: The first real backtest (QNT-092) produced a fantasy +28% CAGR. Root causes found: Compass/IHG/BAT-class series served whole in GBP while labelled GBX; 269 intra-series ~100x unit flips; 33 dividend records pence-stated but labelled GBP; 16 split records pre-applied by the vendor (Tesco 2021, Aviva 2022, Pennon 2021...). EODHD's raw payloads themselves carry the inconsistency.
Alternatives: Repair inside the backtest (hides a data defect from every other consumer); switch vendors (same class of warts elsewhere, and the raw archive is already licensed and local); manual per-security fixes (unauditable).
Reason: Detection rules are mechanical, evidence for every change is persisted in unit_repair_report.json, everything unresolvable fails loudly, and the append-only store keeps the original rows for audit.
Consequences: Research code must read source="eodhd-gbx" and the *_gbx action files. 48 genuine high-yield dividend records and ~19 residual >20% security-year dividend totals are enumerated in the report for future adjudication (bounded, direction favourable-to-strategy if wrong). The repair reruns after any re-ingestion; the report may only shrink.

---

DEC-021
Date: 2026-08-18
Decision: FTSE 100 strategies benchmark against the iShares Core FTSE 100 UCITS ETF: ISF.LSE (distributing) with its own dividends reinvested at the ex-date close, giving total-return coverage from May 2000. The accumulating class CUKX.LSE is ingested as an independent cross-check, not a benchmark (its pre-2016 EODHD data misses ~30% of sessions). Both flow through the standard raw-first EODHD pipeline into data/canonical/benchmarks/.
Context: QNT-055 requires a total-return benchmark. EODHD's All-In-One plan returns empty series for index endpoints (FTSE.INDX etc.), and licensed index series (FTSE Russell TR) are a separate purchase.
Alternatives: License the official index (cost, and not investable anyway); use the price index + assumed yield (fabrication); construct a cap-weighted series from our own universe (no shares-outstanding data, and it would share every defect of our universe — kept as a possible future addition, clearly labelled).
Reason: An ETF is investable, GBX-denominated, carries genuine fund costs, and its reinvestment construction is validated against CUKX to within 3bp/yr on the 2016+ overlap (gate-tested). Comparing an investable strategy to an investable benchmark is the honest comparison.
Consequences: The benchmark embeds ISF's TER (~0.07%), slightly flattering strategy excess returns by that amount — documented rather than adjusted. Pre-2000 backtests would need a different series. The benchmark shares EODHD provenance with strategy data; an index from a second vendor would be a stronger independent check if ever licensed.

---

DEC-022
Date: 2026-08-21
Decision: The experiment registry's metadata store is SQLite (standard library, one file at data/registry.sqlite, PRAGMA user_version for schema versioning, foreign keys on). Bulk results — equity curves, holdings, rolling series — stay in Parquet under the immutable run records; the registry holds records and references only. Records serialise as pydantic JSON payloads with extra="forbid", so a record written by a newer schema fails loudly on read instead of silently dropping fields.
Context: QNT-063 required choosing between Parquet, SQLite and PostgreSQL. Registry records are MUTATED as conclusions arrive, which Parquet (append-only analytics) handles badly; DEC-004 deferred PostgreSQL until something genuinely needs a shared transactional store.
Alternatives: PostgreSQL (right answer once paper trading in Epic 15 needs shared transactional state — revisit then, with a migration path from the versioned schema); Parquet (wrong shape for mutation); JSON files (no transactions, no counting queries).
Reason: A single-researcher registry needs transactions, zero administration and durable single-file backup semantics — SQLite exactly.
Consequences: Concurrency is single-writer (fine for one researcher; revisit with Epic 15). The user_version gate means schema migrations are deliberate, written operations. The registry file is inside data/ (gitignored): the registry is operational state, while its SCHEMA lives in code under version control.

---

DEC-023
Date: 2026-08-21
Decision: Delisting resolution in backtests. (1) Lifecycle delisting records are derived for every FTSE-100-ever security whose repaired price series has ended (trp.canonical.lifecycle): ex-date = first session after the last print; reason from curated FTSE-history removal evidence (acquisition/merger), a small adjudication table (NMC Health and Thomas Cook as FAILURE; Invesco/Just Eat/Ferguson/CRH/Flutter as EXCHANGE_MOVE), else the honest UNKNOWN. (2) The engine resolves any DelistingAction without cash terms at the LAST TRADED CLOSE on its ex-date for every reason except FAILURE, which remains a write-off to zero. (3) DEC-019's 15-day forced exit remains as the backstop for securities without records; on the current dataset it fires zero times. (4) A re-adjudication of repaired price values is a NEW full dataset under a bumped source (eodhd-gbx2 adds Melrose's segment fix: its vendor basis becomes GBX-native at the April 2023 demerger, so the whole-series x100 stops there); prior repaired rows are retained for audit and consumers reference the REPAIRED_SOURCE constant.
Context: Departures previously resolved through DEC-019 forced exits — correct proceeds but 15 days late and always warned; claiming ACQUISITION without evidence would fabricate provenance.
Alternatives: Vendor delisting/merger feeds (EODHD's IsDelisted field is unpopulated even for dead names; merger cash terms are not systematically available); write-offs for unknown reasons (wildly pessimistic — most FTSE exits are acquisitions near the last price).
Reason: The last traded close approximates acquisition consideration AND collapsed-failure value alike, so the UNKNOWN label carries no accounting penalty for honesty; only confirmed failures need the hard zero.
Consequences: The momentum baseline re-run on the corrected store: forced exits 10 -> 0, CAGR 10.90% -> 10.69% (the removed Melrose mark inflation and cleaner exits were worth ~20bp of artificial return — the conservative direction). Cash merger terms remain a future refinement where sourced; the reproduction gate now targets the newest run record because older records legitimately stop reproducing across data re-adjudications (their manifests pin the prior versions).

---

DEC-024
Date: 2026-08-21
Decision: Milestone 1 is qualified, not reopened. The M1 conclusion splits into two claims of different strength: (a) Market data / historical universe: PASS — prices, corporate actions, delisted coverage and PIT universe membership meet the M1 bar with DEC-016's enumerated exceptions. (b) True point-in-time fundamentals: PARTIAL / IMPUTED — EODHD provides no reliable historical publication timestamps for most UK/EU fundamental records (confirmed empirically during the bake-off, see DEC-013 consequences), so fundamental availability is DEC-007 conservative imputation (period_end + 120d annual / + 90d interim), not observed publication dates. Imputed availability must never be described as equivalent to observed publication timestamps in any report or conclusion. Research using fundamentals must disclose the imputed basis; price-only research (momentum) is unaffected.
Context: ROADMAP declared "MILESTONE 1 COMPLETE" without distinguishing the two claims; the fundamentals claim as stated overreached what the evidence supports.
Alternatives: Reopen M1 (wrong — the market-data claim is properly evidenced and momentum research needs no fundamentals); leave the unqualified claim (dishonest about the weakest link).
Reason: The platform's value rests on stated claims never exceeding their evidence. The distinction costs nothing operationally — DEC-007 remains the working fallback — and prevents a silent upgrade of imputed dates into "point-in-time" language downstream.
Consequences: ROADMAP M1 status text updated to carry both claims. QNT-103 investigates sourcing real UK publication dates (RNS/LSE announcements, Companies House filing history); QNT-104 adds reporting-lag sensitivity testing for any fundamental-factor result; until then, fundamental-factor conclusions (including HYP-769cd965's) inherit an "imputed availability" weakness. Future fundamental strategy reports must state the proportion of observations with observed vs imputed availability once the distinction exists in the schema.

---

DEC-025
Date: 2026-08-21
Decision: The DEC-016 gaps are reclassified as KNOWN SURVIVORSHIP-RELATED MISSINGNESS with no claimed bias direction. DEC-016's exclusion list and may-only-shrink rule stand unchanged; what is withdrawn is its Reason's characterisation of the bias as "conservative-direction". The sixteen missing securities disappeared overwhelmingly through acquisitions and other corporate events — the missingness is correlated with corporate outcomes, therefore NOT random, and its net effect on any given factor result is unknown (missing acquisition run-ups could as easily overstate as understate a strategy that would have held the acquirees' losers instead).
Context: Directive review 2026-08-21: "do not claim that the resulting bias is necessarily conservative". DEC-016 (and DEC-019/DEC-023, which cite the same direction argument for their own, narrower conventions) claimed a direction the evidence does not establish for portfolio-level results.
Alternatives: Attempt to bound the bias analytically (not possible without the missing histories themselves); ignore the mischaracterisation (leaves a false comfort in the decision log).
Reasoning: A 2.5%-of-member-months hole concentrated in acquisition exits is a selection effect, not noise; honesty requires labelling it as such and treating remediation as a finite, enumerable task.
Consequences: Reports citing DEC-016 must describe the gaps as "known survivorship-related missingness (direction unquantified)". QNT-105 tracks sourcing the sixteen missing histories from a second provider or primary sources — the finite remediation list. The last-close approximations inside DEC-019/DEC-023 remain in force; their per-position reasoning stands, but portfolio-level "conservative" claims are withdrawn there too.

---

DEC-026
Date: 2026-08-21
Decision: FTSE 250 historical membership (QNT-111) is sourced from the official FTSE Russell "FTSE 250 — Historic Additions and Deletions" policy document (April 2026 edition; 1,034 change rows 2002–2026 parsed positionally from the PDF), extended by the LSEG June 2025 and June 2026 annual-review press releases, anchored on the CURRENT constituent list from Wikipedia's 2026-08-20 revision (cross-validated against the June 2026 review: all nine additions present, all nine deletions absent), and validated against 26 dated Wikipedia constituent snapshots 2013–2025 used as replay checkpoints. EODHD's FTMC.INDX components were REJECTED as an anchor: the snapshot is internally inconsistent (contains June 2026 deletions, lacks June 2026 additions). Effective-date convention: changes apply at the index effective date (first trading session of the new composition) — what a replicating investor could actually trade. Promotions/demotions across the 100↔250 boundary resolve to the EXISTING security id via the validated FTSE 100 master (134 companies), asserted by gate tests; the FTSE 100 curated history also supplies synthetic mirror events where the FTSE 250 document omits a boundary row (each cited).
Context: EODHD provides no historical FTSE constituent data (QNT-039). The FTSE 100 curation machinery scales; the FTSE 250's higher churn (~40 events/yr) made document errata material — the parser and replay caught and corrected, with citations: a duplicated September 2017 row (Provident printed twice where Royal Mail belonged — proven by the FTSE 100 mirror), typos (Hvve/Reinshaw/Utilco/Johnson Matthew/Oxford Biomedia/Indivor/Trsut), and omitted rows (recovered from checkpoints).
Alternatives: licensed FTSE Russell constituent history (out of budget); a rules-based rank-101-350 proxy (not the actual index; free-float and nationality rules diverge); Wayback-archived lists (sparser than Wikipedia's revision history).
Reason: The official change document is authoritative for dates and reasons; independent dated snapshots bound residual errors: 41 membership boundaries (of 910 spells) are checkpoint-dated reconciliations flagged '[unverified]' with a ≤6-month uncertainty window — ~0.26% of member-months. All adjudications live in versioned files under data_sources/ftse/ (aliases, corrections, overrides, ledger), each citing its evidence.
Consequences: members("FTSE250", date, as_of) is live over 2009-06-22..2026-08-20 with checkpoint support from 2013 (research coverage start decided separately by QNT-112 measurement). The overlap gate (FTSE100 ∩ FTSE250 = ∅ monthly) and identity-preservation gates run permanently. 46 pre-2013-only companies remain identity-unresolved (logged; excluded from written membership); 16 resolved companies are absent from EODHD's LSE lists entirely — the provisional FTSE 250 exception list, may only shrink, direction NOT claimed (DEC-025 discipline).

---

DEC-027
Date: 2026-08-21
Decision: The FTSE 250 holdout benchmark (QNT-113) is the iShares FTSE 250 UCITS ETF distributing class, MIDD.LSE (full FTSE 250 index including investment trusts, inception March 2004, TER 0.40%), with dividends reinvested at ex-date close — same construction as DEC-021's ISF. Validation: against the Vanguard FTSE 250 UCITS ETF (VMID.LSE, TER 0.10%, from Sept 2014) over their 11.9-year overlap, VMID's annualised total return exceeds MIDD's by +29bp/yr — matching the 30bp TER differential almost exactly — with 0.979 daily return correlation. An independent-issuer cross-check is stronger evidence than a share-class pair. EODHD serves VMID's line in POUNDS (ISF/MIDD in pence); the benchmark loader now converts dividends into each spec's declared quote currency (the hardcoded-GBX assumption produced a nonsense +900%/yr series for VMID before the fix — caught by this validation).
Context: The pre-registered primary metric (HYP-19a4ddba) is IR vs a validated investable FTSE 250 total-return benchmark.
Alternatives: HSBC's FTSE 250 product (tracks the ex-investment-trust variant — wrong index for a full-250 universe); the licensed index series (not investable, not in budget).
Reason: Investable, dividend-inclusive, unit-verified, 2004 inception covers any plausible research window; fees inside the series make the comparison honest about implementability.
Consequences: Strategy excess returns are measured vs an INVESTABLE ETF (0.40%/yr of fees inside the benchmark), not the paper index — disclosed in every report. Benchmark gate added alongside the ISF gates.
