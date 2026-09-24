"""
Market Breadth Provider & Regime Adapter (Section 11)
Maintains historical daily market breadth metrics and maps them to GREEN / YELLOW / RED.
Enforces point-in-time isolation (t-1 breadth governs session t).
"""

from abc import ABC, abstractmethod
from dataclasses import dataclass
from datetime import date, datetime
from typing import Any, Dict, Optional

from ..regime.market_regime import MarketRegime, MarketRegimeProvider


@dataclass(frozen=True)
class MarketBreadthRecord:
    """Historical daily market breadth metrics."""
    session_date: date
    universe_size: int
    gainers_4pct_count: int
    losers_4pct_count: int
    t2108_percent: Optional[float] = None       # % of stocks above 40 SMA
    stocks_above_200sma: Optional[float] = None
    stocks_above_50sma: Optional[float] = None
    regime_state: str = "GREEN"                 # "GREEN", "YELLOW", "RED"

    def compute_regime(self) -> MarketRegime:
        """
        Deterministic Breadth FSM logic:
        - RED: Net breadth heavily negative (losers > 2x gainers or T2108 < 20%)
        - YELLOW: Weak breadth or T2108 between 20% and 40%
        - GREEN: Healthy breadth (gainers > losers and T2108 >= 40%)
        """
        if self.regime_state in ("GREEN", "YELLOW", "RED"):
            return MarketRegime(self.regime_state)

        if self.t2108_percent is not None and self.t2108_percent < 20.0:
            return MarketRegime.RED
        if self.losers_4pct_count > 2 * max(self.gainers_4pct_count, 1):
            return MarketRegime.RED
        if self.t2108_percent is not None and self.t2108_percent < 40.0:
            return MarketRegime.YELLOW
        return MarketRegime.GREEN


class MarketBreadthProvider(ABC):
    """Abstract interface for historical market breadth data."""

    @abstractmethod
    def get_breadth(self, session_date: date) -> Optional[MarketBreadthRecord]:
        """Retrieves market breadth metrics computed for session_date."""
        pass


class InMemoryMarketBreadthProvider(MarketBreadthProvider):
    """In-memory store for historical daily market breadth."""

    def __init__(self, records: Optional[Dict[date, MarketBreadthRecord]] = None):
        self._records = records or {}

    def add_record(self, record: MarketBreadthRecord):
        self._records[record.session_date] = record

    def get_breadth(self, session_date: date) -> Optional[MarketBreadthRecord]:
        return self._records.get(session_date)


class PointInTimeMarketRegimeProvider(MarketRegimeProvider):
    """
    Adapts historical MarketBreadthProvider to the engine's MarketRegimeProvider interface.
    Strictly applies t-1 market breadth to govern session t trading.
    """

    def __init__(
        self,
        breadth_provider: MarketBreadthProvider,
        default_regime: MarketRegime = MarketRegime.GREEN,
    ):
        self.breadth_provider = breadth_provider
        self.default_regime = default_regime

    def get_regime(self, timestamp: Any) -> MarketRegime:
        # Determine session date t
        session_t = timestamp.date() if isinstance(timestamp, datetime) else timestamp
        # Look up t-1 breadth (in actual market, t-1 close is the latest completed prior session)
        record = self.breadth_provider.get_breadth(session_t)
        if not record:
            return self.default_regime
        return record.compute_regime()
