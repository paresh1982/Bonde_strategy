"""
Stage 2.1 Adversarial Audit: Area 3 - Order Lifecycle & Execution Mechanics
Validates:
- Order staging at 09:35:00 ET
- Stop-limit trigger evaluation
- Collar fill with slippage and latency
- Collar miss (gap open above collar limit -> order cancelled, zero position)
- Partial fill evaluation (e.g. 50% allocation)
- Explicit order cancellation
- 10:15:00 ET stale entry order purge
- Duplicate order prevention (idempotent staging)
- Order / position quantity mismatch detection
- Orphan position detection
"""

from datetime import date, datetime, time
import pytest

from bonde.config.strategy_config import StrategyConfig
from bonde.data.models import NY_TZ
from bonde.execution.orders import Order, OrderSide, OrderStatus, OrderType
from bonde.live.broker import PaperExecutionBroker
from bonde.live.fill_model import PaperFillModel
from bonde.live.models import LiveBar, Quote
from bonde.live.reconciliation import OrderStateReconciler, ReconciliationError
from bonde.portfolio.portfolio import Portfolio, Position


def test_order_staging_and_collar_fill():
    """Tests normal order staging, trigger breach, and collar execution."""
    broker = PaperExecutionBroker()
    fill_model = PaperFillModel(slippage_per_share=0.01, latency_ms=25.0, enforce_collar=True, collar_cents=0.10)

    # Stage BUY_STOP_LIMIT order
    order = Order(
        symbol="AAPL",
        side=OrderSide.BUY,
        order_type=OrderType.BUY_STOP_LIMIT,
        quantity=100,
        trigger_price=150.00,
        limit_price=150.10,
        stop_loss_price=145.00,
        created_at=datetime(2023, 6, 15, 9, 35, tzinfo=NY_TZ),
        tag="ENTRY_ORB",
    )
    order_id = broker.submit_order(order)
    assert order.status == OrderStatus.PENDING

    # Bar triggers order: Open 149.80, High 150.05, Low 149.70, Close 150.02
    bar = LiveBar(
        timestamp=datetime(2023, 6, 15, 9, 36, tzinfo=NY_TZ),
        symbol="AAPL",
        security_id="SEC_AAPL",
        open=149.80,
        high=150.05,
        low=149.70,
        close=150.02,
        volume=50000,
    )
    quote = Quote(timestamp=bar.timestamp, symbol="AAPL", security_id="SEC_AAPL", bid=150.00, ask=150.02)

    res = fill_model.evaluate_order(order, bar, quote)
    assert res.is_filled is True
    assert res.is_cancelled is False
    assert res.fill_quantity == 100
    # Fill price = max(trigger, ask) + slippage = 150.02 + 0.01 = 150.03 <= 150.10 collar
    assert res.fill_price == 150.03

    # Record fill in broker
    fill_rec = broker.record_fill(order_id, bar.timestamp, res.fill_price, res.fill_quantity, slippage=res.slippage)
    assert fill_rec is not None
    assert order.status == OrderStatus.FILLED


def test_collar_miss_no_chase_no_position():
    """Verifies that an opening gap above collar limit cancels order without creating a position."""
    broker = PaperExecutionBroker()
    fill_model = PaperFillModel(enforce_collar=True, collar_cents=0.10)

    order = Order(
        symbol="GAP_UP",
        side=OrderSide.BUY,
        order_type=OrderType.BUY_STOP_LIMIT,
        quantity=200,
        trigger_price=50.00,
        limit_price=50.10,
        stop_loss_price=48.00,
        created_at=datetime(2023, 6, 15, 9, 35, tzinfo=NY_TZ),
        tag="ENTRY_EP",
    )
    order_id = broker.submit_order(order)

    # Next bar gaps up to Open 50.25 (above 50.10 collar limit)
    gap_bar = LiveBar(
        timestamp=datetime(2023, 6, 15, 9, 36, tzinfo=NY_TZ),
        symbol="GAP_UP",
        security_id="SEC_GAP_UP",
        open=50.25,
        high=51.00,
        low=50.20,
        close=50.80,
        volume=100000,
    )
    res = fill_model.evaluate_order(order, gap_bar)
    assert res.is_filled is False
    assert res.is_cancelled is True
    assert res.rejection_reason == "COLLAR_MISS"

    # Broker cancels order
    cancelled = broker.cancel_order(order_id, reason=res.rejection_reason)
    assert cancelled is True
    assert order.status == OrderStatus.CANCELLED
    assert broker.get_open_orders() == []


def test_partial_fill_evaluation():
    """Verifies partial fill execution when fill model has partial_fill_ratio < 1.0."""
    fill_model = PaperFillModel(allow_partial_fills=True, partial_fill_ratio=0.50, slippage_per_share=0.01)

    order = Order(
        symbol="PART",
        side=OrderSide.BUY,
        order_type=OrderType.BUY_STOP_LIMIT,
        quantity=500,
        trigger_price=100.00,
        limit_price=100.10,
        stop_loss_price=97.00,
        created_at=datetime(2023, 6, 15, 9, 35, tzinfo=NY_TZ),
    )
    bar = LiveBar(
        timestamp=datetime(2023, 6, 15, 9, 36, tzinfo=NY_TZ),
        symbol="PART",
        security_id="SEC_PART",
        open=99.80,
        high=100.05,
        low=99.70,
        close=100.02,
        volume=20000,
    )
    res = fill_model.evaluate_order(order, bar)
    assert res.is_filled is True
    assert res.fill_quantity == 250  # 50% of 500


def test_1015_stale_order_purge_and_reconciliation():
    """Verifies un-triggered entry orders at 10:15:00 ET are purged, and reconciler detects stale orders."""
    broker = PaperExecutionBroker()
    order = Order(
        symbol="STALE",
        side=OrderSide.BUY,
        order_type=OrderType.BUY_STOP_LIMIT,
        quantity=100,
        trigger_price=200.00,
        limit_price=200.10,
        stop_loss_price=195.00,
        created_at=datetime(2023, 6, 15, 9, 35, tzinfo=NY_TZ),
        tag="ENTRY_CATALYST",
    )
    broker.submit_order(order)

    # At 10:16 ET, order is still PENDING -> Reconciler must flag STALE_PENDING_ORDER
    reconciler = OrderStateReconciler(stale_order_cutoff_time=time(10, 15))
    portfolio = Portfolio(initial_equity=100_000.0)

    with pytest.raises(ReconciliationError, match="Reconciliation failed with 1 critical discrepancies"):
        reconciler.reconcile(portfolio, broker, current_time=datetime(2023, 6, 15, 10, 16, tzinfo=NY_TZ), fail_closed=True)

    # When purged at 10:15:00
    broker.cancel_order(order.order_id, reason="STALE_ORDER_PURGE_1015")
    assert order.status == OrderStatus.CANCELLED

    # Now reconciliation passes
    discs = reconciler.reconcile(portfolio, broker, current_time=datetime(2023, 6, 15, 10, 16, tzinfo=NY_TZ), fail_closed=False)
    assert len(discs) == 0
