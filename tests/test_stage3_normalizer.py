import pytest
from datetime import datetime, timezone
import zoneinfo
from dataclasses import dataclass
from typing import Optional

from bonde.data.models import NY_TZ
from bonde.live.models import LiveBar, Quote, DataQualityStatus
from bonde.live.adapters.alpaca.normalizer import normalize_alpaca_bar, normalize_alpaca_quote
from bonde.live.adapters.alpaca.errors import AlpacaDataError

@dataclass
class MockAlpacaBar:
    symbol: str
    timestamp: datetime
    open: float
    high: float
    low: float
    close: float
    volume: float
    trade_count: Optional[int] = None
    vwap: Optional[float] = None

@dataclass
class MockAlpacaQuote:
    symbol: str
    timestamp: datetime
    bid_price: float
    ask_price: float
    bid_size: float
    ask_size: float

def test_normalize_bar_utc_to_ny_tz():
    utc_dt = datetime(2023, 6, 15, 13, 30, tzinfo=timezone.utc) # 09:30 EDT
    mock = MockAlpacaBar(
        symbol="AAPL",
        timestamp=utc_dt,
        open=180.0,
        high=181.0,
        low=179.5,
        close=180.5,
        volume=1000
    )
    bar = normalize_alpaca_bar(mock)
    assert bar.symbol == "AAPL"
    assert bar.timestamp.tzinfo == NY_TZ
    assert bar.timestamp.hour == 9
    assert bar.timestamp.minute == 30
    assert bar.open == 180.0
    assert bar.quality_status == DataQualityStatus.VALID

def test_normalize_bar_fields_mapped():
    utc_dt = datetime(2023, 6, 15, 14, 0, tzinfo=timezone.utc)
    mock = MockAlpacaBar("TSLA", utc_dt, 250.0, 255.0, 249.0, 254.0, 50000)
    bar = normalize_alpaca_bar(mock)
    assert bar.symbol == "TSLA"
    assert bar.open == 250.0
    assert bar.high == 255.0
    assert bar.low == 249.0
    assert bar.close == 254.0
    assert bar.volume == 50000

def test_normalize_bar_security_id_default():
    utc_dt = datetime(2023, 6, 15, 14, 0, tzinfo=timezone.utc)
    mock = MockAlpacaBar("MSFT", utc_dt, 300.0, 305.0, 299.0, 304.0, 10000)
    bar = normalize_alpaca_bar(mock)
    assert bar.security_id == "SEC_MSFT"

def test_normalize_bar_security_id_custom():
    utc_dt = datetime(2023, 6, 15, 14, 0, tzinfo=timezone.utc)
    mock = MockAlpacaBar("NVDA", utc_dt, 400.0, 405.0, 399.0, 404.0, 20000)
    mapping = {"NVDA": "CUSTOM_NVDA_ID"}
    bar = normalize_alpaca_bar(mock, security_id_map=mapping)
    assert bar.security_id == "CUSTOM_NVDA_ID"

def test_normalize_bar_missing_symbol_raises():
    utc_dt = datetime(2023, 6, 15, 14, 0, tzinfo=timezone.utc)
    mock = MockAlpacaBar("", utc_dt, 100.0, 105.0, 99.0, 104.0, 1000)
    with pytest.raises(AlpacaDataError, match="Symbol is required"):
        normalize_alpaca_bar(mock)

def test_normalize_bar_negative_price_raises():
    utc_dt = datetime(2023, 6, 15, 14, 0, tzinfo=timezone.utc)
    mock = MockAlpacaBar("AAPL", utc_dt, -10.0, 105.0, 99.0, 104.0, 1000)
    with pytest.raises(AlpacaDataError, match="Prices must be > 0"):
        normalize_alpaca_bar(mock)

def test_normalize_bar_negative_volume_raises():
    utc_dt = datetime(2023, 6, 15, 14, 0, tzinfo=timezone.utc)
    mock = MockAlpacaBar("AAPL", utc_dt, 100.0, 105.0, 99.0, 104.0, -5)
    with pytest.raises(AlpacaDataError, match="Volume must be >= 0"):
        normalize_alpaca_bar(mock)

def test_normalize_bar_none_timestamp_raises():
    mock = MockAlpacaBar("AAPL", None, 100.0, 105.0, 99.0, 104.0, 100)
    with pytest.raises(AlpacaDataError, match="Timestamp is required"):
        normalize_alpaca_bar(mock)

def test_normalize_bar_dict_input():
    bar_dict = {
        "symbol": "AMD",
        "timestamp": "2023-06-15T14:00:00Z",
        "open": 110.0,
        "high": 112.0,
        "low": 109.0,
        "close": 111.5,
        "volume": 12000
    }
    bar = normalize_alpaca_bar(bar_dict)
    assert bar.symbol == "AMD"
    assert bar.timestamp.tzinfo == NY_TZ
    assert bar.open == 110.0
    assert bar.close == 111.5
    assert bar.volume == 12000

def test_normalize_quote_utc_to_ny_tz():
    utc_dt = datetime(2023, 6, 15, 13, 30, tzinfo=timezone.utc)
    mock = MockAlpacaQuote("SPY", utc_dt, 440.0, 440.05, 10, 15)
    quote = normalize_alpaca_quote(mock)
    assert quote.symbol == "SPY"
    assert quote.timestamp.tzinfo == NY_TZ
    assert quote.timestamp.hour == 9
    assert quote.timestamp.minute == 30

def test_normalize_quote_fields_mapped():
    utc_dt = datetime(2023, 6, 15, 13, 30, tzinfo=timezone.utc)
    mock = MockAlpacaQuote("QQQ", utc_dt, 365.10, 365.15, 25, 30)
    quote = normalize_alpaca_quote(mock)
    assert quote.bid == 365.10
    assert quote.ask == 365.15
    assert quote.bid_size == 25
    assert quote.ask_size == 30

def test_normalize_quote_negative_price_raises():
    utc_dt = datetime(2023, 6, 15, 13, 30, tzinfo=timezone.utc)
    mock = MockAlpacaQuote("QQQ", utc_dt, -1.0, 365.15, 25, 30)
    with pytest.raises(AlpacaDataError, match="Prices must be > 0"):
        normalize_alpaca_quote(mock)

def test_normalize_quote_inverted_spread_accepted():
    # Normalizer normalizes values, validation gate catches inverted spread
    utc_dt = datetime(2023, 6, 15, 13, 30, tzinfo=timezone.utc)
    mock = MockAlpacaQuote("QQQ", utc_dt, 366.0, 365.0, 25, 30)
    quote = normalize_alpaca_quote(mock)
    assert quote.bid == 366.0
    assert quote.ask == 365.0
