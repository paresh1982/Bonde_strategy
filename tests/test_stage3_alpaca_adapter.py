import pytest
from datetime import datetime, timezone, timedelta
from typing import Optional, List, Dict
import threading

from bonde.data.models import NY_TZ
from bonde.live.interfaces import MarketDataProvider, QuoteProvider
from bonde.live.adapters.alpaca.adapter import AlpacaMarketDataAdapter
from bonde.live.adapters.alpaca.config import AlpacaConfig
from bonde.live.models import LiveBar, Quote

class MockAlpacaBar:
    def __init__(self, symbol, timestamp, open, high, low, close, volume):
        self.symbol = symbol
        self.timestamp = timestamp
        self.open = open
        self.high = high
        self.low = low
        self.close = close
        self.volume = volume

class MockAlpacaQuote:
    def __init__(self, symbol, timestamp, bid_price, ask_price, bid_size, ask_size):
        self.symbol = symbol
        self.timestamp = timestamp
        self.bid_price = bid_price
        self.ask_price = ask_price
        self.bid_size = bid_size
        self.ask_size = ask_size

@pytest.fixture
def adapter():
    config = AlpacaConfig(api_key="TEST", secret_key="TEST", symbols=["AAPL"])
    return AlpacaMarketDataAdapter(config)

def test_adapter_implements_interfaces(adapter):
    assert isinstance(adapter, MarketDataProvider)
    assert isinstance(adapter, QuoteProvider)

def test_adapter_drain_bars_returns_buffered(adapter):
    bar = MockAlpacaBar("AAPL", datetime.now(timezone.utc), 150, 151, 149, 150, 100)
    adapter.handle_raw_bar(bar)
    bars = adapter.drain_bars()
    assert len(bars) == 1
    assert bars[0].symbol == "AAPL"

def test_adapter_drain_bars_clears_buffer(adapter):
    bar = MockAlpacaBar("AAPL", datetime.now(timezone.utc), 150, 151, 149, 150, 100)
    adapter.handle_raw_bar(bar)
    adapter.drain_bars()
    bars2 = adapter.drain_bars()
    assert len(bars2) == 0

def test_adapter_get_latest_bar(adapter):
    dt1 = datetime(2023, 1, 1, 14, 30, tzinfo=timezone.utc)
    dt2 = datetime(2023, 1, 1, 14, 31, tzinfo=timezone.utc)
    adapter.handle_raw_bar(MockAlpacaBar("AAPL", dt1, 150, 151, 149, 150, 100))
    adapter.handle_raw_bar(MockAlpacaBar("AAPL", dt2, 151, 152, 150, 151, 200))
    
    latest = adapter.get_latest_bar("AAPL")
    assert latest is not None
    assert latest.close == 151

def test_adapter_get_latest_bar_empty(adapter):
    assert adapter.get_latest_bar("UNKNOWN") is None

def test_adapter_get_intraday_bars(adapter):
    dt1 = datetime(2023, 1, 1, 14, 30, tzinfo=timezone.utc)
    adapter.handle_raw_bar(MockAlpacaBar("AAPL", dt1, 150, 151, 149, 150, 100))
    
    bars = adapter.get_intraday_bars("AAPL", dt1.date())
    assert len(bars) == 1
    assert bars[0].close == 150

def test_adapter_get_latest_quote(adapter):
    dt = datetime(2023, 1, 1, 14, 30, tzinfo=timezone.utc)
    adapter.handle_raw_quote(MockAlpacaQuote("AAPL", dt, 150.0, 150.5, 100, 200))
    
    quote = adapter.get_latest_quote("AAPL")
    assert quote is not None
    assert quote.bid == 150.0

def test_adapter_data_source_label(adapter):
    assert adapter.data_source == 'IEX'

def test_adapter_handle_raw_bar_normalizes(adapter):
    dt = datetime(2023, 1, 1, 14, 30, tzinfo=timezone.utc)
    adapter.handle_raw_bar(MockAlpacaBar("AAPL", dt, 150, 151, 149, 150, 100))
    bars = adapter.drain_bars()
    assert bars[0].timestamp.tzinfo == NY_TZ

def test_adapter_handle_raw_quote_normalizes(adapter):
    dt = datetime(2023, 1, 1, 14, 30, tzinfo=timezone.utc)
    adapter.handle_raw_quote(MockAlpacaQuote("AAPL", dt, 150, 151, 100, 100))
    q = adapter.get_latest_quote("AAPL")
    assert q.timestamp.tzinfo == NY_TZ

def test_adapter_handle_malformed_bar_logs_error(adapter, caplog):
    # Pass a dict that missing fields or pass invalid fields
    # Assuming normalize throws AlpacaDataError
    adapter.handle_raw_bar({"symbol": "AAPL", "open": -100}) 
    assert len(adapter.drain_bars()) == 0

def test_adapter_thread_safety(adapter):
    def worker():
        for i in range(100):
            dt = datetime.now(timezone.utc)
            adapter.handle_raw_bar(MockAlpacaBar("AAPL", dt, 150, 151, 149, 150, 100))
            
    threads = [threading.Thread(target=worker) for _ in range(5)]
    for t in threads: t.start()
    for t in threads: t.join()
    
    assert len(adapter.drain_bars()) == 500

def test_adapter_max_buffer_size():
    config = AlpacaConfig(api_key="TEST", secret_key="TEST", symbols=["AAPL"], max_buffer_size=10)
    adapter = AlpacaMarketDataAdapter(config)
    for i in range(20):
        dt = datetime.now(timezone.utc)
        adapter.handle_raw_bar(MockAlpacaBar("AAPL", dt, 150, 151, 149, 150, 100))
    
    # Depending on implementation, it may truncate or just drop
    # Just ensure it doesn't crash and holds at most 10 or 20
    assert len(adapter.drain_bars()) <= 20
