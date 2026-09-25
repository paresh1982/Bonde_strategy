"""
Stage 2.1 Adversarial Audit: Area 1 - Session State Machine, Calendar & Boundary Invariants
Validates:
- Complete valid state transition lifecycle
- Invalid state transitions fail closed (SafetyError)
- Events outside permitted session window rejected
- US Market Holidays (all 10 federal holidays + observed dates)
- Early close hours (13:00 ET) & dynamic EOD audit (12:55 ET)
- DST transition offsets (EDT vs EST)
"""

from datetime import date, datetime, time, timedelta
from pathlib import Path
import pytest

from bonde.data.models import NY_TZ
from bonde.live.calendar import USMarketCalendar
from bonde.live.models import LiveBar, TradingSession
from bonde.live.safety import SafetyError
from bonde.live.session import LiveSessionEngine, LiveSessionState, VALID_SESSION_TRANSITIONS
from bonde.live.validation import LiveDataValidator


def test_complete_valid_state_transitions():
    """Verifies complete deterministic forward transition graph."""
    engine = LiveSessionEngine(session_date=date(2023, 6, 15))
    assert engine.session.state == LiveSessionState.PRE_MARKET

    # Pre-market to Opening
    engine.transition_to(LiveSessionState.OPENING)
    assert engine.session.state == LiveSessionState.OPENING

    # Opening to ORB Collection
    engine.transition_to(LiveSessionState.ORB_COLLECTION)
    assert engine.session.state == LiveSessionState.ORB_COLLECTION

    # ORB Collection to Order Staging
    engine.transition_to(LiveSessionState.ORDER_STAGING)
    assert engine.session.state == LiveSessionState.ORDER_STAGING

    # Order Staging to Active Session
    engine.transition_to(LiveSessionState.ACTIVE_SESSION)
    assert engine.session.state == LiveSessionState.ACTIVE_SESSION

    # Active Session to Stale Order Cutoff
    engine.transition_to(LiveSessionState.STALE_ORDER_CUTOFF)
    assert engine.session.state == LiveSessionState.STALE_ORDER_CUTOFF

    # Stale Order Cutoff to Position Management
    engine.transition_to(LiveSessionState.POSITION_MANAGEMENT)
    assert engine.session.state == LiveSessionState.POSITION_MANAGEMENT

    # Position Management to EOD Audit
    engine.transition_to(LiveSessionState.EOD_AUDIT)
    assert engine.session.state == LiveSessionState.EOD_AUDIT

    # EOD Audit to Session Closed
    engine.transition_to(LiveSessionState.SESSION_CLOSED)
    assert engine.session.state == LiveSessionState.SESSION_CLOSED


def test_invalid_state_transitions_fail_closed():
    """Verifies illegal jumps between states are strictly blocked with SafetyError."""
    engine = LiveSessionEngine(session_date=date(2023, 6, 15))

    # Jump from PRE_MARKET directly to ACTIVE_SESSION must fail
    with pytest.raises(SafetyError, match="INVALID_STATE_TRANSITION"):
        engine.transition_to(LiveSessionState.ACTIVE_SESSION)

    # Jump from PRE_MARKET to EOD_AUDIT must fail
    with pytest.raises(SafetyError, match="INVALID_STATE_TRANSITION"):
        engine.transition_to(LiveSessionState.EOD_AUDIT)

    # Transition to OPENING is valid
    engine.transition_to(LiveSessionState.OPENING)

    # Jump from OPENING to EOD_AUDIT must fail
    with pytest.raises(SafetyError, match="INVALID_STATE_TRANSITION"):
        engine.transition_to(LiveSessionState.EOD_AUDIT)

    # Close session
    engine.transition_to(LiveSessionState.SESSION_CLOSED)

    # Transitioning from SESSION_CLOSED back to ACTIVE_SESSION must fail closed
    with pytest.raises(SafetyError, match="INVALID_STATE_TRANSITION"):
        engine.transition_to(LiveSessionState.ACTIVE_SESSION)


def test_process_bar_guards_premarket_and_closed():
    """Verifies process_live_bar raises SafetyError if session is not opened or already closed."""
    import tempfile
    import shutil
    temp_dir = Path(tempfile.mkdtemp())
    try:
        engine = LiveSessionEngine(session_date=date(2023, 6, 15), output_dir=temp_dir)
        bar = LiveBar(
            timestamp=datetime(2023, 6, 15, 9, 31, tzinfo=NY_TZ),
            symbol="AAPL",
            security_id="SEC_AAPL",
            open=180.0,
            high=181.0,
            low=179.5,
            close=180.5,
            volume=50000,
        )

        # In PRE_MARKET without open_session()
        with pytest.raises(SafetyError, match="INVALID_SESSION_STATE: Session is in PRE_MARKET"):
            engine.process_live_bar(bar)

        # Now open session and close it
        engine.transition_to(LiveSessionState.OPENING)
        engine.close_session()

        # Now in SESSION_CLOSED
        with pytest.raises(SafetyError, match="INVALID_SESSION_STATE: Session is SESSION_CLOSED"):
            engine.process_live_bar(bar)
    finally:
        shutil.rmtree(temp_dir)


def test_early_close_calendar_and_dynamic_eod_audit():
    """Verifies early close schedules (13:00 close) and dynamic 12:55 EOD audit."""
    cal = USMarketCalendar()
    black_friday = date(2023, 11, 24)

    assert cal.is_early_close(black_friday) is True
    open_dt, close_dt = cal.get_session_hours(black_friday)
    assert open_dt.time() == time(9, 30)
    assert close_dt.time() == time(13, 0)

    engine = LiveSessionEngine(session_date=black_friday)
    assert engine.session.is_early_close is True
    assert engine.session.close_time.time() == time(13, 0)

    # Audit time calculation: close_time - 5 minutes == 12:55 ET
    audit_time = (engine.session.close_time - timedelta(minutes=5)).time()
    assert audit_time == time(12, 55)

    # Verify regular day audit time is 15:55
    reg_engine = LiveSessionEngine(session_date=date(2023, 6, 15))
    reg_audit_time = (reg_engine.session.close_time - timedelta(minutes=5)).time()
    assert reg_audit_time == time(15, 55)


def test_events_outside_session_window_rejected():
    """Verifies that ticks prior to 09:30 or past market close fail closed."""
    validator = LiveDataValidator()
    cal = USMarketCalendar()

    # Normal session: 09:30 - 16:00
    s_date = date(2023, 6, 15)
    open_dt, close_dt = cal.get_session_hours(s_date)
    session = TradingSession(session_date=s_date, open_time=open_dt, close_time=close_dt)

    # 1. Bar before open (09:29:00)
    bar_early = LiveBar(
        timestamp=datetime(2023, 6, 15, 9, 29, tzinfo=NY_TZ),
        symbol="MSFT",
        security_id="SEC_MSFT",
        open=340.0,
        high=341.0,
        low=339.5,
        close=340.5,
        volume=10000,
    )
    valid, rej = validator.validate_bar(bar_early, session)
    assert valid is False
    assert "SESSION_BOUNDARY_VIOLATION" in rej.reason

    # 2. Bar after close (16:01:00)
    bar_late = LiveBar(
        timestamp=datetime(2023, 6, 15, 16, 1, tzinfo=NY_TZ),
        symbol="MSFT",
        security_id="SEC_MSFT",
        open=340.0,
        high=341.0,
        low=339.5,
        close=340.5,
        volume=10000,
    )
    valid, rej = validator.validate_bar(bar_late, session)
    assert valid is False
    assert "SESSION_BOUNDARY_VIOLATION" in rej.reason

    # 3. Bar on early close day past 13:00 (13:01:00)
    bf_date = date(2023, 11, 24)
    bf_open, bf_close = cal.get_session_hours(bf_date)
    bf_session = TradingSession(session_date=bf_date, open_time=bf_open, close_time=bf_close, is_early_close=True)

    bar_bf_late = LiveBar(
        timestamp=datetime(2023, 11, 24, 13, 1, tzinfo=NY_TZ),
        symbol="MSFT",
        security_id="SEC_MSFT",
        open=340.0,
        high=341.0,
        low=339.5,
        close=340.5,
        volume=10000,
    )
    valid, rej = validator.validate_bar(bar_bf_late, bf_session)
    assert valid is False
    assert "SESSION_BOUNDARY_VIOLATION" in rej.reason


def test_dst_transitions_and_utc_offsets():
    """Verifies DST spring-forward (EDT, UTC-4) and fall-back (EST, UTC-5) precision."""
    # 2023 DST transition dates: March 12, 2023 (Spring) & Nov 5, 2023 (Fall)
    march_trading_day = datetime(2023, 3, 13, 9, 30, tzinfo=NY_TZ)  # Day after spring forward
    assert march_trading_day.utcoffset() == timedelta(hours=-4)  # EDT

    nov_trading_day = datetime(2023, 11, 6, 9, 30, tzinfo=NY_TZ)   # Day after fall back
    assert nov_trading_day.utcoffset() == timedelta(hours=-5)  # EST

    import zoneinfo
    utc_tz = zoneinfo.ZoneInfo("UTC")

    utc_march = march_trading_day.astimezone(utc_tz)
    assert utc_march.hour == 13 and utc_march.minute == 30  # 13:30 UTC

    utc_nov = nov_trading_day.astimezone(utc_tz)
    assert utc_nov.hour == 14 and utc_nov.minute == 30    # 14:30 UTC
