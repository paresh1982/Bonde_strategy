# Stage 1B US Historical Data Dictionary

**Repository:** `C:\work\projects\bonde-strategy`  
**Market:** United States Equities (NYSE / NASDAQ / AMEX)  
**Document:** `docs/stage1b_data_dictionary.md`  
**Status:** IMPLEMENTED SPECIFICATION  

---

## 1. Security Master & Lifecycle Symbology

### 1.1 `security_master` Table / Schema
Maintains canonical immutable entities representing corporate issuers. Solves the ticker recycling problem (`ticker != security_id`).

| Field Name | Type | Constraints | Description |
| :--- | :--- | :--- | :--- |
| `security_id` | `VARCHAR(32)` | PRIMARY KEY | Immutable canonical surrogate key (e.g. `SEC_0001`). |
| `ticker` | `VARCHAR(16)` | NOT NULL | Current or primary trading ticker string. |
| `exchange` | `VARCHAR(16)` | NOT NULL | Primary listing exchange (`NASDAQ`, `NYSE`, `AMEX`). |
| `name` | `VARCHAR(255)`| NOT NULL | Legal issuer corporate name. |
| `first_trade_date` | `DATE` | NOT NULL | Date continuous public trading commenced. |
| `last_trade_date` | `DATE` | NOT NULL | Final recorded trading date. |
| `delisting_date` | `DATE` | NULLABLE | Date trading ceased due to acquisition, bankruptcy, or delisting. |
| `active_flag` | `BOOLEAN` | NOT NULL | `TRUE` if currently listed; `FALSE` if delisted/inactive. |
| `cusip` | `VARCHAR(9)` | NULLABLE | 9-character CUSIP identifier. |
| `figi` | `VARCHAR(12)`| NULLABLE | OpenFIGI unique instrument identifier. |

### 1.2 `security_history` Table / Schema
Tracks temporal validity windows for ticker aliases, renames, and corporate reassignments.

| Field Name | Type | Constraints | Description |
| :--- | :--- | :--- | :--- |
| `security_id` | `VARCHAR(32)` | NOT NULL | Foreign key referencing `security_master(security_id)`. |
| `ticker` | `VARCHAR(16)` | NOT NULL | Historical ticker string active during window. |
| `effective_from`| `DATE` | NOT NULL | Start date (inclusive) of ticker validity. |
| `effective_to` | `DATE` | NULLABLE | End date (inclusive) of validity. `NULL` indicates actively ongoing. |

* **Invariant:** Lookup `resolve_security_id(ticker, as_of_date)` matches records where `effective_from <= as_of_date <= effective_to`. Fails closed (`None`) if unmapped or colliding.

---

## 2. Dual-Price Daily Market Data

### 2.1 `daily_bars` Dual-Price Schema
Strictly isolates raw unadjusted trade dollars from split-adjusted analytical series.

| Field Name | Type | Price Domain | Strategy Usage |
| :--- | :--- | :--- | :--- |
| `security_id` | `VARCHAR(32)` | Identifier | Primary join key to `security_master`. |
| `session_date` | `DATE` | Temporal | Trading session date. |
| `open` | `DOUBLE` | **Unadjusted** | Opening price in raw historical trade dollars. |
| `high` | `DOUBLE` | **Unadjusted** | Daily high for breakout triggers and trade verification. |
| `low` | `DOUBLE` | **Unadjusted** | Daily low for structural stop-loss evaluation. |
| `close` | `DOUBLE` | **Unadjusted** | EOD continuous session close for limit collar and execution. |
| `volume` | `DOUBLE` | **Unadjusted** | Raw traded share volume. |
| `adjusted_open` | `DOUBLE` | **Split-Adjusted** | Split-adjusted open. |
| `adjusted_high` | `DOUBLE` | **Split-Adjusted** | Split-adjusted high for Point-in-Time 65-day high calculation. |
| `adjusted_low` | `DOUBLE` | **Split-Adjusted** | Split-adjusted low for technical shelf identification. |
| `adjusted_close`| `DOUBLE` | **Split-Adjusted** | Split-adjusted close for Point-in-Time 10 EMA calculation. |
| `adjusted_volume`|`DOUBLE` | **Split-Adjusted** | Split-adjusted volume for Point-in-Time $\text{ADV}_{50}$ calculation. |
| `source` | `VARCHAR(32)` | Metadata | Vendor origin (`NORGATE`, `FIRSTRATE`, `SYNTHETIC`). |
| `ingested_at` | `TIMESTAMP` | Metadata | Ingestion timestamp (UTC). |

* **Execution Constraint:** Never use `adjusted_close`, `adjusted_high`, or `adjusted_low` to simulate order fills or stop triggers.

---

## 3. Intraday 1-Minute Execution Bars

### 3.1 `intraday_bars_1m` Schema
Maintains continuous regular trading hours (09:30–16:00 ET) 1-minute bars for candidates passing daily universe filters.

| Field Name | Type | Constraints | Description |
| :--- | :--- | :--- | :--- |
| `security_id` | `VARCHAR(32)` | NOT NULL | Canonical security identifier. |
| `symbol` | `VARCHAR(16)` | NOT NULL | Ticker symbol string. |
| `timestamp_utc` | `TIMESTAMP` | NOT NULL | Bar opening timestamp normalized to UTC. |
| `open` | `DOUBLE` | NOT NULL | 1-minute unadjusted opening trade price. |
| `high` | `DOUBLE` | NOT NULL | 1-minute unadjusted high trade price. |
| `low` | `DOUBLE` | NOT NULL | 1-minute unadjusted low trade price. |
| `close` | `DOUBLE` | NOT NULL | 1-minute unadjusted closing trade price. |
| `volume` | `DOUBLE` | NOT NULL | Shares transacted during the 1-minute interval. |

---

## 4. Catalysts & Event Architecture

### 4.1 Track A: `earnings_events`
Historical corporate earnings releases with verified announcement timing.

| Field Name | Type | Description |
| :--- | :--- | :--- |
| `security_id` | `VARCHAR(32)` | Canonical security identifier. |
| `event_timestamp`| `TIMESTAMP` | Exact release timestamp. |
| `event_date` | `DATE` | Corporate event calendar date. |
| `timing` | `VARCHAR(8)` | `BMO` (Before Market Open), `AMC` (After Market Close), `UNKNOWN`. |
| `availability_timestamp` | `TIMESTAMP` | Time announcement was publicly available in market. |
| `source` | `VARCHAR(32)` | Vendor origin (`ZACKS`, `FMP`, `SEC_EDGAR`). |

* **Point-in-Time Cutoff:** For Day-1 pre-market trading, `availability_timestamp <= 09:29:59 America/New_York`.

### 4.2 Track B: `sec_filings_8k`
SEC EDGAR material corporate events.

| Field Name | Type | Description |
| :--- | :--- | :--- |
| `security_id` | `VARCHAR(32)` | Canonical security identifier. |
| `cik` | `VARCHAR(10)` | SEC Central Index Key. |
| `accession_number`| `VARCHAR(25)`| Unique SEC submission accession number. |
| `acceptance_datetime`|`TIMESTAMP` | Microsecond timestamp from SEC EDGAR ingestion header. |
| `form` | `VARCHAR(8)` | SEC form type (`8-K`). |
| `items` | `VARCHAR(255)`| Item codes (e.g. `Item 1.01 Entry into Material Agreement`). |
| `availability_timestamp`|`TIMESTAMP`| Timestamp filing was queryable by the public. |

---

## 5. Market Breadth & Regime Data

### 5.1 `market_breadth` Schema
Point-in-time daily market health metrics driving the external Market Governor.

| Field Name | Type | Description |
| :--- | :--- | :--- |
| `session_date` | `DATE` | Trading session date $t-1$. |
| `universe_size` | `INTEGER` | Common stock denominator count. |
| `gainers_4pct_count`| `INTEGER` | Count of stocks gaining $\ge +4.0\%$ on the session. |
| `losers_4pct_count` | `INTEGER` | Count of stocks declining $\le -4.0\%$ on the session. |
| `t2108_percent` | `DOUBLE` | Percentage of common stocks trading above 40-day SMA. |
| `regime_state` | `VARCHAR(10)`| `GREEN`, `YELLOW`, `RED`. |
