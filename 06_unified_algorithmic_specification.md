# Unified Algorithmic Specification & Finite-State Machine

```text
                    ┌─────────────────────────┐
                    │  MARKET / PORTFOLIO FSM │
                    └────────────┬────────────┘
                                 │
                  ┌──────────────┴──────────────┐
                  ▼                             ▼
           EXTERNAL GOVERNOR             INTERNAL GOVERNOR
           Green / Yellow / Red          Performance / DD
                  │                             │
                  └──────────────┬──────────────┘
                                 ▼
                       AVAILABLE RISK BUDGET
                                 │
                    ┌────────────┴────────────┐
                    ▼                         ▼
             CATALYST ENGINE             BASE-HIT ENGINE
             EP / EP9M / DEP              65D / 4%+
                    │                         │
                    └────────────┬────────────┘
                                 ▼
                         CANDIDATE GATES
                                 │
                    Catalyst / Structure /
                    Risk / Liquidity / Sector
                                 │
                                 ▼
                         CAPITAL ALLOCATION
                       Catalyst → Base-Hit
                                 │
                                 ▼
                        EXECUTION GATE
                    Stop-Limit + Risk Collar
                                 │
                                 ▼
                             POSITION
                                 │
             ┌───────────────────┼───────────────────┐
             ▼                   ▼                   ▼
           +2R                Failure             Time Stop
        50% Partial         / EOD Governor       / Regime RED
             │                   │                   │
             ▼                   ▼                   ▼
        BE + Runner          Liquidate            Liquidate
             │
             ▼
          10 EMA
           Trail
```

---

## 1. Master State Hierarchy & Veto Authority
The state machine evaluates top-down in strict hierarchical priority. A lower layer can never override a higher layer:

```text
1. Account-Level Catastrophic Governor (Nuclear Kill / Drawdown Freeze)
2. Internal Portfolio Governor (Consecutive Losses / Rolling Expectancy)
3. External Market Monitor (4% Gainers vs. Losers: Green / Yellow / Red)
4. Portfolio Heat & Sector Capacity Limits (6–8R Max Heat | 2.0R Sector Cap)
5. Engine Eligibility (Catalyst vs. Base-Hit Waterfall)
6. Candidate Structural Gates (Catalyst Triage | 65D High | Vol Contraction)
7. Capital Allocation Waterfall (Catalyst Seniority → Residual Base-Hit Allocation)
8. Execution Quality & Liquidity Gate (Stop-Limit Collar | 1.5% ADV Cap | 0.60R Floor)
9. Position Management & Lifecycle (+2.0R GTC Partial | BE Ratchet | 10 EMA Runner)
10. End-of-Day Transition (3:55 PM Mandatory Audit & Stalled Breakout Liquidations)
```

$$\textbf{Account RED} \succ \textbf{Internal RED} \succ \textbf{External RED} \succ \textbf{YELLOW} \succ \textbf{GREEN}$$

---

## 2. Daily Initialization Protocol (08:00 AM – 09:15 AM)
```pseudo
load_account_equity()
calculate_1R()
load_open_positions()
calculate_uncushioned_risk()
calculate_total_portfolio_heat()
calculate_sector_heat()

read_market_monitor()
read_internal_governor()

determine_system_state()

if catastrophic_drawdown:
    ACCOUNT_STATE = FROZEN
elif internal_failure:
    INTERNAL_STATE = RED
else:
    MARKET_STATE = GREEN / YELLOW / RED
```

* **GREEN:** Deploy up to **3.0R** daily risk (subject to $6\text{–}8\text{R}$ portfolio heat ceiling).
* **YELLOW:** Deploy up to **1.0R** daily risk (Catalyst Engine only; Base Hits disabled; max 2–3 open positions).
* **RED:** Deploy **0.0R** risk (All new staged orders purged; existing positions enter defensive protocols).

---

## 3. Catalyst Discovery & Classification (EP / EP9M / DEP)
A candidate enters the Catalyst Engine only if:
```pseudo
price >= minimum_price
catalyst_is_unexpected == TRUE
catalyst_timestamp <= 09:29:59
```

* **Track A (Senior Priority):** Earnings surprise, guidance raise, fundamental forecast revision.
* **Track B (Secondary Priority):** Transformational contract, FDA approval, major regulatory/corporate inflection.

### Episodic Pivot (EP) Setup
```pseudo
gap >= EP_expansion_threshold (>= +10%)
RVOL >= required_RVOL (>= 3.0x 50-day SMA)
catalyst == TRUE
risk_geometry <= 4.0%
```

### EP 9 Million (EP9M) Sub-Species
```pseudo
regular_session_volume >= 9,000,000 shares
price >= $5.00
range_expansion >= +8.0% to +10.0%
catalyst == TRUE
float_turnover >= 15.0% to 20.0%+
```
*Note: EP9M is a high-liquidity subset of Catalyst; due to wide Day-1 ranges ($>4\%$), it executes primarily via DEP.*

---

## 4. Base-Hit Discovery & Vehicles (65D / 4%)
Base-Hit candidates require:
```pseudo
price >= $5.00
daily_expansion >= +4.0%
volume >= 1.5x to 2.0x 50-day SMA
price >= 65-day high (or 260-day high)
dollar_volume >= liquidity_floor ($2.5M to $5.0M)
```
* **Vehicle 1:** Direct 65-Day Breakout (Momentum Burst).
* **Vehicle 2:** The Flat Top / 3 to 5-Day Pullback to 10 EMA (Anticipation).
* **Lifecycle Constraint:** **100% exit within 3 to 5 sessions. ZERO RUNNER.**

---

## 5. Entry Adapter Framework
Qualified Catalyst candidates execute through modular adapters:
* **Day-1 ORB:** First 5-minute Opening Range Breakout.
* **High-Tight DEP:** Consolidation in upper 25% of Day-1 range.
* **Inside-Day Squeeze:** Binary compression within upper third of Day-1.
* **10 EMA Pullback:** Digestion into 50%–75% zone of Day-1 testing the 10 EMA.
* **Tactical Variations:** Low Cheat, Intraday Flat Top, Undercut-and-Reclaim.

All adapters feed the **Universal Risk & Position Management Engine**.

---

## 6. Opening Range Breakout (ORB) Geometry Gate
At 09:35:00 AM EST:
```pseudo
ORH = high(first_5_minutes)
ORL = low(first_5_minutes)

range_pct = (ORH - ORL) / ORH

if range_pct > 4.0%:
    reject_ORB()
    candidate -> DEP_pipeline
else:
    trigger = ORH + $0.01
    stop = ORL - $0.01
```

---

## 7. Universal Risk-Geometry Filter
For every candidate across all modules:
```pseudo
planned_risk_pct = (entry - stop) / entry

if planned_risk_pct > 4.0%:
    REJECT_TRADE()
```
*Stops are never widened to accommodate an oversized range.*

---

## 8. Position Sizing & Liquidity-Cap Engine
```pseudo
PlannedShares = 1R_$ / (Entry - Stop)
LiquidCap = ADV_50 * 0.015
ActualShares = min(PlannedShares, LiquidCap)

if ActualShares < 0.60 * PlannedShares:
    REJECT_TRADE_DUE_TO_LIQUIDITY()
else:
    DEPLOY ActualShares (Accept fractional R between 0.60R and 1.0R)
```

---

## 9. Capital Allocation Waterfall
```pseudo
R_available = min(Market_Regime_Budget, Portfolio_Heat_Cap - Open_Uncushioned_Risk)

R_Catalyst = min(|C| * 1.0R, R_available)
R_Residual = R_available - R_Catalyst
R_BaseHit  = min(|B| * 1.0R, R_Residual)

if |B| * 1.0R > R_Residual:
    Rank Base-Hits by EfficiencyScore = (Day1_RVOL / Planned_Risk_Pct)
    Fund top candidates up to R_Residual
```

---

## 10. Correlation & Sector Governor
```pseudo
if (Sector_Uncushioned_Risk + Proposed_Risk) > 2.0R:
    REJECT_TRADE_DUE_TO_SECTOR_HEAT()

Single_Ticker_Exposure_Max = 1.0R
Deduplicate multiple signals on the same ticker into ONE 1.0R opportunity.
```

---

## 11. Execution Governor & Anti-Chasing Law
```pseudo
Order_Type = STOP_LIMIT
Trigger    = Setup_Trigger
Limit      = Setup_Trigger + Collar (+$0.05 to +$0.15, or <= 0.5%)

if market_executes <= Limit:
    FILL_ORDER()
else:
    CANCEL_ORDER()
    DO_NOT_CHASE()

if actual_fill_risk > 4.0%:
    IMMEDIATE_LIQUIDATION_VOID()
```

---

## 12. Universal Position Lifecycle (Catalyst Engine)
Upon fill:
1. Stage GTC Limit Order: Sell **50% at $+2.0\text{R}$**.
2. Stage GTC Stop Order: Sell **100% at Structural Stop**.

```pseudo
when price touches +2.0R:
    execute_limit_sell(50% position)
    remaining_stop = Entry + $0.01 (Breakeven)
    position_status = CUSHIONED_RUNNER

manage remaining 50% via Daily 10 EMA:
    if daily_close < 10_EMA:
        liquidate_remaining_50% at 3:55 PM
    elif price >= 10_EMA * 1.25 (Parabolic Climax):
        liquidate_remaining_50% into strength
```

---

## 13. Base-Hit Lifecycle
```pseudo
upon fill:
    stage GTC Limit: Sell 100% at +2.0R to +3.0R
    stage Stop: Sell 100% at Structural Stop

at 3:55 PM on Day 3 to 5:
    liquidate 100% position at market (Zero permanent runner)
```

---

## 14. Daily End-of-Day Audit (03:55 PM EST — SENIOR GOVERNOR)
```pseudo
for each open position:
    if position is Fresh_T1:
        if Close <= Entry:
            liquidate_at_market()
    
    elif position is T2:
        if stalled and Close <= Entry:
            liquidate_at_market()
            
    elif position is Base_Hit:
        if holding_period >= 3 to 5 sessions:
            liquidate_at_market()
            
    elif position is DEP:
        if Day >= 5 and not touched(+2.0R):
            liquidate_at_market()
            
    elif position is Cushioned_Runner:
        if Close < Daily_10_EMA:
            liquidate_remaining_50%()
```

---

## 15. External Market RED Defense Protocol
```pseudo
upon Market_Monitor == RED:
    cancel_all_pending_orders()
    new_risk_budget = 0.0R
    
    for each position in Uncushioned_T1_T2:
        tighten_stop_to(Current_Session_LOD)
        
    for each position in Cushioned (+1.0R to +1.5R):
        sell_50%_at_market()
        ratchet_remainder_stop_to(Breakeven)
        
    for each position in Established_Runner:
        tighten_trailing_stop_from(10_EMA, to=Prior_Day_Low)
```

---

## 16. Internal RED Performance Governor
```pseudo
if daily_realized_loss <= -2.5R to -3.0R:
    INTERNAL_RED = TRUE
    HALT_TRADING_FOR_DAY()
    
if consecutive_losses >= 3 to 4:
    SLASH_SIZING_TO_0.25R_PILOT()
    
if consecutive_losses_at_pilot >= 2:
    INTERNAL_RED = TRUE
    FREEZE_TRADING_FOR_2_TO_5_DAYS()
```

---

## 17. Engine-Specific Telemetry & Deactivation
```pseudo
for each engine in [Catalyst, Base-Hit]:
    if engine.consecutive_losses >= 3:
        engine.state = OFFLINE
    elif engine.rolling_10_trade_expectancy <= 0.0R:
        engine.state = OFFLINE
    elif engine.consecutive_stalls >= 5:
        engine.state = OFFLINE
```

---

## 18. Engine Rehabilitation Protocol
```pseudo
when engine is OFFLINE:
    Stage 1: Shadow-track watchlist until 2 consecutive setups hit +2.0R
    Stage 2: Deploy ONE test trade at 0.25R pilot risk
    Stage 3: If pilot hits +2.0R -> Restore engine to full 1.0R operation
```

---

## 19. Catastrophic Account Governor (The Nuclear Kill Switch)
```pseudo
if account_equity_drawdown >= 5.0% to 6.0%:
    LIQUIDATE_100%_POSITIONS_AT_MARKET()
    CANCEL_ALL_STAGED_ORDERS()
    FREEZE_ALL_TRADING_FOR_1_TO_2_WEEKS()
    
    rehabilitation:
        resume trading ONLY at 0.25R pilot size
        require 3 consecutive profitable trades before restoring 1.0R size
```

---

## 20. Backtest State Machine Sequence
Every simulated session must strictly follow point-in-time causality:
$$\begin{aligned}
t-1 \text{ Close} &\longrightarrow \text{Universe Screen} \longrightarrow \text{Point-in-Time Catalyst Verification} \\
&\longrightarrow \text{Market State Evaluation} \longrightarrow \text{Candidate Gates} \longrightarrow \text{Portfolio Heat Check} \\
&\longrightarrow 9\text{:}30\text{–}9\text{:}35\text{ Bar Print} \longrightarrow \text{Risk Geometry Check} \longrightarrow \text{Stop-Limit Simulation} \\
&\longrightarrow 10\text{:}15\text{ Stale Purge} \longrightarrow \text{Intraday Tick Engine} \longrightarrow +2\text{R BE Ratchet} \\
&\longrightarrow 3\text{:}55\text{ PM Mandatory EOD Audit} \longrightarrow 4\text{:}00\text{ PM Close} \longrightarrow \text{Journal Log}
\end{aligned}$$

---

## 21. Minimum Backtest Reporting Schema
Every executed trade record must output:
`Date`, `Ticker`, `Engine`, `Entry_Module`, `Catalyst_Track`, `Catalyst_Timestamp`, `Market_Regime`, `Internal_State`, `Sector`, `Entry_Price`, `Initial_Stop`, `Planned_Risk_Pct`, `Actual_Risk_Pct`, `Shares`, `Planned_R`, `Actual_R`, `Slippage`, `MAE`, `MFE`, `Time_to_1R`, `Time_to_2R`, `Partial_Exit_Price`, `Runner_Exit_Price`, `Final_Net_R`, `Holding_Period_Bars`, `EOD_Exit_Flag`, `Governor_Exit_Flag`.

---

## 22. Fundamental Invariants

$$\boxed{\text{Capital Allocation} = f\big(\text{Regime}, \; \text{Internal State}, \; \text{Catalyst Seniority}, \; \text{Geometry}, \; \text{Liquidity}, \; \text{Sector}, \; \text{Execution}\big)}$$

$$\boxed{\textbf{No lower-level signal can override a higher-level risk governor.}}$$

> **Research Status:** The architecture is fully formalized. The statistical edge and parameters ($9\text{M}$ volume, $65\text{D}$ high, $\le 4.0\%$ geometry, $0.60\text{R}$ liquidity floor, $1.5\%$ ADV cap, and $\$2.5\text{M}$ capacity boundary) are frozen as **testable hypotheses** pending point-in-time historical backtesting, walk-forward analysis, and controlled ablation testing.
