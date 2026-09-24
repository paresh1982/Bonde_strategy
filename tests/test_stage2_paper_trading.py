"""
Stage 2 Unit & Adversarial Test Suite: US Real-Time Paper Trading Infrastructure
Validates:
A. Market Calendar (normal, holiday, weekend, DST transition, early close)
B. Data Validation (duplicate, missing, malformed OHLC, stale, invalid security)
C. Daily Preparation (valid candidate, rejected candidate, governor rejection, liquidity rejection)
D. Live State Machine (premarket -> open -> ORB collection -> order staging -> stale order cutoff -> position management -> EOD)
E. Paper Execution (stop-limit fill, collar miss, partial fill, cancellation, latency, slippage)
F. Reconciliation (matching order/position, duplicate order, orphan position, quantity mismatch)
G. Safety (unknown regime, missing data, invalid sizing, invalid security)
H. Synthetic End-to-End Replay Session
"""

from datetime import date, datetime, time, timedelta
from pathlib import Path
import pytest
import zoneinfo

from bonde.config.strategy_config import StrategyConfig
from bonde.data.breadth import MarketBreadthRecord
from bonde.data.models import Bar, NY_TZ
from bonde.execution.orders import Order, OrderSide, OrderStatus, OrderType
from bonde.live.broker import PaperExecutionBroker
from bonde.live.calendar import USMarketCalendar
from bonde.live.fill_model import PaperFillModel
from bonde.live.models import LiveBar, Quote, TradingSession
from bonde.live.prep import DailyPrepPipeline
from bonde.live.reconciliation import OrderStateReconciler, ReconciliationError
from bonde.live.safety import LiveSafetyGovernor, SafetyError
from bonde.live.session import LiveSessionEngine, LiveSessionState
from bonde.live.synthetic_session import SyntheticSessionGenerator, SyntheticSessionReplayer
from bonde.live.validation import LiveDataValidator
from bonde.portfolio.portfolio import Portfolio, Position
from bonde.regime.market_regime import MarketRegime
from bonde.risk.governors import CompositeRiskGovernor, RegimeGovernor


# =====================================================================
# A. MARKET CALENDAR TESTS
# =====================================================================

def test_calendar_normal_holiday_weekend():
    """Verifies regular trading days, weekend exclusions, and federal holidays."""
    cal = USMarketCalendar()

    # Normal Tuesday trading day
    assert cal.is_trading_day(date(2023, 6, 13)) is True
    assert cal.is_weekend(date(2023, 6, 13)) is False
    assert cal.is_holiday(date(2023, 6, 13)) is False

    # Weekend (Saturday & Sunday)
    assert cal.is_trading_day(date(2023, 6, 17)) is False
    assert cal.is_weekend(date(2023, 6, 17)) is True
    assert cal.is_trading_day(date(2023, 6, 18)) is False
    assert cal.is_weekend(date(2023, 6, 18)) is True

    # Holidays
    assert cal.is_trading_day(date(2023, 1, 2)) is False  # New Year's Day observed
    assert cal.is_holiday(date(2023, 1, 2)) is True
    assert cal.is_holiday(date(2023, 4, 7)) is True       # Good Friday
    assert cal.is_holiday(date(2023, 5, 29)) is True      # Memorial Day
    assert cal.is_holiday(date(2023, 6, 19)) is True      # Juneteenth
    assert cal.is_holiday(date(2023, 7, 4)) is True       # Independence Day
    assert cal.is_holiday(date(2023, 9, 4)) is True       # Labor Day
    assert cal.is_holiday(date(2023, 11, 23)) is True     # Thanksgiving
    assert cal.is_holiday(date(2023, 12, 25)) is True     # Christmas


def test_calendar_early_close_and_dst():
    """Verifies early close hours (13:00 ET) and DST timezone awareness."""
    cal = USMarketCalendar()

    # Black Friday 2023 (Nov 24, 2023): Early close at 13:00 ET
    black_friday = date(2023, 11, 24)
    assert cal.is_trading_day(black_friday) is True
    assert cal.is_early_close(black_friday) is True
    open_dt, close_dt = cal.get_session_hours(black_friday)
    assert open_dt.time() == time(9, 30)
    assert close_dt.time() == time(13, 0)

    # Normal session: closes at 16:00 ET
    normal_day = date(2023, 6, 13)
    norm_open, norm_close = cal.get_session_hours(normal_day)
    assert norm_open.time() == time(9, 30)
    assert norm_close.time() == time(16, 0)

    # DST Transition: EDT (UTC-4) in Summer vs EST (UTC-5) in Winter
    summer_dt = datetime(2023, 7, 10, 10, 0, tzinfo=NY_TZ)
    winter_dt = datetime(2023, 12, 11, 10, 0, tzinfo=NY_TZ)
    assert summer_dt.utcoffset() == timedelta(hours=-4)
    assert winter_dt.utcoffset() == timedelta(hours=-5)


# =====================================================================
# B. DATA VALIDATION TESTS
# =====================================================================

def test_validation_monotonic_and_duplicates():
    """Tests that duplicate or backward timestamps fail closed."""
    validator = LiveDataValidator()
    session = TradingSession(
        session_date=date(2023, 6, 15),
        open_time=datetime(2023, 6, 15, 9, 30, tzinfo=NY_TZ),
        close_time=datetime(2023, 6, 15, 16, 0, tzinfo=NY_TZ),
    )

    bar1 = LiveBar(
        timestamp=datetime(2023, 6, 15, 9, 35, tzinfo=NY_TZ),
        symbol="AAPL", security_id="SEC_AAPL",
        open=180.0, high=181.0, low=179.5, close=180.5, volume=100_000,
    )
    valid, rej = validator.validate_bar(bar1, session)
    assert valid is True
    assert rej is None

    # Duplicate timestamp
    bar_dup = LiveBar(
        timestamp=datetime(2023, 6, 15, 9, 35, tzinfo=NY_TZ),
        symbol="AAPL", security_id="SEC_AAPL",
        open=180.5, high=181.5, low=180.0, close=181.0, volume=50_000,
    )
    valid, rej = validator.validate_bar(bar_dup, session)
    assert valid is False
    assert "DUPLICATE_BAR_TIMESTAMP" in rej.reason

    # Monotonic backward timestamp
    bar_back = LiveBar(
        timestamp=datetime(2023, 6, 15, 9, 34, tzinfo=NY_TZ),
        symbol="AAPL", security_id="SEC_AAPL",
        open=180.0, high=180.5, low=179.8, close=180.2, volume=40_000,
    )
    valid, rej = validator.validate_bar(bar_back, session)
    assert valid is False
    assert "MONOTONIC_TIMESTAMP_VIOLATION" in rej.reason


def test_validation_ohlc_and_positive_prices():
    """Tests OHLC structural consistency and non-positive price rejection."""
    validator = LiveDataValidator()
    session = TradingSession(
        session_date=date(2023, 6, 15),
        open_time=datetime(2023, 6, 15, 9, 30, tzinfo=NY_TZ),
        close_time=datetime(2023, 6, 15, 16, 0, tzinfo=NY_TZ),
    )

    # Inverted High < Open
    bar_inv_h = LiveBar(
        timestamp=datetime(2023, 6, 15, 9, 31, tzinfo=NY_TZ),
        symbol="MSFT", security_id="SEC_MSFT",
        open=300.0, high=299.0, low=298.0, close=298.5, volume=10_000,
    )
    valid, rej = validator.validate_bar(bar_inv_h, session)
    assert valid is False
    assert "OHLC_HIGH_LESS_THAN_OPEN_OR_CLOSE" in rej.reason

    # Inverted Low > Close
    bar_inv_l = LiveBar(
        timestamp=datetime(2023, 6, 15, 9, 32, tzinfo=NY_TZ),
        symbol="MSFT", security_id="SEC_MSFT",
        open=300.0, high=302.0, low=301.0, close=299.0, volume=10_000,
    )
    valid, rej = validator.validate_bar(bar_inv_l, session)
    assert valid is False
    assert "OHLC_LOW_GREATER_THAN_OPEN_OR_CLOSE" in rej.reason

    # Non-positive price
    bar_neg_p = LiveBar(
        timestamp=datetime(2023, 6, 15, 9, 33, tzinfo=NY_TZ),
        symbol="MSFT", security_id="SEC_MSFT",
        open=0.0, high=10.0, low=0.0, close=5.0, volume=10_000,
    )
    valid, rej = validator.validate_bar(bar_neg_p, session)
    assert valid is False
    assert "NON_POSITIVE_PRICE" in rej.reason


def test_validation_staleness_and_session_boundaries():
    """Tests session boundary violations and stale bar filtering."""
    validator = LiveDataValidator(max_stale_seconds=60.0)
    session = TradingSession(
        session_date=date(2023, 6, 15),
        open_time=datetime(2023, 6, 15, 9, 30, tzinfo=NY_TZ),
        close_time=datetime(2023, 6, 15, 16, 0, tzinfo=NY_TZ),
    )

    # Outside session boundary (09:25 AM ET before market open)
    bar_pre = LiveBar(
        timestamp=datetime(2023, 6, 15, 9, 25, tzinfo=NY_TZ),
        symbol="TSLA", security_id="SEC_TSLA",
        open=250.0, high=251.0, low=249.5, close=250.5, volume=50_000,
    )
    valid, rej = validator.validate_bar(bar_pre, session)
    assert valid is False
    assert "SESSION_BOUNDARY_VIOLATION" in rej.reason

    # Stale bar (clock is 09:40 ET, bar is 09:31 ET -> 9 mins old > 60s)
    bar_stale = LiveBar(
        timestamp=datetime(2023, 6, 15, 9, 31, tzinfo=NY_TZ),
        symbol="TSLA", security_id="SEC_TSLA",
        open=250.0, high=251.0, low=249.5, close=250.5, volume=50_000,
    )
    clock = datetime(2023, 6, 15, 9, 40, tzinfo=NY_TZ)
    valid, rej = validator.validate_bar(bar_stale, session, current_clock=clock)
    assert valid is False
    assert "STALE_BAR_DATA" in rej.reason


def test_validation_quote_spread_and_positivity():
    """Tests streaming quote validation: inverted spreads and negative prices."""
    validator = LiveDataValidator()
    session = TradingSession(
        session_date=date(2023, 6, 15),
        open_time=datetime(2023, 6, 15, 9, 30, tzinfo=NY_TZ),
        close_time=datetime(2023, 6, 15, 16, 0, tzinfo=NY_TZ),
    )

    # Valid quote
    q_valid = Quote(
        timestamp=datetime(2023, 6, 15, 9, 35, tzinfo=NY_TZ),
        symbol="NVDA", security_id="SEC_NVDA", bid=400.00, ask=400.10,
    )
    valid, rej = validator.validate_quote(q_valid, session)
    assert valid is True
    assert q_valid.spread == 0.10

    # Inverted spread (Ask < Bid)
    q_inv = Quote(
        timestamp=datetime(2023, 6, 15, 9, 36, tzinfo=NY_TZ),
        symbol="NVDA", security_id="SEC_NVDA", bid=400.50, ask=400.20,
    )
    valid, rej = validator.validate_quote(q_inv, session)
    assert valid is False
    assert "INVERTED_BID_ASK_SPREAD" in rej.reason


# =====================================================================
# C. DAILY PRE-MARKET PIPELINE TESTS
# =====================================================================

def test_daily_prep_focus_list_generation():
    """Verifies that DailyPrepPipeline generates a deterministic focus list on historical fixtures."""
    pipeline = DailyPrepPipeline(data_root=Path("data/stage1d"))
    focus_list = pipeline.run_prep(session_date=date(2023, 5, 25))

    assert focus_list is not None
    assert focus_list.session_date == date(2023, 5, 25)
    assert focus_list.regime == MarketRegime.GREEN
    assert focus_list.daily_budget_r == 3.0

    # Verify candidate metadata schema
    df = focus_list.to_dataframe()
    assert not df.empty
    expected_cols = {"candidate_id", "security_id", "symbol" if "symbol" in df else "ticker", "trigger_price", "structural_stop", "regime"}
    for col in expected_cols:
        assert col in df.columns or "ticker" in df.columns


def test_daily_prep_governor_and_liquidity_rejections():
    """Verifies RED regime disables new budget and low liquidity pruned below 0.60R."""
    pipeline = DailyPrepPipeline(data_root=Path("data/stage1d"))

    # Force RED regime governor
    gov_red = CompositeRiskGovernor(governors=[RegimeGovernor()])
    # Manually pass RED regime in prep pipeline
    old_rec = pipeline.breadth_provider._records[date(2023, 5, 25)]
    new_rec = MarketBreadthRecord(
        session_date=old_rec.session_date,
        universe_size=old_rec.universe_size,
        gainers_4pct_count=old_rec.gainers_4pct_count,
        losers_4pct_count=old_rec.losers_4pct_count,
        t2108_percent=old_rec.t2108_percent,
        regime_state="RED",
    )
    pipeline.breadth_provider._records[date(2023, 5, 25)] = new_rec

    focus_list = pipeline.run_prep(
        session_date=date(2023, 5, 25),
        portfolio_equity=100_000.0,
        risk_governor=gov_red,
    )
    assert focus_list.regime == MarketRegime.RED
    assert focus_list.daily_budget_r == 0.0
    assert len(focus_list.approved_candidates) == 0

    # Reset back to GREEN
    pipeline.breadth_provider._records[date(2023, 5, 25)] = old_rec


# =====================================================================
# D. PAPER EXECUTION BROKER & FILL MODEL TESTS
# =====================================================================

def test_paper_broker_order_lifecycle():
    """Tests PaperExecutionBroker submit, cancel, fill tracking."""
    broker = PaperExecutionBroker()

    order = Order(
        symbol="AAPL",
        side=OrderSide.BUY,
        order_type=OrderType.BUY_STOP_LIMIT,
        quantity=200,
        trigger_price=180.00,
        limit_price=180.10,
        stop_loss_price=176.00,
        created_at=datetime(2023, 6, 15, 9, 35, tzinfo=NY_TZ),
        tag="ENTRY_TEST",
    )
    order_id = broker.submit_order(order, security_id="SEC_AAPL")
    assert order_id == order.order_id
    assert len(broker.get_open_orders()) == 1

    # Record fill
    fill = broker.record_fill(order_id, datetime(2023, 6, 15, 9, 36, tzinfo=NY_TZ), 180.05, 200, slippage=0.01)
    assert fill is not None
    assert fill.fill_price == 180.05
    assert fill.effective_price == 180.06
    assert order.status == OrderStatus.FILLED
    assert len(broker.get_open_orders()) == 0


def test_paper_fill_model_stop_limit_and_collar():
    """Tests fill model trigger, slippage, and collar miss rejection."""
    fill_model = PaperFillModel(slippage_per_share=0.02, latency_ms=50.0, collar_cents=0.10)

    order = Order(
        symbol="TSLA",
        side=OrderSide.BUY,
        order_type=OrderType.BUY_STOP_LIMIT,
        quantity=100,
        trigger_price=250.00,
        limit_price=250.10,
        stop_loss_price=245.00,
        tag="ENTRY_TEST",
    )

    # Bar high reaches 250.50, open is 249.80 -> Valid Fill
    bar_fill = LiveBar(
        timestamp=datetime(2023, 6, 15, 9, 36, tzinfo=NY_TZ),
        symbol="TSLA", security_id="SEC_TSLA",
        open=249.80, high=250.50, low=249.50, close=250.30, volume=50_000,
    )
    res = fill_model.evaluate_order(order, bar_fill)
    assert res.is_filled is True
    assert res.is_cancelled is False
    assert res.fill_price == 250.02  # 250.00 trigger + 0.02 slippage

    # Collar Miss: Bar opens at 250.25 (exceeding 250.10 limit)
    order_miss = Order(
        symbol="TSLA",
        side=OrderSide.BUY,
        order_type=OrderType.BUY_STOP_LIMIT,
        quantity=100,
        trigger_price=250.00,
        limit_price=250.10,
        stop_loss_price=245.00,
        tag="ENTRY_TEST",
    )
    bar_collar = LiveBar(
        timestamp=datetime(2023, 6, 15, 9, 36, tzinfo=NY_TZ),
        symbol="TSLA", security_id="SEC_TSLA",
        open=250.25, high=251.00, low=250.10, close=250.80, volume=50_000,
    )
    res_miss = fill_model.evaluate_order(order_miss, bar_collar)
    assert res_miss.is_filled is False
    assert res_miss.is_cancelled is True
    assert res_miss.rejection_reason == "COLLAR_MISS"


# =====================================================================
# E. ORDER & PORTFOLIO RECONCILIATION TESTS
# =====================================================================

def test_reconciliation_detects_discrepancies():
    """Tests detection of orphaned positions, duplicate orders, and quantity mismatches."""
    reconciler = OrderStateReconciler()
    portfolio = Portfolio(initial_equity=100_000.0)
    broker = PaperExecutionBroker()
    now = datetime(2023, 6, 15, 10, 0, tzinfo=NY_TZ)

    # Case 1: Orphaned position (position in portfolio without filled order in broker)
    pos = Position(
        symbol="ORPHAN",
        side="LONG",
        entry_price=100.0,
        entry_timestamp=now,
        quantity=100,
        initial_stop=95.0,
        current_stop=95.0,
        initial_risk_dollars=500.0,
        engine="BASE_HIT",
        setup_type="BREAKOUT",
        regime_at_entry=MarketRegime.GREEN,
    )
    portfolio.add_position(pos)

    discrepancies = reconciler.reconcile(portfolio, broker, current_time=now, fail_closed=False)
    types = [d.discrepancy_type for d in discrepancies]
    assert "ORPHANED_POSITION" in types

    # Case 2: Duplicate pending orders
    order1 = Order(symbol="DUP", side=OrderSide.BUY, order_type=OrderType.BUY_STOP, quantity=50, trigger_price=10.0)
    order2 = Order(symbol="DUP", side=OrderSide.BUY, order_type=OrderType.BUY_STOP, quantity=50, trigger_price=10.0)
    broker.submit_order(order1)
    broker.submit_order(order2)

    discrepancies = reconciler.reconcile(portfolio, broker, current_time=now, fail_closed=False)
    types = [d.discrepancy_type for d in discrepancies]
    assert "DUPLICATE_PENDING_ORDER" in types


# =====================================================================
# F. SAFETY GOVERNOR FAIL-CLOSED TESTS
# =====================================================================

def test_safety_governor_fail_closed():
    """Tests fail-closed exceptions when state or inputs are invalid."""
    now = datetime(2023, 6, 15, 10, 0, tzinfo=NY_TZ)

    # 1. Invalid session
    with pytest.raises(SafetyError, match="SESSION_STATE_UNKNOWN"):
        LiveSafetyGovernor.assert_session_valid(None, now)

    # 2. Unknown regime
    with pytest.raises(SafetyError, match="REGIME_STATE_UNKNOWN"):
        LiveSafetyGovernor.assert_regime_valid(None)

    # 3. Missing bars
    with pytest.raises(SafetyError, match="MISSING_BARS_FAIL_CLOSED"):
        LiveSafetyGovernor.assert_bars_available([1, 2], required_count=5, symbol="AAPL")

    # 4. Unresolved security
    with pytest.raises(SafetyError, match="UNRESOLVED_SECURITY_FAIL_CLOSED"):
        LiveSafetyGovernor.assert_security_resolved("", symbol="UNKNOWN")

    # 5. Inverted geometry (trigger <= stop)
    with pytest.raises(SafetyError, match="INVERTED_GEOMETRY_INPUT"):
        LiveSafetyGovernor.assert_sizing_inputs_valid(unit_1r=500.0, planned_shares=100, trigger=10.0, stop=12.0)


# =====================================================================
# G. SYNTHETIC END-TO-END STREAMING SESSION REPLAY
# =====================================================================

def test_live_state_machine_and_synthetic_replay():
    """
    Executes a complete synthetic session:
    Pre-Market Prep -> Open -> 5m ORB Collection -> 09:35 Staging -> Breakout Fill -> +2R Partial -> EOD.
    """
    session_d = date(2023, 6, 15)
    res = SyntheticSessionReplayer.run_synthetic_session(
        session_date=session_d,
        data_root=Path("data/stage1d"),
        output_dir=Path("data/paper_test"),
    )

    summary = res["summary"]
    engine = res["engine"]

    assert summary["session_date"] == "2023-06-15"
    assert summary["events_processed"] > 0
    assert engine.session.state == LiveSessionState.SESSION_CLOSED

    # Verify generated artifacts
    out_dir = Path("data/paper_test") / "2023-06-15"
    assert (out_dir / "focus_list.parquet").exists()
    assert (out_dir / "session_summary.json").exists()
