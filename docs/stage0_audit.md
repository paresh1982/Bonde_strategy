# Stage 0 Implementation Readiness Audit: USA Strategy Architecture

**Repository:** `C:\work\projects\bonde-strategy`  
**Target Market:** United States Equities (NYSE / NASDAQ / AMEX)  
**Date:** September 2026  
**Status:** Frozen Stage 0 Baseline  

---

## 1. Executive Summary

This audit establishes the implementation baseline for **Stage 0 of the USA Trading System**. Stage 0 is an event-driven, deterministic research/backtest engine designed to prove that the strategy's documented rules can be executed in software without lookahead bias, discretionary decisions, or hidden assumptions.

The six source specification documents audited are:
1. `01_episodic_pivots_and_catalysts.md`
2. `02_momentum_and_swing_trading_setups.md`
3. `03_risk_management_and_position_sizing.md`
4. `04_market_breadth_and_routines.md`
5. `05_authoritative_sources_and_references.md`
6. `06_unified_algorithmic_specification.md`

---

## 2. Rules Found & Audited

### 2.1 Universe & Liquidity Filters
* **Exchange Scope:** US common stocks trading on primary exchanges (`04` L8, `06` L250).
* **Price Floor:** Prior close $\ge \$5.00$ (`02` L17, `04` L40, `06` L78, L88). *(Note conflict with $3.00 in `01` L91)*.
* **Volume Liquidity:** 50-day average volume $\text{ADV}_{50} \ge 100,000$ shares (`04` L39).
* **Dollar Volume Floor:** Prior close $\times \text{ADV}_{50} \ge \$2,500,000$ (`04` L41, `06` L88).
* **Participation Cap:** Position size $\le 1.5\%$ of $\text{ADV}_{50}$ (`06` L114).
* **Liquidity Allocation Floor:** If $\text{AllocatedShares} < 0.60 \times \text{PlannedShares}$, reject trade entirely (`06` L117–120).

### 2.2 Setup Detection
* **Base-Hit Breakout (65D / 4%):**
  * 65-day high breakout (`02` L13, `04` L45, `06` L87).
  * Range expansion $\ge +4.0\%$ (`02` L12, `04` L38).
  * Volume expansion $\ge 1.5\text{x}$ 50-day average (`02` L14, `04` L47).
  * Consolidation variants: Flat Top and 3–5 day pullbacks to 10 EMA (`02` L26–48).
* **Catalyst / Episodic Pivot (EP / EP9M / DEP):**
  * Gap $\ge +10.0\%$ (`01` L35, `06` L73).
  * Relative volume $\ge 3.0\text{x}$ 50-day average (`01` L37, `06` L74).
  * Closing range in top $25\%$ of Day 1 (`01` L40).
  * EP9M: Day 1 volume $\ge 9,000,000$ shares (`06` L78).
  * DEP: 2–5 day shelf in upper 50% of Day 1 range; never violates Day 1 LOD (`06` L50–52).

### 2.3 Entry Execution & Geometry Gates
* **Opening Range Breakout (ORB):** 5-minute range (09:30:00–09:35:00 EST).
  * $\text{Trigger} = \text{ORH} + \$0.01$; $\text{Stop} = \text{ORL} - \$0.01$ (`06` L106–107).
  * Range geometry gate: $[(\text{ORH} - \text{ORL}) / \text{ORH}] \le 4.0\%$ (`06` L101–104).
* **Stop-Limit Collar:** $\text{Limit} = \text{Trigger} + \text{Collar}$ ($+\$0.05\text{ to } +\$0.15$, or $\le 0.5\%$). If market opens above limit, cancel without chasing (`06` L137–146).
* **10:15 AM Stale Order Purge:** Any unfilled morning Buy Stop is cancelled at 10:15:00 EST (`06` L253).

### 2.4 Position Sizing & Portfolio Governors
* **Risk Units:**
  * Green regime: $1\text{R}_{\$} = \text{Equity} \times 0.010$ (1.0% account risk).
  * Yellow regime: $1\text{R}_{\$} = \text{Equity} \times 0.005$ (0.5% account risk).
  * Red regime: New trades disabled ($0\text{R}$ risk).
* **Position Sizing:** $\text{Shares} = \text{floor}(1\text{R}_{\$} / (\text{Entry} - \text{Stop}))$.
* **Portfolio Heat Cap:** Maximum 6.0R to 8.0R open uncushioned risk (`06` L122).
* **Sector Cap:** Maximum 2.0R open uncushioned risk in the same industry group (`06` L130).
* **Ticker Deduplication:** Maximum 1.0R per ticker. Multiple signals deduplicated into a single opportunity (`06` L133).
* **Waterfall Priority:** Catalyst Engine funded first; residual risk allocated to Base Hits sorted by $\text{EfficiencyScore} = \text{RVOL} / \text{Risk\%}$ (`06` L124–127).

### 2.5 Position Management & Exit Rules
* **Catalyst Lifecycle (+2R / BE / Runner):**
  * Sell 50% at $+2.0\text{R}$ via GTC Limit order (`06` L152).
  * Upon fill, move stop on remaining 50% to Breakeven ($\text{Entry} + \$0.01$) (`06` L156).
  * Trail runner on daily close below 10 EMA (`06` L159).
  * Parabolic climax exit if price $\ge 25\%\text{–}30\%$ above 10 EMA (`06` L162).
* **Base-Hit Lifecycle:** 100% exit at $+2.0\text{R}\text{ to }+3.0\text{R}$ or after 3–5 sessions at 03:55 PM. No runner (`06` L169–174).
* **03:55 PM Mandatory EOD Audit:**
  * Fresh T1: If $\text{Close} \le \text{Entry}$, liquidate at market close (`06` L180).
  * T2: If stalled and $\text{Close} \le \text{Entry}$, liquidate at market close (`06` L183).
  * DEP: If Day 5 reached without $+2.0\text{R}$, liquidate at market close (`06` L189).

---

## 3. Rules That Can Be Implemented Now (Stage 0 MVP Scope)

1. **Deterministic 1-Minute Bar Engine:** Ingestion of 1-minute OHLCV bars stamped in `America/New_York` timezone.
2. **5-Minute ORB Construction & Geometry Check:** Calculating ORH/ORL from 09:30:00 to 09:34:59 EST, evaluating $\le 4.0\%$ geometry at 09:35:00 EST.
3. **Stop-Limit Collar Matching:** Simulating fill within collar vs. missed trade if bar opens above collar.
4. **10:15 AM Stale Order Purge:** Cancelling unfilled staged orders at 10:15:00 EST.
5. **Base-Hit Intraday Breakout Trigger (D1):** Detecting 65-day high cross intraday and establishing the initial structural stop.
6. **Same-Bar Stop Precedence (D2):** Enforcing stop-loss execution before profit target when both levels are touched in the same bar.
7. **Regime-Dependent Position Sizing (D3, D4):**
   * Green: $\text{Equity} \times 0.01$.
   * Yellow: $\text{Equity} \times 0.005$.
   * Floor integer division for shares.
8. **1.5% ADV Liquidity Cap & 0.60R Floor:** Mathematical capping and rejection of illiquid setups.
9. **Single-Ticker Deduplication & Sector Cap Interface (D5):** Enforcing max 1.0R per symbol and max 2.0R per sector via pluggable `SectorProvider`.
10. **Universal Management Engine:** $+2.0\text{R}$ partial exit (50%), Breakeven stop ratchet, and 03:55 PM EOD audit scratches.
11. **Telemetry & Audit Journal:** 27-field trade records and explicit rejection event logs.

---

## 4. Rules Requiring Data Not Yet Available

1. **Historical Delisted Equities Database:** Comprehensive point-in-time US equity universe including bankruptcies and acquisitions (e.g. Norgate Data, CRSP).
2. **Historical 1-Minute Intraday Bar Feed:** Full tick/1-minute history across thousands of tickers from 2010 to 2024.
3. **Point-in-Time Corporate Earnings Calendar:** Historical timestamps (BMO vs. AMC) and consensus estimates for Track A EPs.
4. **SEC EDGAR 8-K & PR News Feeds:** Machine-readable point-in-time corporate announcements for Track B EPs.
5. **Cross-Sectional Market Breadth Database:** Daily OHLCV for all 6,000+ US stocks to compute 4% Gainers vs. 4% Losers.
6. **Point-in-Time Float Shares:** Historical daily floating share counts.
7. **Historical GICS Industry Group Mapping:** Survivorship-free historical industry classifications.

---

## 5. Identified Contradictions in Existing Specifications

| # | Topic | Document A | Document B | Conflict / Resolution for Stage 0 |
| :---: | :--- | :--- | :--- | :--- |
| **C1** | **Price Floor** | `01` L39, L88 states $\$3.00\text{–}\$4.00$. | `02` L17, `04` L40, `06` L78, L85 states $\ge \$5.00$. | **Resolved for Stage 0:** Enforce $\ge \$5.00$ floor strictly per `06`. Reject sub-$5 stocks. |
| **C2** | **Profit Tranche Size** | `01` L75, `03` L53 states "1/3 to 1/2 of shares". | `06` L152, L155 states "strictly 50% of shares". | **Resolved for Stage 0:** Enforce strictly $50\%$ per `06`. Odd shares: $\text{floor}(N/2)$. |
| **C3** | **Trailing Stop MA** | `01` L80, `03` L62 states "8 EMA or 10 EMA". | `06` L159 states "Daily 10 EMA". | **Resolved for Stage 0:** Enforce Daily 10 EMA strictly per `06`. |
| **C4** | **Base-Hit Exit Architecture** | `03` L51–64 applies 3-step trailing runner to swing trades. | `06` L89, L174 mandates "100% exit at 3–5 days; ZERO RUNNER". | **Resolved for Stage 0:** Enforce Document 06. Base Hits have zero runner and exit 100% within 3–5 days. |
| **C5** | **Market RED Action on Runners** | `04` L19 mandates "100% Cash". | `06` L200 & Q38 allow holding runners trailing on PDL. | **Resolved for Stage 0:** Follow `06`. In RED, new trades are $0\text{R}$; runners trail on Prior Day Low. |

---

## 6. Ambiguities Flagged for Human Review

1. **Intrabar Same-Bar High/Low Priority:** Resolved for Stage 0 via confirmed decision **D2: Stop is assumed to trigger first**.
2. **Base-Hit Breakout Trigger:** Resolved for Stage 0 via confirmed decision **D1: Intraday breakout over 65-day high $+ \$0.01$**.
3. **Base-Hit Time-Stop Duration:** "3 to 5 sessions" is ambiguous. For Stage 0, default to **Day 5 close at 03:55 PM** unless $+2.0\text{R}$ is hit earlier or position closes below entry.
4. **Dollar Volume Baseline:** Calculated as $\text{Close}_{t-1} \times \text{ADV}_{50} \ge \$2,500,000$.

---

## 7. Confirmed Stage 0 Assumptions (D1–D8)

* **Assumption D1:** Base-Hit trigger is an intraday breakout over 65-day high.
* **Assumption D2:** Same-bar target and stop collision assumes STOP FIRST.
* **Assumption D3:** Green regime risk is $1.0\%$ of account equity ($\text{Equity} \times 0.01$). Sizing is $\text{floor}(\text{Risk} / \text{StopDistance})$.
* **Assumption D4:** Yellow regime risk is $0.5\%$ of account equity ($\text{Equity} \times 0.005$).
* **Assumption D5:** Sector classification is accessed via abstract `SectorProvider`; not hard-coded.
* **Assumption D6:** Market Monitor state (GREEN, YELLOW, RED) is supplied as an external daily input.
* **Assumption D7:** 1-minute OHLCV (`America/New_York` timezone) is the canonical simulation resolution. Initial MVP uses synthetic/sample test bars.
* **Assumption D8:** Commissions and slippage are zero in Stage 0 baseline, wrapped in pluggable `CommissionModel` and `SlippageModel` interfaces.

---

## 8. Deferred Components (Post-Stage 0)

1. Automated SEC EDGAR / PR Newswire NLP text classifier.
2. Full cross-sectional US market breadth calculation engine.
3. Complex DEP discretionary variants (Low Cheat, Shakeout & Reclaim).
4. Point-in-time floating share turnover calculations.
5. Live broker API connectivity, real-money execution, and web UI.
6. Multi-broker fee and dark pool routing simulations.
