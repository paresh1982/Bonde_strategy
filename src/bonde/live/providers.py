"""
Synthetic Live Data Providers (Stage 2)
Provides in-memory streaming market data and catalyst events for testing and simulation.
"""

from datetime import date, datetime, time, timedelta
from typing import Dict, List, Optional
import zoneinfo

from ..data.catalysts import EarningsEvent, SECFilingEvent
from ..data.models import Bar, NY_TZ
from .interfaces import CatalystProvider, MarketDataProvider, QuoteProvider
from .models import LiveBar, Quote


class SyntheticMarketDataProvider(MarketDataProvider, QuoteProvider):
    """
    In-memory streaming market data provider that serves bars and quotes chronologically.
    """

    def __init__(self):
        self._bars_by_symbol: Dict[str, List[LiveBar]] = {}
        self._quotes_by_symbol: Dict[str, List[Quote]] = {}
        self._current_clock: Optional[datetime] = None

    def set_clock(self, clock: datetime):
        self._current_clock = clock

    def add_bar(self, bar: LiveBar):
        sec_id = bar.security_id or f"SEC_{bar.symbol}"
        self._bars_by_symbol.setdefault(sec_id, []).append(bar)
        self._bars_by_symbol.setdefault(bar.symbol, []).append(bar)

    def add_quote(self, quote: Quote):
        sec_id = quote.security_id or f"SEC_{quote.symbol}"
        self._quotes_by_symbol.setdefault(sec_id, []).append(quote)
        self._quotes_by_symbol.setdefault(quote.symbol, []).append(quote)

    def get_latest_bar(self, security_id: str) -> Optional[LiveBar]:
        bars = self._bars_by_symbol.get(security_id, [])
        if not bars:
            return None
        if self._current_clock is None:
            return bars[-1]
        eligible = [b for b in bars if b.timestamp <= self._current_clock]
        return eligible[-1] if eligible else None

    def get_intraday_bars(
        self, security_id: str, session_date: date, up_to_time: Optional[datetime] = None
    ) -> List[LiveBar]:
        bars = self._bars_by_symbol.get(security_id, [])
        cutoff = up_to_time or self._current_clock
        res = [
            b for b in bars
            if b.timestamp.date() == session_date
            and (cutoff is None or b.timestamp <= cutoff)
        ]
        res.sort(key=lambda b: b.timestamp)
        return res

    def get_latest_quote(self, security_id: str) -> Optional[Quote]:
        quotes = self._quotes_by_symbol.get(security_id, [])
        if not quotes:
            return None
        if self._current_clock is None:
            return quotes[-1]
        eligible = [q for q in quotes if q.timestamp <= self._current_clock]
        return eligible[-1] if eligible else None


class SyntheticCatalystProvider(CatalystProvider):
    """
    In-memory provider for synthetic Track A (Earnings) and Track B (8-K filings) events.
    """

    def __init__(self, earnings: Optional[List[EarningsEvent]] = None, filings: Optional[List[SECFilingEvent]] = None):
        self._earnings = earnings or []
        self._filings = filings or []

    def add_earnings_event(self, ev: EarningsEvent):
        self._earnings.append(ev)

    def add_filing(self, filing: SECFilingEvent):
        self._filings.append(filing)

    def get_premarket_earnings(self, session_date: date) -> List[EarningsEvent]:
        """Returns earnings verified available strictly before 09:30:00 ET on session_date."""
        cutoff = datetime.combine(session_date, time(9, 29, 59), tzinfo=NY_TZ)
        res = []
        for ev in self._earnings:
            if ev.event_date == session_date and ev.availability_timestamp <= cutoff:
                res.append(ev)
            elif ev.event_date < session_date:
                days_diff = (session_date - ev.event_date).days
                if days_diff <= 4 and ev.availability_timestamp <= cutoff:
                    res.append(ev)
        return res

    def get_filings_before(self, security_id: str, as_of: datetime) -> List[SECFilingEvent]:
        target_tz = as_of.tzinfo or NY_TZ
        target_dt = as_of if as_of.tzinfo else as_of.replace(tzinfo=NY_TZ)
        res = [
            f for f in self._filings
            if (f.security_id == security_id or f.security_id == f"SEC_{security_id}")
            and f.availability_timestamp.astimezone(target_tz) <= target_dt
        ]
        res.sort(key=lambda f: f.availability_timestamp)
        return res
