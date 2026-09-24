"""
Core Data Models - Stage 0 Deterministic Engine
Preserves canonical America/New_York session timestamps and market abstractions.
"""

from abc import ABC, abstractmethod
from dataclasses import dataclass
from datetime import date, datetime
from typing import Dict, List, Optional, Tuple
import zoneinfo

NY_TZ = zoneinfo.ZoneInfo("America/New_York")


@dataclass(frozen=True)
class Bar:
    """Canonical 1-minute or aggregated bar."""
    timestamp: datetime
    symbol: str
    open: float
    high: float
    low: float
    close: float
    volume: float

    def __post_init__(self):
        # Validate timezone awareness or attach NY_TZ if naive
        if self.timestamp.tzinfo is None:
            object.__setattr__(self, 'timestamp', self.timestamp.replace(tzinfo=NY_TZ))
        elif self.timestamp.tzinfo != NY_TZ:
            object.__setattr__(self, 'timestamp', self.timestamp.astimezone(NY_TZ))

        # Basic integrity assertion
        if self.low > self.high:
            raise ValueError(f"Bar low ({self.low}) cannot exceed high ({self.high}) for {self.symbol}")
        if self.open < self.low or self.open > self.high:
            raise ValueError(f"Bar open ({self.open}) outside [low, high] for {self.symbol}")
        if self.close < self.low or self.close > self.high:
            raise ValueError(f"Bar close ({self.close}) outside [low, high] for {self.symbol}")
        if self.volume < 0:
            raise ValueError(f"Bar volume ({self.volume}) cannot be negative")


@dataclass(frozen=True)
class CatalystEvent:
    """Structured Catalyst Event Placeholder (Stage 0 point-in-time container)."""
    timestamp: datetime
    symbol: str
    catalyst_type: str  # e.g., 'TRACK_A_EARNINGS', 'TRACK_B_PR'
    is_valid: bool
    source: str

    def __post_init__(self):
        if self.timestamp.tzinfo is None:
            object.__setattr__(self, 'timestamp', self.timestamp.replace(tzinfo=NY_TZ))
        elif self.timestamp.tzinfo != NY_TZ:
            object.__setattr__(self, 'timestamp', self.timestamp.astimezone(NY_TZ))


class SectorProvider(ABC):
    """Abstract interface for point-in-time sector/industry classification (D5)."""
    @abstractmethod
    def get_sector(self, symbol: str, timestamp: datetime) -> Optional[str]:
        pass

    @abstractmethod
    def get_industry_group(self, symbol: str, timestamp: datetime) -> Optional[str]:
        pass


class StaticSectorProvider(SectorProvider):
    """Test implementation of SectorProvider with static/configurable mapping."""
    def __init__(self, mapping: Optional[Dict[str, str]] = None):
        self._mapping = mapping or {}

    def get_sector(self, symbol: str, timestamp: datetime) -> Optional[str]:
        return self._mapping.get(symbol, "GENERAL")

    def get_industry_group(self, symbol: str, timestamp: datetime) -> Optional[str]:
        return self._mapping.get(symbol, "GENERAL")


class CommissionModel(ABC):
    """Abstract interface for commission/fee calculation (D8)."""
    @abstractmethod
    def calculate_commission(self, shares: int, price: float) -> float:
        pass


class ZeroCommissionModel(CommissionModel):
    """Stage 0 default: zero commission."""
    def calculate_commission(self, shares: int, price: float) -> float:
        return 0.0


class SlippageModel(ABC):
    """Abstract interface for fill slippage calculation (D8)."""
    @abstractmethod
    def calculate_slippage(self, price: float, shares: int, side: str) -> float:
        pass


class ZeroSlippageModel(SlippageModel):
    """Stage 0 default: zero slippage."""
    def calculate_slippage(self, price: float, shares: int, side: str) -> float:
        return 0.0


class DailyIndicatorProvider(ABC):
    """Abstract interface for point-in-time daily indicators (e.g., 10 EMA)."""
    @abstractmethod
    def get_ema(self, symbol: str, as_of_date: date, period: int = 10) -> Optional[float]:
        """
        Returns EMA value for symbol computed strictly over completed daily sessions
        prior to or ending on as_of_date.
        Must NOT include uncompleted current-day sessions or future dates.
        Returns None if data is missing or history < period.
        """
        pass


class SeriesDailyIndicatorProvider(DailyIndicatorProvider):
    """
    Computes point-in-time daily EMAs over completed daily close records.
    history: Dict[symbol, List[Tuple[date, float]]] (sorted by date)
    """
    def __init__(self, history: Optional[Dict[str, List[Tuple[date, float]]]] = None):
        self._history = history or {}

    def get_ema(self, symbol: str, as_of_date: date, period: int = 10) -> Optional[float]:
        records = self._history.get(symbol, [])
        # Strict point-in-time filter: sessions up to as_of_date
        completed = [price for d, price in records if d <= as_of_date]
        if len(completed) < period:
            return None

        multiplier = 2.0 / (period + 1.0)
        # Seed with initial SMA of the first `period` closes
        ema = sum(completed[:period]) / float(period)
        for price in completed[period:]:
            ema = (price - ema) * multiplier + ema
        return round(ema, 4)


class ADVProvider(ABC):
    """Abstract interface for point-in-time Average Daily Volume (ADV)."""
    @abstractmethod
    def get_adv_50(self, symbol: str, as_of_date: date) -> Optional[float]:
        """
        Returns ADV50(t) = average daily volume over completed sessions [t-50, t-1].
        Requirements:
          - Strictly prior to as_of_date (never includes session t).
          - Requires at least 50 completed prior sessions.
          - Returns None if fewer than 50 completed prior sessions exist.
        """
        pass


class HistoricalADV50Provider(ADVProvider):
    """
    Calculates point-in-time ADV50 strictly over sessions [t-50, t-1].
    history: Dict[symbol, List[Tuple[date, float]]] (date, daily_volume)
    """
    def __init__(self, history: Optional[Dict[str, List[Tuple[date, float]]]] = None):
        self._history = history or {}

    def get_adv_50(self, symbol: str, as_of_date: date) -> Optional[float]:
        records = self._history.get(symbol, [])
        # Strictly prior sessions: session_date < as_of_date (excludes session t)
        prior_sessions = [vol for d, vol in records if d < as_of_date]
        if len(prior_sessions) < 50:
            return None
        # Last 50 completed sessions [t-50, t-1]
        last_50 = prior_sessions[-50:]
        return round(sum(last_50) / 50.0, 2)
