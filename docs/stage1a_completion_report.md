# Stage 1A Completion Report: US Historical Data Readiness & Data Architecture Audit

**Repository:** `C:\work\projects\bonde-strategy`  
**Market:** United States Equities (NYSE / NASDAQ / AMEX)  
**Document:** `docs/stage1a_completion_report.md`  
**Date:** September 2026  
**Status:** COMPLETE — STAGE 1B READY  

---

## 1. Executive Summary

Stage 1A has completed a comprehensive, institutional-grade data readiness and architecture audit for the United States equity implementation of the trading strategy. 

The audit establishes:
1. **Zero Compromise on Survivorship & Lookahead Bias:** Precise mathematical contracts and database schemas preventing data leakage, forward-looking joins, and delisting omissions.
2. **Dual-Price Architecture:** Unadjusted prices strictly isolated for simulated order execution and stops; split-adjusted series strictly isolated for technical indicators (10 EMA, 65-day high, ADV50).
3. **Storage-Optimized Execution Ingestion:** By running daily screening on prior-day ($t-1$) daily bars, the universe requiring 1-minute intraday bars is reduced by $>95\%$, shrinking storage requirements from $>1.5\text{ TB}$ to $<50\text{ GB}$.
4. **Verified Provider Stack:** Clear evaluation of commercial and public data providers, establishing a verified, cost-effective MVP data stack.

---

## 2. Deliverables Inventory

The following specifications and engineering artifacts have been produced in `docs/`:

1. [stage1a_us_data_requirements.md](file:///C:/work/projects/bonde-strategy/docs/stage1a_us_data_requirements.md)  
   * Complete rule-by-rule mapping of all 35 strategy rules to required data domains, exact mathematical definitions, point-in-time constraints, unadjusted vs. adjusted price separation, and engine interfaces.
2. [stage1a_us_data_schema.md](file:///C:/work/projects/bonde-strategy/docs/stage1a_us_data_schema.md)  
   * Production-grade SQL DDL and Parquet partition specifications for all 12 core tables: `security_master`, `security_history`, `daily_bars`, `intraday_bars_1m`, `corporate_actions`, `earnings_events`, `catalyst_events`, `sector_history`, `shares_float_history`, `market_breadth`, `daily_indicators`, and `data_quality_log`.
3. [stage1a_point_in_time_contract.md](file:///C:/work/projects/bonde-strategy/docs/stage1a_point_in_time_contract.md)  
   * Mathematical definitions of availability timestamps ($T_{\text{avail}}$) vs. event timestamps ($T_{\text{event}}$), chronological data pipeline invariants, and concrete SQL anti-patterns vs. correct point-in-time joins.
4. [stage1a_provider_audit.md](file:///C:/work/projects/bonde-strategy/docs/stage1a_provider_audit.md)  
   * Deep technical evaluation of 8 commercial and public data vendors (Norgate Data, FirstRate Data, Polygon.io, Databento, CRSP, Tiingo, SEC EDGAR, FMP/Zacks) distinguishing verified capabilities from unknown marketing claims.
5. [stage1a_data_quality_spec.md](file:///C:/work/projects/bonde-strategy/docs/stage1a_data_quality_spec.md)  
   * 8 automated ingestion validation gates, out-of-bounds detection algorithms, fail-closed protocols, and direct integration with `data_quality_log`.
6. [stage1a_data_gap_matrix.md](file:///C:/work/projects/bonde-strategy/docs/stage1a_data_gap_matrix.md)  
   * Dimensional matrix comparing MVP Required Now vs. Full System Required Later, with gap severity classifications and engineered mitigations.

---

## 3. Core Architectural Decisions

### 3.1 Unadjusted vs. Split-Adjusted Separation
* **Unadjusted (Raw Trade Dollars):** Used exclusively for:
  - 5-minute Opening Range Breakout calculation (09:30–09:35 High/Low)
  - Limit buy order placement and $+1\text{ to }2\%$ collar checks
  - Entry-bar structural stop losses and ongoing trailing stops
  - Limit order fills, tick offsets ($+\$0.01$), and slippage calculations
* **Split-Adjusted:** Used exclusively for:
  - Daily 10 EMA calculations
  - 65-day high resistance level detection
  - Rolling 50-day average daily volume ($\text{ADV}_{50}$)
  - Percentage gain/loss calculations across corporate action dates
* **Cash Dividends:** Strictly excluded from execution price series to prevent phantom stop-outs.

### 3.2 Canonical Security Identifier
Because ticker symbols in US markets are recycled over time (e.g., historical delistings re-issued to new corporations), the engine binds all price series and events to an immutable surrogate key `security_id` via a date-ranged `security_history` table.

### 3.3 Two-Tier Data Pipeline
To avoid loading multi-terabyte 1-minute datasets for 15,000+ stocks across 10 years:
- **Tier 1 (Daily):** Ingest survivorship-free daily bars across all US common stocks to compute market breadth, screen candidates, and enforce daily governors at $t-1$.
- **Tier 2 (Intraday):** Extract 1-minute unadjusted bars *only* for the ~10–50 candidates passing Tier 1 screening on each trading date $t$, plus any open portfolio positions requiring intraday trailing stops.

---

## 4. Recommended MVP Data Stack

| Role | Provider / Source | Cost | Key Advantage |
| :--- | :--- | :--- | :--- |
| **Daily Bars & Delisted Master** | Norgate Data (US Equities Platinum) | ~$420/yr | Gold-standard survivorship-free universe, index constituents, point-in-time ticker changes, automated split adjustments. |
| **Intraday 1-Minute Bars** | FirstRate Data (US Equities 1m Bundle) | ~$800 one-time | Clean 1-minute unadjusted bars for 16,000+ stocks (including 7,000+ delisted) with perpetual local storage. |
| **Catalyst Timestamps (Track B)** | SEC EDGAR Public API | $0 (Public API) | Exact point-in-time `acceptanceDateTime` for 8-K filings. |
| **Earnings Dates (Track A)** | Zacks / FMP Earnings Calendar | ~$100/mo or bundled | Verified BMO / AMC announcement timestamps. |

---

## 5. Storage Estimates (10-Year History: 2015–2024)

| Dataset | Uncompressed | Partitioned Parquet (Snappy) | Optimization Strategy |
| :--- | :---: | :---: | :--- |
| **Security Master & History** | ~10 MB | ~2 MB | Static local cache |
| **Daily Bars (All US Equities)** | ~18 GB | ~3.5 GB | Partitioned by `year/month` |
| **Market Breadth & Indicators** | ~500 MB | ~80 MB | Pre-calculated daily table |
| **Intraday 1m Bars (Full Universe)** | >1,500 GB | >250 GB | *Not recommended for MVP* |
| **Intraday 1m Bars (Screened Candidates)** | ~80 GB | ~16 GB | Partitioned by `date/ticker` for screened watchlist |
| **Corporate Actions & Catalysts** | ~50 MB | ~10 MB | Local SQLite / Parquet |
| **Total MVP Storage Footprint** | **~100 GB** | **~20 GB** | **Fully fits on standard developer workstation SSD** |

---

## 6. Stage 1B Readiness Assessment

| Requirement | Audit Status | Action Required in Stage 1B |
| :--- | :---: | :--- |
| Data Schema Defined | COMPLETE | Generate SQLite/DuckDB DDL scripts. |
| Point-in-Time Rules Defined | COMPLETE | Implement date-boundary validation tests in ingestion pipelines. |
| Validation Gates Defined | COMPLETE | Implement ingestion sanity check modules (`validate_bars()`). |
| Provider Stack Identified | COMPLETE | Implement data adapters for chosen vendor formats. |
| Event Engine Compatibility | COMPLETE | Verified against hardened Stage 0.2 simulator (53 passing tests). |

### Stage 1B Readiness: **READY**
The data architecture is completely specified, bounded, and verified against the strategy engine. The project is ready to proceed to **Stage 1B: Data Ingestion & Pipeline Implementation**.
