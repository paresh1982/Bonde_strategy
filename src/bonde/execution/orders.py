"""
Order Data Models (Section 7)
Deterministic representation of entry, stop, and target orders.
"""

from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from typing import Optional
import uuid


class OrderSide(str, Enum):
    BUY = "BUY"
    SELL = "SELL"


class OrderType(str, Enum):
    BUY_STOP = "BUY_STOP"
    BUY_STOP_LIMIT = "BUY_STOP_LIMIT"
    SELL_STOP = "SELL_STOP"
    SELL_LIMIT = "SELL_LIMIT"
    MARKET_EXIT = "MARKET_EXIT"


class OrderStatus(str, Enum):
    PENDING = "PENDING"
    TRIGGERED = "TRIGGERED"
    FILLED = "FILLED"
    CANCELLED = "CANCELLED"
    REJECTED = "REJECTED"
    EXPIRED = "EXPIRED"


@dataclass
class Order:
    symbol: str
    side: OrderSide
    order_type: OrderType
    quantity: int
    trigger_price: float
    limit_price: Optional[float] = None
    stop_loss_price: Optional[float] = None
    created_at: Optional[datetime] = None
    status: OrderStatus = OrderStatus.PENDING
    order_id: str = field(default_factory=lambda: str(uuid.uuid4())[:8])
    filled_at: Optional[datetime] = None
    fill_price: Optional[float] = None
    rejection_reason: Optional[str] = None
    tag: str = ""  # e.g., 'ENTRY_ORB', 'ENTRY_BASE_HIT', 'PARTIAL_TARGET', 'STOP_LOSS', 'EOD_AUDIT'

    def fill(self, timestamp: datetime, price: float):
        self.status = OrderStatus.FILLED
        self.filled_at = timestamp
        self.fill_price = price

    def cancel(self, reason: str = "CANCELLED"):
        self.status = OrderStatus.CANCELLED
        self.rejection_reason = reason

    def reject(self, reason: str):
        self.status = OrderStatus.REJECTED
        self.rejection_reason = reason
