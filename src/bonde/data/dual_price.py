"""
Dual-Price Daily Data Architecture (Section 3)
Strictly isolates Unadjusted Daily Data (Execution, Stops, Orders) from
Split-Adjusted Daily Data (10 EMA, 65-Day High, ADV50, Analytical Indicators).
"""

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from datetime import date, datetime, timezone
from typing import Dict, List, Optional, Tuple


@dataclass(frozen=True)
class DailyBar:
    """
    Canonical Dual-Price Daily Bar.
    Enforces strict distinction between raw trade dollars and split-adjusted analytical series.
    """
    security_id: str
    session_date: date
    # Unadjusted Prices (Strictly for Execution, Stops, Limits, Fills)
    open: float
    high: float
    low: float
    close: float
    volume: float
    # Split-Adjusted Prices (Strictly for Technical Indicators, 10 EMA, 65D High, ADV50)
    adjusted_open: float
    adjusted_high: float
    adjusted_low: float
    adjusted_close: float
    adjusted_volume: float
    # Provenance & Metadata
    source: str = "SYNTHETIC"
    ingested_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))
    strict_validation: bool = False

    def __post_init__(self):
        if not self.strict_validation:
            return
        # Basic logical invariants on unadjusted
        if self.low > self.high:
            raise ValueError(f"Daily low ({self.low}) cannot exceed high ({self.high}) for {self.security_id}")
        if self.open < self.low or self.open > self.high:
            raise ValueError(f"Daily open ({self.open}) outside [low, high] for {self.security_id}")
        if self.close < self.low or self.close > self.high:
            raise ValueError(f"Daily close ({self.close}) outside [low, high] for {self.security_id}")
        if self.volume < 0:
            raise ValueError(f"Daily volume ({self.volume}) cannot be negative")

        # Invariants on split-adjusted
        if self.adjusted_low > self.adjusted_high:
            raise ValueError(f"Adjusted low ({self.adjusted_low}) cannot exceed high ({self.adjusted_high})")
        if self.adjusted_open < self.adjusted_low or self.adjusted_open > self.adjusted_high:
            raise ValueError(f"Adjusted open ({self.adjusted_open}) outside [low, high]")
        if self.adjusted_close < self.adjusted_low or self.adjusted_close > self.adjusted_high:
            raise ValueError(f"Adjusted close ({self.adjusted_close}) outside [low, high]")
        if self.adjusted_volume < 0:
            raise ValueError(f"Adjusted volume ({self.adjusted_volume}) cannot be negative")

    # Explicit accessors preventing accidental confusion
    @property
    def execution_close(self) -> float:
        """Unadjusted close for stop-loss and order fill evaluation."""
        return self.close

    @property
    def execution_high(self) -> float:
        """Unadjusted high for breakout trigger check."""
        return self.high

    @property
    def execution_low(self) -> float:
        """Unadjusted low for stop price check."""
        return self.low

    @property
    def analytical_close(self) -> float:
        """Split-adjusted close for moving average calculation."""
        return self.adjusted_close

    @property
    def analytical_high(self) -> float:
        """Split-adjusted high for 65-day high resistance level."""
        return self.adjusted_high


class DailyBarProvider(ABC):
    """Abstract interface for Point-in-Time Daily Bar retrieval."""

    @abstractmethod
    def get_bar(self, security_id: str, session_date: date) -> Optional[DailyBar]:
        """Retrieves single daily bar for security on exact session date."""
        pass

    @abstractmethod
    def get_bars_range(
        self,
        security_id: str,
        start_date: date,
        end_date: date,
    ) -> List[DailyBar]:
        """
        Retrieves daily bars for security over [start_date, end_date] inclusive.
        Must return bars strictly sorted chronologically by session_date.
        """
        pass

    @abstractmethod
    def get_prior_completed_bars(
        self,
        security_id: str,
        as_of_date: date,
        count: int,
    ) -> List[DailyBar]:
        """
        Retrieves up to `count` daily bars strictly PRIOR to as_of_date (i.e. session_date < as_of_date).
        Strictly prevents lookahead to as_of_date.
        """
        pass


class InMemoryDailyBarProvider(DailyBarProvider):
    """
    In-memory reference provider storing dual-price daily bars.
    Guarantees strict chronological ordering and point-in-time slice boundaries.
    """

    def __init__(self, bars: Optional[List[DailyBar]] = None):
        # Key: (security_id, session_date) -> DailyBar
        self._bars_by_key: Dict[Tuple[str, date], DailyBar] = {}
        # Key: security_id -> List[DailyBar] (sorted)
        self._bars_by_sec: Dict[str, List[DailyBar]] = {}

        if bars:
            for b in bars:
                self.add_bar(b)

    def add_bar(self, bar: DailyBar):
        self._bars_by_key[(bar.security_id, bar.session_date)] = bar
        sec_list = self._bars_by_sec.setdefault(bar.security_id, [])
        # Insert maintaining sort by session_date
        sec_list.append(bar)
        sec_list.sort(key=lambda b: b.session_date)

    def get_bar(self, security_id: str, session_date: date) -> Optional[DailyBar]:
        return self._bars_by_key.get((security_id, session_date))

    def get_bars_range(
        self,
        security_id: str,
        start_date: date,
        end_date: date,
    ) -> List[DailyBar]:
        sec_list = self._bars_by_sec.get(security_id, [])
        return [b for b in sec_list if start_date <= b.session_date <= end_date]

    def get_prior_completed_bars(
        self,
        security_id: str,
        as_of_date: date,
        count: int,
    ) -> List[DailyBar]:
        """Strictly returns completed sessions prior to as_of_date (session_date < as_of_date)."""
        sec_list = self._bars_by_sec.get(security_id, [])
        prior = [b for b in sec_list if b.session_date < as_of_date]
        if not prior:
            return []
        return prior[-count:]
