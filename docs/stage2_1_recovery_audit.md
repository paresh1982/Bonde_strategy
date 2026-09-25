# Stage 2.1 — Session Interruption, Recovery & Parity Audit

## 1. Recovery Architecture Overview

In a live trading environment, process failure (e.g. process crash, container restart, network disconnect) must never lead to lost order state, duplicate entries, or orphaned broker fills.

The Stage 2.1 architecture implements continuous checkpointing and deterministic state reconstruction via [`LiveSessionEngine.recover_session`](file:///C:/work/projects/bonde-strategy/src/bonde/live/session.py) and [`DailyFocusList.load_parquet`](file:///C:/work/projects/bonde-strategy/src/bonde/live/prep.py).

---

## 2. Checkpoint & Artifact Hierarchy

State is persisted under `data/paper/YYYY-MM-DD/` at discrete lifecycle milestones:

| Artifact | Format | Checkpointed When | Reconstructed State |
| :--- | :--- | :--- | :--- |
| `focus_list.parquet` | Parquet | End of `run_premarket()` (09:15 ET) | Approved & rejected candidate signals, allocated shares, regime state, daily budget. |
| `orders.parquet` | Parquet | End of `_stage_orders_at_0935()` | Staged, pending, filled, and cancelled orders with order IDs, trigger/collar limits, and tags. |
| `fills.parquet` | Parquet | Post-fill in `broker.record_fill()` | Executed fill prints, fill prices, quantities, slippage, and timestamps. |
| `rejections.parquet` | Parquet | Cutoff & cancellations | Logged rejections (collar misses, 10:15 purges, governor vetos). |
| `telemetry.parquet` | Parquet | Session close / EOD | Full 27 canonical + 14 live telemetry fields for all completed trades. |
| `session_summary.json` | JSON | End of `close_session()` | High-level summary of trades, PnL, ending equity, and reconciliation status. |

---

## 3. Mid-Session Interruption Matrix

| Interruption Point | State at Interruption | In-Flight Risk | Recovery Procedure | Post-Recovery Parity Verification |
| :--- | :--- | :--- | :--- | :--- |
| **1. Pre-Market Crash** (08:00 - 09:29 ET) | Focus list generated; market not open. | None. | Load `focus_list.parquet`. Restore regime and candidate allocations. State resumes at `OPENING`. | Zero re-screening; identical candidates; no duplicate calculation. |
| **2. Opening Range Crash** (09:30 - 09:34 ET) | Market open; ORB bars accumulating. | Unstaged signals. | Load focus list. ORB bars re-ingested from historical market replay or streaming buffer. | ORH/ORL calculated deterministically upon reaching 09:35:00 ET. |
| **3. Order Staging Crash** (09:35:00 ET) | Orders staged to broker; zero fills. | Duplicate staging on restart. | Load `orders.parquet`. Populate `broker._orders` and `_staged_orders`. Staging deduplication prevents duplicate submissions. | Open order count equals focus list approved candidate count. |
| **4. Post-Entry Fill Crash** (09:36 - 10:14 ET) | Position opened; pending orders active. | Orphan position or missing portfolio state. | Load `orders.parquet` and `fills.parquet`. Reconstruct `Position` in `portfolio.open_positions` with initial stop and risk. | `portfolio.get_position(sym)` restored; reconciler confirms 0 discrepancies. |
| **5. Post-Partial Exit Crash** (10:15 - 15:54 ET) | 50% sold at +2R; stop ratcheted to Breakeven ($Entry + \$0.01$). | Loss of cushioned status or stop ratchet. | Load partial fill records. Position reconstructed with `has_partial_filled=True`, `is_cushioned=True`, remaining shares, and Breakeven stop. | Realized PnL intact; remaining shares protected from T1/T2 liquidation. |
| **6. Pre-EOD Audit Crash** (15:50 ET) | Positions active into close. | Missed T1/T2 scratch liquidation. | Recover positions; bar stream evaluated at 15:55 (or 12:55). T1/T2 scratch logic evaluates normally. | Uncushioned failing trades liquidated at close; cushioned runners carried. |
| **7. Post-EOD Audit Crash** (16:00 ET) | Session complete; trades closed. | Incomplete reporting. | Run `close_session()`. Reconciler performs 3-way audit and exports all parquet/json artifacts. | Session summary matches exact final equity and trade journal. |

---

## 4. Verification Test Case

The entire recovery lifecycle was validated in [`tests/test_stage2_1_reconciliation_recovery.py::test_session_recovery_after_order_staging_and_fill`](file:///C:/work/projects/bonde-strategy/tests/test_stage2_1_reconciliation_recovery.py):
1. Pre-market was generated and checkpointed.
2. Orders were staged and filled by the paper broker.
3. The engine instance was discarded to simulate an abrupt crash.
4. `LiveSessionEngine.recover_session()` was invoked on the checkpoint directory.
5. All focus candidates, staged orders, fills, and active portfolio positions were reconstructed with 100% numerical and state parity.
