import pytest
from datetime import date, datetime

from bonde.data.models import NY_TZ
from bonde.live.calendar import USMarketCalendar
from bonde.live.models import LiveBar, Quote, TradingSession, DataQualityStatus
from bonde.live.validation import LiveDataValidator
from bonde.live.adapters.alpaca.normalizer import normalize_alpaca_bar
from bonde.live.adapters.alpaca.errors import AlpacaDataError

@pytest.fixture
def test_session():
    cal = USMarketCalendar()
    s_date = date(2023, 6, 15)
    open_dt, close_dt = cal.get_session_hours(s_date)
    return TradingSession(session_date=s_date, open_time=open_dt, close_time=close_dt)

@pytest.fixture
def validator():
    return LiveDataValidator()

def test_bar_with_zero_price_rejected(validator, test_session):
    dt = datetime(2023, 6, 15, 10, 30, tzinfo=NY_TZ)
    bar = LiveBar(dt, "AAPL", "SEC_AAPL", 0.0, 150.0, 0.0, 145.0, 1000)
    valid, rej = validator.validate_bar(bar, test_session)
    assert not valid
    assert rej is not None
    assert "NON_POSITIVE_PRICE" in rej.reason

def test_bar_with_negative_price_rejected(validator, test_session):
    dt = datetime(2023, 6, 15, 10, 30, tzinfo=NY_TZ)
    bar = LiveBar(dt, "AAPL", "SEC_AAPL", -1.0, 150.0, -1.0, 145.0, 1000)
    valid, rej = validator.validate_bar(bar, test_session)
    assert not valid
    assert rej is not None
    assert "NON_POSITIVE_PRICE" in rej.reason

def test_bar_with_ohlc_violation_rejected(validator, test_session):
    dt = datetime(2023, 6, 15, 10, 30, tzinfo=NY_TZ)
    bar = LiveBar(dt, "AAPL", "SEC_AAPL", 150.0, 140.0, 145.0, 145.0, 1000)
    valid, rej = validator.validate_bar(bar, test_session)
    assert not valid
    assert rej is not None
    assert "OHLC" in rej.reason

def test_bar_outside_session_hours_rejected(validator, test_session):
    dt = datetime(2023, 6, 15, 8, 0, tzinfo=NY_TZ)
    bar = LiveBar(dt, "AAPL", "SEC_AAPL", 150.0, 155.0, 145.0, 150.0, 1000)
    valid, rej = validator.validate_bar(bar, test_session)
    assert not valid
    assert rej is not None
    assert "SESSION_BOUNDARY_VIOLATION" in rej.reason

def test_bar_after_close_rejected(validator, test_session):
    dt = datetime(2023, 6, 15, 16, 5, tzinfo=NY_TZ)
    bar = LiveBar(dt, "AAPL", "SEC_AAPL", 150.0, 155.0, 145.0, 150.0, 1000)
    valid, rej = validator.validate_bar(bar, test_session)
    assert not valid
    assert rej is not None
    assert "SESSION_BOUNDARY_VIOLATION" in rej.reason

def test_duplicate_timestamp_rejected(validator, test_session):
    dt = datetime(2023, 6, 15, 10, 30, tzinfo=NY_TZ)
    bar = LiveBar(dt, "AAPL", "SEC_AAPL", 150.0, 155.0, 145.0, 150.0, 1000)
    valid1, _ = validator.validate_bar(bar, test_session)
    assert valid1
    valid2, rej2 = validator.validate_bar(bar, test_session)
    assert not valid2
    assert rej2 is not None
    assert "DUPLICATE_BAR_TIMESTAMP" in rej2.reason

def test_monotonic_violation_rejected(validator, test_session):
    dt1 = datetime(2023, 6, 15, 10, 31, tzinfo=NY_TZ)
    dt2 = datetime(2023, 6, 15, 10, 30, tzinfo=NY_TZ)
    bar1 = LiveBar(dt1, "AAPL", "SEC_AAPL", 150.0, 155.0, 145.0, 150.0, 1000)
    bar2 = LiveBar(dt2, "AAPL", "SEC_AAPL", 150.0, 155.0, 145.0, 150.0, 1000)
    valid1, _ = validator.validate_bar(bar1, test_session)
    assert valid1
    valid2, rej2 = validator.validate_bar(bar2, test_session)
    assert not valid2
    assert rej2 is not None
    assert "MONOTONIC_TIMESTAMP_VIOLATION" in rej2.reason

def test_quote_inverted_spread_rejected(validator, test_session):
    dt = datetime(2023, 6, 15, 10, 30, tzinfo=NY_TZ)
    quote = Quote(dt, "AAPL", "SEC_AAPL", 151.0, 150.0, 100, 100)
    valid, rej = validator.validate_quote(quote, test_session)
    assert not valid
    assert rej is not None
    assert "INVERTED_BID_ASK_SPREAD" in rej.reason

def test_quote_zero_bid_rejected(validator, test_session):
    dt = datetime(2023, 6, 15, 10, 30, tzinfo=NY_TZ)
    quote = Quote(dt, "AAPL", "SEC_AAPL", 0.0, 150.0, 100, 100)
    valid, rej = validator.validate_quote(quote, test_session)
    assert not valid
    assert rej is not None
    assert "NON_POSITIVE_QUOTE" in rej.reason

def test_malformed_bar_from_normalizer_rejected():
    with pytest.raises(AlpacaDataError):
        normalize_alpaca_bar({"symbol": "AAPL", "timestamp": None, "open": 100})
