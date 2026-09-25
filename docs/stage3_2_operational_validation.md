# Stage 3.2 — Operational Validation Report

## 1. Multi-Session Lifecycle Specification

The `MultiSessionRunner` enforces chronological deterministic execution across consecutive US market sessions.

```
       08:00 - 09:29 ET              09:30 ET               09:30 - 15:54 ET              15:55 ET            16:00 ET
  ┌───────────────────────┐    ┌─────────────────┐    ┌─────────────────────────┐    ┌────────────────┐    ┌─────────────┐
  │ Pre-Market Prep       │    │ Opening Bell    │    │ Live Feed Ingestion     │    │ EOD Audit      │    │ Close & EOD │
  │ - Restore Cash & Pos  │───>│ - Days Held +1  │───>│ - Bar Validation        │───>│ - T1 Exit Check│───>│ - Reconcile │
  │ - Screen & Waterfall  │    │ - Check Regime  │    │ - Order Staging (09:35) │    │ - T2 Stall Exit│    │ - Checkpoint│
  │ - Audit Candidates    │    │ - State: OPENING│    │ - Fill/Stop/Target Exec │    │ - Cancel Orders│    │ - Daily Rep │
  └───────────────────────┘    └─────────────────┘    └─────────────────────────┘    └────────────────┘    └─────────────┘
```

---

## 2. Multi-Session Invariants & Boundary Enforcements

### A. Calendar & Holiday Handling
- Integrated with `USMarketCalendar`.
- All session dates checked via `calendar.is_trading_day()`.
- Automatically skips weekends (Saturday/Sunday) and all 10 NYSE observed holidays.
- Validated with Juneteenth 2023: June 16 (Friday) skips June 17, 18, and 19 (holiday), resuming on June 20 (Tuesday).

### B. Early Closes
- Detects Black Friday, Christmas Eve, and July 3 early closes via `calendar.is_early_close()`.
- Session boundaries automatically truncated to 09:30 – 13:00 ET.
- EOD audit executes at 12:55 ET on early close days.

### C. Overnight Position Carrying
- In `PAPER` mode:
  - Positions not closed at 16:00 ET persist into the next trading session.
  - On the following trading morning at 09:30 ET, `open_session()` increments `pos.days_held += 1`.
  - At 15:55 ET of Day 2 (`days_held == 1`), `_evaluate_eod_audit()` checks the T2 stall liquidation rule (if close <= entry, liquidates position).
- In `OBSERVE` mode:
  - Open positions and broker fills are strictly wiped on every step to maintain **zero paper exposure**.

---

## 3. Persistent Ledger Schema

Persisted at `data/paper_live/multi_session_ledger.json`:

```json
{
  "version": "stage3_2",
  "data_source": "IEX",
  "last_updated": "2026-09-25T14:49:00-04:00",
  "session_count": 2,
  "sessions": [
    {
      "session_date": "2023-06-15",
      "mode": "PAPER",
      "feed_health": "HEALTHY",
      "disconnects": 0,
      "reconnects": 0,
      "candidates_generated": 5,
      "candidates_rejected": 3,
      "governor_vetoes": 2,
      "orders_staged": 2,
      "orders_cancelled": 0,
      "collar_misses": 0,
      "fills": 1,
      "stops": 0,
      "targets": 1,
      "eod_exits": 0,
      "realized_pnl": 450.0,
      "unrealized_pnl": 0.0,
      "ending_equity": 100450.0,
      "ending_cash": 100450.0,
      "open_positions_count": 0,
      "open_positions": [],
      "r_multiples": [2.0],
      "data_quality_events": 0,
      "is_early_close": false,
      "data_source": "IEX"
    }
  ]
}
```

---

## 4. Crash Recovery Invariants

Verified across 4 distinct crash points:
1. **Pre-Market Crash**: Focus list checkpointed to disk (`focus_list.parquet`). Process restart reconstructs candidate metadata and resumes at `OPENING`.
2. **Order Staging Crash**: Staged stop-limit orders checkpointed to disk (`orders.parquet`). Process restart restores order book at `ACTIVE_SESSION`.
3. **Active Position Crash**: Open position and trailing stops checkpointed (`fills.parquet`). Process restart recovers portfolio position and resumes stop/target monitoring.
4. **Disconnect Crash**: Fail-closed mechanism cancels untriggered entry orders while preserving protective stops. Process restart restores position and reconnects feed with backfill.
