"""
Stage 0.2 Determinism & Position-Lifecycle Hardening Tests
Adversarially verifies:
1. Entry-bar conservative stop execution & D2 precedence
2. Master InternalLossGovernor wiring & circuit breaker
3. T+2 / 03:55 PM Stall Audit & Cushioned Runner immunity
4. Daily 10 EMA data contract & runner liquidations
5. ADV50 data contract [t-50, t-1] & strict point-in-time isolation
6. ORB raw geometry vs. Universal Risk Geometry distinction
"""

from datetime import date, datetime, time
import pytest
from bonde.config.strategy_config import StrategyConfig
from bonde.data.models import (
    Bar,
    HistoricalADV50Provider,
    NY_TZ,
    SeriesDailyIndicatorProvider,
    StaticSectorProvider,
)
from bonde.engine.backtest import Stage0BacktestEngine
from bonde.execution.orders import Order, OrderSide, OrderType, OrderStatus
from bonde.portfolio.portfolio import Position, PositionStatus
from bonde.regime.market_regime import MarketRegime, StaticRegimeProvider
from bonde.risk.governors import CompositeRiskGovernor, InternalLossGovernor
from bonde.setups.catalyst import CatalystORBSetup


# ==============================================================================
# 1. ENTRY-BAR STOP EVALUATION & D2 PRECEDENCE
# ==============================================================================

def test_entry_bar_fill_without_stop_breach():
    """Order fills on bar t; bar t low remains well above stop -> position remains OPEN."""
    engine = Stage0BacktestEngine()
    order = Order(
        symbol="ORB_CLEAN",
        side=OrderSide.BUY,
        order_type=OrderType.BUY_STOP_LIMIT,
        quantity=500,
        trigger_price=100.01,
        limit_price=100.11,
        stop_loss_price=98.00,
        tag="CATALYST_ORB",
    )
    engine.pending_orders.append(order)

    # Bar triggers at 100.01, low is 99.50 (above 98.00 stop), close is 100.05
    entry_bar = Bar(
        timestamp=datetime(2026, 1, 5, 9, 36, tzinfo=NY_TZ),
        symbol="ORB_CLEAN",
        open=99.80,
        high=100.10,
        low=99.50,
        close=100.05,
        volume=25_000,
    )
    engine._process_bar(entry_bar, adv_50=500_000)

    pos = engine.portfolio.get_position("ORB_CLEAN")
    assert pos is not None
    assert pos.status == PositionStatus.OPEN
    assert pos.entry_price == 100.01
    assert pos.shares_remaining == 500
    assert len(engine.portfolio.closed_positions) == 0


def test_entry_bar_fill_with_stop_breach():
    """
    Order fills on bar t (high >= trigger), but bar t also drops below stop (low <= stop).
    Conservative post-fill evaluation immediately liquidates on bar t.
    """
    engine = Stage0BacktestEngine()
    order = Order(
        symbol="ORB_STOPPED",
        side=OrderSide.BUY,
        order_type=OrderType.BUY_STOP_LIMIT,
        quantity=500,
        trigger_price=100.01,
        limit_price=100.11,
        stop_loss_price=98.00,
        tag="CATALYST_ORB",
    )
    engine.pending_orders.append(order)

    # Bar touches 100.05 (fill at 100.01) then collapses to 97.50 (below 98.00 stop)
    entry_bar = Bar(
        timestamp=datetime(2026, 1, 5, 9, 36, tzinfo=NY_TZ),
        symbol="ORB_STOPPED",
        open=99.80,
        high=100.05,
        low=97.50,
        close=97.80,
        volume=50_000,
    )
    engine._process_bar(entry_bar, adv_50=500_000)

    pos = engine.portfolio.get_position("ORB_STOPPED")
    assert pos is None  # Closed and removed from active
    assert len(engine.portfolio.closed_positions) == 1

    closed = engine.portfolio.closed_positions[0]
    assert closed.status == PositionStatus.CLOSED
    assert closed.exit_price == 98.00
    assert closed.exit_reason == "ENTRY_BAR_STOP_BREACH"
    assert closed.realized_pnl == (98.00 - 100.01) * 500


def test_entry_bar_gap_through_stop():
    """
    If a bar opens below stop after an intraday order, stop executes at open print (slippage).
    """
    engine = Stage0BacktestEngine()
    order = Order(
        symbol="ORB_GAP_STOP",
        side=OrderSide.BUY,
        order_type=OrderType.BUY_STOP,
        quantity=200,
        trigger_price=50.00,
        stop_loss_price=48.00,
        tag="CATALYST_ORB",
    )
    engine.pending_orders.append(order)

    # Bar opens at 47.00, spikes to 50.10 (triggers buy), and prints low 47.00
    bar = Bar(
        timestamp=datetime(2026, 1, 5, 9, 36, tzinfo=NY_TZ),
        symbol="ORB_GAP_STOP",
        open=47.00,
        high=50.10,
        low=47.00,
        close=49.00,
        volume=50_000,
    )
    engine._process_bar(bar, adv_50=500_000)

    closed = engine.portfolio.closed_positions[0]
    assert closed.status == PositionStatus.CLOSED
    assert closed.exit_price == 47.00  # min(stop, open) = 47.00


def test_entry_bar_target_and_stop_collision_stop_first():
    """
    If on the entry bar both the +2R target AND structural stop are touched,
    the D2 invariant forces STOP FIRST.
    """
    engine = Stage0BacktestEngine()
    order = Order(
        symbol="ORB_COLLISION",
        side=OrderSide.BUY,
        order_type=OrderType.BUY_STOP_LIMIT,
        quantity=500,
        trigger_price=100.01,
        limit_price=100.11,
        stop_loss_price=98.00,
        tag="CATALYST_ORB",
    )
    engine.pending_orders.append(order)

    # Risk = 2.01 -> Target = 100.01 + 4.02 = 104.03
    # Bar touches 105.00 (crosses target) AND drops to 97.00 (crosses stop)
    bar = Bar(
        timestamp=datetime(2026, 1, 5, 9, 36, tzinfo=NY_TZ),
        symbol="ORB_COLLISION",
        open=99.90,
        high=105.00,
        low=97.00,
        close=101.00,
        volume=100_000,
    )
    engine._process_bar(bar, adv_50=500_000)

    assert len(engine.portfolio.closed_positions) == 1
    closed = engine.portfolio.closed_positions[0]
    assert closed.exit_reason == "SAME_BAR_STOP_FIRST"
    assert closed.exit_price == 98.00


def test_entry_bar_collar_miss_no_position():
    """
    If the bar gaps above the limit collar, the order is cancelled as COLLAR_MISS
    and no position is created.
    """
    engine = Stage0BacktestEngine()
    order = Order(
        symbol="ORB_CHASE",
        side=OrderSide.BUY,
        order_type=OrderType.BUY_STOP_LIMIT,
        quantity=500,
        trigger_price=100.01,
        limit_price=100.11,
        stop_loss_price=98.00,
        tag="CATALYST_ORB",
    )
    engine.pending_orders.append(order)

    # Bar opens at 100.25 (exceeding limit of 100.11)
    bar = Bar(
        timestamp=datetime(2026, 1, 5, 9, 36, tzinfo=NY_TZ),
        symbol="ORB_CHASE",
        open=100.25,
        high=100.50,
        low=100.20,
        close=100.40,
        volume=30_000,
    )
    engine._process_bar(bar, adv_50=500_000)

    assert engine.portfolio.get_position("ORB_CHASE") is None
    assert len(engine.portfolio.closed_positions) == 0
    assert order.status == OrderStatus.CANCELLED
    assert order.rejection_reason == "COLLAR_MISS"


# ==============================================================================
# 2. INTERNAL LOSS GOVERNOR
# ==============================================================================

def test_internal_loss_governor_loss_counts_and_recovery():
    """
    Verifies 1 loss, 2 losses, 3 losses (tripping halt), and win reset.
    """
    gov = InternalLossGovernor(max_consecutive_losses=3)

    # 1 Loss
    gov.record_closed_trade(-100.0)
    assert gov.consecutive_losses == 1
    assert gov.is_halted is False

    # 2 Losses
    gov.record_closed_trade(-200.0)
    assert gov.consecutive_losses == 2
    assert gov.is_halted is False

    # 3 Losses -> HALT
    gov.record_closed_trade(-50.0)
    assert gov.consecutive_losses == 3
    assert gov.is_halted is True

    # Check evaluate rejects
    allowed, reason = gov.evaluate("TEST", 1000.0, 1000.0, MarketRegime.GREEN, "TECH", [])
    assert allowed is False
    assert "INTERNAL_GOVERNOR_HALTED" in reason

    # Win resets
    gov.record_closed_trade(500.0)
    assert gov.consecutive_losses == 0
    assert gov.is_halted is False

    allowed, reason = gov.evaluate("TEST", 1000.0, 1000.0, MarketRegime.GREEN, "TECH", [])
    assert allowed is True
    assert reason is None


def test_internal_loss_governor_blocks_new_order_in_engine():
    """
    Tests that 3 consecutive closed trade losses inside the engine halt subsequent ORB stagings.
    """
    engine = Stage0BacktestEngine()
    composite_gov = engine.risk_governor

    # Simulate 3 consecutive losses recorded via engine's governor
    composite_gov.record_closed_trade(-500.0)
    composite_gov.record_closed_trade(-300.0)
    composite_gov.record_closed_trade(-200.0)

    # Now attempt to stage an ORB at 09:35:00
    base_ts = datetime(2026, 1, 5, 9, 30, tzinfo=NY_TZ)
    bars = [
        Bar(base_ts.replace(minute=30), "HALTED_SYM", 100.0, 101.0, 99.5, 100.5, 10_000),
        Bar(base_ts.replace(minute=31), "HALTED_SYM", 100.5, 101.2, 100.0, 101.0, 10_000),
        Bar(base_ts.replace(minute=32), "HALTED_SYM", 101.0, 101.5, 100.5, 101.2, 10_000),
        Bar(base_ts.replace(minute=33), "HALTED_SYM", 101.2, 101.8, 101.0, 101.5, 10_000),
        Bar(base_ts.replace(minute=34), "HALTED_SYM", 101.5, 102.0, 101.2, 101.8, 10_000),
        Bar(base_ts.replace(minute=35), "HALTED_SYM", 101.8, 102.0, 101.5, 101.9, 10_000),
    ]
    engine.run(bars, adv_50_map={"HALTED_SYM": 500_000})

    # Order must NOT be staged because Internal Loss Governor vetoed
    assert len(engine.pending_orders) == 0
    rej_df = engine.journal.rejections_to_dataframe()
    assert not rej_df.empty
    assert any("INTERNAL_GOVERNOR_HALTED" in r for r in rej_df["rejection_reason"])


# ==============================================================================
# 3. T+2 / 03:55 PM STALL AUDIT
# ==============================================================================

def test_t2_hold_condition_satisfied():
    """
    On Day 2 (days_held == 1), an uncushioned position closing above Entry price
    satisfies the hold condition and is carried overnight.
    """
    engine = Stage0BacktestEngine()
    pos = Position(
        symbol="T2_STRONG",
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
        days_held=1,  # Day 2
        is_cushioned=False,
    )
    engine.portfolio.add_position(pos)

    # 03:55 PM bar closing at $51.50 (> $50.00 entry)
    bar_t2 = Bar(
        timestamp=datetime(2026, 1, 6, 15, 55, tzinfo=NY_TZ),
        symbol="T2_STRONG",
        open=51.20,
        high=51.60,
        low=51.10,
        close=51.50,
        volume=50_000,
    )
    engine._evaluate_eod_audit(bar_t2)

    assert pos.status == PositionStatus.OPEN
    assert len(engine.portfolio.closed_positions) == 0


def test_t2_stall_liquidated_close_below_entry():
    """
    On Day 2 (days_held == 1), an uncushioned position closing at or below Entry
    is flagged as a stalled breakout and liquidated at market close (03:55 PM).
    """
    engine = Stage0BacktestEngine()
    pos = Position(
        symbol="T2_STALLED",
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
        days_held=1,  # Day 2
        is_cushioned=False,
    )
    engine.portfolio.add_position(pos)

    # 03:55 PM bar closing at $49.80 (<= $50.00 entry)
    bar_t2 = Bar(
        timestamp=datetime(2026, 1, 6, 15, 55, tzinfo=NY_TZ),
        symbol="T2_STALLED",
        open=50.10,
        high=50.20,
        low=49.70,
        close=49.80,
        volume=50_000,
    )
    engine._evaluate_eod_audit(bar_t2)

    assert pos.status == PositionStatus.CLOSED
    assert pos.exit_reason == "EOD_AUDIT_T2_STALL_CLOSE_BELOW_ENTRY"
    assert pos.exit_price == 49.80


def test_t2_boundary_close_equals_entry_liquidates():
    """Boundary test: on Day 2, Close exactly equal to Entry is liquidated."""
    engine = Stage0BacktestEngine()
    pos = Position(
        symbol="T2_FLAT",
        side="LONG",
        entry_price=50.00,
        entry_timestamp=datetime(2026, 1, 5, 9, 36, tzinfo=NY_TZ),
        quantity=100,
        initial_stop=48.00,
        current_stop=48.00,
        initial_risk_dollars=200.0,
        engine="CATALYST",
        setup_type="ORB",
        regime_at_entry=MarketRegime.GREEN,
        days_held=1,
        is_cushioned=False,
    )
    engine.portfolio.add_position(pos)

    # Bar closing at exactly $50.00
    bar_flat = Bar(
        timestamp=datetime(2026, 1, 6, 15, 55, tzinfo=NY_TZ),
        symbol="T2_FLAT",
        open=50.10,
        high=50.20,
        low=49.90,
        close=50.00,
        volume=10_000,
    )
    engine._evaluate_eod_audit(bar_flat)

    assert pos.status == PositionStatus.CLOSED
    assert pos.exit_reason == "EOD_AUDIT_T2_STALL_CLOSE_BELOW_ENTRY"


def test_t2_cushioned_position_bypasses_stall_scratch():
    """
    If a position has achieved +2.0R (is_cushioned == True), it is immune to the
    T2 stall scratch and is managed as a runner.
    """
    engine = Stage0BacktestEngine()
    pos = Position(
        symbol="T2_RUNNER",
        side="LONG",
        entry_price=50.00,
        entry_timestamp=datetime(2026, 1, 5, 9, 36, tzinfo=NY_TZ),
        quantity=100,
        initial_stop=48.00,
        current_stop=50.01,  # Breakeven stop
        initial_risk_dollars=200.0,
        engine="CATALYST",
        setup_type="ORB",
        regime_at_entry=MarketRegime.GREEN,
        days_held=1,
        is_cushioned=True,  # Cushioned!
    )
    engine.portfolio.add_position(pos)

    # Bar closing at $50.00 (flat with entry, but position is cushioned)
    bar_t2 = Bar(
        timestamp=datetime(2026, 1, 6, 15, 55, tzinfo=NY_TZ),
        symbol="T2_RUNNER",
        open=50.10,
        high=50.30,
        low=50.00,
        close=50.00,
        volume=10_000,
    )
    engine._evaluate_eod_audit(bar_t2)

    assert pos.status == PositionStatus.OPEN  # NOT liquidated by T2 stall rule


# ==============================================================================
# 4. DAILY 10 EMA DATA CONTRACT
# ==============================================================================

def test_daily_ema_uses_completed_sessions_only():
    """Verifies SeriesDailyIndicatorProvider calculates EMA strictly over completed sessions."""
    # Build 12 daily closes
    history = {
        "AAPL": [
            (date(2026, 1, d), 100.0 + d) for d in range(1, 13)
        ]
    }
    provider = SeriesDailyIndicatorProvider(history)

    # As of Jan 10 (10 completed sessions)
    ema_10 = provider.get_ema("AAPL", as_of_date=date(2026, 1, 10), period=10)
    assert ema_10 is not None
    assert isinstance(ema_10, float)
    assert 100.0 < ema_10 < 111.0


def test_daily_ema_excludes_current_day_future_session():
    """Verifies sessions strictly after as_of_date cannot enter the EMA."""
    history = {
        "AAPL": [
            (date(2026, 1, 1), 100.0),
            (date(2026, 1, 2), 101.0),
            (date(2026, 1, 3), 102.0),
            (date(2026, 1, 4), 103.0),
            (date(2026, 1, 5), 104.0),
            (date(2026, 1, 6), 105.0),
            (date(2026, 1, 7), 106.0),
            (date(2026, 1, 8), 107.0),
            (date(2026, 1, 9), 108.0),
            (date(2026, 1, 10), 109.0),
            (date(2026, 1, 11), 200.0),  # Massive future outlier!
        ]
    }
    provider = SeriesDailyIndicatorProvider(history)

    # As of Jan 10: Jan 11 outlier MUST be excluded
    ema = provider.get_ema("AAPL", as_of_date=date(2026, 1, 10), period=10)
    assert ema is not None
    assert ema < 115.0  # Outlier not included


def test_daily_ema_missing_data_returns_none():
    """Fewer than 10 sessions returns None explicitly rather than a silent fallback."""
    history = {
        "NEW_IPO": [(date(2026, 1, d), 50.0) for d in range(1, 6)]  # Only 5 sessions
    }
    provider = SeriesDailyIndicatorProvider(history)
    assert provider.get_ema("NEW_IPO", as_of_date=date(2026, 1, 5), period=10) is None
    assert provider.get_ema("NON_EXISTENT", as_of_date=date(2026, 1, 5), period=10) is None


def test_cushioned_runner_liquidated_below_10_ema():
    """A cushioned runner closing below 10 EMA at 03:55 PM is liquidated."""
    history = {
        "RUNNER_SYM": [(date(2026, 1, d), 100.0) for d in range(1, 15)]  # 10 EMA is 100.00
    }
    ind_provider = SeriesDailyIndicatorProvider(history)
    engine = Stage0BacktestEngine(daily_indicator_provider=ind_provider)

    pos = Position(
        symbol="RUNNER_SYM",
        side="LONG",
        entry_price=90.00,
        entry_timestamp=datetime(2026, 1, 5, 9, 36, tzinfo=NY_TZ),
        quantity=100,
        initial_stop=88.00,
        current_stop=90.01,
        initial_risk_dollars=200.0,
        engine="CATALYST",
        setup_type="ORB",
        regime_at_entry=MarketRegime.GREEN,
        days_held=5,
        is_cushioned=True,
    )
    engine.portfolio.add_position(pos)

    # Bar closing at $98.50 (< 100.00 10 EMA) at 03:55 PM
    bar_eod = Bar(
        timestamp=datetime(2026, 1, 14, 15, 55, tzinfo=NY_TZ),
        symbol="RUNNER_SYM",
        open=99.00,
        high=99.20,
        low=98.30,
        close=98.50,
        volume=50_000,
    )
    engine._evaluate_eod_audit(bar_eod)

    assert pos.status == PositionStatus.CLOSED
    assert pos.exit_reason == "RUNNER_CLOSE_BELOW_10_EMA"


# ==============================================================================
# 5. ADV50 DATA CONTRACT [t-50, t-1]
# ==============================================================================

def test_adv50_exactly_50_sessions():
    """HistoricalADV50Provider computes exact average with exactly 50 completed prior sessions."""
    # 50 sessions each with 100,000 shares on days 1..50
    history = {
        "STOCK_50": [(date(2026, 1, 1) + pytest.importorskip("datetime").timedelta(days=i), 100_000.0) for i in range(50)]
    }
    provider = HistoricalADV50Provider(history)
    target_date = date(2026, 1, 1) + pytest.importorskip("datetime").timedelta(days=50)

    adv = provider.get_adv_50("STOCK_50", as_of_date=target_date)
    assert adv == 100_000.0


def test_adv50_49_sessions_returns_none():
    """With 49 completed sessions, ADV50 returns None (explicit unavailable state)."""
    history = {
        "STOCK_49": [(date(2026, 1, 1) + pytest.importorskip("datetime").timedelta(days=i), 100_000.0) for i in range(49)]
    }
    provider = HistoricalADV50Provider(history)
    target_date = date(2026, 1, 1) + pytest.importorskip("datetime").timedelta(days=49)

    assert provider.get_adv_50("STOCK_49", as_of_date=target_date) is None


def test_adv50_strictly_excludes_session_t():
    """Session t volume must never be included in ADV50(t)."""
    from datetime import timedelta
    # 50 sessions with 100,000 volume, plus session t with 10,000,000 volume
    t_date = date(2026, 3, 1)
    history = {
        "STOCK_T": [(t_date - timedelta(days=50 - i), 100_000.0) for i in range(50)]
    }
    history["STOCK_T"].append((t_date, 10_000_000.0))  # Session t outlier

    provider = HistoricalADV50Provider(history)
    adv = provider.get_adv_50("STOCK_T", as_of_date=t_date)
    # Must be 100,000, NOT influenced by the 10M outlier on date t
    assert adv == 100_000.0


def test_adv50_rolling_update():
    """Rolling from t to t+1 drops session t-50 and adds session t."""
    from datetime import timedelta
    start_date = date(2026, 1, 1)
    # Session 0 has 500,000 volume. Sessions 1..50 have 100,000 volume.
    history_list = [(start_date, 500_000.0)]
    for i in range(1, 51):
        history_list.append((start_date + timedelta(days=i), 100_000.0))

    provider = HistoricalADV50Provider({"ROLL": history_list})

    # At day 50 (sessions 0..49): 1 session of 500k + 49 sessions of 100k -> avg = (500k + 4.9M)/50 = 108,000
    adv_d50 = provider.get_adv_50("ROLL", as_of_date=start_date + timedelta(days=50))
    assert adv_d50 == 108_000.0

    # At day 51 (sessions 1..50): session 0 drops out; 50 sessions of 100k -> avg = 100,000
    adv_d51 = provider.get_adv_50("ROLL", as_of_date=start_date + timedelta(days=51))
    assert adv_d51 == 100_000.0


# ==============================================================================
# 6. ORB RAW GEOMETRY vs. UNIVERSAL RISK GEOMETRY
# ==============================================================================

def test_orb_and_universal_risk_pass():
    """Both ORB raw geometry and universal trade risk geometry <= 4.0% qualify."""
    setup = CatalystORBSetup(max_risk_geometry_pct=0.040)
    # Range = 100.00 to 98.00 (2.0% raw range)
    bars = [
        Bar(datetime(2026, 1, 5, 9, 30, tzinfo=NY_TZ), "ORB_BOTH_PASS", 98.50, 100.00, 98.00, 99.00, 10_000),
        Bar(datetime(2026, 1, 5, 9, 31, tzinfo=NY_TZ), "ORB_BOTH_PASS", 99.00, 99.50, 98.50, 99.20, 10_000),
        Bar(datetime(2026, 1, 5, 9, 32, tzinfo=NY_TZ), "ORB_BOTH_PASS", 99.20, 99.80, 99.00, 99.60, 10_000),
        Bar(datetime(2026, 1, 5, 9, 33, tzinfo=NY_TZ), "ORB_BOTH_PASS", 99.60, 99.90, 99.30, 99.70, 10_000),
        Bar(datetime(2026, 1, 5, 9, 34, tzinfo=NY_TZ), "ORB_BOTH_PASS", 99.70, 99.90, 99.40, 99.80, 10_000),
    ]
    cand = setup.evaluate_first_5_minutes("ORB_BOTH_PASS", bars)
    assert cand.is_qualified is True

    # Universal risk = (100.01 - 97.99) / 100.01 = 2.0198% <= 4.0%
    univ_risk = (cand.trigger_price - cand.stop_price) / cand.trigger_price
    assert univ_risk <= 0.040


def test_universal_risk_gate_rejects_when_tick_offset_exceeds_4pct():
    """
    On a low-priced stock, raw ORB geometry may be 3.99% (passes setup),
    but after adding the 2-cent offset (Trigger = ORH + $0.01, Stop = ORL - $0.01),
    the Universal Risk Gate strictly rejects the candidate.
    """
    engine = Stage0BacktestEngine()
    # ORH = 5.01, ORL = 4.81 -> raw range = (5.01 - 4.81) / 5.01 = 0.20 / 5.01 = 3.992% <= 4.0% (PASSES setup)
    # But Trigger = 5.02, Stop = 4.80 -> Universal risk = (5.02 - 4.80) / 5.02 = 0.22 / 5.02 = 4.38% > 4.0%!
    base_ts = datetime(2026, 1, 5, 9, 30, tzinfo=NY_TZ)
    bars = [
        Bar(base_ts.replace(minute=30), "LOW_PRICE_SYM", 4.90, 5.01, 4.81, 4.95, 10_000),
        Bar(base_ts.replace(minute=31), "LOW_PRICE_SYM", 4.95, 5.00, 4.85, 4.98, 10_000),
        Bar(base_ts.replace(minute=32), "LOW_PRICE_SYM", 4.98, 5.01, 4.88, 4.99, 10_000),
        Bar(base_ts.replace(minute=33), "LOW_PRICE_SYM", 4.99, 5.01, 4.89, 5.00, 10_000),
        Bar(base_ts.replace(minute=34), "LOW_PRICE_SYM", 5.00, 5.01, 4.90, 5.00, 10_000),
        Bar(base_ts.replace(minute=35), "LOW_PRICE_SYM", 5.00, 5.01, 4.95, 5.00, 10_000),
    ]
    engine.run(bars, adv_50_map={"LOW_PRICE_SYM": 500_000})

    assert len(engine.pending_orders) == 0
    rej_df = engine.journal.rejections_to_dataframe()
    assert any("UNIVERSAL_RISK_GEOMETRY_EXCEEDED" in r for r in rej_df["rejection_reason"])
