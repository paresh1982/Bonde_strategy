"""
Unit Tests for Execution Simulator & Order Lifecycle (Tests 1, 3, 9)
"""

from datetime import datetime, time
import zoneinfo
from bonde.data.models import Bar, NY_TZ
from bonde.execution.orders import Order, OrderSide, OrderType, OrderStatus
from bonde.execution.simulator import ExecutionSimulator


def test_stop_limit_collar_fill():
    """Test 1: Price touches trigger and is within collar -> FILLED."""
    simulator = ExecutionSimulator()

    # Trigger = $32.11, Limit = $32.21 (+$0.10 collar)
    order = Order(
        symbol="TEST",
        side=OrderSide.BUY,
        order_type=OrderType.BUY_STOP_LIMIT,
        quantity=500,
        trigger_price=32.11,
        limit_price=32.21,
        stop_loss_price=30.80,
    )

    # Bar opens at 32.05, high touches 32.15, low 32.00, close 32.12 at 09:36 AM
    bar = Bar(
        timestamp=datetime(2026, 1, 5, 9, 36, 0, tzinfo=NY_TZ),
        symbol="TEST",
        open=32.05,
        high=32.15,
        low=32.00,
        close=32.12,
        volume=50_000.0,
    )

    fill = simulator.process_entry_order(order, bar)

    assert fill is not None
    assert order.status == OrderStatus.FILLED
    assert fill.fill_price == 32.11  # Filled at trigger
    assert fill.quantity == 500


def test_stop_limit_collar_miss():
    """Test 3: Bar opens above limit collar -> NO FILL / CANCELLED."""
    simulator = ExecutionSimulator()

    order = Order(
        symbol="TEST",
        side=OrderSide.BUY,
        order_type=OrderType.BUY_STOP_LIMIT,
        quantity=500,
        trigger_price=32.11,
        limit_price=32.21,  # +$0.10 collar
        stop_loss_price=30.80,
    )

    # Bar gaps open at 32.35 (above the $32.21 limit collar)
    bar = Bar(
        timestamp=datetime(2026, 1, 5, 9, 36, 0, tzinfo=NY_TZ),
        symbol="TEST",
        open=32.35,
        high=32.60,
        low=32.30,
        close=32.50,
        volume=100_000.0,
    )

    fill = simulator.process_entry_order(order, bar)

    assert fill is None
    assert order.status == OrderStatus.CANCELLED
    assert order.rejection_reason == "COLLAR_MISS"


def test_stale_order_cutoff_1015():
    """Test 9: Order pending at 10:15:00 EST -> CANCELLED."""
    simulator = ExecutionSimulator(stale_order_time=time(10, 15, 0))

    order = Order(
        symbol="TEST",
        side=OrderSide.BUY,
        order_type=OrderType.BUY_STOP_LIMIT,
        quantity=500,
        trigger_price=32.11,
        limit_price=32.21,
    )

    # Bar at exactly 10:15:00 EST
    bar = Bar(
        timestamp=datetime(2026, 1, 5, 10, 15, 0, tzinfo=NY_TZ),
        symbol="TEST",
        open=31.80,
        high=31.90,
        low=31.75,
        close=31.85,
        volume=10_000.0,
    )

    fill = simulator.process_entry_order(order, bar)

    assert fill is None
    assert order.status == OrderStatus.CANCELLED
    assert order.rejection_reason == "STALE_ORDER_PURGE"


def test_order_remains_pending_if_not_triggered():
    """Order remains pending if bar high does not reach trigger."""
    simulator = ExecutionSimulator()

    order = Order(
        symbol="TEST",
        side=OrderSide.BUY,
        order_type=OrderType.BUY_STOP_LIMIT,
        quantity=500,
        trigger_price=32.11,
        limit_price=32.21,
    )

    # Bar high is only 32.05 (below 32.11)
    bar = Bar(
        timestamp=datetime(2026, 1, 5, 9, 40, 0, tzinfo=NY_TZ),
        symbol="TEST",
        open=31.95,
        high=32.05,
        low=31.90,
        close=32.00,
        volume=15_000.0,
    )

    fill = simulator.process_entry_order(order, bar)

    assert fill is None
    assert order.status == OrderStatus.PENDING
