# Stage 2.1 — Failure Injection & Safety Matrix

This matrix documents the simulated failure modes, detection mechanisms, actions taken, severity classifications, and verifying test cases implemented during the Stage 2.1 adversarial audit.

| Category | Injected Failure Mode | Detection Mechanism | System Action | Severity | Verifying Test Case |
| :--- | :--- | :--- | :--- | :--- | :--- |
| **Data Ingestion** | High < Open or Close | `LiveDataValidator.validate_bar` | Reject bar tick; log `RejectedEvent`; no state update | `CRITICAL` | `test_corrupt_ohlc_geometry` |
| **Data Ingestion** | Low > Open or Close | `LiveDataValidator.validate_bar` | Reject bar tick; log `RejectedEvent`; no state update | `CRITICAL` | `test_corrupt_ohlc_geometry` |
| **Data Ingestion** | Price <= 0.0 (O, H, L, C) | `LiveDataValidator.validate_bar` | Reject bar tick; log `RejectedEvent`; no state update | `CRITICAL` | `test_non_positive_prices_and_negative_volume` |
| **Data Ingestion** | Negative volume | `LiveDataValidator.validate_bar` | Reject bar tick; log `RejectedEvent`; no state update | `ERROR` | `test_non_positive_prices_and_negative_volume` |
| **Data Ingestion** | Duplicate timestamp | `LiveDataValidator.validate_bar` | Reject duplicate bar tick; log `RejectedEvent` | `ERROR` | `test_duplicate_and_backward_timestamps` |
| **Data Ingestion** | Backwards timestamp regression | `LiveDataValidator.validate_bar` | Reject out-of-order bar; log `RejectedEvent` | `ERROR` | `test_duplicate_and_backward_timestamps` |
| **Data Ingestion** | Stale bar (> 300s age) | `LiveDataValidator.validate_bar` | Reject stale bar; log `RejectedEvent` | `ERROR` | `test_stale_bar_rejection` |
| **Data Ingestion** | Tick outside RTH window | `LiveDataValidator.validate_bar` | Reject bar; log `SESSION_BOUNDARY_VIOLATION` | `ERROR` | `test_events_outside_session_window_rejected` |
| **Quotes** | Inverted spread (Ask < Bid) | `LiveDataValidator.validate_quote` | Reject quote tick; log `RejectedEvent` | `CRITICAL` | `test_quote_adversarial_validation` |
| **Quotes** | Non-positive Bid or Ask | `LiveDataValidator.validate_quote` | Reject quote tick; log `RejectedEvent` | `CRITICAL` | `test_quote_adversarial_validation` |
| **Quotes** | Negative quote size | `LiveDataValidator.validate_quote` | Reject quote tick; log `RejectedEvent` | `ERROR` | `test_quote_adversarial_validation` |
| **Session FSM** | Bar arriving in `PRE_MARKET` | `LiveSessionEngine.process_live_bar` | Raise `SafetyError`; block execution | `CRITICAL` | `test_process_bar_guards_premarket_and_closed` |
| **Session FSM** | Bar arriving in `SESSION_CLOSED` | `LiveSessionEngine.process_live_bar` | Raise `SafetyError`; block execution | `CRITICAL` | `test_process_bar_guards_premarket_and_closed` |
| **Session FSM** | Illegal state skip | `LiveSessionEngine.transition_to` | Raise `SafetyError`; reject transition | `CRITICAL` | `test_invalid_state_transitions_fail_closed` |
| **Order Lifecycle** | Opening gap > collar limit | `PaperFillModel.evaluate_order` | Cancel order with `COLLAR_MISS`; no position | `WARN` | `test_collar_miss_no_chase_no_position` |
| **Order Lifecycle** | Stale order past 10:15:00 ET | `LiveSessionEngine._purge_stale_orders` | Cancel order with `STALE_ORDER_PURGE_1015` | `INFO` | `test_1015_stale_order_purge_and_reconciliation` |
| **Order Lifecycle** | Duplicate staging attempt | `LiveSessionEngine._stage_orders_at_0935` | Skip staging; prevent duplicate order submission | `INFO` | `test_idempotent_session_operations` |
| **Intrabar** | Simultaneous Target & Stop breach | `LiveSessionEngine._evaluate_order_fills_and_exits` | **STOP FIRST**: Exit at stop; ignore target order | `CRITICAL` | `test_intrabar_target_and_stop_collision_stop_first` |
| **Intrabar** | Entry fill + Stop breach same bar | `LiveSessionEngine._evaluate_order_fills_and_exits` | **STOP IMMEDIATE**: Fill then close at stop | `WARN` | `test_entry_fill_and_stop_breach_same_bar` |
| **Intrabar** | Entry fill + Target hit same bar | `LiveSessionEngine._evaluate_order_fills_and_exits` | **FILL THEN TARGET**: 50% partial exit, stop to BE | `INFO` | `test_entry_fill_and_target_hit_same_bar` |
| **Risk Governor** | Sizing < 0.60R minimum viable | `PortfolioAllocationWaterfall` | Reject candidate (`BELOW_MIN_VIABLE_ALLOCATION`) | `WARN` | `test_min_allocation_boundary_059_vs_060` |
| **Risk Governor** | Sector heat > 2.0R uncushioned | `PortfolioAllocationWaterfall` | Reject candidate (`SECTOR_HEAT_EXCEEDED`) | `WARN` | `test_sector_cap_20r_boundary` |
| **Risk Governor** | RED market regime | `PortfolioAllocationWaterfall` | Reject all trades (`RED_REGIME_NEW_TRADES_DISABLED`) | `WARN` | `test_regime_budgets_green_yellow_red` |
| **Reconciliation** | Orphan broker position | `OrderStateReconciler.reconcile` | Detect `MISSING_STRATEGY_POSITION`; raise error | `CRITICAL` | `test_reconciliation_detects_all_discrepancy_types` |
| **Reconciliation** | Orphan strategy position | `OrderStateReconciler.reconcile` | Detect `ORPHANED_POSITION`; raise error | `CRITICAL` | `test_reconciliation_detects_all_discrepancy_types` |
| **Reconciliation** | Quantity mismatch | `OrderStateReconciler.reconcile` | Detect `QUANTITY_MISMATCH`; raise error | `CRITICAL` | `test_reconciliation_detects_all_discrepancy_types` |
| **Reconciliation** | Unknown order ID | `OrderStateReconciler.reconcile` | Detect `UNKNOWN_ORDER_ID`; raise error | `CRITICAL` | `test_reconciliation_detects_all_discrepancy_types` |
| **Recovery** | Process crash after staging/fill | `LiveSessionEngine.recover_session` | Restore focus list, orders, fills, and positions | `INFO` | `test_session_recovery_after_order_staging_and_fill` |
