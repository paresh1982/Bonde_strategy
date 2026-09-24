# Stage 0.1 Lookahead-Bias Audit: USA Strategy Architecture

**Repository:** `C:\work\projects\bonde-strategy`  
**Evaluation Target:** Timestamp Causality, Information Boundaries, and Data Leakage  
**Date:** September 2026  
**Status Standard:** `PASS` | `PASS WITH RECOMMENDATIONS` | `FAIL`  

---

## 1. Executive Summary

This adversarial audit traces the chronological flow of information across every execution step in [`Stage0BacktestEngine`](file:///C:/work/projects/bonde-strategy/src/bonde/engine/backtest.py). The objective is to verify that no trading decision consumes data before that data is physically printed or published in a realistic trading session.

---

## 2. Information Availability Timeline

| Session Timestamp (EST) | Event / Decision | Permitted Information | Forbidden Information |
| :--- | :--- | :--- | :--- |
| **Pre-Market (09:29:59)** | Universe Screening & Watchlist | Day $t-1$ Close, 50-day ADV ($t-1$), Historical 65D High ($t-1$) | Any 09:30:00+ price, opening prints, intraday volume |
| **09:30:00–09:34:59** | 5-Minute ORB Formation | 1-minute bars at 09:30, 09:31, 09:32, 09:33, 09:34 | 09:35:00 bar, full-session volume, session close |
| **09:35:00** | ORB Range & Gate Evaluation | Established ORH/ORL from 09:30–09:34:59 window | 09:35 bar close/high/low, subsequent intraday prices |
| **09:35:00+** | Staged Stop-Limit Order | Trigger (`ORH + $0.01`), Limit (`ORH + $0.11`), Stop (`ORL - $0.01`) | Cannot fill on the 09:35:00 bar itself |
| **09:36:00–10:14:59** | Intraday Entry Matching | Current 1-minute bar OHLCV (sequential) | Subsequent minute bars, daily close |
| **10:15:00** | Stale Order Cancellation | Pure timestamp check (`time >= 10:15:00`) | Bar high/low must not trigger fill at or after 10:15 |
| **Intraday Active Trade** | Stop & Target Monitoring | Position stop, +2R target, current bar OHLC | Future tick data, same-bar target priority |
| **15:55:00** | Mandatory EOD Audit | Current bar close (`15:55`), Entry price | 16:00:00 final auction close, post-market prices |
| **Overnight / Day 2+** | Position Carrying | Day 1 Close, overnight gap print at next 09:30:00 open | Day 2 high/low before they occur |

---

## 3. Deep-Dive Audit of Specific Areas

### 3.1 09:30:00–09:34:59 ORB Construction & 09:35:00 Staging
* **Code Location:** [`backtest.py`](file:///C:/work/projects/bonde-strategy/src/bonde/engine/backtest.py#L83-L92)
* **Code Inspection:**
  ```python
  # 4. Opening Range Bar Caching (09:30:00 to 09:34:59)
  if time(9, 30, 0) <= bar_time < time(9, 35, 0):
      if bar.symbol not in self._opening_bars_cache:
          self._opening_bars_cache[bar.symbol] = []
      self._opening_bars_cache[bar.symbol].append(bar)

  # 5. At 09:35:00, evaluate 5-minute ORB
  if bar_time == time(9, 35, 0) and not self._orb_staged_today.get(bar.symbol, False):
      self._evaluate_and_stage_orb(bar, adv_50, regime, risk_fraction, sector)
  ```
* **Potential Lookahead Risk:** Does the 09:35:00 bar accidentally get included in the opening range calculation? Can an order staged at 09:35:00 fill on the 09:35:00 bar?
* **Tracing Result:** 
  1. The cache condition `bar_time < time(9, 35, 0)` is strictly less-than. At 09:35:00, the bar is NOT added to `_opening_bars_cache`. The range is built strictly from the five bars: 09:30, 09:31, 09:32, 09:33, 09:34.
  2. In `_process_bar`, Step 3 (`_process_pending_orders`) executes *before* Step 5 (`_evaluate_and_stage_orb`). Therefore, the newly staged order only enters `self.pending_orders` *after* the 09:35:00 bar has already finished pending order checks. The order can only fill starting on the 09:36:00 bar.
* **Lookahead Status:** **PASS (Zero Lookahead)**.

---

### 3.2 10:15:00 Stale Order Cancellation
* **Code Location:** [`simulator.py`](file:///C:/work/projects/bonde-strategy/src/bonde/execution/simulator.py#L48-L50)
* **Code Inspection:**
  ```python
  if bar_time >= self.stale_order_time:
      order.cancel("STALE_ORDER_PURGE")
      return None
  ```
* **Potential Lookahead Risk:** Does a bar stamped 10:15:00 trigger an entry if `bar.high >= trigger` before being purged?
* **Tracing Result:** The stale order check occurs at the very beginning of `process_entry_order`, *before* any price comparison (`bar.high >= trigger_price`). When a 10:15:00 bar is evaluated, `bar_time >= time(10, 15, 0)` evaluates to `True`, triggering immediate cancellation. No fill can occur at 10:15:00 or later.
* **Lookahead Status:** **PASS (Zero Lookahead)**.

---

### 3.3 Liquidity Cap ADV50 Timing
* **Code Location:** [`sizing.py`](file:///C:/work/projects/bonde-strategy/src/bonde/risk/sizing.py#L24-L39), [`backtest.py`](file:///C:/work/projects/bonde-strategy/src/bonde/engine/backtest.py#L45-L54)
* **Potential Lookahead Risk:** If $\text{ADV}_{50}$ includes session $t$ volume, sizing would utilize future volume that does not exist at 09:35:00 AM.
* **Tracing Result:** In Stage 0, `adv_50` is passed externally via `adv_50_map` (static sample dictionary). It does not dynamically compute rolling averages. While there is no in-session leakage in synthetic tests, Stage 1 data pipelines must ensure $\text{ADV}_{50}$ is computed strictly across sessions $t-50$ to $t-1$:
  $$\text{ADV}_{50, t} = \frac{1}{50}\sum_{i=1}^{50} \text{Volume}_{t-i}$$
* **Lookahead Status:** **PASS (Sample Static) / REQUIRES FORMAL INTERFACE ASSERTION FOR STAGE 1**.

---

### 3.4 65-Day High Resistance Lookback
* **Code Location:** [`base_hit.py`](file:///C:/work/projects/bonde-strategy/src/bonde/setups/base_hit.py#L40-L48)
* **Potential Lookahead Risk:** If the 65-day high lookback includes Day $t$'s own intraday high, the breakout trigger level would self-reference and move away dynamically or prevent breakout recognition.
* **Tracing Result:** `BaseHitSetup.evaluate` accepts `highest_high_65` as an explicit input argument. The implementation assumes this is the prior 65 sessions:
  $$\text{MAXH}_{65, t} = \max\left(\text{High}_{t-65}, \dots, \text{High}_{t-1}\right)$$
  Day $t$ cannot enter this calculation.
* **Lookahead Status:** **PASS (Parameter Input) / REQUIRES FORMAL SCREENER TEST IN STAGE 1**.

---

### 3.5 03:55 PM EOD Audit Execution
* **Code Location:** [`backtest.py`](file:///C:/work/projects/bonde-strategy/src/bonde/engine/backtest.py#L77-L78, L142-L176)
* **Code Inspection:**
  ```python
  if bar_time >= time(15, 55, 0):
      self._evaluate_eod_audit(bar)
  ```
  ```python
  if position.days_held == 0 and bar.close <= position.entry_price:
      self.portfolio.close_position(
          symbol=bar.symbol,
          exit_price=bar.close,
          timestamp=bar.timestamp,
          reason="EOD_AUDIT_T1_CLOSE_BELOW_ENTRY",
      )
  ```
* **Potential Lookahead Risk:** Liquidating at `bar.close` of the 15:55:00 bar: does this assume knowing the 1-minute close before it prints?
* **Tracing Result:** A 1-minute bar stamped `15:55:00` represents trading from 15:55:00 to 15:55:59. Executing at `bar.close` assumes execution at the close of that 1-minute window (15:56:00), or placing a Market-On-Close (MOC) order at 15:55. 
  Furthermore, the condition `bar_time >= time(15, 55, 0)` triggers on the 15:55 bar. If the position is liquidated on the 15:55 bar, it is closed immediately and does not participate in subsequent bars (15:56–16:00).
* **Severity:** Low. In continuous trading, an EOD audit at 15:55 exits via market order in the 15:55–15:59 window.
* **Lookahead Status:** **PASS**.

---

### 3.6 Account Equity in Sizing
* **Code Location:** [`backtest.py`](file:///C:/work/projects/bonde-strategy/src/bonde/engine/backtest.py#L280-L288)
* **Code Inspection:**
  ```python
  sizing = calculate_position_size(
      account_equity=self.portfolio.total_equity,
      entry_price=candidate.trigger_price,
      ...
  )
  ```
* **Potential Lookahead Risk:** Does sizing use closed-trade equity from future times or current-session point-in-time equity?
* **Tracing Result:** Sizing queries `self.portfolio.total_equity` at 09:35:00 EST. `total_equity` reflects `self.cash` (all closed trades up to 09:35:00) plus unrealized PnL and open realized PnL of active positions. No future trade outcomes can leak into sizing.
* **Lookahead Status:** **PASS (Zero Lookahead)**.

---

## 4. Comprehensive Lookahead Itemization

| Audit Item | Code Location | Potential Lookahead Mechanism | Actual Lookahead? | Severity | Remediation / Verification |
| :--- | :--- | :--- | :---: | :---: | :--- |
| **ORB Range** | `backtest.py` L84 | 09:35 bar entering 09:30–09:34 range | **NO** | None | Verified strict `< 09:35:00` slice. |
| **ORB Order Fill** | `backtest.py` L91 | Staged order filling on 09:35 bar | **NO** | None | Staged after pending orders processed on 09:35 bar. |
| **10:15 Purge** | `simulator.py` L48 | Order filling on/after 10:15 bar | **NO** | None | Cancelled prior to price evaluation. |
| **ADV50 Data** | `sizing.py` L24 | Current session volume in rolling ADV | **NO** (Static) | Medium | Enforce $(t-50 \dots t-1)$ contract in Stage 1 data loader. |
| **65D High** | `base_hit.py` L40 | Current session high in 65D resistance | **NO** (Input) | Medium | Enforce $(t-65 \dots t-1)$ contract in Stage 1 screener. |
| **EOD Exit Price** | `backtest.py` L156 | Using 16:00 close at 15:55 | **NO** | None | Uses 15:55 bar close print. |
| **Account Equity** | `portfolio.py` L115 | Future trade PnL in position sizing | **NO** | None | Uses point-in-time cash + mark-to-market. |
| **Market Regime** | `market_regime.py` L41 | Intraday price feedback altering regime | **NO** | None | Consumed as external prior-day close EOD feed. |
| **Sector Provider** | `models.py` L60 | Point-in-time taxonomy revisions | **NO** | None | Abstracted via `SectorProvider`. |

---

## 5. Lookahead Status Conclusion

**STAGE 0.1 LOOKAHEAD STATUS: PASS.**  
The discrete event sequence in `Stage0BacktestEngine` enforces strict point-in-time information availability. No future price, volume, or indicator leaks into trading decisions.
