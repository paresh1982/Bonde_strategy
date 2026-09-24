"""
Execution Simulator & Order Matching Engine (D2, D8, Section 13, Section 14)
Enforces chronological order processing, stop-limit collar matching, stale order cancellation,
and mandatory Same-Bar Stop Precedence.
"""

from dataclasses import dataclass
from datetime import datetime, time
from typing import List, Optional, Tuple

from ..data.models import Bar, CommissionModel, SlippageModel, ZeroCommissionModel, ZeroSlippageModel
from .orders import Order, OrderSide, OrderType, OrderStatus


@dataclass(frozen=True)
class FillEvent:
    order: Order
    timestamp: datetime
    fill_price: float
    quantity: int
    slippage: float
    commission: float
    is_same_bar_stop: bool = False


class ExecutionSimulator:
    def __init__(
        self,
        commission_model: Optional[CommissionModel] = None,
        slippage_model: Optional[SlippageModel] = None,
        stale_order_time: time = time(10, 15, 0),
    ):
        self.commission_model = commission_model or ZeroCommissionModel()
        self.slippage_model = slippage_model or ZeroSlippageModel()
        self.stale_order_time = stale_order_time

    def process_entry_order(self, order: Order, bar: Bar) -> Optional[FillEvent]:
        """
        Simulates entry orders against an incoming intraday Bar.
        Enforces Stop-Limit Collar logic and 10:15 AM stale purge.
        """
        if order.status != OrderStatus.PENDING:
            return None

        bar_time = bar.timestamp.time()

        # Check stale order cutoff
        if bar_time >= self.stale_order_time:
            order.cancel("STALE_ORDER_PURGE")
            return None

        # BUY_STOP_LIMIT logic
        if order.order_type == OrderType.BUY_STOP_LIMIT:
            if bar.high >= order.trigger_price:
                limit_price = order.limit_price or (order.trigger_price + 0.10)

                # Case B: Bar opened above the allowable collar (missed trade)
                if bar.open > limit_price:
                    order.cancel("COLLAR_MISS")
                    return None

                # Case A: Price reaches trigger and open is within collar
                fill_price = max(order.trigger_price, bar.open)

                if fill_price > limit_price:
                    order.cancel("COLLAR_MISS")
                    return None

                # Apply slippage & commission models
                slippage = self.slippage_model.calculate_slippage(fill_price, order.quantity, "BUY")
                effective_price = fill_price + slippage
                commission = self.commission_model.calculate_commission(order.quantity, effective_price)

                order.fill(bar.timestamp, effective_price)
                return FillEvent(
                    order=order,
                    timestamp=bar.timestamp,
                    fill_price=effective_price,
                    quantity=order.quantity,
                    slippage=slippage,
                    commission=commission,
                )

        # BUY_STOP (Standard without limit collar)
        elif order.order_type == OrderType.BUY_STOP:
            if bar.high >= order.trigger_price:
                fill_price = max(order.trigger_price, bar.open)
                slippage = self.slippage_model.calculate_slippage(fill_price, order.quantity, "BUY")
                effective_price = fill_price + slippage
                commission = self.commission_model.calculate_commission(order.quantity, effective_price)

                order.fill(bar.timestamp, effective_price)
                return FillEvent(
                    order=order,
                    timestamp=bar.timestamp,
                    fill_price=effective_price,
                    quantity=order.quantity,
                    slippage=slippage,
                    commission=commission,
                )

        return None

    def evaluate_position_exits(
        self,
        current_stop: float,
        partial_target: Optional[float],
        bar: Bar,
        has_partial_filled: bool = False,
    ) -> Tuple[Optional[str], Optional[float], bool]:
        """
        Evaluates stop and target exits against the current intraday bar.
        MANDATORY RULE (D2): If both stop and target could have been reached in the same bar,
        STOP IS ASSUMED TO OCCUR FIRST.
        
        Returns:
            (exit_type: 'STOP' | 'TARGET' | None, exit_price: float | None, is_same_bar: bool)
        """
        stop_hit = bar.low <= current_stop
        target_hit = partial_target is not None and not has_partial_filled and bar.high >= partial_target

        # Rule D2: SAME-BAR TARGET + STOP -> STOP FIRST
        if stop_hit and target_hit:
            exit_price = min(current_stop, bar.open)
            return "STOP", exit_price, True

        if stop_hit:
            # Adverse gap execution at open print if bar opened below stop
            exit_price = min(current_stop, bar.open)
            return "STOP", exit_price, False

        if target_hit:
            # Positive gap execution at open print if bar opened above target
            exit_price = max(partial_target, bar.open)
            return "TARGET", exit_price, False

        return None, None, False
