"""
Market Regime FSM & Provider (D6, Section 15)
Provides deterministic regime state (GREEN, YELLOW, RED) and risk fractions.
"""

from abc import ABC, abstractmethod
from datetime import datetime
from enum import Enum
from typing import Dict, Optional


class MarketRegime(str, Enum):
    GREEN = "GREEN"
    YELLOW = "YELLOW"
    RED = "RED"


class MarketRegimeProvider(ABC):
    """Abstract interface for point-in-time Market Monitor regime state."""
    @abstractmethod
    def get_regime(self, timestamp: datetime) -> MarketRegime:
        pass

    def get_risk_fraction(self, timestamp: datetime) -> float:
        """Returns the permitted equity risk fraction for the current regime."""
        regime = self.get_regime(timestamp)
        if regime == MarketRegime.GREEN:
            return 0.010  # 1.0% equity risk (D3)
        elif regime == MarketRegime.YELLOW:
            return 0.005  # 0.5% equity risk (D4)
        else:
            return 0.000  # 0% risk / new trades disabled in RED


class StaticRegimeProvider(MarketRegimeProvider):
    """Static or date-mapped regime provider for Stage 0 deterministic simulation."""
    def __init__(self, default_regime: MarketRegime = MarketRegime.GREEN, schedule: Optional[Dict[str, MarketRegime]] = None):
        self._default_regime = default_regime
        self._schedule = schedule or {}

    def get_regime(self, timestamp: datetime) -> MarketRegime:
        date_str = timestamp.strftime("%Y-%m-%d")
        return self._schedule.get(date_str, self._default_regime)
