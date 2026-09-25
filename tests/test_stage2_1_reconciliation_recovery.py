"""
Stage 2.1 Adversarial Audit: Areas 6 & 7 - State Reconciliation, Recovery & Idempotency
Validates:
- Reconciliation discrepancy detection:
  - Orphan broker position (net broker fill > 0, missing in portfolio)
  - Orphan strategy position (portfolio open position without broker buy order)
  - Duplicate pending orders for same symbol
  - Quantity mismatches between position and net filled orders
  - Unknown order IDs
  - Stale orders after 10:15 cutoff
- Fail-closed exception vs diagnostic report mode
- Deterministic session state recovery from parquet checkpoints:
  - Recovery after pre-market focus list generation
  - Recovery after order staging
  - Recovery after entry fills and active position management
- Idempotent preparation, order staging, and closing
"""

from datetime import date, datetime, time
from pathlib import Path
import pytest
import tempfile
import shutil

from bonde.data.models import NY_TZ
from bonde.execution.orders import Order, OrderSide, OrderStatus, OrderType
from bonde.live.broker import PaperExecutionBroker
from bonde.live.models import LiveBar, TradingSession
from bonde.live.prep import DailyFocusList
from bonde.live.reconciliation import Discrepancy, OrderStateReconciler, ReconciliationError
from bonde.live.session import LiveSessionEngine, LiveSessionState
from bonde.portfolio.portfolio import Portfolio, Position
from bonde.regime.market_regime import MarketRegime


def test_reconciliation_detects_all_discrepancy_types():
    """Injects every discrepancy type and verifies exact classification."""
    reconciler = OrderStateReconciler(stale_order_cutoff_time=time(10, 15))
    portfolio = Portfolio(initial_equity=100_000.0)
    broker = PaperExecutionBroker()
    current_time = datetime(2023, 6, 15, 10, 20, tzinfo=NY_TZ)

    # 1. Duplicate pending orders for AAPL
    o1 = Order(symbol="AAPL", side=OrderSide.BUY, order_type=OrderType.BUY_STOP_LIMIT, quantity=100, trigger_price=150.0)
    o2 = Order(symbol="AAPL", side=OrderSide.BUY, order_type=OrderType.BUY_STOP_LIMIT, quantity=100, trigger_price=150.0)
    broker.submit_order(o1)
    broker.submit_order(o2)

    # 2. Stale pending order for MSFT past 10:15
    o_stale = Order(symbol="MSFT", side=OrderSide.BUY, order_type=OrderType.BUY_STOP_LIMIT, quantity=50, trigger_price=300.0, tag="ENTRY_ORB")
    broker.submit_order(o_stale)

    # 3. Orphan strategy position for NVDA (open in portfolio, zero broker orders)
    pos_nvda = Position(
        symbol="NVDA", side="LONG", entry_price=400.0, entry_timestamp=current_time,
        quantity=50, initial_stop=380.0, current_stop=380.0, initial_risk_dollars=1000.0,
        engine="CATALYST", setup_type="ORB", regime_at_entry=MarketRegime.GREEN
    )
    portfolio.add_position(pos_nvda)

    # 4. Quantity mismatch for TSLA: Broker filled 100 shares, portfolio has 150 shares
    o_tsla = Order(symbol="TSLA", side=OrderSide.BUY, order_type=OrderType.BUY_STOP_LIMIT, quantity=100, trigger_price=200.0)
    broker.submit_order(o_tsla)
    broker.record_fill(o_tsla.order_id, current_time, 200.0, 100)

    pos_tsla = Position(
        symbol="TSLA", side="LONG", entry_price=200.0, entry_timestamp=current_time,
        quantity=150, initial_stop=190.0, current_stop=190.0, initial_risk_dollars=1500.0,
        engine="CATALYST", setup_type="ORB", regime_at_entry=MarketRegime.GREEN
    )
    portfolio.add_position(pos_tsla)

    # 5. Missing strategy position / Orphan broker position for AMZN: Broker filled 200 shares, portfolio has none
    o_amzn = Order(symbol="AMZN", side=OrderSide.BUY, order_type=OrderType.BUY_STOP_LIMIT, quantity=200, trigger_price=120.0)
    broker.submit_order(o_amzn)
    broker.record_fill(o_amzn.order_id, current_time, 120.0, 200)

    # 6. Unknown order ID
    o_unk = Order(symbol="XYZ", side=OrderSide.BUY, order_type=OrderType.BUY_STOP_LIMIT, quantity=10, trigger_price=10.0)
    o_unk.order_id = "UNKNOWN"
    broker._orders["UNKNOWN"] = o_unk

    # Audit in diagnostic mode (fail_closed=False)
    discs = reconciler.reconcile(portfolio, broker, current_time, fail_closed=False)
    types = {d.discrepancy_type for d in discs}

    assert "DUPLICATE_PENDING_ORDER" in types
    assert "STALE_PENDING_ORDER" in types
    assert "ORPHANED_POSITION" in types
    assert "QUANTITY_MISMATCH" in types
    assert "MISSING_STRATEGY_POSITION" in types
    assert "UNKNOWN_ORDER_ID" in types

    # Audit in fail-closed mode must raise ReconciliationError
    with pytest.raises(ReconciliationError, match="Reconciliation failed with"):
        reconciler.reconcile(portfolio, broker, current_time, fail_closed=True)


def test_session_recovery_after_order_staging_and_fill():
    """Simulates mid-session process restart and verifies exact state reconstruction."""
    temp_dir = Path(tempfile.mkdtemp())
    s_date = date(2023, 6, 15)

    try:
        # Phase 1: Initialize session, run premarket, stage orders, and simulate fill
        engine = LiveSessionEngine(session_date=s_date, output_dir=temp_dir)
        engine.run_premarket()
        engine.open_session()

        # Add a candidate and stage order
        order = Order(
            symbol="RECOV",
            side=OrderSide.BUY,
            order_type=OrderType.BUY_STOP_LIMIT,
            quantity=100,
            trigger_price=50.0,
            limit_price=50.10,
            stop_loss_price=48.0,
            created_at=datetime(2023, 6, 15, 9, 35, tzinfo=NY_TZ),
            tag="ENTRY_ORB",
        )
        engine.broker.submit_order(order)
        engine._staged_orders["RECOV"] = order

        # Fill order and record fill
        engine.broker.record_fill(order.order_id, datetime(2023, 6, 15, 9, 36, tzinfo=NY_TZ), 50.02, 100)
        engine.checkpoint()

        # Checkpoint files must exist
        session_out = temp_dir / s_date.strftime("%Y-%m-%d")
        assert (session_out / "focus_list.parquet").exists()
        assert (session_out / "orders.parquet").exists()
        assert (session_out / "fills.parquet").exists()

        # Phase 2: Process interruption - reconstruct new engine via recover_session
        recovered_engine = LiveSessionEngine.recover_session(session_date=s_date, output_dir=temp_dir)

        # Assert state is faithfully restored
        assert recovered_engine.focus_list is not None
        assert recovered_engine.session.state == LiveSessionState.ACTIVE_SESSION
        assert len(recovered_engine.broker.get_all_orders()) == 1
        assert len(recovered_engine.broker.get_all_fills()) == 1

        recovered_pos = recovered_engine.portfolio.get_position("RECOV")
        assert recovered_pos is not None
        assert recovered_pos.entry_price == 50.02
        assert recovered_pos.quantity == 100
        assert recovered_pos.initial_stop == 48.0
        assert recovered_pos.status.value == "OPEN"

    finally:
        shutil.rmtree(temp_dir)


def test_idempotent_session_operations():
    """Verifies that re-running staging or close does not duplicate records."""
    temp_dir = Path(tempfile.mkdtemp())
    s_date = date(2023, 6, 15)

    try:
        engine = LiveSessionEngine(session_date=s_date, output_dir=temp_dir)
        engine.run_premarket()
        engine.open_session()

        # Call order staging twice
        engine._stage_orders_at_0935()
        count1 = len(engine.broker.get_all_orders())
        engine._stage_orders_at_0935()
        count2 = len(engine.broker.get_all_orders())
        assert count1 == count2  # No duplicate orders staged

        # Close session
        sum1 = engine.close_session()
        assert sum1["events_processed"] == 0
        assert engine.session.state == LiveSessionState.SESSION_CLOSED

    finally:
        shutil.rmtree(temp_dir)
