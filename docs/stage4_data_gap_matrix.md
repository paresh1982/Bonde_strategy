# Stage 4 — Historical Data Gap Matrix: Local Fixture vs. Institutional Backtest

**Repository:** `C:\work\projects\bonde-strategy`  
**Market:** United States Equities (NYSE / NASDAQ / AMEX)  
**Document:** `docs/stage4_data_gap_matrix.md`  
**Status:** COMPLETE GAP ANALYSIS  
**Date:** September 2026  

---

## 1. Overview & Evaluation Framework

To maintain scientific integrity and prevent backtest curve-fitting, this document details the exact technical gaps between the **local Stage 1D verification fixtures** currently available in the repository and the **full institutional datasets** required to execute a valid multi-year historical backtest.

### Gap Severity Definitions
* **BLOCKER**: Missing data makes it impossible to run a statistically valid multi-year backtest. Omitting this data causes fatal survivorship bias or execution distortion.
* **CRITICAL**: Seriously degrades strategy qualification fidelity (e.g. inability to detect real-time catalysts or regime switches).
* **MODERATE**: Reduces universe filtering precision (e.g. float cap approximations) without breaking core order execution or risk governors.
* **LOW**: Minor friction refinement (e.g. tick-level Level 2 queue depth vs. fixed $0.01 slippage).

---

## 2. Institutional Data Gap Matrix

| Data Dimension | Local In-Repo Status | Required Institutional Specification | Gap Severity | Concrete Impact if Executed on Current Data | Required Vendor / Source |
| :--- | :--- | :--- | :---: | :--- | :--- |
| **1. Intraday 1-Minute Bars** | **7 sessions (2,730 bars)** across 6 tickers | 10-year continuous 1-minute RTH bars (09:30–16:00 ET) for all US common stocks | **BLOCKER** | Cannot compute 09:30–09:35 ORB high/low or simulate intraday trailing stops for 99.5% of trading days. | **FirstRate Data** (US 1-Minute Equity Bundle) or **Polygon.io** (Flat Files) |
| **2. Survivorship-Free Security Master** | 14 securities (12 active, 2 delisted) | Point-in-time universe of all listed and delisted US common stocks (1995–present, ~10,000+ securities) | **BLOCKER** | Severe survivorship bias; strategy win rate and expectancy would be artificially inflated by ignoring bankrupt/delisted failures. | **Norgate Data** (US Equities Survivorship-Free) or **CRSP** |
| **3. Historical Daily Dual-Price Bars** | 12 symbols (18,558 daily bars, 2018–2023) | Full-universe daily unadjusted and split-adjusted OHLCV for all US equities | **BLOCKER** | Screening pool restricted to 12 hand-picked stocks; cannot discover market-wide momentum setups. | **Norgate Data** / **FirstRate Data** / **Sharadar** |
| **4. Point-in-Time Float Series** | **0 records** (float filter unconstrained) | Historical floating shares series (< 50M share filter) as of each trade date $t$ | **MODERATE** | Inability to filter out large-cap non-runners; may admit large-float stocks into candidate pool. | **Compustat** / **SEC EDGAR** (Form 10-Q/10-K shares outstanding) |
| **5. Market Breadth Feed** | Synthetic 1,566-session table with static values | Daily counts of $+4\%$ gainers, $-4\%$ losers, and stocks $> 40$ SMA computed across all ~6,500 active common stocks | **CRITICAL** | Market Governor cannot accurately transition between GREEN, YELLOW, and RED regimes on historical market turning points. | Calculated daily from full-universe daily bar database |
| **6. Historical Earnings Calendar** | 30 events across 4 tickers | Complete US earnings announcement database with verified BMO ($< 09:30$) and AMC ($\ge 16:00$) release timestamps | **CRITICAL** | Cannot detect Episodic Pivots (Track A) across the wider market. | **Zacks Investment Research** or **Bloomberg** |
| **7. Material Corporate PR / 8-K** | 5 filings across 3 tickers | Complete SEC EDGAR 8-K filings database with exact `acceptanceDateTime` for Items 1.01 and 8.01 | **CRITICAL** | Cannot detect Track B contract win / biotech catalyst setups across the wider market. | **SEC EDGAR Public Index** via automated parser |
| **8. Historical Sector Classifications** | 14 static mappings | Historical GICS or SIC sector classifications tracking company business changes over time | **LOW** | Potential misclassification of historical corporate conglomerates; 2-position sector cap slightly blurred. | **Norgate Data** (GICS history) or **SEC SIC** codes |

---

## 3. Data Procurement & Ingestion Roadmap

To advance to production-grade historical backtesting, the following commercial datasets must be acquired and ingested into `data/`:

```
                           DATA PROCUREMENT ROADMAP
┌────────────────────────────────────────────────────────────────────────┐
│ 1. Core Daily & Symbology Foundation:                                  │
│    - Acquire Norgate Data US Equities (Survivorship-Free + Delisted)   │
│    - Ingest into DuckDB `security_master` and `security_history`       │
│    - Build full historical daily dual-price parquet files              │
├────────────────────────────────────────────────────────────────────────┤
│ 2. Pre-Computed Market Regimes:                                        │
│    - Compute daily +4% / -4% breadth and T2108 across all common stocks│
│    - Store daily regime history (GREEN, YELLOW, RED)                   │
├────────────────────────────────────────────────────────────────────────┤
│ 3. Targeted Intraday Extraction:                                       │
│    - Ingest FirstRate Data 1-minute historical bars for all candidates │
│      passing t-1 pre-market screening gates                            │
│    - Verify 390 RTH bars per regular session                           │
├────────────────────────────────────────────────────────────────────────┤
│ 4. Catalyst Ingestion:                                                 │
│    - Ingest Zacks earnings calendar with BMO/AMC timestamps            │
│    - Ingest SEC EDGAR Item 1.01/8.01 8-K acceptance timestamps         │
└────────────────────────────────────────────────────────────────────────┘
```

---

## 4. Operational Stop Conclusion

Until the above commercial datasets are procured and loaded into the storage layer:
- The strategy mechanics are **100% verified** against the Stage 1D fixture dataset.
- Full multi-year backtesting across the complete US equity universe is **HELD**.
- Fabricating simulated returns without full commercial vendor data is strictly rejected.
