# Stage 3.2 — Failure Mode & Adversarial Analysis Matrix

## 1. Adversarial & Data Failure Scenarios Matrix

| Failure / Anomaly | Engine State When Injected | Detection Mechanism | Fail-Closed Action Taken | Residual Risk |
| :--- | :--- | :--- | :--- | :--- |
| **Missing In-Session Bar** | `ACTIVE_SESSION` (10:15 ET) | `LiveDataValidator` gap check (> 5 min) | Emits warning telemetry, continues protective stops | Low — existing trailing stops remain active |
| **Feed Staleness (60s–90s)** | `ACTIVE_SESSION` (11:00 ET) | `LivePaperRunner.check_staleness()` | Transitions to `DEGRADED`, blocks new orders | None — entries gated |
| **Feed Outage (> 90s)** | `ACTIVE_SESSION` (11:02 ET) | `LivePaperRunner.check_staleness()` | Transitions to `HALTED`, cancels all pending entries, checkpoints | None — protective stops preserved |
| **Non-Positive Bar Price** | `ACTIVE_SESSION` (09:40 ET) | `LiveDataValidator.validate_bar()` | Rejects bar fail-closed, does not update engine | None — corrupt price rejected |
| **OHLC Inconsistency** | `ORB_COLLECTION` (09:32 ET) | `LiveDataValidator.validate_bar()` | Rejects bar, increments `bars_rejected` | None — bar discarded |
| **Pre-Market Bar Ingestion** | `PRE_MARKET` (08:30 ET) | `LiveSessionEngine.process_live_bar()` | Raises `SafetyError` fail-closed | None — session state guarded |
| **Post-Close Bar Ingestion** | `SESSION_CLOSED` (16:05 ET) | `LiveSessionEngine.process_live_bar()` | Raises `SafetyError` fail-closed | None — engine refuses post-close bars |
| **Early Close Day Ingestion** | `SESSION_CLOSED` (13:05 ET) | `USMarketCalendar.get_session_hours()` | Boundary violation rejects bar fail-closed | None — early close enforced |
| **External Live Broker Setup** | `INIT` | `_assert_broker_is_local_paper()` | Raises `SafetyError`, aborts process | Zero — live broker blocked |
| **Process Crash During Staging** | `ORDER_STAGING` (09:35 ET) | Parquet checkpoint recovery | `recover_session()` restores orders from disk | None — state fully reconstructed |
| **Process Crash with Open Position**| `POSITION_MANAGEMENT` (14:00 ET) | Fills parquet recovery | `recover_session()` rebuilds position and stops | None — stops reinstated |
| **WebSocket Hard Disconnect** | `ACTIVE_SESSION` (10:00 ET) | `AlpacaConnectionManager` thread monitor | Checkpoints, cancels pending entries, triggers backoff reconnect | None — entries purged |
| **Reconnect Exhaustion** | Reconnecting | `max_reconnect_attempts` reached | Transitions to `HALTED`, preserves open stops | None — manual intervention required |

---

## 2. Invariant Compliance
- **Zero Real Orders**: Enforced via `_assert_broker_is_local_paper()` runtime assertion.
- **Fail-Closed Principle**: Every data defect, boundary violation, or state mismatch results in cancellation of untriggered entries and preservation of open stops.
- **State Recovery**: Deterministic parquet checkpoints ensure complete post-crash auditability.
