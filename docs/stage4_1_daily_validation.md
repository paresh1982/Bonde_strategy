# STAGE 4.1 — DAILY DUAL-PRICE & INDICATOR INTEGRITY REPORT

## 1. Dual-Price Separation Architecture
- **Unadjusted Prices** (`open`, `high`, `low`, `close`, `volume`): Strictly reserved for execution, stops, limit collars, and fills.
- **Split-Adjusted Prices** (`adjusted_open`, `adjusted_high`, `adjusted_low`, `adjusted_close`, `adjusted_volume`): Strictly reserved for technical indicators.

## 2. Anti-Lookahead Invariants Verified
- **65-Day High**: Computed strictly across completed sessions `[t-65, t-1]`.
- **ADV50**: Computed strictly across completed sessions `[t-50, t-1]`.
- **10 EMA**: Computed strictly using information available through `t-1`.
- **Adversarial Proof**: Corrupting or inserting session `t` bars produces 0.000000 delta in baseline indicator calculations as of date `t`.

## 3. Data Integrity Checks
- OHLC logical order: PASS
- Positive prices and volume: PASS
- Duplicate timestamp detection: PASS
