# STAGE 4.1 — CONSOLIDATED COMMERCIAL DATA QUALITY REPORT

**Gate Status**: `DATA_BLOCKED_FOR_BASELINE_BACKTEST`
**Audit Timestamp**: `2026-09-25T11:10:21.125723+00:00`
**Total Raw Files Ingested**: 37
**Total Volume Scanned**: 2,557,307 bytes

### Evaluation Metrics
- **PASS**: 4
- **WARN**: 0
- **BLOCKER**: 5

### Summary of Gate Items

| Dimension | Severity | Satisfied | Summary |
|---|---|---|---|
| Raw Data Integrity & Manifest | `PASS` | True | Manifest computed for 37 raw vendor files with SHA-256 integrity. |
| Commercial Security Master Resolution | `PASS` | True | Point-in-time identity verified across ticker changes, recycling, and delisting. |
| Security Master Commercial Universe Coverage | `BLOCKER` | False | Only 12 securities in security master (curated verification fixtures only). |
| Daily Dual-Price & Indicator Integrity | `PASS` | True | Dual-price integrity validated across 12 daily series. |
| Historical 1-Minute Intraday Coverage | `BLOCKER` | False | Only 7 isolated intraday sessions present (2730 bars). |
| Catalyst Feed Breadth & Completeness | `BLOCKER` | False | Only 29 earnings events and 5 8-Ks present (sample fixtures). |
| Point-in-Time Float & Shares Outstanding | `BLOCKER` | False | Commercial point-in-time float dataset absent. |
| Historical Sector Classification Coverage | `BLOCKER` | False | Only 14 sector records present (fixture sample only). |
| Historical Cross-Sectional Market Breadth | `PASS` | True | Cross-sectional breadth verified across 1564 trading sessions (2018-01-02 to 2023-12-29). |

### Blocker Analysis

- 🛑 [Security Master Commercial Universe Coverage] Only 12 securities in security master (curated verification fixtures only).
- 🛑 [Historical 1-Minute Intraday Coverage] Only 7 isolated intraday sessions present (2730 bars).
- 🛑 [Catalyst Feed Breadth & Completeness] Only 29 earnings events and 5 8-Ks present (sample fixtures).
- 🛑 [Point-in-Time Float & Shares Outstanding] Commercial point-in-time float dataset absent.
- 🛑 [Historical Sector Classification Coverage] Only 14 sector records present (fixture sample only).

### Formal Conclusion

> [!CAUTION]
> **BASELINE BACKTEST STRICTLY BLOCKED**: Commercial full-market institutional datasets are not present locally. In strict accordance with the Stage 4 and Stage 4.1 mandates, the engine refuses to run fabricated backtests, interpolate missing data, or generate synthetic performance claims.
