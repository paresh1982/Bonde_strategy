# Stage 1B Test Execution Report

**Repository:** `C:\work\projects\bonde-strategy`  
**Market:** United States Equities (NYSE / NASDAQ / AMEX)  
**Document:** `docs/stage1b_test_report.md`  
**Status:** ALL 70 TESTS PASSING (100% SUCCESS)  
**Date:** September 2026  

---

## 1. Executive Summary

A comprehensive test run was executed across the entire repository using `pytest`. All 53 legacy tests (Stage 0, 0.1, and 0.2) and all 17 new Stage 1B data infrastructure and adversarial tests passed cleanly.

```text
============================= test session starts =============================
platform win32 -- Python 3.13.12, pytest-8.3.4, pluggy-1.6.0
rootdir: C:\work\projects\bonde-strategy
collected 70 items

tests\test_audit_stage0_1.py ......                                      [  8%]
tests\test_base_hit.py ....                                              [ 14%]
tests\test_catalyst_orb.py ...                                           [ 18%]
tests\test_eod_governor.py ...                                           [ 22%]
tests\test_orders.py ....                                                [ 28%]
tests\test_regime.py ..                                                  [ 31%]
tests\test_same_bar.py ...                                               [ 35%]
tests\test_sector_governor.py ..                                         [ 38%]
tests\test_sizing.py .....                                               [ 45%]
tests\test_stage0_2_hardening.py .....................                   [ 75%]
tests\test_stage1b_data_infrastructure.py .................              [100%]

============================= 70 passed in 2.38s ==============================
```

---

## 2. Module Test Breakdown

| Test Suite | Purpose | Tests | Status |
| :--- | :--- | :---: | :---: |
| [test_audit_stage0_1.py](file:///C:/work/projects/bonde-strategy/tests/test_audit_stage0_1.py) | Stage 0.1 rule traceability and governor invariants | 6 | **PASS** |
| [test_base_hit.py](file:///C:/work/projects/bonde-strategy/tests/test_base_hit.py) | Base-Hit setup detection and risk geometry | 4 | **PASS** |
| [test_catalyst_orb.py](file:///C:/work/projects/bonde-strategy/tests/test_catalyst_orb.py) | 5-minute ORB range calculation and trigger logic | 3 | **PASS** |
| [test_eod_governor.py](file:///C:/work/projects/bonde-strategy/tests/test_eod_governor.py) | Mandatory 03:55 PM EOD audit and Day-1 liquidation | 3 | **PASS** |
| [test_orders.py](file:///C:/work/projects/bonde-strategy/tests/test_orders.py) | Order lifecycle, stop-limit collars, and state transitions | 4 | **PASS** |
| [test_regime.py](file:///C:/work/projects/bonde-strategy/tests/test_regime.py) | Market Regime FSM (GREEN / YELLOW / RED) | 2 | **PASS** |
| [test_same_bar.py](file:///C:/work/projects/bonde-strategy/tests/test_same_bar.py) | Conservative same-bar exit priority (`SAME_BAR_STOP_FIRST`) | 3 | **PASS** |
| [test_sector_governor.py](file:///C:/work/projects/bonde-strategy/tests/test_sector_governor.py) | Sector exposure caps and uncushioned risk tracking | 2 | **PASS** |
| [test_sizing.py](file:///C:/work/projects/bonde-strategy/tests/test_sizing.py) | Risk sizing, 1.5% ADV cap, and 0.60R deployment cutoff | 5 | **PASS** |
| [test_stage0_2_hardening.py](file:///C:/work/projects/bonde-strategy/tests/test_stage0_2_hardening.py) | Post-fill entry stops, T2 stall, runner 10 EMA trailing | 21 | **PASS** |
| [test_stage1b_data_infrastructure.py](file:///C:/work/projects/bonde-strategy/tests/test_stage1b_data_infrastructure.py) | Point-in-time data contracts, dual price, quality gates, pipeline | 17 | **PASS** |
| **TOTAL** | **Comprehensive Full System Coverage** | **70** | **100% PASS** |

---

## 3. Adversarial & Point-in-Time Test Verification

The 17 tests added in [test_stage1b_data_infrastructure.py](file:///C:/work/projects/bonde-strategy/tests/test_stage1b_data_infrastructure.py) explicitly verify:

### 3.1 Security Identity Resolution
1. `test_ticker_recycling`: Proved two distinct corporate entities (`SEC_COMP_A` and `SEC_COMP_B`) using the same ticker `"XYZ"` resolve to the correct entity on respective historical dates, and return `None` during the interregnum.
2. `test_delisted_security_fails_closed`: Confirmed that querying a delisted security (`DEAD`) on or before delisting resolves, but queries after delisting fail closed (`None`).
3. `test_security_ticker_change`: Verified that corporate symbol renames (`FB` $\rightarrow$ `META`) correctly map to the same canonical `security_id` across date boundaries.

### 3.2 Dual-Price Architecture
4. `test_dual_price_separation`: Verified that a 2-for-1 split produces distinct unadjusted prices for execution properties (`execution_close = 100.0`) and split-adjusted prices for analytical properties (`analytical_close = 50.0`).
5. `test_dual_price_validation_errors`: Confirmed strict logical invariant enforcement (`low > high` raises `ValueError`).

### 3.3 Anti-Leakage Adversarial Tests
6. `test_indicators_insufficient_history_fails_closed`: Verified that calculating 65D High with $< 65$ bars, ADV50 with $< 50$ bars, or 10 EMA with $< 10$ bars returns `None` and halts setup qualification.
7. `test_adversarial_session_t_anti_leakage`: **CRITICAL VERIFICATION.** Generated a 70-day series through session $t-1$. Injected an extreme corrupted bar on session $t$ (High = $999,999, Close = $999,999, Volume = 100,000,000). Proved that 65D High, ADV50, and 10 EMA computed for session $t$ remained **100% identical** to baseline, demonstrating absolute zero lookahead.

### 3.4 Universe Screening & Candidate Generation
8. `test_universe_screening_filters`: Verified rejection of stocks below the $\$5.00$ price floor and below the $100,000$ share $\text{ADV}_{50}$ filter.
9. `test_base_hit_candidate_generator`: Confirmed deterministic generation of Base-Hit breakout trigger ($\text{High}_{65} + \$0.01$) and structural stop, enforcing the $\le 4.0\%$ geometry gate.

### 3.5 Catalyst Point-in-Time Availability
10. `test_track_a_earnings_premarket_cutoff`: Verified that earnings announced at 07:00 ET qualify for Day-1 pre-market, whereas earnings released at 09:30:01 ET or 16:30 ET are rejected for Day-1 opening execution.
11. `test_track_b_sec_filing_availability`: Verified that SEC 8-K filings are visible only after their exact SEC EDGAR `acceptanceDateTime`.

### 3.6 Intraday Data, Breadth, and Sectors
12. `test_candidate_targeted_intraday_extraction`: Confirmed that 1-minute bars are extracted only for qualified candidates and open positions, eliminating multi-terabyte processing overhead.
13. `test_market_breadth_fsm`: Verified deterministic mapping of market breadth ratios to `GREEN`, `YELLOW`, and `RED`.
14. `test_point_in_time_sector_provider`: Verified date-bounded sector lookups and fail-closed behavior when historical sectors are unmapped.

### 3.7 Data Quality, Manifest, and Pipeline
15. `test_data_quality_gates`: Verified that inverted OHLC, negative volumes, and $>50\%$ intraday spikes trigger `QualityStatus.FAIL` and generate machine-readable anomaly logs.
16. `test_manifest_creation_and_integrity`: Confirmed SHA-256 dataset checksum generation, storage, and retrieval.
17. `test_synthetic_end_to_end_pipeline`: **SYSTEM INTEGRATION.** Executed the complete data-to-execution pipeline (Security Master $\rightarrow$ Daily Provider $\rightarrow$ PIT Screener $\rightarrow$ Candidate Generator $\rightarrow$ Targeted 1m Bars $\rightarrow$ Stage 0.2 Engine $\rightarrow$ Portfolio $\rightarrow$ Trade Journal). Confirmed order filling and position lifecycle with zero lookahead bias.
