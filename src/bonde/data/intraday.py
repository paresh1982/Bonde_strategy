"""
Intraday 1-Minute Data & Candidate-Targeted Extraction (Sections 9 & 10)
Maintains regular session (09:30–16:00 ET) 1-minute unadjusted bars.
Enforces candidate-targeted extraction to optimize memory and local storage.
"""

from abc import ABC, abstractmethod
from dataclasses import dataclass
from datetime import date, datetime, time, timezone
from typing import Dict, List, Optional, Tuple
import zoneinfo

from .models import Bar, NY_TZ

UTC_TZ = timezone.utc


@dataclass(frozen=True)
class IntradayBarRecord:
    """Canonical 1-minute bar record stored internally."""
    security_id: str
    symbol: str
    timestamp_utc: datetime
    open: float
    high: float
    low: float
    close: float
    volume: float

    def to_engine_bar(self) -> Bar:
        """Converts into Stage 0/0.2 Bar object localized to America/New_York."""
        ts_ny = self.timestamp_utc.astimezone(NY_TZ)
        return Bar(
            timestamp=ts_ny,
            symbol=self.symbol,
            open=self.open,
            high=self.high,
            low=self.low,
            close=self.close,
            volume=self.volume,
        )


class IntradayBarProvider(ABC):
    """Abstract interface for candidate-targeted 1-minute bar extraction."""

    @abstractmethod
    def get_intraday_bars(
        self,
        security_id: str,
        session_date: date,
        start_time: time = time(9, 30, 0),
        end_time: time = time(16, 0, 0),
    ) -> List[Bar]:
        """
        Extracts 1-minute bars for a specific candidate security on session_date.
        Must return bars chronologically sorted and localized to America/New_York.
        """
        pass

    @abstractmethod
    def has_intraday_data(self, security_id: str, session_date: date) -> bool:
        """Checks whether 1-minute intraday data is available for security on session_date."""
        pass


class InMemoryIntradayBarProvider(IntradayBarProvider):
    """
    In-memory reference provider for candidate-targeted 1-minute bars.
    """

    def __init__(self, bars: Optional[List[IntradayBarRecord]] = None):
        # Key: (security_id, session_date) -> List[IntradayBarRecord]
        self._bars_by_session: Dict[Tuple[str, date], List[IntradayBarRecord]] = {}
        if bars:
            for b in bars:
                self.add_bar(b)

    def add_bar(self, bar: IntradayBarRecord):
        session_d = bar.timestamp_utc.astimezone(NY_TZ).date()
        sec_list = self._bars_by_session.setdefault((bar.security_id, session_d), [])
        sec_list.append(bar)
        sec_list.sort(key=lambda b: b.timestamp_utc)

    def has_intraday_data(self, security_id: str, session_date: date) -> bool:
        return (security_id, session_date) in self._bars_by_session

    def get_intraday_bars(
        self,
        security_id: str,
        session_date: date,
        start_time: time = time(9, 30, 0),
        end_time: time = time(16, 0, 0),
    ) -> List[Bar]:
        raw_bars = self._bars_by_session.get((security_id, session_date), [])
        result = []
        for b in raw_bars:
            engine_bar = b.to_engine_bar()
            bar_t = engine_bar.timestamp.time()
            if start_time <= bar_t <= end_time:
                result.append(engine_bar)
        return result
