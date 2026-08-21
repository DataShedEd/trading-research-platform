# QNT-101 — Dust-sell ordering: a sale costing more than it raises cannot crash the book

- **Ticket ID:** QNT-101
- **Status:** DONE
- **Priority:** P2
- **Epic:** EPIC 8 — Backtesting Engine

## Problem
The top-10 sensitivity run (HYP-769cd965) crashed with LedgerError: fully invested, one
dust share whose £5 minimum commission exceeded its sale proceeds, and that net-negative
sale processed first — pushing cash below zero, which the ledger rightly refuses.

## Resolution
2026-08-21. Sells execute net-positive first, so ordinary sales raise the cash that
absorbs a dust sale's net cost; a dust sale that still cannot be afforded defers with a
warning and exits later (or via its lifecycle record). Regression test with the exact
fixture (9,990 shares at 100 plus one 10p share, £5 minimum commission). The crashed
experiment was ABANDONED with the defect as its reason — the honest denominator — and
rerun as qvm-top10-sensitivity-b. 846 default + 22 gate tests green.
