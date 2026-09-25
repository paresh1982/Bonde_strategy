"""
Alpaca WebSocket Connection Manager (Stage 3)
Manages WebSocket lifecycle with reconnect, backoff, and health monitoring.

NOTE: alpaca-py is imported lazily inside methods to allow testing without the SDK.
"""

import logging
import random
import threading
import time
from datetime import datetime, timezone
from typing import Callable, List, Optional

from .config import AlpacaConfig
from .errors import AlpacaConnectionError, AlpacaAuthError

logger = logging.getLogger(__name__)


class AlpacaConnectionManager:
    """Manages Alpaca WebSocket lifecycle with deterministic reconnect behavior.

    Provides:
    - Exponential backoff reconnection (with jitter)
    - Heartbeat / staleness monitoring
    - Thread-safe state tracking
    - Graceful shutdown

    alpaca-py is imported lazily so unit tests can run without the SDK installed.
    """

    def __init__(
        self,
        config: AlpacaConfig,
        on_bar_callback: Optional[Callable] = None,
        on_quote_callback: Optional[Callable] = None,
        on_error_callback: Optional[Callable] = None,
    ):
        self._config = config
        self._on_bar = on_bar_callback or (lambda b: None)
        self._on_quote = on_quote_callback or (lambda q: None)
        self._on_error = on_error_callback or (lambda e: None)
        self._stream = None
        self._stream_thread: Optional[threading.Thread] = None
        self._is_connected = False
        self._reconnect_count = 0
        self._last_data_time: Optional[datetime] = None
        self._subscribed_symbols: List[str] = list(config.symbols or [])
        self._shutdown_requested = False
        self._lock = threading.Lock()
        self.staleness_timeout_seconds: float = config.staleness_halt_seconds
        self.max_reconnect_attempts: int = config.max_reconnect_attempts

    def _get_backoff_delay(self, attempt: int) -> float:
        """Calculate exponential backoff delay capped at reconnect_max_delay_seconds."""
        base = self._config.reconnect_base_delay_seconds * (2 ** attempt)
        return min(base, self._config.reconnect_max_delay_seconds)

    def _handle_successful_connect(self) -> None:
        """Update internal state upon successful connection."""
        with self._lock:
            self._is_connected = True
            self._reconnect_count = 0

    def connect(self, symbols: Optional[List[str]] = None) -> None:
        """Initialize WebSocket connection and subscribe to symbols.

        Args:
            symbols: List of ticker symbols to subscribe (max config.max_symbols).

        Raises:
            ValueError: If symbol count exceeds limit.
            AlpacaConnectionError: If connection fails.
            AlpacaAuthError: If authentication fails.
        """
        target_symbols = list(symbols if symbols is not None else (self._config.symbols or []))
        if len(target_symbols) > self._config.max_symbols:
            raise ValueError(
                f"Symbol count {len(target_symbols)} exceeds limit {self._config.max_symbols}"
            )

        try:
            from alpaca.data.live import StockDataStream
            from alpaca.data.enums import DataFeed
        except ImportError as e:
            raise AlpacaConnectionError(
                "alpaca-py SDK not installed. Install with: pip install alpaca-py"
            ) from e

        feed = DataFeed.IEX if self._config.feed == "iex" else DataFeed.SIP
        self._stream = StockDataStream(
            api_key=self._config.api_key,
            secret_key=self._config.secret_key,
            feed=feed,
            raw_data=False,
        )

        async def _bar_handler(bar):
            try:
                self._on_bar(bar)
                self.update_last_data_time()
            except Exception as e:
                logger.error(f"Error in bar handler: {e}")
                self._on_error(e)

        async def _quote_handler(quote):
            try:
                self._on_quote(quote)
                self.update_last_data_time()
            except Exception as e:
                logger.error(f"Error in quote handler: {e}")
                self._on_error(e)

        if target_symbols:
            self._stream.subscribe_bars(_bar_handler, *target_symbols)
            self._stream.subscribe_quotes(_quote_handler, *target_symbols)
        self._subscribed_symbols = target_symbols

        self._shutdown_requested = False
        self._stream_thread = threading.Thread(
            target=self._run_stream, daemon=True, name="alpaca-ws"
        )
        self._stream_thread.start()

        self._handle_successful_connect()

        logger.info(
            f"Alpaca {self._config.feed.upper()} WebSocket connected. "
            f"Subscribed to {len(target_symbols)} symbols."
        )

    def _run_stream(self):
        """Background thread target for WebSocket event loop."""
        try:
            self._stream.run()
        except Exception as e:
            with self._lock:
                self._is_connected = False
            if not self._shutdown_requested:
                logger.error(f"Alpaca WebSocket stream error: {e}")
                self._on_error(AlpacaConnectionError(str(e)))

    def disconnect(self) -> None:
        """Graceful WebSocket shutdown."""
        self._shutdown_requested = True
        if self._stream is not None:
            try:
                self._stream.stop()
            except Exception as e:
                logger.warning(f"Error stopping stream: {e}")
        with self._lock:
            self._is_connected = False
        if self._stream_thread and self._stream_thread.is_alive():
            self._stream_thread.join(timeout=5.0)
        logger.info("Alpaca WebSocket disconnected.")

    def reconnect(self) -> bool:
        """Attempt reconnection with exponential backoff.

        Returns:
            True if reconnection succeeded, False if max attempts exhausted.
        """
        with self._lock:
            if self._reconnect_count >= self.max_reconnect_attempts:
                logger.error(
                    f"Max reconnect attempts ({self.max_reconnect_attempts}) "
                    f"exhausted. Giving up."
                )
                return False
            attempt = self._reconnect_count
            self._reconnect_count += 1

        delay = self._get_backoff_delay(attempt)
        jitter = random.uniform(0, delay * 0.1)
        total_delay = delay + jitter

        logger.info(
            f"Reconnect attempt {attempt + 1}/{self.max_reconnect_attempts} "
            f"in {total_delay:.1f}s"
        )
        time.sleep(total_delay)

        try:
            if self._stream is not None:
                try:
                    self._stream.stop()
                except Exception:
                    pass

            self.connect(self._subscribed_symbols)
            self._handle_successful_connect()
            logger.info("Reconnection successful.")
            return True
        except Exception as e:
            logger.error(f"Reconnect attempt {attempt + 1} failed: {e}")
            return False

    @property
    def is_connected(self) -> bool:
        with self._lock:
            return self._is_connected

    @is_connected.setter
    def is_connected(self, value: bool) -> None:
        with self._lock:
            self._is_connected = value

    @property
    def last_data_time(self) -> Optional[datetime]:
        with self._lock:
            return self._last_data_time

    @last_data_time.setter
    def last_data_time(self, val: Optional[datetime]) -> None:
        with self._lock:
            self._last_data_time = val

    @property
    def seconds_since_last_data(self) -> Optional[float]:
        """Seconds since last data received. None if no data ever received."""
        with self._lock:
            if self._last_data_time is None:
                return None
            now_utc = datetime.now(timezone.utc)
            # handle tz-aware or naive
            if self._last_data_time.tzinfo is None:
                now_utc = datetime.now()
            return (now_utc - self._last_data_time).total_seconds()

    def update_last_data_time(self) -> None:
        """Called when valid data is received."""
        with self._lock:
            self._last_data_time = datetime.now(timezone.utc)

    @property
    def is_stale(self) -> bool:
        """True if no data received for > staleness timeout."""
        secs = self.seconds_since_last_data
        if secs is None:
            return False
        return secs > self.staleness_timeout_seconds

    @property
    def is_stale_warning(self) -> bool:
        """True if no data received for > staleness_warning_seconds."""
        secs = self.seconds_since_last_data
        if secs is None:
            return False
        return secs > self._config.staleness_warning_seconds

    @property
    def reconnect_count(self) -> int:
        with self._lock:
            return self._reconnect_count

    @property
    def reconnect_attempts(self) -> int:
        with self._lock:
            return self._reconnect_count

    @reconnect_attempts.setter
    def reconnect_attempts(self, val: int) -> None:
        with self._lock:
            self._reconnect_count = val

    @property
    def subscribed_symbols(self) -> List[str]:
        return list(self._subscribed_symbols)
