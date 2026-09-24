"""
Catalyst Data Ingestion & Interfaces (Sections 7 & 8)
Implements Track A (Historical Earnings Timestamps) and Track B (SEC EDGAR 8-K Filings).
Enforces strict point-in-time availability rules.
"""

from abc import ABC, abstractmethod
from dataclasses import dataclass
from datetime import date, datetime, time, timedelta
from typing import Dict, List, Optional
import zoneinfo

NY_TZ = zoneinfo.ZoneInfo("America/New_York")


@dataclass(frozen=True)
class EarningsEvent:
    """Historical Track A Earnings Event."""
    security_id: str
    event_timestamp: datetime
    event_date: date
    timing: str                 # "BMO" (Before Market Open), "AMC" (After Market Close), "UNKNOWN"
    source: str
    availability_timestamp: datetime
    event_type: str = "EARNINGS"

    def __post_init__(self):
        # Normalize timezone to America/New_York
        if self.availability_timestamp.tzinfo is None:
            object.__setattr__(self, 'availability_timestamp', self.availability_timestamp.replace(tzinfo=NY_TZ))
        elif self.availability_timestamp.tzinfo != NY_TZ:
            object.__setattr__(self, 'availability_timestamp', self.availability_timestamp.astimezone(NY_TZ))

        if self.event_timestamp.tzinfo is None:
            object.__setattr__(self, 'event_timestamp', self.event_timestamp.replace(tzinfo=NY_TZ))
        elif self.event_timestamp.tzinfo != NY_TZ:
            object.__setattr__(self, 'event_timestamp', self.event_timestamp.astimezone(NY_TZ))

    def is_available_for_premarket(self, session_date: date) -> bool:
        """
        Determines if earnings announcement was verified available strictly before
        09:30:00 ET on session_date (handles BMO on session_date and AMC on prior session).
        """
        cutoff = datetime.combine(session_date, time(9, 29, 59), tzinfo=NY_TZ)
        if self.event_date == session_date:
            return self.availability_timestamp <= cutoff
        if self.event_date < session_date:
            days_diff = (session_date - self.event_date).days
            if days_diff <= 4 and self.availability_timestamp <= cutoff:
                return True
        return False


@dataclass(frozen=True)
class SECFilingEvent:
    """Historical Track B SEC 8-K Filing Event."""
    security_id: str
    cik: str
    accession_number: str
    filing_type: str            # e.g., "8-K"
    filing_timestamp: datetime
    acceptance_datetime: datetime
    form: str                   # "8-K"
    items: List[str]            # e.g. ["Item 1.01", "Item 8.01"]
    source_url: str
    availability_timestamp: datetime

    def __post_init__(self):
        if self.availability_timestamp.tzinfo is None:
            object.__setattr__(self, 'availability_timestamp', self.availability_timestamp.replace(tzinfo=NY_TZ))
        elif self.availability_timestamp.tzinfo != NY_TZ:
            object.__setattr__(self, 'availability_timestamp', self.availability_timestamp.astimezone(NY_TZ))

    def is_available_before(self, as_of: datetime) -> bool:
        """Determines if the SEC filing was publicly accepted before as_of datetime."""
        target_tz = as_of.tzinfo or NY_TZ
        target_dt = as_of if as_of.tzinfo else as_of.replace(tzinfo=NY_TZ)
        return self.availability_timestamp.astimezone(target_tz) <= target_dt


class EarningsProvider(ABC):
    """Abstract interface for Point-in-Time Earnings Events (Track A)."""

    @abstractmethod
    def get_earnings_event(
        self,
        security_id: str,
        session_date: date,
    ) -> Optional[EarningsEvent]:
        """Retrieves earnings event for security on session_date if verified available."""
        pass


class FilingProvider(ABC):
    """Abstract interface for Point-in-Time SEC 8-K Filings (Track B)."""

    @abstractmethod
    def get_filings_before(
        self,
        security_id: str,
        as_of: datetime,
    ) -> List[SECFilingEvent]:
        """Retrieves SEC 8-K filings publicly accepted strictly before as_of."""
        pass


class InMemoryEarningsProvider(EarningsProvider):
    """In-memory store for Track A Earnings Events."""

    def __init__(self, events: Optional[List[EarningsEvent]] = None):
        self._events_by_key: Dict[tuple, EarningsEvent] = {}
        if events:
            for ev in events:
                self.add_event(ev)

    def add_event(self, ev: EarningsEvent):
        self._events_by_key[(ev.security_id, ev.event_date)] = ev

    def get_earnings_event(
        self,
        security_id: str,
        session_date: date,
    ) -> Optional[EarningsEvent]:
        # 1. Direct match for session_date (e.g. BMO release on session_date)
        ev = self._events_by_key.get((security_id, session_date))
        if ev and ev.is_available_for_premarket(session_date):
            return ev
        # 2. Check prior dates (up to 4 days back for AMC releases)
        for offset in range(1, 5):
            prior_date = session_date - timedelta(days=offset)
            ev_prior = self._events_by_key.get((security_id, prior_date))
            if ev_prior and ev_prior.is_available_for_premarket(session_date):
                return ev_prior
        return None


class InMemoryFilingProvider(FilingProvider):
    """In-memory store for Track B SEC 8-K Filings."""

    def __init__(self, filings: Optional[List[SECFilingEvent]] = None):
        self._filings: Dict[str, List[SECFilingEvent]] = {}
        if filings:
            for f in filings:
                self.add_filing(f)

    def add_filing(self, filing: SECFilingEvent):
        sec_list = self._filings.setdefault(filing.security_id, [])
        sec_list.append(filing)
        sec_list.sort(key=lambda f: f.availability_timestamp)

    def get_filings_before(
        self,
        security_id: str,
        as_of: datetime,
    ) -> List[SECFilingEvent]:
        sec_list = self._filings.get(security_id, [])
        return [f for f in sec_list if f.is_available_before(as_of)]
