# Stage 0.2 Canonical Event Priority Matrix: USA Strategy Architecture

**Repository:** `C:\work\projects\bonde-strategy`  
**Standard:** Strict Intraday Determinism and Precedence Resolution  
**Scope:** Canonical America/New_York Trading Session Event Loop  
**Date:** September 2026  

---

## 1. Master Session Timeline & Canonical Event Ordering

In an event-driven backtest simulation operating on 1-minute discrete OHLCV bars, deterministic event ordering prevents lookahead bias, race conditions, and optimistic fill distortions.

The engine executes operations within each session according to the strict priority sequence below:

```text
08:00 AM EST  ──►  Pre-Market System Initialization & External Feed Refresh
09:30:00 AM   ──►  Session Open & First 1-Minute Bar; 5-Minute ORB Window Opens
09:30–09:34   ──►  Opening Range Accumulation (Bars strictly < 09:35:00)
09:35:00 AM   ──►  ORB Lock, Raw Geometry Gate (<=4%), Universal Risk Gate (<=4%), 
                   Sizing, Master Governors Veto, and Stop-Limit Order Staging
09:36–10:14   ──►  Order Processing, Intraday Fill, Immediate Post-Fill Exit Check, 
                   and Mark-to-Market
10:15:00 AM   ──►  Stale Order Purge (Pending Morning Buy Stops Cancelled Before Price Eval)
10:15–15:54   ──►  Position Exit Monitoring (+2R Limit Sell, Structural Stop, Breakeven Ratchet)
15:55:00 PM   ──►  Mandatory Senior EOD Audit:
                   1. Fresh T1 Scratch (Close <= Entry)
                   2. T2 Stalled Scratch (Close <= Entry)
                   3. Base-Hit Time Stop (Day 5 Liquidation)
                   4. Cushioned Runner 10 EMA Exit (Close < 10 EMA)
16:00:00 PM   ──►  Session Final Close, PnL Mark-to-Market, and Daily Journal Log
```

---

## 2. Intrabar Priority Hierarchy (Within Any Single Bar $B_t$)

When a single 1-minute bar $B_t$ arrives at timestamp $T$, the engine processes operations in this exact immutable order:

| Priority | Operational Phase | Specific Evaluation & Action | Precedence Rules & Invariants |
| :---: | :--- | :--- | :--- |
| **1** | **Date Rollover** | New date check; increment `days_held` on active positions; reset daily caches (`_opening_bars_cache`, `_orb_staged_today`). | Ensures holding periods increment strictly once per daily session boundary. |
| **2** | **Existing Position Exits** | Evaluate active positions against $B_t$ High/Low for $+2.0\text{R}$ Target and Stop Loss. | **Rule D2 (STOP-FIRST):** If both Target and Stop are reachable within $B_t$, Stop executes first at `min(stop, open)`. |
| **3** | **Senior EOD Audit** | Triggered if `bar_time >= 15:55:00 EST`. Evaluates T1 Scratch, T2 Stall, Day 5 Base-Hit Time Stop, and Cushioned Runner 10 EMA. | Closes positions at `bar.close` print. Closed positions immediately exit the active book and notify internal governors. |
| **4** | **Pending Order Processing** | Process staged `Order` instances: <br>a) If `bar_time >= 10:15:00`: Cancel order (`STALE_ORDER_PURGE`). <br>b) If `bar.high >= trigger`: Check `bar.open > limit` (`COLLAR_MISS`); else fill at `max(trigger, open)`. | Stale purge precedes price trigger at 10:15:00. Collar miss prevents price chasing. |
| **5** | **Post-Fill Exit Check** | **NEW IN STAGE 0.2:** If an order filled during Priority 4 on Bar $B_t$, immediately evaluate whether $B_t$ Low breached `initial_stop`. | **Conservative Invariant:** If $B_t$ Low breaches stop, position is stopped out on Bar $B_t$ (`ENTRY_BAR_STOP_BREACH`). |
| **6** | **Opening Range Cache** | If `09:30:00 <= bar_time < 09:35:00`: Append $B_t$ to `_opening_bars_cache[symbol]`. | Bar 09:35:00 is strictly excluded from opening range formation. |
| **7** | **ORB Gate & Order Staging** | At exactly `bar_time == 09:35:00`: <br>a) Compute `(ORH - ORL) / ORH <= 4.0%`. <br>b) Compute `(Trigger - Stop) / Trigger <= 4.0%`. <br>c) Check ADV50 and Risk Governors. <br>d) Stage `BUY_STOP_LIMIT`. | Staging occurs after Priority 4 on Bar 09:35:00, guaranteeing staged order cannot fill earlier than 09:36:00. |

---

## 3. Simultaneous Timestamp Collision Matrix

| Simultaneous Events | Trigger Condition | Canonical Precedence | Resolution Logic |
| :--- | :--- | :--- | :--- |
| **Target + Stop Collision** | Active position; `low <= stop` AND `high >= target` on same bar. | **STOP FIRST** | Stop executes at `min(stop, bar.open)`. Target order ignored. |
| **Entry Fill + Stop Breach** | Pending order fills at trigger; same bar registers `low <= stop`. | **STOP IMMEDIATE** | Position opened, then immediately closed at `min(stop, bar.open)` (`ENTRY_BAR_STOP_BREACH`). |
| **Entry Fill + Target Hit** | Pending order fills at trigger; same bar registers `high >= target`. | **FILL THEN TARGET** | Position opened; partial 50% exit executed at target price; stop ratcheted to Breakeven (`Entry + $0.01`). |
| **Entry Fill + Target + Stop** | Pending order fills; same bar reaches both Target and Stop levels. | **FILL THEN STOP** | Position opened; Rule D2 applies: Stop executes immediately; target ignored. |
| **Collar Gap vs. Fill** | Buy stop limit pending; bar opens above limit price (`open > limit`). | **CANCEL (NO CHASE)** | Order cancelled as `COLLAR_MISS`. No position created. |
| **10:15:00 vs. High >= Trigger** | Pending order active at 10:15:00; bar high exceeds trigger price. | **PURGE FIRST** | Order cancelled as `STALE_ORDER_PURGE`. Fill does not occur. |
| **15:55:00 T1 / T2 Close <= Entry** | Uncushioned position on Day 1 or Day 2; bar close at 15:55 is $\le \text{Entry}$. | **LIQUIDATE AT CLOSE** | Liquidated at `bar.close`. Position removed; trade logged with `eod_exit_flag=True`. |
| **15:55:00 Cushioned Runner vs. T2 Scratch** | Position on Day 2 achieved +2R (`is_cushioned=True`); close $\le \text{Entry}$. | **IMMUNE TO SCRATCH** | Cushioned runners are protected from T1/T2 scratch; managed by 10 EMA rule. |
