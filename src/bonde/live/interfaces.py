"""
Abstract Provider Interfaces for Live / Paper Data (Stage 2)
Decouples vendor APIs (Polygon, Alpaca, IBKR, FirstRate) from the strategy engine.
"""

from abc import ABC, abstractmethod
from datetime import date, datetime
from typing import Dict, List, Optional, Tuple

from ..data.catalysts import EarningsEvent, SECFilingEvent
from ..data.dual_price import DailyBar
from ..execution.orders import Order
from .models import LiveBar, Quote, TradingSession


class MarketDataProvider(ABC):
    """Unified interface for live and streaming market data feeds."""

    @abstractmethod
    def get_latest_bar(self, security_id: str) -> Optional[LiveBar]:
        """Retrieves the latest 1-minute bar for a security."""
        pass

    @abstractmethod
    def get_intraday_bars(
        self, security_id: str, session_date: date, up_to_time: Optional[datetime] = None
    ) -> List[LiveBar]:
        """Retrieves regular session 1-minute bars up to a point in time."""
        pass


class QuoteProvider(ABC):
    """Interface for streaming top-of-book bid/ask quotes."""

    @abstractmethod
    def get_latest_quote(self, security_id: str) -> Optional[Quote]:
        """Retrieves current top-of-book quote."""
        pass


class CatalystProvider(ABC):
    """Interface for real-time catalyst announcements (Track A earnings & Track B 8-K filings)."""

    @abstractmethod
    def get_premarket_earnings(self, session_date: date) -> List[EarningsEvent]:
        """Retrieves earnings announcements verified available before 09:30 ET."""
        pass

    @abstractmethod
    def get_filings_before(self, security_id: str, as_of: datetime) -> List[SECFilingEvent]:
        """Retrieves SEC 8-K filings accepted prior to as_of datetime."""
        pass


class CalendarProvider(ABC):
    """Interface for querying market trading schedules."""

    @abstractmethod
    def get_session(self, session_date: date) -> Optional[TradingSession]:
        """Returns session details for date, or None if holiday/weekend."""
        pass

    @abstractmethod
    def is_trading_day(self, session_date: date) -> bool:
        pass


class LiveExecutionBridge(ABC):
    """Interface for paper execution and order lifecycle management."""

    @abstractmethod
    def submit_order(self, order: Order) -> str:
        """Submits an order and returns unique order_id."""
        pass

    @abstractmethod
    def cancel_order(self, order_id: str, reason: str) -> bool:
        """Cancels a pending order."""
        pass

    @abstractmethod
    def get_order(self, order_id: str) -> Optional[Order]:
        """Retrieves order by order_id."""
        pass

    @abstractmethod
    def get_open_orders(self) -> List[Order]:
        """Retrieves all active pending orders."""
        pass
