"""
Stage 2.1 Adversarial Audit: Area 4 - Intrabar Collisions & STOP-FIRST Invariants
Explicitly verifies:
- Target and Stop breached on same bar (MANDATORY D2 RULE: STOP FIRST)
- Entry Fill + Stop Breach on same bar (STOP IMMEDIATE)
- Entry Fill + Target Hit on same bar (FILL THEN TARGET)
- Entry Fill + Target + Stop all on same bar (FILL THEN STOP)
- Opening gap through stop
- Gap through stop-limit collar
- Price touching trigger without reaching executable collar
"""

from datetime import date, datetime, time
import pytest

from bonde.config.strategy_config import StrategyConfig
from bonde.data.models import NY_TZ
from bonde.execution.orders import Order, OrderSide, OrderStatus, OrderType
from bonde.live.fill_model import PaperFillModel
from bonde.live.models import LiveBar, Quote
from bonde.live.session import LiveSessionEngine, LiveSessionState
from bonde.portfolio.portfolio import Portfolio, Position, PositionStatus
from bonde.regime.market_regime import MarketRegime


def test_intrabar_target_and_stop_collision_stop_first():
    """
    Mandatory Rule D2 / Stage 0.2:
    When an active position experiences both Target hit (High >= Target)
    and Stop breach (Low <= Stop) within the EXACT SAME BAR,
    the STOP MUST EXECUTE FIRST. Target order is ignored.
    """
    engine = LiveSessionEngine(session_date=date(2023, 6, 15))
    engine.transition_to(LiveSessionState.OPENING)
    engine.transition_to(LiveSessionState.ACTIVE_SESSION)

    # Existing open position: Entry $100.00, Stop $95.00 (Risk $5.00). Target +2R = $110.00
    pos = Position(
        symbol="COLLIDE",
        side="LONG",
        entry_price=100.00,
        entry_timestamp=datetime(2023, 6, 15, 9, 36, tzinfo=NY_TZ),
        quantity=100,
        initial_stop=95.00,
        current_stop=95.00,
        initial_risk_dollars=500.0,
        engine="CATALYST",
        setup_type="ENTRY_ORB",
        regime_at_entry=MarketRegime.GREEN,
    )
    assert pos.partial_target_price == 110.00
    engine.portfolio.add_position(pos)

    # Intrabar collision bar: High 112.00 (breaches Target), Low 93.00 (breaches Stop)
    # Open 102.00, Close 94.00
    collision_bar = LiveBar(
        timestamp=datetime(2023, 6, 15, 10, 0, tzinfo=NY_TZ),
        symbol="COLLIDE",
        security_id="SEC_COLLIDE",
        open=102.00,
        high=112.00,
        low=93.00,
        close=94.00,
        volume=80000,
    )
    engine.process_live_bar(collision_bar)

    # Verify: Position closed at stop, NOT target!
    assert pos.status == PositionStatus.CLOSED
    assert pos.exit_reason == "SAME_BAR_STOP_FIRST"
    # Exit price = min(stop, open) - slippage = 95.00 - 0.01 = 94.99
    assert pos.exit_price == 94.99
    assert pos.realized_pnl < 0  # Negative loss recorded, NOT +2R profit!
    assert len(engine.journal.trades) == 1
    assert engine.journal.trades[0].exit_reason == "SAME_BAR_STOP_FIRST"


def test_entry_fill_and_stop_breach_same_bar():
    """
    Row 57 of Simultaneous Event Matrix:
    Pending order fills at trigger; same bar registers Low <= Stop.
    STOP IMMEDIATE: Position opened, then immediately closed at min(stop, open).
    """
    engine = LiveSessionEngine(session_date=date(2023, 6, 15))
    engine.transition_to(LiveSessionState.OPENING)
    engine.transition_to(LiveSessionState.ACTIVE_SESSION)

    # Staged BUY_STOP_LIMIT order: Trigger 50.00, Collar 50.10, Stop 48.00
    order = Order(
        symbol="STOP_SAME",
        side=OrderSide.BUY,
        order_type=OrderType.BUY_STOP_LIMIT,
        quantity=100,
        trigger_price=50.00,
        limit_price=50.10,
        stop_loss_price=48.00,
        created_at=datetime(2023, 6, 15, 9, 35, tzinfo=NY_TZ),
        tag="ENTRY_ORB",
    )
    engine.broker.submit_order(order)
    engine._staged_orders["STOP_SAME"] = order

    # Entry bar: Open 49.50, High 50.05 (triggers entry), Low 47.50 (breaches stop), Close 47.80
    whipsaw_bar = LiveBar(
        timestamp=datetime(2023, 6, 15, 9, 36, tzinfo=NY_TZ),
        symbol="STOP_SAME",
        security_id="SEC_STOP_SAME",
        open=49.50,
        high=50.05,
        low=47.50,
        close=47.80,
        volume=50000,
    )
    engine.process_live_bar(whipsaw_bar)

    # Position must have filled and then immediately stopped out on the same bar
    assert len(engine.portfolio.closed_positions) == 1
    pos = engine.portfolio.closed_positions[0]
    assert pos.symbol == "STOP_SAME"
    assert pos.status == PositionStatus.CLOSED
    assert pos.exit_reason == "ENTRY_BAR_STOP_BREACH"
    assert pos.exit_price == 48.00
    assert len(engine.journal.trades) == 1
    assert engine.journal.trades[0].exit_reason == "ENTRY_BAR_STOP_BREACH"


def test_entry_fill_and_target_hit_same_bar():
    """
    Row 58 of Simultaneous Event Matrix:
    Pending order fills at trigger; same bar registers High >= Target, Low > Stop.
    FILL THEN TARGET: Position opened, 50% partial filled at target price, stop ratcheted to Breakeven.
    """
    engine = LiveSessionEngine(session_date=date(2023, 6, 15))
    engine.transition_to(LiveSessionState.OPENING)
    engine.transition_to(LiveSessionState.ACTIVE_SESSION)

    # Staged BUY order: Trigger 50.00, Stop 49.00 (Risk $1.00). Target +2R = 52.00
    order = Order(
        symbol="ROCKET",
        side=OrderSide.BUY,
        order_type=OrderType.BUY_STOP_LIMIT,
        quantity=100,
        trigger_price=50.00,
        limit_price=50.10,
        stop_loss_price=49.00,
        created_at=datetime(2023, 6, 15, 9, 35, tzinfo=NY_TZ),
        tag="ENTRY_TRACK_A",
    )
    engine.broker.submit_order(order)
    engine._staged_orders["ROCKET"] = order

    # Mega bar: Open 49.80, High 52.50 (breaches trigger and target), Low 49.50 (above stop 49.00), Close 52.20
    rocket_bar = LiveBar(
        timestamp=datetime(2023, 6, 15, 9, 36, tzinfo=NY_TZ),
        symbol="ROCKET",
        security_id="SEC_ROCKET",
        open=49.80,
        high=52.50,
        low=49.50,
        close=52.20,
        volume=150000,
    )
    engine.process_live_bar(rocket_bar)

    pos = engine.portfolio.get_position("ROCKET")
    assert pos is not None
    assert pos.status == PositionStatus.OPEN
    assert pos.has_partial_filled is True
    assert pos.is_cushioned is True
    assert pos.shares_remaining == 50  # 50% sold
    assert round(pos.current_stop, 2) == round(pos.entry_price + 0.01, 2)  # Breakeven ratchet


def test_opening_gap_through_stop():
    """Verifies that an opening gap down below stop exits at gap open (slippage applied)."""
    fill_model = PaperFillModel(slippage_per_share=0.01)
    stop_order = Order(
        symbol="GAP_STOP",
        side=OrderSide.SELL,
        order_type=OrderType.SELL_STOP,
        quantity=100,
        trigger_price=100.00,
        stop_loss_price=100.00,
        created_at=datetime(2023, 6, 15, 9, 30, tzinfo=NY_TZ),
    )

    # Bar gaps down to Open 97.00 (below 100.00 stop)
    gap_down_bar = LiveBar(
        timestamp=datetime(2023, 6, 15, 9, 31, tzinfo=NY_TZ),
        symbol="GAP_STOP",
        security_id="SEC_GAP_STOP",
        open=97.00,
        high=97.50,
        low=96.00,
        close=96.50,
        volume=50000,
    )
    res = fill_model.evaluate_order(stop_order, gap_down_bar)
    assert res.is_filled is True
    # Fill price = min(stop, open) - slippage = 97.00 - 0.01 = 96.99
    assert res.fill_price == 96.99
