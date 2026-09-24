# Stage 1A US Historical Data Schema Specification

**Repository:** `C:\work\projects\bonde-strategy`  
**Storage Architecture:** Hybrid Parquet + DuckDB Lakehouse  
**Scope:** Relational & Columnar Data Schemas for US Equities Backtesting  
**Date:** September 2026  
**Status Standard:** FROZEN ARCHITECTURAL SCHEMA FOR STAGE 1  

---

## 1. Storage Technology Architecture

To support fast symbol/date slicing, point-in-time joins, rolling window aggregations, and high-speed iterative backtests across billions of data points, the backtest database employs a **hybrid Parquet + DuckDB architecture**:

- **Metadata, Reference Data, and Events (DuckDB / SQL):** `security_master`, `security_history`, `corporate_actions`, `earnings_events`, `catalyst_events`, `sector_history`, `market_breadth`.
- **High-Volume Time-Series (Partitioned Apache Parquet Files):** `daily_bars`, `intraday_bars_1m`, `daily_indicators`.
  - Partitioning strategy for `daily_bars`: Partitioned by year (`year=YYYY/daily.parquet`).
  - Partitioning strategy for `intraday_bars_1m`: Partitioned by year and month (`year=YYYY/month=MM/{security_id}.parquet`).

---

## 2. Definitive Database Schemas

### 2.1 `security_master`
Canonical registry of all US common stocks, ETFs, and equities ever active in the investment universe.

```sql
CREATE TABLE security_master (
    security_id         INTEGER PRIMARY KEY,         -- Permanent internal surrogate ID (e.g. 10001)
    primary_ticker      VARCHAR(10) NOT NULL,        -- Most recent / primary ticker symbol
    company_name        VARCHAR(255) NOT NULL,       -- Legal corporate name
    figi                VARCHAR(12) UNIQUE,          -- Bloomberg Financial Instrument Global Identifier
    cusip               VARCHAR(9),                  -- Committee on Uniform Security Identification Procedures
    primary_exchange    VARCHAR(10) NOT NULL,        -- NYSE, NASDAQ, AMEX, BATS
    asset_type          VARCHAR(20) NOT NULL,        -- COMMON_STOCK, ETF, ADR, PREFERRED, WARRANT
    is_actively_trading BOOLEAN NOT NULL,            -- True if currently listed; False if delisted
    first_traded_date   DATE NOT NULL,               -- Earliest historical trading date in database
    last_traded_date    DATE NOT NULL,               -- Latest historical trading date or delisting date
    created_at          TIMESTAMP WITH TIME ZONE NOT NULL DEFAULT CURRENT_TIMESTAMP
);
CREATE INDEX idx_sec_master_ticker ON security_master(primary_ticker);
CREATE INDEX idx_sec_master_figi ON security_master(figi);
```
* **Point-in-Time Rule:** Read-only reference table. `asset_type == 'COMMON_STOCK'` is strictly enforced during universe screening.

---

### 2.2 `security_history`
Chronological mapping of ticker symbols to `security_id` to handle ticker renames, mergers, and symbol reassignments.

```sql
CREATE TABLE security_history (
    history_id          INTEGER PRIMARY KEY,
    security_id         INTEGER NOT NULL REFERENCES security_master(security_id),
    ticker              VARCHAR(10) NOT NULL,        -- Historical ticker used during this window
    effective_from      DATE NOT NULL,               -- Start date for this ticker (inclusive)
    effective_to        DATE NOT NULL,               -- End date for this ticker (inclusive; 9999-12-31 for current)
    exchange            VARCHAR(10) NOT NULL,
    change_reason       VARCHAR(50) NOT NULL,        -- INITIAL_LISTING, REBRAND, MERGER, EXCHANGE_TRANSFER
    created_at          TIMESTAMP WITH TIME ZONE NOT NULL DEFAULT CURRENT_TIMESTAMP,
    CONSTRAINT uq_sec_date_window UNIQUE (security_id, effective_from)
);
CREATE INDEX idx_sec_hist_ticker_date ON security_history(ticker, effective_from, effective_to);
```
* **Point-in-Time Rule:** When querying by symbol on date $t$, join with `ticker = :sym AND effective_from <= t AND effective_to >= t`.

---

### 2.3 `daily_bars`
Daily session price and volume records containing both unadjusted (execution) and split-adjusted (indicator) values.

```sql
CREATE TABLE daily_bars (
    security_id         INTEGER NOT NULL REFERENCES security_master(security_id),
    trading_date        DATE NOT NULL,
    -- Unadjusted (Raw nominal execution dollars)
    open_unadj          DOUBLE PRECISION NOT NULL,
    high_unadj          DOUBLE PRECISION NOT NULL,
    low_unadj           DOUBLE PRECISION NOT NULL,
    close_unadj         DOUBLE PRECISION NOT NULL,
    volume_unadj        BIGINT NOT NULL,
    -- Corporate Action Adjustment Factors
    split_factor        DOUBLE PRECISION NOT NULL DEFAULT 1.0,  -- Cumulative split factor to base date
    dividend_factor     DOUBLE PRECISION NOT NULL DEFAULT 1.0,  -- Cash dividend adjustment factor
    -- Split-Adjusted (For technical indicators & 65D highs)
    open_adj            DOUBLE PRECISION NOT NULL,
    high_adj            DOUBLE PRECISION NOT NULL,
    low_adj             DOUBLE PRECISION NOT NULL,
    close_adj           DOUBLE PRECISION NOT NULL,
    volume_adj          BIGINT NOT NULL,
    -- Session Integrity
    is_halted           BOOLEAN NOT NULL DEFAULT FALSE,
    is_suspicious       BOOLEAN NOT NULL DEFAULT FALSE,
    PRIMARY KEY (security_id, trading_date)
);
CREATE INDEX idx_daily_bars_date ON daily_bars(trading_date);
```
* **Point-in-Time Rule:** Date $t$ data is published after market close (16:00:00 EST). Decisions made during intraday session $t$ can only consume `daily_bars` where `trading_date < t`.

---

### 2.4 `intraday_bars_1m`
Canonical 1-minute OHLCV bars stamped in `America/New_York` timezone.

```sql
CREATE TABLE intraday_bars_1m (
    security_id         INTEGER NOT NULL REFERENCES security_master(security_id),
    timestamp           TIMESTAMP WITH TIME ZONE NOT NULL, -- Canonical America/New_York timestamp
    open                DOUBLE PRECISION NOT NULL,        -- Unadjusted raw trade open
    high                DOUBLE PRECISION NOT NULL,        -- Unadjusted raw trade high
    low                 DOUBLE PRECISION NOT NULL,        -- Unadjusted raw trade low
    close               DOUBLE PRECISION NOT NULL,        -- Unadjusted raw trade close
    volume              BIGINT NOT NULL,                  -- Raw shares traded within the 1-minute window
    trades_count        INTEGER,                          -- Number of discrete print transactions
    vwap                DOUBLE PRECISION,                 -- Volume Weighted Average Price within bar
    PRIMARY KEY (security_id, timestamp)
);
CREATE INDEX idx_intra_1m_sec_ts ON intraday_bars_1m(security_id, timestamp);
```
* **Point-in-Time Rule:** A 1-minute bar stamped `2026-01-05 09:35:00-05:00` covers trades from 09:35:00 to 09:35:59. It becomes fully available to the engine at 09:36:00.

---

### 2.5 `corporate_actions`
Full ledger of splits, dividends, mergers, spin-offs, and delistings.

```sql
CREATE TABLE corporate_actions (
    action_id           INTEGER PRIMARY KEY,
    security_id         INTEGER NOT NULL REFERENCES security_master(security_id),
    action_type         VARCHAR(20) NOT NULL,        -- STOCK_SPLIT, REVERSE_SPLIT, CASH_DIVIDEND, DELISTING, MERGER
    ex_date             DATE NOT NULL,               -- Effective date of corporate action
    record_date         DATE,
    ratio_from          DOUBLE PRECISION,            -- E.g. 1.0 in a 2-for-1 split
    ratio_to            DOUBLE PRECISION,            -- E.g. 2.0 in a 2-for-1 split
    cash_amount         DOUBLE PRECISION,            -- Cash dividend / payout per share
    delisting_reason    VARCHAR(50),                 -- MERGER, LIQUIDATION, NON_COMPLIANCE, BANKRUPTCY
    final_trading_price DOUBLE PRECISION,            -- Last traded price before delisting
    public_announcement_date DATE NOT NULL,          -- When action was made public
    created_at          TIMESTAMP WITH TIME ZONE NOT NULL DEFAULT CURRENT_TIMESTAMP
);
CREATE INDEX idx_corp_act_sec_date ON corporate_actions(security_id, ex_date);
```
* **Point-in-Time Rule:** Corporate action adjustments are applied backwards in time from `ex_date`. The fact of an upcoming split cannot alter execution prices until `ex_date`.

---

### 2.6 `earnings_events`
Point-in-time corporate earnings announcements (Track A).

```sql
CREATE TABLE earnings_events (
    event_id            INTEGER PRIMARY KEY,
    security_id         INTEGER NOT NULL REFERENCES security_master(security_id),
    fiscal_quarter      VARCHAR(10) NOT NULL,        -- Q1-2026, Q4-2025
    announcement_date   DATE NOT NULL,
    announcement_time   TIMESTAMP WITH TIME ZONE NOT NULL, -- Physical public release timestamp
    timing_convention   VARCHAR(10) NOT NULL,        -- BMO (Before Market Open), AMC (After Market Close), DURING
    eps_reported        DOUBLE PRECISION NOT NULL,   -- As reported (unadjusted for later restatements)
    eps_estimate        DOUBLE PRECISION,            -- Consensus estimate prior to release
    eps_surprise_pct    DOUBLE PRECISION,            -- Reported vs. Estimate percentage
    revenue_reported    DOUBLE PRECISION NOT NULL,
    revenue_estimate    DOUBLE PRECISION,
    revenue_surprise_pct DOUBLE PRECISION,
    provider_source     VARCHAR(50) NOT NULL,        -- ZACKS, BENZINGA, FMP
    created_at          TIMESTAMP WITH TIME ZONE NOT NULL DEFAULT CURRENT_TIMESTAMP
);
CREATE INDEX idx_earnings_sec_time ON earnings_events(security_id, announcement_time);
```
* **Point-in-Time Rule:** BMO events are tradable on `announcement_date` at 09:30:00 EST. AMC events are tradable on `announcement_date + 1 session` at 09:30:00 EST.

---

### 2.7 `catalyst_events`
Structured Track B news, 8-K regulatory filings, FDA approvals, and contract announcements.

```sql
CREATE TABLE catalyst_events (
    catalyst_id         INTEGER PRIMARY KEY,
    security_id         INTEGER NOT NULL REFERENCES security_master(security_id),
    catalyst_type       VARCHAR(50) NOT NULL,        -- TRACK_A_EARNINGS, TRACK_B_8K, TRACK_B_FDA, TRACK_B_CONTRACT
    public_timestamp    TIMESTAMP WITH TIME ZONE NOT NULL, -- Physical availability timestamp (SEC acceptanceDateTime)
    filing_type         VARCHAR(20),                 -- 8-K, 6-K, PRESS_RELEASE
    headline            TEXT NOT NULL,
    is_material         BOOLEAN NOT NULL DEFAULT TRUE,
    source_url          VARCHAR(500),
    created_at          TIMESTAMP WITH TIME ZONE NOT NULL DEFAULT CURRENT_TIMESTAMP
);
CREATE INDEX idx_cat_sec_ts ON catalyst_events(security_id, public_timestamp);
```
* **Point-in-Time Rule:** Must strictly satisfy `public_timestamp < 09:30:00 EST` on the trade date to qualify for morning ORB.

---

### 2.8 `sector_history`
Point-in-time industry and sector classifications to enforce the 2.0R Sector Concentration Governor.

```sql
CREATE TABLE sector_history (
    classification_id   INTEGER PRIMARY KEY,
    security_id         INTEGER NOT NULL REFERENCES security_master(security_id),
    taxonomy_standard   VARCHAR(20) NOT NULL,        -- GICS, SIC, NAICS
    sector              VARCHAR(100) NOT NULL,       -- E.g. INFORMATION_TECHNOLOGY
    industry_group      VARCHAR(100) NOT NULL,       -- E.g. SEMICONDUCTORS
    industry            VARCHAR(100) NOT NULL,
    sub_industry        VARCHAR(100),
    effective_from      DATE NOT NULL,               -- Start date of classification
    effective_to        DATE NOT NULL,               -- End date (9999-12-31 for current)
    created_at          TIMESTAMP WITH TIME ZONE NOT NULL DEFAULT CURRENT_TIMESTAMP,
    CONSTRAINT uq_sector_window UNIQUE (security_id, taxonomy_standard, effective_from)
);
CREATE INDEX idx_sec_sector_date ON sector_history(security_id, effective_from, effective_to);
```
* **Point-in-Time Rule:** Query requires `effective_from <= date_t AND effective_to >= date_t`.

---

### 2.9 `shares_float_history`
Point-in-time shares outstanding and free float for turnover and liquidity analysis.

```sql
CREATE TABLE shares_float_history (
    float_id            INTEGER PRIMARY KEY,
    security_id         INTEGER NOT NULL REFERENCES security_master(security_id),
    effective_date      DATE NOT NULL,               -- Date filed / published in 10-Q / 10-K
    shares_outstanding  BIGINT NOT NULL,             -- Total shares outstanding
    free_float_shares   BIGINT NOT NULL,             -- Public floating shares
    insider_ownership_pct DOUBLE PRECISION,
    source_filing       VARCHAR(50),                 -- SEC_10Q, SEC_10K, REUTERS
    created_at          TIMESTAMP WITH TIME ZONE NOT NULL DEFAULT CURRENT_TIMESTAMP,
    CONSTRAINT uq_float_date UNIQUE (security_id, effective_date)
);
CREATE INDEX idx_float_sec_date ON shares_float_history(security_id, effective_date);
```
* **Point-in-Time Rule:** New float data is only valid starting on the SEC filing acceptance date, NOT on the fiscal period end date.

---

### 2.10 `market_breadth`
Pre-calculated daily market breadth metrics to drive the external Market Monitor FSM (GREEN / YELLOW / RED).

```sql
CREATE TABLE market_breadth (
    trading_date        DATE PRIMARY KEY,
    universe_size       INTEGER NOT NULL,            -- Clean common stock universe denominator
    gainers_4pct_count  INTEGER NOT NULL,            -- Number of stocks gaining >= +4.0%
    losers_4pct_count   INTEGER NOT NULL,            -- Number of stocks losing >= -4.0%
    t2108_percent       DOUBLE PRECISION,            -- % of stocks above 40-day SMA
    stocks_above_200sma DOUBLE PRECISION,
    stocks_above_50sma  DOUBLE PRECISION,
    regime_state        VARCHAR(10) NOT NULL,        -- GREEN, YELLOW, RED
    created_at          TIMESTAMP WITH TIME ZONE NOT NULL DEFAULT CURRENT_TIMESTAMP
);
```
* **Point-in-Time Rule:** Computed after market close on date $t-1$. Valid for strategy initialization at 08:00 AM on date $t$.

---

### 2.11 `daily_indicators`
Pre-computed technical indicators for candidates, strictly enforcing $t-1$ lookbacks.

```sql
CREATE TABLE daily_indicators (
    security_id         INTEGER NOT NULL REFERENCES security_master(security_id),
    trading_date        DATE NOT NULL,               -- Session date T (computed using data up to T)
    ema_10_split_adj    DOUBLE PRECISION NOT NULL,   -- 10-day EMA of split-adjusted close
    sma_50_volume       DOUBLE PRECISION NOT NULL,   -- ADV50 of split-adjusted volume
    high_65_split_adj   DOUBLE PRECISION NOT NULL,   -- MAXH65 over [T-65, T]
    high_260_split_adj  DOUBLE PRECISION NOT NULL,   -- MAXH260 over [T-260, T]
    atr_14              DOUBLE PRECISION NOT NULL,
    PRIMARY KEY (security_id, trading_date)
);
CREATE INDEX idx_daily_ind_sec_date ON daily_indicators(security_id, trading_date);
```
* **Point-in-Time Rule:** For intraday execution on date $t$, the engine selects indicators where `trading_date = t - 1 session`.

---

### 2.12 `data_quality_log`
Audit log recording every data anomaly, gap, or out-of-bounds filter event.

```sql
CREATE TABLE data_quality_log (
    log_id              INTEGER PRIMARY KEY,
    security_id         INTEGER REFERENCES security_master(security_id),
    trading_date        DATE NOT NULL,
    data_domain         VARCHAR(50) NOT NULL,        -- DAILY_BARS, INTRADAY_1M, CORPORATE_ACTIONS
    anomaly_type        VARCHAR(50) NOT NULL,        -- BAD_OHLC_ORDER, PRICE_SPIKE, NEGATIVE_VOLUME, TIME_GAP
    severity            VARCHAR(10) NOT NULL,        -- WARNING, ERROR, FATAL_DISCARD
    details             TEXT NOT NULL,
    recorded_at         TIMESTAMP WITH TIME ZONE NOT NULL DEFAULT CURRENT_TIMESTAMP
);
CREATE INDEX idx_dq_date_sev ON data_quality_log(trading_date, severity);
```
