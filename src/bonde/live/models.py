"""
Normalized Live Market Data & Session Models (Stage 2)
Provides provider-agnostic representations of bars, quotes, events, and session states.
"""

from dataclasses import dataclass, field
from datetime import date, datetime
from enum import Enum
from typing import Any, Dict, Optional
import zoneinfo

from ..data.models import Bar, NY_TZ


class DataQualityStatus(str, Enum):
    VALID = "VALID"
    STALE = "STALE"
    OUT_OF_BOUNDS = "OUT_OF_BOUNDS"
    MONOTONIC_VIOLATION = "MONOTONIC_VIOLATION"
    DUPLICATE = "DUPLICATE"
    GAP = "GAP"
    MALFORMED = "MALFORMED"
    UNKNOWN_SECURITY = "UNKNOWN_SECURITY"
    SESSION_VIOLATION = "SESSION_VIOLATION"


class MarketEventType(str, Enum):
    BAR = "BAR"
    QUOTE = "QUOTE"
    CATALYST = "CATALYST"
    SESSION_STATE_CHANGE = "SESSION_STATE_CHANGE"
    ERROR = "ERROR"


@dataclass
class LiveBar:
    """Normalized 1-minute OHLCV Bar for live/paper streaming."""
    timestamp: datetime
    symbol: str
    security_id: str
    open: float
    high: float
    low: float
    close: float
    volume: float
    quality_status: DataQualityStatus = DataQualityStatus.VALID

    def __post_init__(self):
        if self.timestamp.tzinfo is None:
            self.timestamp = self.timestamp.replace(tzinfo=NY_TZ)
        elif self.timestamp.tzinfo != NY_TZ:
            self.timestamp = self.timestamp.astimezone(NY_TZ)

    def to_engine_bar(self) -> Bar:
        """Converts to internal Stage 0/1 Bar format consumed by execution engine."""
        return Bar(
            timestamp=self.timestamp,
            symbol=self.symbol,
            open=self.open,
            high=self.high,
            low=self.low,
            close=self.close,
            volume=self.volume,
        )

    @classmethod
    def from_engine_bar(cls, bar: Bar, security_id: Optional[str] = None) -> "LiveBar":
        return cls(
            timestamp=bar.timestamp,
            symbol=bar.symbol,
            security_id=security_id or f"SEC_{bar.symbol}",
            open=bar.open,
            high=bar.high,
            low=bar.low,
            close=bar.close,
            volume=bar.volume,
        )


@dataclass
class Quote:
    """Normalized top-of-book market quote."""
    timestamp: datetime
    symbol: str
    security_id: str
    bid: float
    ask: float
    bid_size: float = 100.0
    ask_size: float = 100.0

    def __post_init__(self):
        if self.timestamp.tzinfo is None:
            self.timestamp = self.timestamp.replace(tzinfo=NY_TZ)
        elif self.timestamp.tzinfo != NY_TZ:
            self.timestamp = self.timestamp.astimezone(NY_TZ)

    @property
    def mid(self) -> float:
        return round((self.bid + self.ask) / 2.0, 4)

    @property
    def spread(self) -> float:
        return round(self.ask - self.bid, 4)


@dataclass
class MarketEvent:
    """Normalized event dispatched across the live pipeline."""
    timestamp: datetime
    event_type: MarketEventType
    payload: Any


@dataclass
class TradingSession:
    """Representation of an active or planned trading session."""
    session_date: date
    open_time: datetime
    close_time: datetime
    is_early_close: bool = False
    state: str = "PRE_MARKET"


@dataclass
class RejectedEvent:
    """Fail-closed audit log for rejected data ticks or invalid events."""
    timestamp: datetime
    security_id: str
    symbol: str
    reason: str
    source: str
    severity: str = "ERROR"
    payload: Dict[str, Any] = field(default_factory=dict)
