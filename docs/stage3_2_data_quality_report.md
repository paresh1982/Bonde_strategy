# Stage 3.2 — Data Quality & Telemetry Report

## 1. Feed Telemetry & Health Monitoring
The real-time data validator and multi-session telemetry monitor track 8 critical data quality dimensions:

| Dimension | Detection Threshold | Action Taken | Telemetry Logged |
| :--- | :--- | :--- | :--- |
| **Missing Bars** | Bar timestamp gap > 5m | Warning emitted, non-blocking | `gap_minutes`, `last_timestamp` |
| **Stale Bars** | No bars received for 60s–90s | Transition to `DEGRADED` | `FEED_DEGRADATION` decision |
| **Feed Stall / Halt** | No bars received for > 90s | Transition to `HALTED`, cancel entries | `FEED_HALTED` decision |
| **Monotonic Violations** | Timestamp <= prior timestamp | Rejected fail-closed | `MONOTONIC_TIMESTAMP_VIOLATION` |
| **Price / Volume Errors** | Non-positive prices or negative volume | Rejected fail-closed | `NON_POSITIVE_PRICE`, `NEGATIVE_VOLUME` |
| **OHLC Inconsistency** | High < max(O, C) or Low > min(O, C) | Rejected fail-closed | `OHLC_HIGH_LESS_THAN_OPEN_OR_CLOSE` |
| **Session Boundary** | Bar time outside 09:30 – 16:00 / 13:00 | Rejected fail-closed | `SESSION_BOUNDARY_VIOLATION` |
| **Inverted Quotes** | Bid > Ask | Rejected fail-closed | `INVERTED_BID_ASK_SPREAD` |

---

## 2. Latency Profiling
- **Metric Captured**: Real-world reception time minus normalized bar timestamp.
- **Expected Free Tier Latency**: 10ms – 250ms under typical broadband conditions.
- **Fail-Closed Threshold**: Latency exceeding 300 seconds triggers staleness rejection via `LiveDataValidator`.
- **Latency Distribution Tracked**: `latency_ms_avg` and `latency_ms_max` exported to daily and aggregate reports.

---

## 3. IEX Single-Exchange Diagnostic Findings

### Coverage & Volume Limitations
- IEX represents roughly ~2.5% of total consolidated US equity volume.
- **Impact on ADV50**: ADV50 calculations in the strategy MUST remain rooted in consolidated historical daily bars (`data/stage1d/`). They CANNOT be computed from IEX live bars without severe liquidity distortion.
- **Zero-Volume Minutes**: On lower-liquidity tickers, IEX produces minutes with 0 trades. The system safely handles zero-volume bars provided OHLC structure remains consistent.
- **ORB High / Low Discrepancies**: Because IEX captures only trades executed on the IEX venue, the IEX 5-minute ORB high and low can diverge from consolidated SIP ORB levels. Stage 3.2 telemetry tags all decisions with `data_source="IEX"` to maintain strict separation from SIP backtest results.
