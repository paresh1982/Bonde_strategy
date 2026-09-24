"""
Transaction Cost Models for Stage 1D Multi-Year Historical Backtest (Phase 6)
Supports Zero-Cost Baseline, Conservative Active Trader Model, and Stress Model.
"""

from abc import ABC, abstractmethod
from typing import Tuple

from ..data.models import CommissionModel, SlippageModel


class BaseCostScenario(ABC):
    """Encapsulates both commission and slippage for a given backtest scenario."""
    name: str

    @abstractmethod
    def calculate_entry_cost(self, shares: int, price: float) -> Tuple[float, float]:
        """Returns (effective_fill_price, commission_dollars)."""
        pass

    @abstractmethod
    def calculate_exit_cost(self, shares: int, price: float, is_stop: bool = False) -> Tuple[float, float]:
        """Returns (effective_exit_price, commission_dollars)."""
        pass


class ZeroCostModel(BaseCostScenario, CommissionModel, SlippageModel):
    """
    Scenario A: Zero-Cost Baseline
    Commission = $0, Slippage = $0
    """
    name: str = "ZERO_COST_BASELINE"

    def calculate_commission(self, shares: int, price: float) -> float:
        return 0.0

    def calculate_slippage(self, price: float, shares: int, side: str) -> float:
        return 0.0

    def calculate_entry_cost(self, shares: int, price: float) -> Tuple[float, float]:
        return price, 0.0

    def calculate_exit_cost(self, shares: int, price: float, is_stop: bool = False) -> Tuple[float, float]:
        return price, 0.0


class ConservativeActiveTraderCostModel(BaseCostScenario, CommissionModel, SlippageModel):
    """
    Scenario B: Conservative Retail / Active Trader Model
    - Commission: $0.005 per share (Interactive Brokers Active Trader Pro tier), min $1.00 per order
    - Slippage: $0.01 per share fixed bid-ask half-spread / market impact
    """
    name: str = "CONSERVATIVE_ACTIVE_TRADER"

    def __init__(self, per_share_commission: float = 0.005, min_commission: float = 1.00, per_share_slippage: float = 0.01):
        self.per_share_commission = per_share_commission
        self.min_commission = min_commission
        self.per_share_slippage = per_share_slippage

    def calculate_commission(self, shares: int, price: float) -> float:
        if shares <= 0:
            return 0.0
        return max(self.min_commission, round(shares * self.per_share_commission, 2))

    def calculate_slippage(self, price: float, shares: int, side: str) -> float:
        # Long entries buy higher, exits sell lower
        return self.per_share_slippage

    def calculate_entry_cost(self, shares: int, price: float) -> Tuple[float, float]:
        eff_price = round(price + self.per_share_slippage, 4)
        comm = self.calculate_commission(shares, eff_price)
        return eff_price, comm

    def calculate_exit_cost(self, shares: int, price: float, is_stop: bool = False) -> Tuple[float, float]:
        eff_price = round(max(0.01, price - self.per_share_slippage), 4)
        comm = self.calculate_commission(shares, eff_price)
        return eff_price, comm


class StressCostModel(BaseCostScenario, CommissionModel, SlippageModel):
    """
    Scenario C: Stress Model
    - Commission: $0.01 per share, min $1.50 per order
    - Entry Slippage: $0.03 per share (wider bid/ask spread)
    - Stop Exit Slippage: $0.05 per share (wider spread + adverse gap slippage)
    - Regular Target / EOD Exit Slippage: $0.03 per share
    """
    name: str = "STRESS_MODEL"

    def __init__(
        self,
        per_share_commission: float = 0.01,
        min_commission: float = 1.50,
        per_share_slippage: float = 0.03,
        adverse_stop_slippage: float = 0.05,
    ):
        self.per_share_commission = per_share_commission
        self.min_commission = min_commission
        self.per_share_slippage = per_share_slippage
        self.adverse_stop_slippage = adverse_stop_slippage

    def calculate_commission(self, shares: int, price: float) -> float:
        if shares <= 0:
            return 0.0
        return max(self.min_commission, round(shares * self.per_share_commission, 2))

    def calculate_slippage(self, price: float, shares: int, side: str) -> float:
        return self.per_share_slippage

    def calculate_entry_cost(self, shares: int, price: float) -> Tuple[float, float]:
        eff_price = round(price + self.per_share_slippage, 4)
        comm = self.calculate_commission(shares, eff_price)
        return eff_price, comm

    def calculate_exit_cost(self, shares: int, price: float, is_stop: bool = False) -> Tuple[float, float]:
        slip = self.adverse_stop_slippage if is_stop else self.per_share_slippage
        eff_price = round(max(0.01, price - slip), 4)
        comm = self.calculate_commission(shares, eff_price)
        return eff_price, comm
