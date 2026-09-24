# Stage 0 Completion Report: USA Strategy Architecture

**Repository:** `C:\work\projects\bonde-strategy`  
**Execution Environment:** Python 3.13.12 (win32)  
**Test Suite Status:** 26/26 PASSED (100%)  
**Completion Date:** September 22, 2026  

---

## A. Implemented Components

1. **Configuration Layer (`bonde.config.strategy_config`):**
   - Frozen Stage 0 baseline configuration dataclass preserving market timing, risk gates, liquidity caps, and exit parameters.
2. **Canonical Data Model (`bonde.data.models` & `bonde.data.loaders`):**
   - Strict 1-minute `Bar` model with timezone enforcement (`America/New_York`).
   - Abstract `SectorProvider` and `StaticSectorProvider` (D5) preventing static GICS hardcoding.
   - Abstract `CommissionModel` and `SlippageModel` (D8) with zero-cost defaults.
   - Structured `CatalystEvent` point-in-time metadata container.
3. **Market Regime FSM (`bonde.regime.market_regime`):**
   - External regime provider consuming GREEN, YELLOW, and RED market states (D6).
   - Regime risk fraction mapping: Green = 1.0% (D3), Yellow = 0.5% (D4), Red = 0.0% (new trades disabled).
4. **Position Sizing & Liquidity Engine (`bonde.risk.sizing`):**
   - Volatility-adjusted 1R share calculation with integer floor division.
   - 1.5% ADV50 liquidity participation ceiling.
   - 0.60R minimum allocation threshold (rejects trades where allocated shares < 60% of planned shares).
5. **Portfolio Risk Governors (`bonde.risk.governors`):**
   - Hierarchical Composite Risk Governor enforcing the master veto priority.
   - Sector Concentration Governor (max 2.0R uncushioned in same industry group).
   - Single-Ticker Governor (max 1.0R per symbol, deduplicating signals).
   - Portfolio Heat Governor (max 6.0R uncushioned open risk).
   - Internal Loss Governor (tracks consecutive losses for pilot/pause states).
6. **Execution Simulator (`bonde.execution.simulator` & `bonde.execution.orders`):**
   - Stop-Limit collar matching engine (`Trigger + $0.10`); rejects price chasing (`COLLAR_MISS`).
   - 10:15:00 AM stale order purge (`STALE_ORDER_PURGE`).
   - **MANDATORY SAME-BAR RULE (D2):** Enforces **STOP FIRST** when both target and stop are reached in the same bar.
7. **Setup Detection Modules (`bonde.setups`):**
   - 5-minute Opening Range Breakout (ORB) with $\le 4.0\%$ geometry gate (`ORB_GEOMETRY_FAIL`).
   - Base-Hit 65-day high intraday breakout detector (D1) establishing structural stops.
   - Inside-Day compression squeeze evaluator.
8. **Position Lifecycle & EOD Audit (`bonde.portfolio.portfolio`):**
   - Active position tracker calculating unrealized and realized PnL.
   - Partial exit at $+2.0\text{R}$ (50% tranche) with immediate Breakeven ratchet (`Entry + $0.01`).
   - 03:55 PM EOD audit: liquidates fresh T1 positions closing $\le \text{Entry}$; enforces Day 5 time stop on Base Hits.
9. **Telemetry & Audit Journal (`bonde.telemetry.trade_log`):**
   - Structured 27-column master trade record.
   - Explicit rejection event logger capturing non-qualifying setups.
10. **Event-Driven Backtest Engine (`bonde.engine.backtest`):**
    - Chronological bar simulator ensuring zero future lookahead bias.

---

## B. Unit Test Execution Results

```text
============================= test session starts =============================
platform win32 -- Python 3.13.12, pytest-8.3.4, pluggy-1.6.0
rootdir: C:\work\projects\bonde-strategy
configfile: pyproject.toml
collected 26 items

tests/test_base_hit.py::test_valid_base_hit_qualification PASSED         [  3%]
tests/test_base_hit.py::test_base_hit_price_floor_rejection PASSED       [  7%]
tests/test_base_hit.py::test_base_hit_volume_expansion_rejection PASSED  [ 11%]
tests/test_base_hit.py::test_base_hit_risk_geometry_rejection PASSED     [ 15%]
tests/test_catalyst_orb.py::test_orb_geometry_pass PASSED                [ 19%]
tests/test_catalyst_orb.py::test_orb_geometry_rejection PASSED           [ 23%]
tests/test_catalyst_orb.py::test_inside_day_setup PASSED                 [ 26%]
tests/test_eod_governor.py::test_eod_audit_liquidates_t1_close_below_entry PASSED [ 30%]
tests/test_eod_governor.py::test_eod_audit_holds_t1_close_above_entry PASSED [ 34%]
tests/test_eod_governor.py::test_base_hit_day_5_time_stop PASSED         [ 38%]
tests/test_orders.py::test_stop_limit_collar_fill PASSED                 [ 42%]
tests/test_orders.py::test_stop_limit_collar_miss PASSED                 [ 46%]
tests/test_orders.py::test_stale_order_cutoff_1015 PASSED                [ 50%]
tests/test_orders.py::test_order_remains_pending_if_not_triggered PASSED [ 53%]
tests/test_regime.py::test_regime_risk_fractions PASSED                  [ 57%]
tests/test_regime.py::test_red_regime_rejects_new_trades PASSED          [ 61%]
tests/test_same_bar.py::test_same_bar_stop_precedence PASSED             [ 65%]
tests/test_same_bar.py::test_target_only_fill PASSED                     [ 69%]
tests/test_same_bar.py::test_stop_only_fill PASSED                       [ 73%]
tests/test_sector_governor.py::test_sector_governor_enforces_2r_cap PASSED [ 76%]
tests/test_sector_governor.py::test_sector_governor_cushion_unlock PASSED [ 80%]
tests/test_sizing.py::test_green_regime_sizing PASSED                    [ 84%]
tests/test_sizing.py::test_yellow_regime_sizing PASSED                   [ 88%]
tests/test_sizing.py::test_liquidity_cap_rejection PASSED                [ 92%]
tests/test_sizing.py::test_liquidity_cap_fractional_accepted PASSED      [ 96%]
tests/test_sizing.py::test_sizing_validation_errors PASSED               [100%]

============================= 26 passed in 3.37s ==============================
```
* **Tests Run:** 26  
* **Tests Passed:** 26 (100%)  
* **Tests Failed:** 0  

---

## C. Strategy Rules Implementation Matrix

| Strategy Rule | Document Reference | Implemented | Tested | Verification Details |
| :--- | :--- | :---: | :---: | :--- |
| **Price Floor ($\ge \$5.00$)** | `02` L17, `06` L78 | Yes | Yes | Rejects setups with price $< \$5.00$ |
| **1R Sizing (Green = 1.0%)** | `03` L15, `06` L113 | Yes | Yes | `floor(equity * 0.01 / stop_dist)` |
| **1R Sizing (Yellow = 0.5%)** | `03` L75, `06` L56 | Yes | Yes | `floor(equity * 0.005 / stop_dist)` |
| **Liquidity Cap (1.5% ADV)** | `06` L114 | Yes | Yes | Caps shares at `ADV50 * 0.015` |
| **Allocation Floor (0.60R)** | `06` L117 | Yes | Yes | Rejects trades if allocated $< 0.60 \times$ planned |
| **ORB 5-Min Geometry ($\le 4\%$)** | `06` L103 | Yes | Yes | Rejects 5-min range $> 4.0\%$ |
| **ORB Trigger & Stop Offset** | `06` L106 | Yes | Yes | Buy Stop = ORH + $0.01, Stop = ORL - $0.01 |
| **Stop-Limit Collar ($+\$0.10$)** | `06` L138 | Yes | Yes | Fills within collar; cancels on collar miss |
| **10:15 AM Stale Order Purge** | `06` L253 | Yes | Yes | Cancels unfilled staged orders at 10:15 EST |
| **Same-Bar Stop Precedence** | Confirmed D2 | Yes | Yes | Invariant: Stop executes before target |
| **Red Regime Freeze** | `04` L19, `06` L57 | Yes | Yes | Rejects 100% of new orders in Red state |
| **Sector Cap (Max 2.0R)** | `06` L130 | Yes | Yes | Blocks orders exceeding 2.0R in same sector |
| **Sector Cushion Unlock** | `06` L130 | Yes | Yes | +2R BE stop resets active sector risk to 0 |
| **Single Ticker Deduplication** | `06` L133 | Yes | Yes | Prevents multiple positions in same ticker |
| **+2.0R Partial Exit (50%)** | `06` L152 | Yes | Yes | Sells 50% shares at +2.0R limit |
| **Breakeven Ratchet** | `06` L156 | Yes | Yes | Stop moved to Entry + $0.01 on +2R fill |
| **03:55 PM EOD T1 Scratch** | `06` L180 | Yes | Yes | Liquidates T1 close $\le$ Entry at market |
| **Base-Hit Day 5 Time Stop** | `06` L173 | Yes | Yes | Liquidates Base Hits held $\ge 5$ sessions |
| **Master Veto Hierarchy** | `06` L37 | Yes | Yes | Evaluated in strict hierarchical order |

---

## D. Assumptions Made in Stage 0

1. **Intraday Bar Resolution:** 1-minute OHLCV is assumed as the canonical simulation granularity.
2. **Same-Bar Collision (D2):** When both target and stop price levels fall within the same 1-minute bar, the stop is assumed to execute first.
3. **Execution Slippage & Commissions (D8):** Baseline simulation assumes zero slippage and zero commissions; interfaces `SlippageModel` and `CommissionModel` are in place for Stage 1.
4. **Base-Hit Breakout Execution (D1):** Executed as an intraday breakout upon breaching the 65-day high $+ \$0.01$.
5. **Dollar Volume Baseline:** Evaluated as $\text{Close}_{t-1} \times \text{ADV}_{50} \ge \$2,500,000$.
6. **Sector Taxonomy (D5):** Interfaced via `SectorProvider` to decouple point-in-time sector metadata from core simulation logic.
7. **Market Monitor (D6):** Consumed as an external daily feed (GREEN, YELLOW, RED) rather than computed cross-sectionally.

---

## E. Unresolved Questions for Production Backtesting

1. **Point-in-Time Corporate Earnings Feed:** An institutional historical database providing exact timestamped earnings announcements (BMO vs. AMC) is required to run the Catalyst Engine across 2010–2024.
2. **Survivorship-Bias-Free Delisting Universe:** Free retail APIs (e.g. yfinance) suffer severe survivorship bias. A survivorship-free vendor (e.g. Norgate Data US Equities) is necessary before publishing performance claims.
3. **Historical Sector Mapping Data:** Historical GICS classifications must be procured to enforce the 2.0R Sector Cap point-in-time.
4. **Trading Halts & LULD Policy:** How the simulation handles overnight gap freezes or intra-day LULD pauses where market stops cannot fill at expected prices.

---

## F. Data Requirements for Stage 1

| Dataset | Required Frequency | Format | Purpose in Stage 1 |
| :--- | :---: | :---: | :--- |
| **US Equities Daily OHLCV (Survivorship-Free)** | Daily | Parquet / CSV | Universe screening, 65D highs, 50 SMA volume, delistings |
| **US Equities 1-Minute Intraday Bars** | 1-minute | Parquet / DuckDB | ORB construction, Stop-Limit collar matching, MAE/MFE |
| **Point-in-Time Earnings Calendar** | Event / Daily | CSV / Database | Validating Track A Earnings EP dates (BMO/AMC) |
| **GICS Industry Group Historical Mapping** | Point-in-Time | CSV / Database | Enforcing the 2.0R Sector Cap historically |

---

## G. Known Limitations of Stage 0

1. **Synthetic Data Focus:** Verification was conducted on engineered synthetic datasets designed to validate software logic and edge cases; Stage 0 **does not establish statistical edge or profitability**.
2. **No Track B NLP Parser:** Automated text parsing of SEC 8-K filings and PR Newswire is not implemented in Stage 0.
3. **No Standalone Breadth Generator:** The Market Monitor breadth calculation across 6,000+ stocks is externalized.
4. **Static Slippage Baseline:** Variable bid/ask spreads and liquidity sweep slippage are not modeled in Stage 0.

---

## H. Recommended Stage 1 Roadmap

Stage 1 must **NOT** jump to live trading or broker integration.  
**Stage 1 Scope:**
1. Ingest survivorship-free historical daily data (2010–2024) from Norgate Data or CRSP.
2. Connect historical 1-minute bar feeds for screened candidates.
3. Ingest point-in-time earnings announcement calendar data (BMO/AMC).
4. Run the first historical walk-forward backtest of the Base-Hit Engine and Track A Catalyst Engine.
5. Execute parameter sensitivity surface testing on the 4% range expansion and 4% risk geometry gates.
