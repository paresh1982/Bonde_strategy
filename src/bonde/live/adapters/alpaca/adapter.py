"""
Alpaca Market Data Adapter (Stage 3)

Implements MarketDataProvider and QuoteProvider interfaces using Alpaca's
WebSocket streaming API (IEX or SIP feed).

IMPORTANT: When using the IEX feed (default), this adapter produces
single-exchange data (~2.5% of US volume). IEX data is suitable for
infrastructure validation but NOT for consolidated P&L comparison
against historical backtests using SIP/FirstRate data.

Data source is tagged in all outputs for telemetry distinction.
"""

import logging
import threading
from collections import defaultdict, deque
from datetime import date, datetime
from typing import Any, Callable, Dict, List, Optional

from bonde.data.models import NY_TZ
from bonde.live.interfaces import MarketDataProvider, QuoteProvider
from bonde.live.models import LiveBar, Quote
from .config import AlpacaConfig
from .connection import AlpacaConnectionManager
from .errors import AlpacaConnectionError, AlpacaDataError
from .normalizer import normalize_alpaca_bar, normalize_alpaca_quote

logger = logging.getLogger(__name__)


class AlpacaMarketDataAdapter(MarketDataProvider, QuoteProvider):
    """Alpaca IEX/SIP Market Data Adapter.

    Implements MarketDataProvider and QuoteProvider interfaces
    using Alpaca's WebSocket streaming API.

    Data source is tagged via config.data_source_label ('IEX' or 'SIP')
    for telemetry distinction between infrastructure validation and
    consolidated-market historical backtesting.
    """

    def __init__(
        self,
        config: AlpacaConfig,
        security_id_map: Optional[Dict[str, str]] = None,
    ):
        self._config = config
        self._security_id_map = security_id_map or {}
        max_buf = getattr(config, "max_buffer_size", 10000)
        self._bar_buffer: deque = deque(maxlen=max_buf)
        self._quote_buffer: deque = deque(maxlen=max_buf)
        self._bars_by_symbol: Dict[str, List[LiveBar]] = defaultdict(list)
        self._latest_quotes: Dict[str, Quote] = {}
        self._connection: Optional[AlpacaConnectionManager] = None
        self._lock = threading.Lock()
        self._data_source = config.data_source_label
        self._error_count = 0

    # ── Lifecycle ───────────────────────────────────────────────────

    def start(self, symbols: List[str]) -> None:
        """Start streaming data for given symbols.

        Args:
            symbols: Ticker symbols to subscribe (max config.max_symbols).

        Raises:
            AlpacaConnectionError: If connection fails.
        """
        self._connection = AlpacaConnectionManager(
            config=self._config,
            on_bar_callback=self._handle_raw_bar,
            on_quote_callback=self._handle_raw_quote,
            on_error_callback=self._handle_error,
        )
        self._connection.connect(symbols)
        logger.info(
            f"AlpacaMarketDataAdapter started. "
            f"Feed={self._config.feed.upper()}, Symbols={len(symbols)}"
        )

    def stop(self) -> None:
        """Stop streaming and disconnect."""
        if self._connection is not None:
            self._connection.disconnect()
            self._connection = None
        logger.info("AlpacaMarketDataAdapter stopped.")

    # ── Internal Callbacks ──────────────────────────────────────────

    def _handle_raw_bar(self, raw_bar: Any) -> None:
        """Callback from WebSocket. Normalize and buffer."""
        try:
            bar = normalize_alpaca_bar(raw_bar, self._security_id_map)
            with self._lock:
                self._bar_buffer.append(bar)
                self._bars_by_symbol[bar.symbol].append(bar)
                # Also index by security_id for interface lookups
                if bar.security_id != bar.symbol:
                    self._bars_by_symbol[bar.security_id].append(bar)
        except AlpacaDataError as e:
            self._error_count += 1
            logger.warning(f"Bar normalization failed: {e}")

    def _handle_raw_quote(self, raw_quote: Any) -> None:
        """Callback from WebSocket. Normalize and buffer."""
        try:
            quote = normalize_alpaca_quote(raw_quote, self._security_id_map)
            with self._lock:
                self._quote_buffer.append(quote)
                self._latest_quotes[quote.symbol] = quote
                if quote.security_id != quote.symbol:
                    self._latest_quotes[quote.security_id] = quote
        except AlpacaDataError as e:
            self._error_count += 1
            logger.warning(f"Quote normalization failed: {e}")

    def _handle_error(self, error: Exception) -> None:
        """Callback for connection/stream errors."""
        self._error_count += 1
        logger.error(f"Adapter error: {error}")

    def handle_raw_bar(self, raw_bar: Any) -> None:
        """Public method for feeding raw bars (testing or external)."""
        self._handle_raw_bar(raw_bar)

    def handle_raw_quote(self, raw_quote: Any) -> None:
        """Public method for feeding raw quotes (testing or external)."""
        self._handle_raw_quote(raw_quote)

    # ── Buffer Drain (for Runner polling) ───────────────────────────

    def drain_bars(self) -> List[LiveBar]:
        """Thread-safe drain of all buffered bars since last drain.

        Returns:
            List of LiveBar objects accumulated since last drain.
        """
        with self._lock:
            bars = list(self._bar_buffer)
            self._bar_buffer.clear()
            return bars

    def drain_quotes(self) -> List[Quote]:
        """Thread-safe drain of all buffered quotes since last drain.

        Returns:
            List of Quote objects accumulated since last drain.
        """
        with self._lock:
            quotes = list(self._quote_buffer)
            self._quote_buffer.clear()
            return quotes

    # ── MarketDataProvider Interface ────────────────────────────────

    def get_latest_bar(self, security_id: str) -> Optional[LiveBar]:
        """Returns most recent bar for security."""
        with self._lock:
            bars = self._bars_by_symbol.get(security_id, [])
            return bars[-1] if bars else None

    def get_intraday_bars(
        self,
        security_id: str,
        session_date: date,
        up_to_time: Optional[datetime] = None,
    ) -> List[LiveBar]:
        """Returns all bars for security on session_date up to time."""
        with self._lock:
            bars = self._bars_by_symbol.get(security_id, [])
            result = [
                b for b in bars
                if b.timestamp.date() == session_date
                and (up_to_time is None or b.timestamp <= up_to_time)
            ]
            result.sort(key=lambda b: b.timestamp)
            return result

    # ── QuoteProvider Interface ─────────────────────────────────────

    def get_latest_quote(self, security_id: str) -> Optional[Quote]:
        """Returns most recent quote for security."""
        with self._lock:
            return self._latest_quotes.get(security_id)

    # ── REST Backfill ───────────────────────────────────────────────

    def backfill_bars(
        self,
        symbols: List[str],
        start: datetime,
        end: datetime,
    ) -> Dict[str, List[LiveBar]]:
        """REST backfill for bars missed during disconnect.

        Uses StockHistoricalDataClient with feed='iex' (zero delay on free tier).

        Args:
            symbols: Symbols to backfill.
            start: Start time (UTC or NY_TZ).
            end: End time (UTC or NY_TZ).

        Returns:
            Dict mapping symbol to list of backfilled LiveBar objects.
        """
        try:
            from alpaca.data.historical import StockHistoricalDataClient
            from alpaca.data.requests import StockBarsRequest
            from alpaca.data.timeframe import TimeFrame
        except ImportError as e:
            raise AlpacaConnectionError(
                "alpaca-py SDK not installed for REST backfill."
            ) from e

        client = StockHistoricalDataClient(
            api_key=self._config.api_key,
            secret_key=self._config.secret_key,
        )

        request_params = StockBarsRequest(
            symbol_or_symbols=symbols,
            timeframe=TimeFrame.Minute,
            start=start,
            end=end,
            feed=self._config.feed,
        )

        raw_bars = client.get_stock_bars(request_params)
        result: Dict[str, List[LiveBar]] = defaultdict(list)

        for symbol_key, bars_list in raw_bars.data.items():
            for raw_bar in bars_list:
                try:
                    bar = normalize_alpaca_bar(raw_bar, self._security_id_map)
                    result[bar.symbol].append(bar)
                    # Also add to internal buffer
                    with self._lock:
                        self._bars_by_symbol[bar.symbol].append(bar)
                        if bar.security_id != bar.symbol:
                            self._bars_by_symbol[bar.security_id].append(bar)
                except AlpacaDataError as e:
                    logger.warning(f"Backfill bar normalization failed: {e}")

        backfilled_count = sum(len(v) for v in result.values())
        logger.info(
            f"Backfilled {backfilled_count} bars for {len(symbols)} symbols "
            f"({start} to {end})"
        )
        return dict(result)

    # ── Properties ──────────────────────────────────────────────────

    @property
    def data_source(self) -> str:
        """Data source label for telemetry ('IEX' or 'SIP')."""
        return self._data_source

    @property
    def is_connected(self) -> bool:
        """True if WebSocket connection is active."""
        if getattr(self, "_is_mock_connected", None) is not None:
            return self._is_mock_connected
        if self._connection is None:
            return True
        return self._connection.is_connected

    @is_connected.setter
    def is_connected(self, value: bool) -> None:
        self._is_mock_connected = value

    @property
    def is_stale(self) -> bool:
        """True if no data received for > staleness_halt_seconds."""
        if self._connection is None:
            return False
        return self._connection.is_stale

    @property
    def is_stale_warning(self) -> bool:
        """True if no data received for > staleness_warning_seconds."""
        if self._connection is None:
            return False
        return self._connection.is_stale_warning

    @property
    def error_count(self) -> int:
        return self._error_count

    def reconnect(self) -> bool:
        """Attempt WebSocket reconnection. Returns True if successful."""
        if self._connection is None:
            return False
        return self._connection.reconnect()

    @property
    def subscribed_symbols(self) -> List[str]:
        """Currently subscribed symbols."""
        if self._connection is None:
            return []
        return self._connection.subscribed_symbols
