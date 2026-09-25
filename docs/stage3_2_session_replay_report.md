# Stage 3.2 — Session Replay & Multi-Day Validation Report

## 1. Replay Test Suite Overview
Deterministic replay was executed across multi-session test scenarios to verify state persistence, candidate auditing, overnight carry, and restart resilience.

---

## 2. Replay Scenarios & Outcomes

### Scenario 1: Multi-Session Calendar and Holiday Skipping
- **Dates**: 2023-06-16 (Friday) to 2023-06-20 (Tuesday).
- **Events**: Juneteenth holiday on Monday 2023-06-19.
- **Outcome**: `MultiSessionRunner` processed exactly 2 sessions (Friday and Tuesday), skipping weekend and Monday.
- **Verification**: `test_calendar_holiday_skipping_and_early_close` PASS.

### Scenario 2: Multi-Session Overnight Position Carrying & T2 EOD Stall
- **Day 1 (2023-06-15)**: Open position in `AAPL` (100 shares @ $150.00, stop $145.00). Position held overnight (`days_held = 0`).
- **Day 2 (2023-06-16)**:
  - Pre-market prep accounts for open position risk.
  - Opening bell (09:30 ET) increments `days_held` to 1.
  - Position remains open and stop intact.
  - Verified that `days_held` and portfolio equity are preserved across session boundaries.
- **Verification**: `test_multi_session_paper_mode_carries_positions_overnight` PASS.

### Scenario 3: Multi-Session OBSERVE Mode
- **Execution**: 390 1-minute bars with valid ORB breakout setup fed to runner in `OBSERVE` mode.
- **Outcome**: Candidate detected, sized, and hypothetical order logged in `CandidateDecisionAudit` and `OperationalDecisionJournal`.
- **Strict Verification**:
  - Open paper positions: strictly 0.
  - Broker simulated fills: strictly 0.
  - Carried positions to Day 2: strictly 0.
- **Verification**: `test_multi_session_observe_mode_preserves_zero_paper_positions` PASS.

### Scenario 4: Mid-Session Crash & Recovery Across 3 Stages
- **Crash A (Pre-Market)**: Checkpointed at 09:25 -> Recovered session state restored to `OPENING` with intact focus list.
- **Crash B (Order Staging)**: Checkpointed at 09:35 -> Recovered session restored to `ACTIVE_SESSION` with intact staged orders.
- **Crash C (Active Position)**: Checkpointed with open position -> Recovered session restored with intact position and stop loss.
- **Verification**: `test_crash_recovery_at_premarket_staging_and_active_positions` PASS.

---

## 3. Aggregate Performance Output (Synthetic 2-Day Validation)
- **Sessions Completed**: 2
- **Feed Uptime**: 100.0%
- **Orders Staged**: 4
- **Orders Filled**: 2
- **Paper P&L**: $250.00 (1 target exit @ +2.0R, 1 stop exit @ -1.0R)
- **Win Rate**: 50.0%
- **R Distribution**: Mean = +0.50R, Median = +0.50R, Min = -1.00R, Max = +2.00R
- **Disclaimers**: Purely operational validation; no statistical edge inferred.
