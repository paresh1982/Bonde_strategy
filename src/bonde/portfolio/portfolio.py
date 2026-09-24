"""
Position & Portfolio Models (Section 8, Section 12, Section 13)
Tracks active position lifecycle, partial profit realization, Breakeven ratchets, and portfolio heat.
"""

from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
import math
from typing import Dict, List, Optional
from ..regime.market_regime import MarketRegime


class PositionStatus(str, Enum):
    OPEN = "OPEN"
    CLOSED = "CLOSED"


@dataclass
class Position:
    symbol: str
    side: str  # 'LONG'
    entry_price: float
    entry_timestamp: datetime
    quantity: int
    initial_stop: float
    current_stop: float
    initial_risk_dollars: float
    engine: str  # 'CATALYST' or 'BASE_HIT'
    setup_type: str
    regime_at_entry: MarketRegime
    partial_target_price: Optional[float] = None
    sector: Optional[str] = "GENERAL"
    has_partial_filled: bool = False
    is_cushioned: bool = False
    shares_remaining: int = 0
    realized_pnl: float = 0.0
    unrealized_pnl: float = 0.0
    exit_timestamp: Optional[datetime] = None
    exit_price: Optional[float] = None
    exit_reason: Optional[str] = None
    status: PositionStatus = PositionStatus.OPEN
    days_held: int = 0
    day1_close: Optional[float] = None
    r_multiple: float = 0.0

    def __post_init__(self):
        if self.shares_remaining == 0:
            self.shares_remaining = self.quantity
        if self.partial_target_price is None:
            risk_per_share = self.entry_price - self.initial_stop
            self.partial_target_price = round(self.entry_price + (2.0 * risk_per_share), 2)

    @property
    def current_risk_dollars(self) -> float:
        """Returns active downside dollar risk based on current stop."""
        if self.status == PositionStatus.CLOSED or self.is_cushioned:
            return 0.0
        risk_per_share = max(0.0, self.entry_price - self.current_stop)
        return self.shares_remaining * risk_per_share

    def update_price(self, current_price: float):
        """Updates unrealized PnL."""
        if self.status == PositionStatus.OPEN:
            self.unrealized_pnl = (current_price - self.entry_price) * self.shares_remaining

    def execute_partial_exit(self, price: float, timestamp: datetime, ratio: float = 0.50):
        """
        Executes partial profit-taking (default 50% tranche per D30, C2).
        Moves remaining stop to Breakeven (Entry + $0.01).
        """
        if self.has_partial_filled or self.status != PositionStatus.OPEN:
            return

        shares_to_exit = math.floor(self.shares_remaining * ratio)
        if shares_to_exit <= 0:
            return

        partial_pnl = (price - self.entry_price) * shares_to_exit
        self.realized_pnl += partial_pnl
        self.shares_remaining -= shares_to_exit
        self.has_partial_filled = True

        # Breakeven ratchet (D30, Section 12)
        self.current_stop = self.entry_price + 0.01
        self.is_cushioned = True

    def close(self, exit_price: float, timestamp: datetime, reason: str):
        """Closes remaining open position."""
        if self.status == PositionStatus.CLOSED:
            return

        remaining_pnl = (exit_price - self.entry_price) * self.shares_remaining
        self.realized_pnl += remaining_pnl
        self.shares_remaining = 0
        self.exit_price = exit_price
        self.exit_timestamp = timestamp
        self.exit_reason = reason
        self.status = PositionStatus.CLOSED
        self.unrealized_pnl = 0.0

        # Calculate final net R-multiple
        if self.initial_risk_dollars > 0:
            self.r_multiple = self.realized_pnl / self.initial_risk_dollars


class Portfolio:
    """Portfolio state tracker enforcing cash, positions, and aggregate heat."""
    def __init__(self, initial_equity: float = 100_000.0):
        self.initial_equity = initial_equity
        self.cash = initial_equity
        self.open_positions: Dict[str, Position] = {}
        self.closed_positions: List[Position] = []

    @property
    def total_equity(self) -> float:
        unrealized = sum(p.unrealized_pnl for p in self.open_positions.values())
        open_realized = sum(p.realized_pnl for p in self.open_positions.values())
        return self.cash + unrealized + open_realized

    @property
    def total_uncushioned_risk_dollars(self) -> float:
        return sum(p.current_risk_dollars for p in self.open_positions.values() if not p.is_cushioned)

    def add_position(self, position: Position):
        if position.symbol in self.open_positions:
            raise ValueError(f"Cannot add duplicate position for {position.symbol}")
        self.open_positions[position.symbol] = position

    def get_position(self, symbol: str) -> Optional[Position]:
        return self.open_positions.get(symbol)

    def close_position(self, symbol: str, exit_price: float, timestamp: datetime, reason: str):
        if symbol in self.open_positions:
            pos = self.open_positions.pop(symbol)
            pos.close(exit_price, timestamp, reason)
            self.cash += pos.realized_pnl
            self.closed_positions.append(pos)
