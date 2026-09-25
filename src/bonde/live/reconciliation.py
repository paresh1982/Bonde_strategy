"""
Order & Portfolio State Reconciliation Engine (Stage 2)
Verifies consistency between Strategy State, Paper Broker, and Portfolio positions.
Detects duplicates, quantity mismatches, orphaned positions, and stale orders.
"""

from dataclasses import dataclass
from datetime import datetime, time
from typing import Any, Dict, List, Optional

from ..execution.orders import Order, OrderSide, OrderStatus, OrderType
from ..portfolio.portfolio import Portfolio, PositionStatus
from .broker import PaperExecutionBroker


@dataclass
class Discrepancy:
    discrepancy_type: str
    symbol: str
    severity: str  # "WARN", "CRITICAL"
    details: str
    timestamp: datetime


class ReconciliationError(Exception):
    """Raised when critical state mismatch occurs (fail-closed)."""
    pass


class OrderStateReconciler:
    """
    Validates state alignment between Strategy, Broker, and Portfolio.
    """

    def __init__(self, stale_order_cutoff_time: time = time(10, 15)):
        self.stale_order_cutoff_time = stale_order_cutoff_time
        self.discrepancies: List[Discrepancy] = []

    def reconcile(
        self,
        portfolio: Portfolio,
        broker: PaperExecutionBroker,
        current_time: datetime,
        fail_closed: bool = True,
    ) -> List[Discrepancy]:
        """
        Runs comprehensive consistency audit across portfolio and broker orders.
        """
        current_discrepancies: List[Discrepancy] = []
        open_positions = portfolio.open_positions
        open_orders = broker.get_open_orders()
        all_orders = broker.get_all_orders()

        # 1. Detect duplicate pending entry orders for the same ticker
        pending_symbols = {}
        for o in open_orders:
            if o.side == OrderSide.BUY:
                pending_symbols.setdefault(o.symbol, []).append(o)

        for sym, ords in pending_symbols.items():
            if len(ords) > 1:
                disc = Discrepancy(
                    discrepancy_type="DUPLICATE_PENDING_ORDER",
                    symbol=sym,
                    severity="CRITICAL",
                    details=f"Found {len(ords)} active BUY orders for {sym} (IDs: {[o.order_id for o in ords]})",
                    timestamp=current_time,
                )
                current_discrepancies.append(disc)

        # 2. Detect stale pending orders after 10:15 cutoff
        if current_time.time() >= self.stale_order_cutoff_time:
            for o in open_orders:
                if o.side == OrderSide.BUY and "ENTRY" in o.tag:
                    disc = Discrepancy(
                        discrepancy_type="STALE_PENDING_ORDER",
                        symbol=o.symbol,
                        severity="CRITICAL",
                        details=f"Pending entry order {o.order_id} exists past {self.stale_order_cutoff_time} cutoff",
                        timestamp=current_time,
                    )
                    current_discrepancies.append(disc)

        # 3. Detect orphaned positions (position open in portfolio without any filled buy order in broker)
        filled_buy_symbols = {o.symbol for o in all_orders if o.status == OrderStatus.FILLED and o.side == OrderSide.BUY}
        for sym, pos in open_positions.items():
            if sym not in filled_buy_symbols:
                disc = Discrepancy(
                    discrepancy_type="ORPHANED_POSITION",
                    symbol=sym,
                    severity="CRITICAL",
                    details=f"Position {sym} ({pos.quantity} shares) has no filled BUY order in broker",
                    timestamp=current_time,
                )
                current_discrepancies.append(disc)

        # 4. Detect quantity mismatches between open position and filled orders
        for sym, pos in open_positions.items():
            filled_buys = sum(o.quantity for o in all_orders if o.symbol == sym and o.status == OrderStatus.FILLED and o.side == OrderSide.BUY)
            # Subtract partial sales
            filled_sells = sum(o.quantity for o in all_orders if o.symbol == sym and o.status == OrderStatus.FILLED and o.side == OrderSide.SELL)
            net_filled = filled_buys - filled_sells
            if pos.quantity != net_filled and net_filled > 0:
                disc = Discrepancy(
                    discrepancy_type="QUANTITY_MISMATCH",
                    symbol=sym,
                    severity="CRITICAL",
                    details=f"Position shares ({pos.quantity}) != Net filled order shares ({net_filled})",
                    timestamp=current_time,
                )
                current_discrepancies.append(disc)

        # 5. Detect missing strategy positions (broker net position > 0, but no open position in strategy portfolio)
        broker_symbols = {o.symbol for o in all_orders if o.status == OrderStatus.FILLED}
        for b_sym in broker_symbols:
            b_buys = sum(o.quantity for o in all_orders if o.symbol == b_sym and o.status == OrderStatus.FILLED and o.side == OrderSide.BUY)
            b_sells = sum(o.quantity for o in all_orders if o.symbol == b_sym and o.status == OrderStatus.FILLED and o.side == OrderSide.SELL)
            net_broker = b_buys - b_sells
            if net_broker > 0 and b_sym not in open_positions:
                disc = Discrepancy(
                    discrepancy_type="MISSING_STRATEGY_POSITION",
                    symbol=b_sym,
                    severity="CRITICAL",
                    details=f"Broker has net position of {net_broker} shares for {b_sym}, but strategy portfolio has no open position",
                    timestamp=current_time,
                )
                current_discrepancies.append(disc)

        # 6. Detect invalid or unknown order IDs
        for o in all_orders:
            if not o.order_id or not o.symbol or o.order_id == "UNKNOWN":
                disc = Discrepancy(
                    discrepancy_type="UNKNOWN_ORDER_ID",
                    symbol=o.symbol or "UNKNOWN",
                    severity="CRITICAL",
                    details=f"Encountered invalid or unknown order ID: '{o.order_id}'",
                    timestamp=current_time,
                )
                current_discrepancies.append(disc)

        self.discrepancies.extend(current_discrepancies)

        if fail_closed:
            criticals = [d for d in current_discrepancies if d.severity == "CRITICAL"]
            if criticals:
                raise ReconciliationError(
                    f"Reconciliation failed with {len(criticals)} critical discrepancies: {criticals[0].details}"
                )

        return current_discrepancies
