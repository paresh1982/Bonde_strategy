# Stage 3 Architecture: US Live Market-Data Integration

## 1. Objective & Boundaries

Stage 3 integrates a live US market-data provider into the existing Bonde paper-trading engine.

### Strict Non-Negotiable Boundaries:
1. **Infrastructure Validation Only**: The current feed is approved strictly for pipeline, timing, normalization, and paper-execution testing. It is **NOT** approved as the definitive consolidated US market-data source for final strategy P&L validation.
2. **Frozen Strategy Integrity**: Documents 01–06 and strategy rules (sizing, governors, ORB, participation limits, catalysts, regime gates) remain 100% untouched.
3. **No Real Orders / No Live Broker**: All execution is handled locally by `PaperExecutionBroker` within the Stage 2/2.1 engine. No real-money order routing exists.
4. **No India Functionality**: The system remains strictly US equity focused.
5. **Provider Isolation**: All provider-specific logic resides solely within `src/bonde/live/adapters/alpaca/`.

---

## 2. Selected Provider: Alpaca Markets (IEX Feed)

- **Feed**: IEX Real-Time Feed ($0/month).
- **SDK**: `alpaca-py` (async WebSocket + REST client).
- **Connection**: Single WebSocket connection streaming 1-minute OHLCV bars and top-of-book quotes.
- **Capacity**: Up to 30 concurrent symbols (our active focus list is 10–20 symbols).
- **REST Backfill**: Zero-delay historical bar API (`feed='iex'`) used to backfill gaps following network disconnects.

### IEX Caveats & Operational Scope:
- **Coverage**: IEX represents ~2.5% of total US equity volume.
- **Liquidity Differences**: Heavily traded stocks (AAPL, TSLA, NVDA) have sufficient tick density, while smaller-cap names may experience 1-minute bar gaps (no IEX trades in that minute).
- **ORB High/Low Geometry**: The 5-minute Opening Range Breakout (09:30–09:34 ET) calculated from IEX bars may differ by 1–5 cents from consolidated NBBO/SIP bars.
- **Telemetry Tagging**: All logs, session summaries, and telemetry records are explicitly tagged with `data_source="IEX"` and a warning note so future quantitative analysis distinguishes infrastructure testing from consolidated SIP backtests.

---

## 3. Data Ingestion & Execution Pipeline

```
  ┌─────────────────────────┐
  │   Alpaca WebSocket /    │
  │     REST Backfill       │
  └────────────┬────────────┘
               │ (Raw JSON / alpaca-py objects, UTC timestamps)
               ▼
  ┌─────────────────────────┐
  │ AlpacaMarketDataAdapter │
  │    & Normalizer         │ ───► UTC converted to America/New_York (NY_TZ)
  └────────────┬────────────┘      Enforces non-negative volume, positive prices
               │ (Normalized LiveBar & Quote)
               ▼
  ┌─────────────────────────┐
  │   LiveDataValidator     │ ───► Fail-Closed Gates:
  │  (Existing Stage 2.1)   │      - Monotonic timestamps
  └────────────┬────────────┘      - Session boundary (RTH 09:30-16:00 ET)
               │                   - Positive prices, valid OHLC geometry
               ▼                   - Non-inverted bid/ask spreads
  ┌─────────────────────────┐
  │    LivePaperRunner      │ ───► Staleness monitoring (60s warn, 90s halt)
  │    & SessionEngine      │ ───► Checkpoint intervals & disconnect recovery
  └────────────┬────────────┘
               │
               ▼
  ┌─────────────────────────┐
  │  PaperExecutionBroker   │ ───► Local paper fills, slippage, commissions
  │     & Portfolio         │      Pending entry cancellation on disconnect
  └────────────┬────────────┘
               │
               ▼
  ┌─────────────────────────┐
  │ Telemetry / Audit Logs  │ ───► Tagged with data_source="IEX"
  └─────────────────────────┘
```

---

## 4. Disconnect, Reconnect & Fail-Closed Recovery

When a network drop or provider disconnection occurs:
1. **Disconnect Detection**: Runner detects inactive connection or stream error.
2. **Fail-Closed Order Management**: Untriggered pending entry orders (`BUY_STOP`, `BUY_STOP_LIMIT`) are immediately cancelled to prevent stale breakout fills. Existing stop-loss protection orders for filled positions are retained.
3. **State Checkpointing**: Current engine and portfolio state is persisted to disk.
4. **Exponential Backoff Reconnection**: Reconnect attempts are made with exponential backoff and jitter up to `max_reconnect_attempts` (default: 3). If all attempts fail, the session safely halts.
5. **REST Gap Backfill**: Upon successful reconnect, the adapter queries Alpaca REST API from the last received timestamp to the current time, normalizes the missing bars, validates them, and feeds them through the engine without duplicating bars.

---

## 5. Upgrade Path to SIP Consolidated Feed

The adapter boundary is decoupled from the feed type:
- Changing from IEX ($0/mo) to Consolidated SIP ($99/mo) requires changing only `feed = 'sip'` in `AlpacaConfig` (or setting environment variable `ALPACA_FEED=sip`).
- Zero changes to strategy logic, validation gates, runner, or execution broker are required.

---

## 6. Verification & Test Suite

The Stage 3 implementation is covered by unit, mock, and end-to-end integration tests:
- `tests/test_stage3_normalizer.py`: Bar/quote conversions, UTC to NY_TZ mapping, error rejection.
- `tests/test_stage3_alpaca_adapter.py`: Interface conformance, thread-safe buffering, backfill.
- `tests/test_stage3_connection.py`: Reconnect backoff, staleness detection, graceful shutdown.
- `tests/test_stage3_safety_gates.py`: Inverted spreads, non-positive prices, session boundary, duplicate timestamps.
- `tests/test_stage3_runner.py`: Session lifecycle, staleness warnings/halts, checkpointing.
- `tests/test_stage3_disconnect_recovery.py`: Fail-closed disconnect handling, order cancellation, backfill deduplication.
- `tests/test_stage3_e2e_paper_session.py`: Full synthetic live paper session through the complete stack.
