# Stage 1A US Historical Data Requirements Specification

**Repository:** `C:\work\projects\bonde-strategy`  
**Topic:** US Equities Historical Data Requirements & Point-in-Time Audit  
**Scope:** United States Equities (NYSE / NASDAQ / AMEX) 2010–2024  
**Date:** September 2026  
**Status Standard:** AUTHORITATIVE DATA ARCHITECTURE SPECIFICATION  

---

## 1. Executive Summary & Audit Methodology

Stage 0.2 hardened the deterministic event-driven backtest engine, eliminating lookahead leaks and standardizing data contracts for daily indicators and rolling volume averages. 

This document defines the **definitive data specification** required to execute a statistically valid, survivorship-bias-free, point-in-time backtest of the US Momentum & Catalyst Strategy.

### Core Principle: The Causality Invariant
$$\text{Information Available at Simulation Timestamp } T = f\left(\text{Public Market Events } \le T\right)$$
No trade decision, universe screening, position sizing, risk governor evaluation, or order matching may consume:
1. Future prices or volume.
2. Future corporate action announcements.
3. Retrofitted contemporary sector classifications.
4. Future earnings release restatements.
5. Post-delisting survivorship-filtered ticker universes.

---

## 2. Complete Strategy Rule to Data Element Mapping

| # | Strategy Rule | Document Reference | Required Data Element | Required Fields | Point-in-Time Requirement | Historical Availability | Data Quality Requirement | Existing Code Interface | Missing Implementation |
| :--- | :--- | :--- | :--- | :--- | :--- | :--- | :--- | :--- | :--- |
| **1** | **Price Floor ($\ge \$5.00$)** | `02` L17, `06` L78 | Prior Daily Close | `close_unadj`, `split_factor`, `trading_date` | Session $t-1$ Close | Ubiquitous (Norgate, CRSP, Polygon) | Exact unadjusted cash close | [`StrategyConfig.price_floor`](file:///C:/work/projects/bonde-strategy/src/bonde/config/strategy_config.py#L20) | Daily pipeline data loader |
| **2** | **Liquidity Floor ($\text{ADV}_{50} \ge 100\text{k}$)** | `04` L39 | 50-Day Rolling Share Volume | `volume`, `split_factor`, `trading_date` | Completed sessions $[t-50, t-1]$ | Ubiquitous | Split-adjusted historical volume | [`HistoricalADV50Provider`](file:///C:/work/projects/bonde-strategy/src/bonde/data/models.py#L160) | Daily volume aggregator |
| **3** | **Dollar Volume Floor ($\ge \$2.5\text{M}$)** | `04` L41, `06` L88 | $\text{ADV}_{50} \times \text{Close}_{t-1}$ | `volume`, `close_unadj`, `split_factor` | Session $t-1$ Close $\times \text{ADV}_{50}$ | Ubiquitous | Unadjusted close $\times$ split-adjusted ADV | [`StrategyConfig.min_dollar_volume`](file:///C:/work/projects/bonde-strategy/src/bonde/config/strategy_config.py#L22) | Cross-product screener |
| **4** | **65-Day High Resistance** | `02` L13, `06` L87 | Historical Daily Highs | `high_split_adj`, `trading_date` | Sessions $[t-65, t-1]$ | High (Norgate, CRSP, FirstRate) | Split-adjusted; strictly excludes Day $t$ | [`BaseHitSetup.evaluate`](file:///C:/work/projects/bonde-strategy/src/bonde/setups/base_hit.py#L40) | Rolling MAXH65 screener |
| **5** | **4.0% Daily Range Expansion** | `02` L12, `04` L38 | Daily Range | `high_unadj`, `low_unadj`, `close_unadj` | Day $t$ intraday high/low | High | Unadjusted intraday print | [`BaseHitSetup.evaluate`](file:///C:/work/projects/bonde-strategy/src/bonde/setups/base_hit.py#L40) | Intraday expansion trigger |
| **6** | **1.5x Volume Expansion** | `02` L14, `04` L47 | Day $t$ Volume vs. $\text{ADV}_{50}$ | `intraday_volume`, `adv_50` | Cumulative volume at trigger timestamp | High | Split-adjusted volume ratio | [`BaseHitSetup.evaluate`](file:///C:/work/projects/bonde-strategy/src/bonde/setups/base_hit.py#L62) | Cumulative volume tracker |
| **7** | **Episodic Pivot Gap ($\ge +10\%$)** | `01` L35, `06` L73 | Pre-market / Open Gap | `open_unadj_t`, `close_unadj_{t-1}` | 09:30:00 AM Open print vs $t-1$ Close | High | Split-adjusted gap percentage | [`CatalystORBSetup`](file:///C:/work/projects/bonde-strategy/src/bonde/setups/catalyst.py#L24) | Pre-market screener |
| **8** | **EP Relative Volume ($\ge 3.0\text{x}$)** | `01` L37, `06` L74 | Full-Day Volume vs. $\text{ADV}_{50}$ | `daily_volume`, `adv_50` | Day $t$ close volume | High | Split-adjusted volume ratio | [`StrategyConfig`](file:///C:/work/projects/bonde-strategy/src/bonde/config/strategy_config.py#L21) | Daily volume classifier |
| **9** | **EP9M Heavy Liquidity ($\ge 9\text{M}$)** | `06` L78 | Absolute Session Volume | `daily_volume_unadj` | Day $t$ total volume $\ge 9,000,000$ | Ubiquitous | Unadjusted raw shares traded | [`StrategyConfig`](file:///C:/work/projects/bonde-strategy/src/bonde/config/strategy_config.py#L21) | Volume threshold filter |
| **10** | **5-Minute ORB Window** | `06` L100 | 1-Minute Intraday Bars | `open`, `high`, `low`, `close`, `volume` | Exactly 09:30:00–09:34:59 EST | Medium (FirstRate, Databento, Polygon) | Regular trading hours only, zero gaps | [`CatalystORBSetup.evaluate_first_5_minutes`](file:///C:/work/projects/bonde-strategy/src/bonde/setups/catalyst.py#L40) | Intraday bar loader |
| **11** | **ORB Geometry Gate ($\le 4.0\%$)** | `06` L103 | 5-Minute Range | `ORH`, `ORL` | Exactly 09:35:00 EST | Derived from 1m bars | Unadjusted raw dollar values | [`CatalystORBSetup`](file:///C:/work/projects/bonde-strategy/src/bonde/setups/catalyst.py#L73) | Implemented |
| **12** | **Universal Risk Gate ($\le 4.0\%$)** | `06` L182 | Order Trigger & Stop | `trigger_price`, `stop_price` | 09:35:00 EST order staging | Derived from ORH/ORL + ticks | Unadjusted dollar values | [`Stage0BacktestEngine._evaluate_and_stage_orb`](file:///C:/work/projects/bonde-strategy/src/bonde/engine/backtest.py#L286) | Implemented |
| **13** | **Stop-Limit Collar Matching** | `06` L138 | 1-Minute Intraday Bars | `open`, `high`, `low`, `close` | 09:36:00–10:14:59 EST | Medium | Unadjusted execution prices | [`ExecutionSimulator.process_entry_order`](file:///C:/work/projects/bonde-strategy/src/bonde/execution/simulator.py#L37) | Implemented |
| **14** | **10:15 AM Stale Purge** | `06` L253 | Bar Timestamp | `timestamp` | Exactly 10:15:00 EST | Ubiquitous | Timezone America/New_York | [`ExecutionSimulator`](file:///C:/work/projects/bonde-strategy/src/bonde/execution/simulator.py#L48) | Implemented |
| **15** | **Same-Bar Stop Precedence (D2)** | Confirmed D2 | 1-Minute Intraday Bars | `low`, `high`, `open` | Intraday continuous | Ubiquitous | Invariant STOP-FIRST | [`ExecutionSimulator.evaluate_position_exits`](file:///C:/work/projects/bonde-strategy/src/bonde/execution/simulator.py#L123) | Implemented |
| **16** | **Entry-Bar Stop Breach** | Stage 0.2 | 1-Minute Intraday Bars | `low`, `initial_stop` | Entry Bar $t$ post-fill | Ubiquitous | Immediate post-fill evaluation | [`Stage0BacktestEngine._process_pending_orders`](file:///C:/work/projects/bonde-strategy/src/bonde/engine/backtest.py#L225) | Implemented |
| **17** | **+2.0R Partial Exit (50%)** | `01` L74, `06` L152 | 1-Minute Intraday Bars | `high`, `partial_target` | Intraday continuous | Ubiquitous | GTC Limit simulation | [`Position.execute_partial_exit`](file:///C:/work/projects/bonde-strategy/src/bonde/portfolio/portfolio.py#L67) | Implemented |
| **18** | **Breakeven Ratchet** | `01` L76, `06` L156 | Internal State | `current_stop = entry + $0.01` | Immediate on +2R fill | Internal | Zero risk accounting | [`Position.execute_partial_exit`](file:///C:/work/projects/bonde-strategy/src/bonde/portfolio/portfolio.py#L85) | Implemented |
| **19** | **03:55 PM EOD T1 Scratch** | `06` L180 | 1-Minute Close Print | `close_unadj`, `timestamp` | Exactly 15:55:00 EST | Ubiquitous | 15:55:00 bar close print | [`Stage0BacktestEngine._evaluate_eod_audit`](file:///C:/work/projects/bonde-strategy/src/bonde/engine/backtest.py#L152) | Implemented |
| **20** | **03:55 PM EOD T2 Stall** | `06` L183 | 1-Minute Close Print | `close_unadj`, `timestamp` | Day 2 at 15:55:00 EST | Ubiquitous | 15:55:00 bar close print | [`Stage0BacktestEngine._evaluate_eod_audit`](file:///C:/work/projects/bonde-strategy/src/bonde/engine/backtest.py#L157) | Implemented |
| **21** | **Base-Hit Day 5 Time Stop** | `02` L48, `06` L173 | Session Count | `days_held >= 5` | Day 5 at 15:55:00 EST | Internal | Session boundary counter | [`Stage0BacktestEngine._evaluate_eod_audit`](file:///C:/work/projects/bonde-strategy/src/bonde/engine/backtest.py#L162) | Implemented |
| **22** | **Daily 10 EMA Trailing Runner** | `01` L79, `06` L159 | Historical Daily Closes | `close_split_adj`, `trading_date` | Completed daily sessions up to $t-1$ | Ubiquitous | Split-adjusted EMA calculation | [`DailyIndicatorProvider`](file:///C:/work/projects/bonde-strategy/src/bonde/data/models.py#L108) | Daily close series connector |
| **23** | **Parabolic Climax ($\ge 25\% > 10\text{EMA}$)** | `06` L162 | Intraday High vs. 10 EMA | `high_unadj`, `ema_10` | Intraday continuous | High | Split-aligned price to EMA | [`StrategyConfig.parabolic_climax_pct`](file:///C:/work/projects/bonde-strategy/src/bonde/config/strategy_config.py#L44) | Climax exit evaluator |
| **24** | **1R Position Sizing** | `03` L23, `06` L113 | Account Equity, Entry, Stop | `equity`, `entry`, `stop` | Point-in-time equity at 09:35 | Internal | Integer floor division | [`calculate_position_size`](file:///C:/work/projects/bonde-strategy/src/bonde/risk/sizing.py#L31) | Implemented |
| **25** | **Liquidity Cap (1.5% ADV50)** | `06` L114 | Rolling $\text{ADV}_{50}$ | `adv_50` | Completed sessions $[t-50, t-1]$ | Ubiquitous | Split-adjusted average volume | [`calculate_liquidity_cap`](file:///C:/work/projects/bonde-strategy/src/bonde/risk/sizing.py#L24) | Implemented |
| **26** | **Allocation Floor (0.60R)** | `06` L117 | Planned vs. Allocated Shares | `ratio = allocated / planned` | Point-in-time sizing check | Internal | Strict cutoff $\ge 0.60$ | [`calculate_position_size`](file:///C:/work/projects/bonde-strategy/src/bonde/risk/sizing.py#L88) | Implemented |
| **27** | **Portfolio Heat Cap (6.0R)** | `06` L122 | Total Uncushioned Open Risk | `current_risk_dollars` | Point-in-time aggregate check | Internal | Uncushioned sum $\le 6.0\text{R}$ | [`HeatGovernor`](file:///C:/work/projects/bonde-strategy/src/bonde/risk/governors.py#L46) | Implemented |
| **28** | **Sector Cap (2.0R)** | `06` L130 | Point-in-Time Industry Group | `industry_group`, `current_risk` | Effective classification at date $t$ | Specialized (CRSP, Norgate, FactSet) | Historical point-in-time mapping | [`SectorGovernor`](file:///C:/work/projects/bonde-strategy/src/bonde/risk/governors.py#L74) | Historical sector provider |
| **29** | **Sector Cushion Unlock** | `06` L130 | Position Cushion Flag | `is_cushioned = True` | Upon +2R BE ratchet | Internal | Downside risk reset to 0.0 | [`SectorGovernor`](file:///C:/work/projects/bonde-strategy/src/bonde/risk/governors.py#L94) | Implemented |
| **30** | **Single Ticker Cap (1.0R)** | `06` L133 | Active Positions | `symbol` | Point-in-time check | Internal | Max 1 open position per symbol | [`SingleTickerGovernor`](file:///C:/work/projects/bonde-strategy/src/bonde/risk/governors.py#L107) | Implemented |
| **31** | **Internal Loss Circuit Breaker** | `06` L332 | Closed Trade PnL History | `realized_pnl` | Real-time on trade close | Internal | 3 consecutive losses = Halt | [`InternalLossGovernor`](file:///C:/work/projects/bonde-strategy/src/bonde/risk/governors.py#L123) | Implemented |
| **32** | **External Market RED Freeze** | `04` L19, `06` L57 | Daily Breadth / Market State | `regime = GREEN/YELLOW/RED` | Available at 08:00 AM for day $t$ | Specialized breadth feed | Prior-day market close calculation | [`RegimeGovernor`](file:///C:/work/projects/bonde-strategy/src/bonde/risk/governors.py#L29) | Implemented |
| **33** | **Track A Earnings Announcement** | `01` L17, `06` L38 | Corporate Earnings Calendar | `announcement_time`, `BMO_AMC` | Public timestamp $< 09:30:00$ Day $t$ | Specialized (Zacks, Benzinga, FMP) | Strict BMO/AMC tagging | [`CatalystEvent`](file:///C:/work/projects/bonde-strategy/src/bonde/data/models.py#L45) | Point-in-time earnings loader |
| **34** | **Track B PR / 8-K Catalyst** | `01` L23, `06` L39 | SEC 8-K / News Filings | `filing_datetime`, `item_code` | Acceptance timestamp $< 09:30:00$ | SEC EDGAR API | Acceptance timestamp | [`CatalystEvent`](file:///C:/work/projects/bonde-strategy/src/bonde/data/models.py#L45) | Structured catalyst loader |
| **35** | **Float Turnover / 9M Liquidity** | `01` L38, `06` L78 | Shares Outstanding & Float | `shares_out`, `free_float` | Effective on date $t$ | Specialized (CRSP, FactSet, SEC) | Point-in-time shares | None | Float history provider |

---

## 3. Data Domain Requirements

### A. Daily Equity Data
* **Unadjusted vs. Split-Adjusted Separation:**
  - **UNADJUSTED (Raw Dollar Quotes):** Strictly required for **trade execution, simulated orders, stop-loss triggers, limit collars, tick offsets ($+\$0.01$), and slippage modeling**. Backtest execution orders must reflect nominal historical exchange quotes.
  - **SPLIT-ADJUSTED:** Required for **historical indicators, 65-day high resistance calculation, moving averages, and percentage return calculations**. An unadjusted 65-day high would create a false breakout signal immediately following a reverse stock split.
  - **CASH DIVIDENDS:** Ordinary cash dividends must **NOT** adjust historical prices used for execution or stops. Cash dividend adjustments (e.g. Yahoo Finance adjusted close) distort technical levels and intraday price reality.
* **Volume Handling:**
  - Raw share volume is used for execution liquid caps and Day-1 EP9M thresholds ($9,000,000$ shares).
  - Split-adjusted historical volume is used for rolling 50-day volume ($\text{ADV}_{50}$) and relative volume expansion ratios ($\text{RVOL} \ge 1.5\text{x}$ or $3.0\text{x}$).

### B. 1-Minute Intraday Data
* **Market Hours & Session Granularity:**
  - Regular Trading Hours (RTH): `09:30:00` to `16:00:00` America/New_York.
  - Pre-Market (Optional for screening): `08:00:00` to `09:29:59` America/New_York (required to detect gap percent prior to open).
* **Minimum Intraday Scope (Storage Optimization):**
  - Storing 1-minute bars for 15,000 securities across 15 years requires $> 1\text{ TB}$ of data.
  - **Optimization Architecture:** Daily screening is conducted across the full universe. 1-minute intraday bars are only ingested and loaded for **qualifying candidates** that meet the daily screening criteria on date $t-1$ (65-day high proximity, Track A earnings gap, or volume expansion).

### C. Survivorship-Bias-Free Universe & Canonical Security Identity
* **The Ticker Re-use Problem:** US equity tickers are frequently recycled by exchanges. For example, ticker `AAPL` has remained constant, but hundreds of three- and four-letter tickers were reassigned to completely different companies after delistings.
* **Canonical Security Identifier:** The database must use an immutable surrogate primary key (`security_id` as an integer or UUID) linked to ticker history:
  $$\text{security\_history: } (\text{security\_id}, \; \text{ticker}, \; \text{effective\_from}, \; \text{effective\_to})$$
* **Delisted Coverage:** The historical universe must include delisted, acquired, and bankrupt securities (approx. 7,000+ delisted US equities between 2010 and 2024).

### D. Corporate Actions
* **Stock Splits & Reverse Splits:** Multiplier applied to split-adjusted series. Must record exact `ex_date`.
* **Mergers, Cash Buyouts, Delistings:** Terminal trading date recorded. Delisting price must be captured (or zero in catastrophic bankruptcies) to avoid unclosed positions.
* **Ticker Changes:** Must preserve continuous price history under the same `security_id`.

### E. Earnings & Catalyst Data (Track A)
* **Point-in-Time Availability:** Distinguish `announcement_timestamp` from database ingestion time.
* **BMO vs. AMC Tagging:**
  - **Before Market Open (BMO):** Released prior to 09:30:00 EST. Tradable on Day $t$.
  - **After Market Close (AMC):** Released after 16:00:00 EST. Tradable on Day $t+1$.
* **Restatement Immunity:** Original reported EPS and revenue estimates must be preserved. Point-in-time backtesting strictly forbids using post-hoc accounting restatements.

### F. SEC Filings & Press Releases (Track B)
* **Point-in-Time Public Release:** SEC EDGAR `acceptanceDateTime` represents the physical timestamp when an 8-K became available to public subscribers.
* **Structured Ingestion:** Filings are ingested with standardized classification codes (e.g. `FDA_APPROVAL`, `CONTRACT_WIN`, `MERGER_ACQUISITION`).

### G. Point-in-Time Sector & Industry Classification
* **No Backward Retrofitting:** Applying contemporary GICS tables backward through history creates false industry groupings for companies that transitioned themes.
* **Effective Date Tracking:** Classification tables must record `(security_id, sector, industry_group, effective_date, expiry_date)`.

### H. ADV50: Share Volume vs. Dollar Volume
* **Share Volume $\text{ADV}_{50}$:** Used for liquidity participation capping ($\text{LiquidCap} = \lfloor \text{ADV}_{50} \times 0.015 \rfloor$).
* **Dollar Volume $\text{ADV}_{\$, 50}$:** Used for universe quality filtering ($\text{Close}_{t-1} \times \text{ADV}_{50} \ge \$2,500,000$).
* Both metrics must be calculated strictly across sessions $[t-50, t-1]$.
