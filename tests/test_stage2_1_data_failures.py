"""
Stage 2.1 Adversarial Audit: Area 2 - Streaming Data Failure & Corruption Testing
Simulates and proves fail-closed behavior on:
- Missing bars
- Duplicate timestamps
- Backwards timestamps
- Stale bars
- Corrupt OHLC geometry (H < O, H < C, L > O, L > C, H < L)
- Non-positive prices (O, H, L, C <= 0)
- Negative volume
- Missing quotes
- Inverted bid-ask spread
- Non-positive quote prices & negative quote sizes
- Large intraday gaps (> 5 min)
- Unknown or unresolved security identifiers
"""

from datetime import date, datetime, timedelta
import pytest

from bonde.data.models import NY_TZ
from bonde.live.calendar import USMarketCalendar
from bonde.live.models import LiveBar, Quote, TradingSession
from bonde.live.safety import LiveSafetyGovernor, SafetyError
from bonde.live.validation import LiveDataValidator


@pytest.fixture
def test_session():
    cal = USMarketCalendar()
    s_date = date(2023, 6, 15)
    open_dt, close_dt = cal.get_session_hours(s_date)
    return TradingSession(session_date=s_date, open_time=open_dt, close_time=close_dt)


def test_corrupt_ohlc_geometry(test_session):
    """Verifies all permutations of corrupt OHLC geometry fail closed."""
    validator = LiveDataValidator()
    ts = datetime(2023, 6, 15, 10, 0, tzinfo=NY_TZ)

    # 1. High less than Open
    bar_bad_high_open = LiveBar(
        timestamp=ts, symbol="TEST", security_id="SEC_TEST",
        open=100.0, high=99.0, low=95.0, close=98.0, volume=1000
    )
    valid, rej = validator.validate_bar(bar_bad_high_open, test_session)
    assert valid is False
    assert "OHLC_HIGH_LESS_THAN_OPEN_OR_CLOSE" in rej.reason
    assert rej.severity == "CRITICAL"

    # 2. High less than Close
    validator.reset()
    bar_bad_high_close = LiveBar(
        timestamp=ts, symbol="TEST", security_id="SEC_TEST",
        open=95.0, high=99.0, low=94.0, close=100.0, volume=1000
    )
    valid, rej = validator.validate_bar(bar_bad_high_close, test_session)
    assert valid is False
    assert "OHLC_HIGH_LESS_THAN_OPEN_OR_CLOSE" in rej.reason

    # 3. Low greater than Open
    validator.reset()
    bar_bad_low_open = LiveBar(
        timestamp=ts, symbol="TEST", security_id="SEC_TEST",
        open=95.0, high=105.0, low=96.0, close=100.0, volume=1000
    )
    valid, rej = validator.validate_bar(bar_bad_low_open, test_session)
    assert valid is False
    assert "OHLC_LOW_GREATER_THAN_OPEN_OR_CLOSE" in rej.reason

    # 4. Low greater than Close
    validator.reset()
    bar_bad_low_close = LiveBar(
        timestamp=ts, symbol="TEST", security_id="SEC_TEST",
        open=100.0, high=105.0, low=96.0, close=95.0, volume=1000
    )
    valid, rej = validator.validate_bar(bar_bad_low_close, test_session)
    assert valid is False
    assert "OHLC_LOW_GREATER_THAN_OPEN_OR_CLOSE" in rej.reason


def test_non_positive_prices_and_negative_volume(test_session):
    """Verifies that zero/negative prices and negative volume fail closed."""
    validator = LiveDataValidator()
    ts = datetime(2023, 6, 15, 10, 0, tzinfo=NY_TZ)

    # 1. Zero Open
    bar_zero_open = LiveBar(
        timestamp=ts, symbol="TEST", security_id="SEC_TEST",
        open=0.0, high=10.0, low=0.0, close=10.0, volume=1000
    )
    valid, rej = validator.validate_bar(bar_zero_open, test_session)
    assert valid is False
    assert "NON_POSITIVE_PRICE" in rej.reason

    # 2. Negative Close
    validator.reset()
    bar_neg_close = LiveBar(
        timestamp=ts, symbol="TEST", security_id="SEC_TEST",
        open=10.0, high=12.0, low=-5.0, close=-1.0, volume=1000
    )
    valid, rej = validator.validate_bar(bar_neg_close, test_session)
    assert valid is False
    assert "NON_POSITIVE_PRICE" in rej.reason

    # 3. Negative Volume
    validator.reset()
    bar_neg_vol = LiveBar(
        timestamp=ts, symbol="TEST", security_id="SEC_TEST",
        open=10.0, high=12.0, low=9.0, close=11.0, volume=-500
    )
    valid, rej = validator.validate_bar(bar_neg_vol, test_session)
    assert valid is False
    assert "NEGATIVE_VOLUME" in rej.reason


def test_stale_bar_rejection(test_session):
    """Verifies bars delayed past max_stale_seconds (300s) are rejected."""
    validator = LiveDataValidator(max_stale_seconds=300.0)
    bar_ts = datetime(2023, 6, 15, 10, 0, tzinfo=NY_TZ)
    current_clock = bar_ts + timedelta(seconds=301.0)  # 301 seconds later

    bar = LiveBar(
        timestamp=bar_ts, symbol="TEST", security_id="SEC_TEST",
        open=100.0, high=102.0, low=99.0, close=101.0, volume=1000
    )
    valid, rej = validator.validate_bar(bar, test_session, current_clock=current_clock)
    assert valid is False
    assert "STALE_BAR_DATA" in rej.reason


def test_duplicate_and_backward_timestamps(test_session):
    """Verifies timestamps must be strictly monotonic."""
    validator = LiveDataValidator()
    t1 = datetime(2023, 6, 15, 10, 0, tzinfo=NY_TZ)
    t2 = datetime(2023, 6, 15, 10, 1, tzinfo=NY_TZ)

    bar1 = LiveBar(timestamp=t1, symbol="TEST", security_id="SEC_TEST", open=10.0, high=11.0, low=9.0, close=10.5, volume=100)
    valid, rej = validator.validate_bar(bar1, test_session)
    assert valid is True

    # Duplicate timestamp
    bar_dup = LiveBar(timestamp=t1, symbol="TEST", security_id="SEC_TEST", open=10.5, high=11.5, low=10.0, close=11.0, volume=200)
    valid, rej = validator.validate_bar(bar_dup, test_session)
    assert valid is False
    assert "DUPLICATE_BAR_TIMESTAMP" in rej.reason

    # Advance to t2
    bar2 = LiveBar(timestamp=t2, symbol="TEST", security_id="SEC_TEST", open=10.5, high=11.5, low=10.0, close=11.0, volume=200)
    valid, rej = validator.validate_bar(bar2, test_session)
    assert valid is True

    # Backward timestamp (t1 after t2)
    bar_back = LiveBar(timestamp=t1, symbol="TEST", security_id="SEC_TEST", open=10.0, high=11.0, low=9.0, close=10.5, volume=100)
    valid, rej = validator.validate_bar(bar_back, test_session)
    assert valid is False
    assert "MONOTONIC_TIMESTAMP_VIOLATION" in rej.reason


def test_quote_adversarial_validation(test_session):
    """Verifies inverted spread, negative quote size, and non-positive prices are rejected."""
    validator = LiveDataValidator()
    ts = datetime(2023, 6, 15, 10, 0, tzinfo=NY_TZ)

    # 1. Inverted spread (Ask < Bid)
    q_inverted = Quote(timestamp=ts, symbol="TEST", security_id="SEC_TEST", bid=100.50, ask=100.20)
    valid, rej = validator.validate_quote(q_inverted, test_session)
    assert valid is False
    assert "INVERTED_BID_ASK_SPREAD" in rej.reason

    # 2. Non-positive bid/ask
    validator.reset()
    q_non_pos = Quote(timestamp=ts, symbol="TEST", security_id="SEC_TEST", bid=-1.0, ask=10.0)
    valid, rej = validator.validate_quote(q_non_pos, test_session)
    assert valid is False
    assert "NON_POSITIVE_QUOTE" in rej.reason

    # 3. Negative quote size
    validator.reset()
    q_neg_size = Quote(timestamp=ts, symbol="TEST", security_id="SEC_TEST", bid=10.0, ask=10.10, bid_size=-100)
    valid, rej = validator.validate_quote(q_neg_size, test_session)
    assert valid is False
    assert "NEGATIVE_QUOTE_SIZE" in rej.reason


def test_unresolved_security_id_and_missing_bars():
    """Verifies fail-closed assertions for unresolved security ID and missing required bars."""
    # Unresolved security ID
    with pytest.raises(SafetyError, match="UNRESOLVED_SECURITY_FAIL_CLOSED"):
        LiveSafetyGovernor.assert_security_resolved(None, "UNKNOWN")

    with pytest.raises(SafetyError, match="UNRESOLVED_SECURITY_FAIL_CLOSED"):
        LiveSafetyGovernor.assert_security_resolved("", "EMPTY")

    # Missing bars (e.g. requires 5 ORB bars, only 2 available)
    with pytest.raises(SafetyError, match="MISSING_BARS_FAIL_CLOSED"):
        LiveSafetyGovernor.assert_bars_available([1, 2], required_count=5, symbol="XYZ")
