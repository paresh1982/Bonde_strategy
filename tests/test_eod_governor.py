"""
Unit Tests for End-of-Day (EOD) Audit Governor (Section 14)
Enforces 03:55 PM mandatory liquidations on failed breakouts.
"""

from datetime import datetime
from bonde.data.models import Bar, NY_TZ
from bonde.engine.backtest import Stage0BacktestEngine
from bonde.portfolio.portfolio import Position, PositionStatus
from bonde.regime.market_regime import MarketRegime


def test_eod_audit_liquidates_t1_close_below_entry():
    """T1 position closing at or below entry is liquidated at 03:55 PM."""
    engine = Stage0BacktestEngine()

    # Create active T1 position entered at $50.00
    pos = Position(
        symbol="T1_FAIL",
        side="LONG",
        entry_price=50.00,
        entry_timestamp=datetime(2026, 1, 5, 9, 36, tzinfo=NY_TZ),
        quantity=200,
        initial_stop=48.00,
        current_stop=48.00,
        initial_risk_dollars=400.0,
        engine="CATALYST",
        setup_type="ORB",
        regime_at_entry=MarketRegime.GREEN,
        days_held=0,
    )
    engine.portfolio.add_position(pos)

    # 03:55 PM bar closing at $49.80 (<= $50.00 entry)
    eod_bar = Bar(
        timestamp=datetime(2026, 1, 5, 15, 55, tzinfo=NY_TZ),
        symbol="T1_FAIL",
        open=49.90,
        high=50.10,
        low=49.70,
        close=49.80,
        volume=100_000,
    )

    engine._evaluate_eod_audit(eod_bar)

    assert pos.status == PositionStatus.CLOSED
    assert pos.exit_price == 49.80
    assert pos.exit_reason == "EOD_AUDIT_T1_CLOSE_BELOW_ENTRY"
    assert pos.realized_pnl == (49.80 - 50.00) * 200  # -$40.00 (-0.10R)


def test_eod_audit_holds_t1_close_above_entry():
    """T1 position closing above entry price is held overnight."""
    engine = Stage0BacktestEngine()

    pos = Position(
        symbol="T1_WIN",
        side="LONG",
        entry_price=50.00,
        entry_timestamp=datetime(2026, 1, 5, 9, 36, tzinfo=NY_TZ),
        quantity=200,
        initial_stop=48.00,
        current_stop=48.00,
        initial_risk_dollars=400.0,
        engine="CATALYST",
        setup_type="ORB",
        regime_at_entry=MarketRegime.GREEN,
        days_held=0,
    )
    engine.portfolio.add_position(pos)

    # 03:55 PM bar closing at $51.20 (> $50.00 entry)
    eod_bar = Bar(
        timestamp=datetime(2026, 1, 5, 15, 55, tzinfo=NY_TZ),
        symbol="T1_WIN",
        open=51.00,
        high=51.40,
        low=50.90,
        close=51.20,
        volume=100_000,
    )

    engine._evaluate_eod_audit(eod_bar)

    assert pos.status == PositionStatus.OPEN
    assert pos.exit_price is None


def test_base_hit_day_5_time_stop():
    """Base-Hit position held for 5 sessions is liquidated at 03:55 PM on Day 5."""
    engine = Stage0BacktestEngine()

    pos = Position(
        symbol="BH_EXPIRE",
        side="LONG",
        entry_price=30.00,
        entry_timestamp=datetime(2026, 1, 5, 10, 0, tzinfo=NY_TZ),
        quantity=500,
        initial_stop=29.00,
        current_stop=29.00,
        initial_risk_dollars=500.0,
        engine="BASE_HIT",
        setup_type="BASE_HIT_65D",
        regime_at_entry=MarketRegime.GREEN,
        days_held=5,  # Reached Day 5
    )
    engine.portfolio.add_position(pos)

    eod_bar = Bar(
        timestamp=datetime(2026, 1, 9, 15, 55, tzinfo=NY_TZ),
        symbol="BH_EXPIRE",
        open=30.80,
        high=31.00,
        low=30.70,
        close=30.85,
        volume=50_000,
    )

    engine._evaluate_eod_audit(eod_bar)

    assert pos.status == PositionStatus.CLOSED
    assert pos.exit_reason == "BASE_HIT_TIME_STOP_DAY_5"
    assert pos.exit_price == 30.85
