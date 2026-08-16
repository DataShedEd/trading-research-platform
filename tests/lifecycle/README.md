# Lifecycle fixtures — the Epic 2 regression harness

`tests/fixtures/security_master/lifecycles.json` defines synthetic companies whose complete
histories exercise the security master end to end. Every subsequent epic that touches the
master must leave this suite green; when a downstream result looks wrong, run this first:

```sh
uv run pytest tests/lifecycle
```

## The narratives

- **icarus** — failure. Lists 1999, compulsory liquidation effective 2018-01-15, but the
  vendor delivers the record on 2018-03-20: probes F3/F4 pin the knowledge-time behaviour.
- **meridian / bracken** — rename plus ticker reuse. Beacon Industries becomes Meridian
  Group (BCN → MRD effective 2015-06-01, *announced* 2015-05-29 — knowledge precedes the
  event); the abandoned BCN is later reassigned to unrelated Bracken Capital. Probes R2/R3
  pin the half-open boundary on the change date itself.
- **talos** — acquisition by meridian (an acquirer inside the master), completing
  2021-10-27 at 18:00 UTC: A4 shows the target still resolving at noon that day.

## Adding a fourth lifecycle

1. Add a company entry (entity, listing, initial ticker) and any events to the JSON.
2. Hand-derive expected outcomes from the narrative — never from code output — and add
   probe rows (`resolve` | `status` | `identifiers` | `acquirer`), giving each a unique id.
3. Probes with `as_of` are automatically exercised through the point-in-time facade and
   run under `pytest -m timetravel` as well.

Every probe is asserted against the built master **and** a Parquet storage round-trip, so
persistence fidelity is covered for free.
