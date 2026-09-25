# Stage 2.1 — US Real-Time Paper-Trading Adversarial Audit

## Executive Summary
This document records the comprehensive adversarial audit of the Stage 2 real-time US paper-trading infrastructure prior to integrating commercial market-data feeds or live broker routing. 

The audit rigorously tested 12 critical operational areas to prove deterministic, fail-closed behavior under hostile, degraded, and edge-case market environments without modifying any frozen strategy rule.

- **Authoritative Specifications (01–06) Modified:** **ZERO (0)**
- **Strategy Parameter Modifications:** **ZERO (0)**
- **India-Market Logic Added:** **ZERO (0)**
- **Live Broker Connections Added:** **ZERO (0)**
- **Total Test Suite:** **127 / 127 Passing** (97 baseline + 30 adversarial tests)

---

## 1. Scope & Adversarial Testing Areas

### 1.1 Area 1: Session State Machine & US Calendar Invariants
- **Validation**: Enforced strict forward-only finite state machine (`PRE_MARKET` $\rightarrow$ `OPENING` $\rightarrow$ `ORB_COLLECTION` $\rightarrow$ `ORDER_STAGING` $\rightarrow$ `ACTIVE_SESSION` $\rightarrow$ `STALE_ORDER_CUTOFF` $\rightarrow$ `POSITION_MANAGEMENT` $\rightarrow$ `EOD_AUDIT` $\rightarrow$ `SESSION_CLOSED`).
- **Fail-Closed Gateways**: Illegal state transitions (e.g. `PRE_MARKET` to `ACTIVE_SESSION`, or `SESSION_CLOSED` to `ACTIVE_SESSION`) raise [`SafetyError`](file:///C:/work/projects/bonde-strategy/src/bonde/live/safety.py). Processing bars prior to `open_session()` or after `close_session()` is strictly blocked.
- **US Calendar Boundaries**: Full support for all 10 US Federal holidays, Saturday/Sunday rollover, early-close sessions (Black Friday, Christmas Eve, July 3rd closing at 13:00 ET), and dynamic EOD audit execution at 12:55 ET.
- **DST Precision**: Verified Eastern Daylight Time (EDT, UTC-4) and Eastern Standard Time (EST, UTC-5) transitions. Pre-market ticks before 09:30:00 and post-close ticks past 16:00:00 (or 13:00:00 early close) are rejected with `SESSION_BOUNDARY_VIOLATION`.

### 1.2 Area 2: Streaming Data Failure & Corruption
- **Corrupt Geometry**: High < Open, High < Close, Low > Open, Low > Close rejected as `OHLC_HIGH_LESS_THAN_OPEN_OR_CLOSE` or `OHLC_LOW_GREATER_THAN_OPEN_OR_CLOSE` with `CRITICAL` severity.
- **Price & Volume Positivity**: Zero or negative Open/High/Low/Close rejected as `NON_POSITIVE_PRICE`. Negative volume rejected as `NEGATIVE_VOLUME`.
- **Staleness**: Ingestion of ticks older than 300 seconds relative to the reference clock rejected as `STALE_BAR_DATA`.
- **Monotonicity**: Duplicate timestamps and backwards timestamp regressions rejected with `DUPLICATE_BAR_TIMESTAMP` and `MONOTONIC_TIMESTAMP_VIOLATION`.
- **Top-of-Book Quotes**: Inverted spreads (Ask < Bid) rejected as `INVERTED_BID_ASK_SPREAD`. Non-positive bid/ask and negative quote sizes rejected as `NON_POSITIVE_QUOTE` and `NEGATIVE_QUOTE_SIZE`.
- **Security Master Assertion**: Unresolved ticker or empty security ID triggers immediate fail-closed abort via [`LiveSafetyGovernor.assert_security_resolved`](file:///C:/work/projects/bonde-strategy/src/bonde/live/safety.py).

### 1.3 Area 3: Order Lifecycle & Staging Mechanics
- **Staging**: At 09:35:00 ET, approved focus list candidates stage `BUY_STOP_LIMIT` orders with price collar $Limit = \text{Trigger} + \$0.10$.
- **Collar Miss / No-Chase**: An opening gap above the limit collar immediately cancels the pending order with `COLLAR_MISS`. Zero shares allocated; zero position created.
- **Partial Fills**: Under degraded liquidity conditions (`partial_fill_ratio < 1.0`), partial quantity is recorded without corrupting total position risk accounting.
- **10:15 Purge**: Un-triggered entry orders active at 10:15:00 ET are cancelled via `STALE_ORDER_PURGE_1015`. Rejection logged to trade journal.
- **Duplicate Prevention**: Idempotent order staging prevents duplicate submissions for active or pending symbols.

### 1.4 Area 4: Intrabar Adversarial Collisions & STOP-FIRST Precedence
- **Simultaneous Target & Stop Collision (Mandatory Rule D2)**: When a 1-minute bar satisfies both `High >= Target` and `Low <= Stop`, **STOP FIRST** invariant is strictly enforced. The trade executes at `min(Stop, Open) - Slippage`. The profit target is discarded, logging a loss rather than a profit.
- **Entry Fill + Stop Breach**: When entry fills at trigger and low breaches stop on the exact same bar, `ENTRY_BAR_STOP_BREACH` executes immediately at the stop price.
- **Entry Fill + Target Hit**: When entry fills at trigger and high breaches target on the same bar (with low staying above stop), `FILL THEN TARGET` executes 50% partial profit taking at target price, and ratchets remaining stop to Breakeven (`Entry + $0.01`).
- **Opening Gap Through Stop**: Stop-loss order gaps down below stop price, executing at `min(Stop, Open) - Slippage`.

### 1.5 Area 5: Portfolio & Risk Governors Boundary Testing
- **1R Sizing**: Sizing exactness on $100,000 equity at 0.5% risk fraction equals exactly $500.00 unit 1R.
- **Minimum Viable Allocation**: Candidate at 0.59R rejected as `BELOW_MIN_VIABLE_ALLOCATION`; candidate at 0.60R approved.
- **Sector Concentration Cap**: Uncushioned sector risk tested at exact boundary (1.4R existing + 0.60R new = 2.0R approved; 1.4R + 0.70R = 2.10R rejected as `SECTOR_HEAT_EXCEEDED`).
- **Portfolio Heat Cap**: Maximum portfolio heat of 6.0R uncushioned strictly enforced.
- **ADV Liquidity Participation**: Maximum 1.5% ADV participation cap enforced.
- **Regime Risk Budgets**:
  - `GREEN`: 3.0R budget; both Catalyst and Base-Hit approved.
  - `YELLOW`: 1.0R budget; only Catalyst approved; Base-Hit rejected with `YELLOW_REGIME_BASE_HIT_DISABLED`.
  - `RED`: 0.0R budget; all new entries rejected with `RED_REGIME_NEW_TRADES_DISABLED`.

### 1.6 Area 6: State Reconciliation
- [`OrderStateReconciler`](file:///C:/work/projects/bonde-strategy/src/bonde/live/reconciliation.py) executes comprehensive 3-way consistency audits:
  1. `DUPLICATE_PENDING_ORDER`: Detects multiple active buy orders for the same ticker.
  2. `STALE_PENDING_ORDER`: Detects pending entry orders past 10:15:00 ET.
  3. `ORPHANED_POSITION`: Detects open portfolio positions without broker buy orders.
  4. `MISSING_STRATEGY_POSITION`: Detects broker net filled positions missing from the strategy portfolio.
  5. `QUANTITY_MISMATCH`: Detects discrepancies between portfolio shares and broker net fills.
  6. `UNKNOWN_ORDER_ID`: Flags corrupt, empty, or unmapped order identifiers.
- Operates in fail-closed mode (`ReconciliationError` raised) or diagnostic reporting mode.

### 1.7 Area 7: Restart & Recovery
- **Mid-Session Checkpointing**: [`LiveSessionEngine`](file:///C:/work/projects/bonde-strategy/src/bonde/live/session.py) checkpoints state immediately after pre-market prep, order staging, and order fills.
- **Deterministic Resumption**: [`LiveSessionEngine.recover_session`](file:///C:/work/projects/bonde-strategy/src/bonde/live/session.py) reconstructs the full session state, focus list, staged orders, fills, and active portfolio positions directly from parquet files.

### 1.8 Area 8: Idempotency
- Multiple calls to `run_premarket()`, `_stage_orders_at_0935()`, or `close_session()` produce identical artifacts without duplicate orders, duplicate fills, or duplicate trades.

### 1.9 Area 9: Replay Determinism
- Three successive runs of the identical synthetic stream generated bit-for-bit identical results:
  - Identical events processed
  - Identical total trades
  - Identical realized PnL
  - Identical ending equity

### 1.10 Area 10: Telemetry Completeness
- Validated that all 27 canonical fields from Document 06 remain intact and all 14 Stage 2 live extension fields are populated correctly in [`LiveTelemetryRecord`](file:///C:/work/projects/bonde-strategy/src/bonde/live/telemetry.py).

### 1.11 Area 11: Safety Invariants
Formally proved all 8 fundamental safety invariants:
1. `UNKNOWN REGIME -> NO ORDER`
2. `INVALID MARKET DATA -> NO ORDER`
3. `STALE DATA -> NO ORDER`
4. `INVALID SESSION STATE -> NO ORDER`
5. `COLLAR MISS -> NO POSITION`
6. `10:15 UNTRIGGERED ORDER -> CANCEL`
7. `SAME-BAR STOP/TARGET -> STOP FIRST`
8. `ORPHAN POSITION -> CRITICAL RECONCILIATION FAILURE`

### 1.12 Area 12: Code Quality
- Verified zero circular dependencies.
- Verified absence of mutable global singleton state.
- Verified deterministic timezone-aware timestamps (`America/New_York`).
- Comprehensive logging and strict exception handling.
