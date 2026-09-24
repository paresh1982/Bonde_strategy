"""
Paper Execution Broker (Stage 2)
Internal mock execution venue that tracks orders, fills, and cancellations without external routing.
"""

from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, Dict, List, Optional
import pandas as pd

from ..execution.orders import Order, OrderSide, OrderStatus, OrderType
from .interfaces import LiveExecutionBridge


@dataclass
class PaperFillRecord:
    fill_id: str
    order_id: str
    symbol: str
    security_id: str
    timestamp: datetime
    side: str
    fill_quantity: int
    fill_price: float
    commission: float
    slippage: float
    effective_price: float


class PaperExecutionBroker(LiveExecutionBridge):
    """
    Internal paper execution venue for simulated trading.
    Accepts strategy orders and maintains local paper order/fill state.
    """

    def __init__(self):
        self._orders: Dict[str, Order] = {}
        self._order_security_map: Dict[str, str] = {}
        self._fills: List[PaperFillRecord] = []
        self._cancellation_reasons: Dict[str, str] = {}

    def reset(self):
        self._orders.clear()
        self._order_security_map.clear()
        self._fills.clear()
        self._cancellation_reasons.clear()

    def submit_order(self, order: Order, security_id: Optional[str] = None) -> str:
        """
        Submits an order to the paper broker.
        Enforces validation that order has valid quantity, prices, and side.
        """
        if order.quantity <= 0:
            order.status = OrderStatus.REJECTED
            order.rejection_reason = "INVALID_QUANTITY"
            self._orders[order.order_id] = order
            return order.order_id

        sec_id = security_id or f"SEC_{order.symbol}"
        self._orders[order.order_id] = order
        self._order_security_map[order.order_id] = sec_id
        return order.order_id

    def cancel_order(self, order_id: str, reason: str = "USER_CANCELLED") -> bool:
        """Cancels a pending order."""
        order = self._orders.get(order_id)
        if not order:
            return False
        if order.status == OrderStatus.PENDING:
            order.cancel(reason)
            self._cancellation_reasons[order_id] = reason
            return True
        return False

    def record_fill(
        self,
        order_id: str,
        timestamp: datetime,
        fill_price: float,
        fill_qty: int,
        commission: float = 0.0,
        slippage: float = 0.0,
    ) -> Optional[PaperFillRecord]:
        """Records a simulated execution fill against an existing order."""
        order = self._orders.get(order_id)
        if not order:
            return None

        order.fill(timestamp=timestamp, price=fill_price)
        sec_id = self._order_security_map.get(order_id, f"SEC_{order.symbol}")
        fill_rec = PaperFillRecord(
            fill_id=f"FILL_{order_id}_{len(self._fills) + 1}",
            order_id=order_id,
            symbol=order.symbol,
            security_id=sec_id,
            timestamp=timestamp,
            side=order.side.value,
            fill_quantity=fill_qty,
            fill_price=fill_price,
            commission=commission,
            slippage=slippage,
            effective_price=round(fill_price + slippage if order.side == OrderSide.BUY else fill_price - slippage, 4),
        )
        self._fills.append(fill_rec)
        return fill_rec

    def get_order(self, order_id: str) -> Optional[Order]:
        return self._orders.get(order_id)

    def get_open_orders(self) -> List[Order]:
        return [o for o in self._orders.values() if o.status == OrderStatus.PENDING]

    def get_orders_for_symbol(self, symbol: str) -> List[Order]:
        return [o for o in self._orders.values() if o.symbol == symbol]

    def get_all_orders(self) -> List[Order]:
        return list(self._orders.values())

    def get_all_fills(self) -> List[PaperFillRecord]:
        return list(self._fills)

    def orders_to_dataframe(self) -> pd.DataFrame:
        if not self._orders:
            return pd.DataFrame()
        records = []
        for o in self._orders.values():
            records.append({
                "order_id": o.order_id,
                "symbol": o.symbol,
                "security_id": self._order_security_map.get(o.order_id, f"SEC_{o.symbol}"),
                "side": o.side.value,
                "order_type": o.order_type.value,
                "quantity": o.quantity,
                "trigger_price": o.trigger_price,
                "limit_price": o.limit_price,
                "stop_loss_price": o.stop_loss_price,
                "status": o.status.value,
                "created_at": o.created_at,
                "filled_at": o.filled_at,
                "fill_price": o.fill_price,
                "rejection_reason": o.rejection_reason,
                "tag": o.tag,
            })
        return pd.DataFrame(records)

    def fills_to_dataframe(self) -> pd.DataFrame:
        if not self._fills:
            return pd.DataFrame()
        return pd.DataFrame([f.__dict__ for f in self._fills])
