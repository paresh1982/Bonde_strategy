# STAGE 4.1 — COMMERCIAL SECURITY MASTER VALIDATION REPORT

## 1. Architectural Invariant
- **Rule**: `ticker != security identity`
- All queries resolve via `resolve_security_id(ticker, as_of_date)`.

## 2. Point-in-Time Identity Tests
- **Corporate Symbol Change**: FB -> META (effective 2022-06-09). Verified `SEC_META` on both sides.
- **Ticker Recycling**: RECY held by Old Recycling Corp (2010–2019) -> resolves `SEC_RECY_OLD`. Held by New Renewable Energy (2020+) -> resolves `SEC_RECY_NEW`. In-between window (2020-01-01 to 2020-05-31) -> fails closed (`None`).
- **Delisting Handling**: SIVB delisted on 2023-03-10. Queries on or before 2023-03-10 return `SEC_SIVB`. Queries after 2023-03-10 return `None` (fail closed; zero survivorship bias).

## 3. Commercial Universe Scale Gap
- Local verification fixtures contain **14 total securities**.
- Full institutional survivorship-bias-free security master requires **~10,000+ active & delisted US equities**.
- Status: **BLOCKER**.
