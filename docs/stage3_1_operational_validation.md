# Stage 3.1 — Controlled Live US Paper-Trading Validation

## 1. Objective and Boundary
Stage 3.1 establishes controlled execution of the Stage 3 Alpaca/IEX streaming infrastructure against live US market data with **strict local paper execution**.

- **Scope**: Operational and data feed infrastructure validation only.
- **Explicit Limitations**:
  - Feed is IEX single-exchange (~2.5% of US volume). It is **not** consolidated SIP market data.
  - Performance and fills are for operational telemetry, not strategy profitability conclusions.
  - Zero external broker order routing (`PaperExecutionBroker` enforced via runtime safety assertions).
  - Documents 01–06 and frozen strategy rules remain untouched.
  - India implementation has not started.

---

## 2. Operational Modes

| Mode | Ingestion & Calculations | Staging / Hypothetical Orders | Local Paper Positions / Fills | Real Orders Routed |
| :--- | :--- | :--- | :--- | :--- |
| **`OBSERVE`** | Active (live IEX streaming) | Calculated & logged in decision journal (`hypothetical=True`) | **0 (Strictly prohibited & cleared)** | **0** |
| **`PAPER`** | Active (live IEX streaming) | Staged via `PaperExecutionBroker` | Executed internally with stop/target tracking | **0** |
| **`HALTED`** | Suspended (fail-closed) | Blocked (untriggered entries cancelled) | Protective stops preserved; checkpoints saved | **0** |

---

## 3. Live Data Health State Machine

```
              Monotonic bars < 60s
     ┌────────────────────────────────────┐
     │                                    │
     ▼                                    │
┌─────────┐   No bars 60s-90s   ┌──────────┐   No bars > 90s   ┌────────┐
│ HEALTHY │ ──────────────────> │ DEGRADED │ ────────────────> │ HALTED │
└─────────┘                     └──────────┘  or recon failure └────────┘
     ▲                               │
     │      Fresh bar received       │
     └───────────────────────────────┘
```

1. **`HEALTHY`**: Active data stream with valid monotonic bar delivery within 60 seconds.
2. **`DEGRADED`**: Data delivery gap between 60s and 90s, or active reconnection in progress. Emits warning telemetry.
3. **`HALTED`**: Data delivery gap exceeding 90s, reconnection failure, or critical schema invariant violation. Cancels pending entries fail-closed, saves state checkpoint, and preserves protective stop state.

---

## 4. Decision Audit Trail & Provider Metadata

Every strategy decision is logged in `OperationalDecisionJournal` with explicit provider metadata:
- **Event Types**:
  - `candidate_generated`
  - `candidate_rejected`
  - `governor_veto`
  - `liquidity_rejection`
  - `risk_geometry_rejection`
  - `order_staged`
  - `order_filled`
  - `collar_miss`
  - `order_cancelled`
  - `stop_triggered`
  - `target_triggered`
  - `eod_exit`
  - `feed_degradation`
  - `feed_recovery`
- **Metadata**:
  - `data_source`: `"IEX"`
  - `provider_timestamp`: ISO 8601 UTC
  - `normalized_timestamp`: ISO 8601 America/New_York
  - `reception_timestamp`: ISO 8601 America/New_York
  - `feed_latency_ms`: Float latency in milliseconds
  - `connection_state`: `"CONNECTED"` | `"DISCONNECTED"`

---

## 5. Daily Operational Report

Generated at market close in both JSON and Markdown formats:
- Session date, operational mode, feed health status
- Candidate generation and rejection breakdown
- Orders staged, filled, and collar misses
- Open paper positions and realized/unrealized paper P&L with R-multiples
- Governor vetoes, liquidity rejections, and data quality rejections
- Disconnect and reconnection events
- Final EOD session state

---

## 6. Safety Assertions

Runtime assertion in `LivePaperRunner._assert_broker_is_local_paper()`:
```python
if not isinstance(self._engine.broker, PaperExecutionBroker):
    raise SafetyError("EXTERNAL_ROUTING_PROHIBITED: Live real-money order routing is strictly forbidden.")
```
Any attempt to pass an external broker immediately halts and aborts with `SafetyError`.
