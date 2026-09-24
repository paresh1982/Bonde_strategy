# Stage 1A Automated Data Quality & Anomaly Detection Specification

**Repository:** `C:\work\projects\bonde-strategy`  
**Market:** United States Equities (NYSE / NASDAQ / AMEX)  
**Document:** `docs/stage1a_data_quality_spec.md`  
**Scope:** Automated Ingestion Validation, Out-of-Bounds Detection, and Anomaly Quarantine Protocols  
**Status:** IMPLEMENTATION-READY SPECIFICATION  

---

## 1. Data Integrity Philosophy: The Fail-Closed Standard

In algorithmic trading backtests, subtle data errors (such as inverted OHLC bars, misaligned split adjustments, or missing timestamps) do not simply create small noise—they produce catastrophic phantom fills, unrealistic multi-hundred percent R-returns, or artificial stop-outs.

The data architecture for the trading system enforces a **strict fail-closed protocol**:
1. **Zero Silent Fallbacks:** No corrupted bar or misaligned corporate action may be silently patched or interpolated without explicit audit logging.
2. **Execution Quarantine:** If an intraday price bar for a candidate security fails logical integrity checks on session $t$, the security is immediately disqualified from order generation for session $t$, and the violation is recorded in `data_quality_log`.
3. **Purity Over Quantity:** A survivorship-bias-free dataset must preserve true market microstructure. Spurious exchange corrections, cancelled prints, and broken trades must be cleansed prior to feeding the event-driven simulator.

---

## 2. Automated Validation Gates

Every historical dataset (Daily Bars, Intraday 1-Minute Bars, Corporate Actions, Catalyst Events) must pass eight sequential automated validation gates prior to ingestion into the research warehouse.

```
                    ┌─────────────────────────┐
                    │ RAW VENDOR DATASTREAM   │
                    └────────────┬────────────┘
                                 │
                                 ▼
                     [Gate 1: OHLC Logic]
                                 │ Pass
                                 ▼
                     [Gate 2: Non-Zero & Positive]
                                 │ Pass
                                 ▼
                     [Gate 3: Timestamp & Uniqueness]
                                 │ Pass
                                 ▼
                     [Gate 4: Session Completeness]
                                 │ Pass
                                 ▼
                     [Gate 5: Spikes & Outliers]
                                 │ Pass
                                 ▼
                     [Gate 6: Split & Corp Action]
                                 │ Pass
                                 ▼
                     [Gate 7: Timezone & DST (UTC)]
                                 │ Pass
                                 ▼
                     [Gate 8: Security Identifier]
                                 │ Pass
                                 ▼
                    ┌─────────────────────────┐
                    │ CLEAN RESEARCH DATASET  │
                    └─────────────────────────┘
```

---

### Gate 1: OHLC Logical Ordering
* **Applies to:** Daily Bars, Intraday 1-Minute Bars.
* **Validation Invariant:**
  $$\text{Low} \le \text{Open} \le \text{High}$$
  $$\text{Low} \le \text{Close} \le \text{High}$$
  $$\text{High} \ge \text{Low} > 0$$
* **Violation Classification:**
  - If $\text{Low} > \text{High}$: `FATAL_DISCARD` (corrupted vendor record).
  - If $\text{Open} > \text{High}$ or $\text{Open} < \text{Low}$: `FATAL_DISCARD`.
  - If $\text{Close} > \text{High}$ or $\text{Close} < \text{Low}$: `FATAL_DISCARD`.
* **Action:** Discard the offending bar, record anomaly in `data_quality_log` with `anomaly_type = 'BAD_OHLC_ORDER'`. If on intraday bar, quarantine the security for that trading session.

---

### Gate 2: Positive Price & Volume Integrity
* **Applies to:** Daily Bars, Intraday 1-Minute Bars.
* **Validation Invariant:**
  $$\text{Open} > 0, \quad \text{High} > 0, \quad \text{Low} > 0, \quad \text{Close} > 0$$
  $$\text{Volume} \ge 0$$
* **Sub-Rules:**
  - **Negative or Zero Prices:** Absolute zero tolerance ($\text{Price} \le 0$ is rejected).
  - **Negative Volume:** Volume $< 0$ indicates bad vendor netting or corrupt tape. Rejected immediately.
  - **Zero Volume During Regular Trading Hours (09:30–16:00 ET):**
    - For high-liquidity stocks ($ADV_{50} > 500,000$), zero volume in a 1-minute bar triggers a `WARNING`.
    - For lower-liquidity small caps, zero volume indicates no trade occurred. Handled via Gate 4 (synthetic flat bar).

---

### Gate 3: Timestamp & Uniqueness Gate
* **Applies to:** All tables.
* **Validation Invariant:**
  - `(security_id, bar_timestamp_utc)` must be strictly unique.
  - `(security_id, trading_date)` must be strictly unique for daily records.
* **Collision Handling:**
  - If identical timestamps arrive with identical OHLCV: Deduplicate, keep single record, log `WARNING`.
  - If identical timestamps arrive with conflicting OHLCV: Reject both, log `ERROR` (`anomaly_type = 'TIMESTAMP_COLLISION'`), flag vendor source.

---

### Gate 4: Session Completeness & Missing Bar Protocols
* **Applies to:** 1-Minute Intraday Bars.
* **Expected Regular Session:** 09:30:00 to 15:59:00 US Eastern (390 discrete 1-minute bars).
* **Expected Early Close Session (e.g., Day after Thanksgiving, Christmas Eve):** 09:30:00 to 12:59:00 US Eastern (210 discrete 1-minute bars).
* **Gap Protocols:**
  - **Opening Bar (09:30:00):** If bar 09:30 is missing, the stock did not open on time or halted immediately. The Opening Range (09:30–09:35) cannot be calculated. Disqualify catalyst setup for that session (`anomaly_type = 'MISSING_OPENING_BAR'`).
  - **Mid-Session Gaps (No trades occurred):**
    - If a valid trade occurred prior to gap and after gap: Forward-fill `Close` to synthetic `Open`, `High`, `Low`, `Close` with $\text{Volume} = 0$.
    - **CRITICAL RESTRICTION:** Never forward-fill missing bars across session boundaries (from 16:00 to 09:30 next day).
  - **Trading Halts (LULD / Regulatory Code M):**
    - When exchange halts a stock, no prints occur. Synthetic bars during halts must be tagged with `is_halted = TRUE` so the simulator does not permit order execution during halts.

---

### Gate 5: Unrealistic Price Spikes & Outlier Detection
* **Applies to:** 1-Minute Intraday Bars.
* **Validation Invariants:**
  1. **Intraday Bar-to-Bar Jump:**
     $$\left|\frac{\text{Close}_t - \text{Close}_{t-1}}{\text{Close}_{t-1}}\right| > 0.50 \quad \text{within 1 minute}$$
     - Exception: 09:30 Opening bar compared to prior day close (Catalyst Gaps can exceed +50%).
     - During 09:31–16:00 ET: If a bar jumps $> 50\%$ in 1 minute and the subsequent bar immediately reverts back $> 40\%$, flag as `OUTLIER_BAD_TICK`.
  2. **Extreme Volume Spikes:**
     $$\text{Volume}_{1m} > 100 \times \text{Average Minute Volume}$$
     - Flag as `VOLUME_ANOMALY` for manual verification if not coinciding with 09:30 open or 16:00 closing cross.

---

### Gate 6: Corporate Action & Split Discontinuity Verification
* **Applies to:** Daily Bars, Intraday Bars, Corporate Actions.
* **Validation Invariants:**
  1. **Split Ratio Sanity:**
     $$\text{Split Ratio} \in \left[\frac{1}{100}, 100\right]$$
     - Any corporate action split ratio outside this range requires manual inspection.
  2. **Split Factor Coherence:**
     - On ex-date $T_{\text{ex}}$ of a 2-for-1 forward split, the split-adjusted close on $T_{\text{ex}}-1$ must equal:
       $$\text{Close}_{\text{adj}}(T-1) = \frac{\text{Close}_{\text{unadj}}(T-1)}{2.0}$$
     - If the vendor's pre-computed split-adjusted series deviates from the cumulative corporate action split factor by $> 0.1\%$, log `FATAL_DISCARD` (`anomaly_type = 'SPLIT_FACTOR_MISMATCH'`).
  3. **Unadjusted Daily to Intraday Parity:**
     - On date $t$, the daily unadjusted OHLC must exactly match the aggregate of intraday 1-minute unadjusted bars:
       $$\text{Daily High}_{\text{unadj}} = \max_{m \in [09:30, 16:00]} \left(\text{High}_{1m}\right)$$
       $$\text{Daily Low}_{\text{unadj}} = \min_{m \in [09:30, 16:00]} \left(\text{Low}_{1m}\right)$$
     - Tolerance: $\pm \$0.01$ (to allow for official exchange opening/closing crosses printed after the continuous session).

---

### Gate 7: Timezone & Daylight Saving Time (DST) Synchronization
* **Applies to:** All Intraday Bars, Catalyst Timestamps.
* **Storage Standard:** All timestamps stored strictly in **UTC** (`TIMESTAMP WITH TIME ZONE`).
* **Validation Invariants:**
  - **EDT (Eastern Daylight Time, UTC-4):**
    - Market Open 09:30:00 ET $\rightarrow$ **13:30:00 UTC**
    - Market Close 16:00:00 ET $\rightarrow$ **20:00:00 UTC**
  - **EST (Eastern Standard Time, UTC-5):**
    - Market Open 09:30:00 ET $\rightarrow$ **14:30:00 UTC**
    - Market Close 16:00:00 ET $\rightarrow$ **21:00:00 UTC**
* **Rejection Rule:** Any bar received with a local timestamp that does not map to exact exchange continuous hours (accounting for US DST transition dates) is rejected with `anomaly_type = 'DST_TIMEZONE_MISALIGNMENT'`.

---

### Gate 8: Security Master & Ticker Recycling Verification
* **Applies to:** Security Master, Security History.
* **Validation Invariants:**
  - A ticker symbol (e.g., `META`, `TSLA`, `AAPL`, `BOX`) may belong to different corporate entities over decades.
  - The lookup function `resolve_security_id(ticker, as_of_date)` must return exactly **one** canonical `security_id`.
  - **Collision Check:** No two distinct companies in `security_master` may hold active overlapping date ranges `[effective_from, effective_to]` for the same ticker string.
  - Violation: Triggers `FATAL_DISCARD` (`anomaly_type = 'TICKER_COLLISION'`).

---

## 3. Anomaly Severity & Automated Handling Matrix

| Anomaly Type | Severity | Simulator Impact | Log Action |
| :--- | :---: | :--- | :--- |
| `BAD_OHLC_ORDER` | `FATAL_DISCARD` | Bar rejected. Day discarded for candidate. | Record in `data_quality_log`. |
| `NEGATIVE_PRICE_OR_VOL` | `FATAL_DISCARD` | Data rejected. Ticker flagged for vendor audit. | Record in `data_quality_log`. |
| `TIMESTAMP_COLLISION` | `ERROR` | Deduplicate if identical; drop both if conflicting. | Record in `data_quality_log`. |
| `MISSING_OPENING_BAR` | `ERROR` | Cannot construct 5-min ORB. Disqualify setup for session. | Record in `data_quality_log`. |
| `INTRADAY_ZERO_VOL_GAP` | `WARNING` | Forward-fill price, set volume to 0. Continue simulation. | Record in `data_quality_log` (summary). |
| `OUTLIER_BAD_TICK` | `ERROR` | Discard bad tick; disqualify order triggers on bar. | Record in `data_quality_log`. |
| `SPLIT_FACTOR_MISMATCH` | `FATAL_DISCARD` | Invalidate ticker history until corporate action reconciled. | Record in `data_quality_log`. |
| `DAILY_INTRADAY_OHLC_MISMATCH` | `WARNING` / `ERROR` | Warning if $\le \$0.02$; Error if $> \$0.02$. | Record in `data_quality_log`. |
| `DST_TIMEZONE_MISALIGNMENT` | `FATAL_DISCARD` | Invalidate ingestion batch; fix timezone converter. | Record in `data_quality_log`. |
| `MISSING_CATALYST_TIME` | `WARNING` | Default to after-market-close ($16:30$ ET) on filing date. | Record in `data_quality_log`. |
| `TICKER_COLLISION` | `FATAL_DISCARD` | Halt backtest until security master map resolved. | Record in `data_quality_log`. |

---

## 4. Integration with `data_quality_log`

All validation gates write directly to the `data_quality_log` table defined in `docs/stage1a_us_data_schema.md`:

```sql
INSERT INTO data_quality_log (
    security_id,
    trading_date,
    data_domain,
    anomaly_type,
    severity,
    details
) VALUES (
    :sec_id,
    :t_date,
    'INTRADAY_1M',
    'BAD_OHLC_ORDER',
    'FATAL_DISCARD',
    'Bar 2024-03-15 14:12:00 UTC has Low (15.20) > High (15.10).'
);
```

### Pre-Backtest Gate Check
Before any backtest session executes:
1. The engine queries `data_quality_log` for any `FATAL_DISCARD` records for the selected backtest universe and date range.
2. If unresolved fatal errors exist, the engine refuses to start and outputs an audit report of affected tickers and dates.
3. At the conclusion of each backtest run, the engine outputs a **Data Quality Telemetry Report**:
   - Total bars evaluated
   - Clean bar ratio ($> 99.99\%$ required)
   - Disqualified trading sessions
   - Quarantined candidates
