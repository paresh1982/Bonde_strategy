"""
Configurable Paper Fill Model (Stage 2)
Simulates realistic bid/ask execution, latency, slippage, collar misses, and partial fills.
"""

from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Optional, Tuple

from ..execution.orders import Order, OrderSide, OrderStatus, OrderType
from .models import LiveBar, Quote


@dataclass
class FillEvaluationResult:
    is_filled: bool
    is_cancelled: bool
    fill_price: Optional[float] = None
    fill_quantity: int = 0
    slippage: float = 0.0
    latency_ms: float = 0.0
    rejection_reason: Optional[str] = None


class PaperFillModel:
    """
    Configurable execution simulator for evaluating paper orders against live bars/quotes.
    """

    def __init__(
        self,
        slippage_per_share: float = 0.01,
        latency_ms: float = 25.0,
        enforce_collar: bool = True,
        collar_cents: float = 0.10,
        allow_partial_fills: bool = False,
        partial_fill_ratio: float = 1.0,
    ):
        self.slippage_per_share = slippage_per_share
        self.latency_ms = latency_ms
        self.enforce_collar = enforce_collar
        self.collar_cents = collar_cents
        self.allow_partial_fills = allow_partial_fills
        self.partial_fill_ratio = partial_fill_ratio

    def evaluate_order(
        self,
        order: Order,
        bar: LiveBar,
        quote: Optional[Quote] = None,
    ) -> FillEvaluationResult:
        """
        Evaluates if a pending order triggers and fills on the given bar/quote.
        """
        if order.status != OrderStatus.PENDING:
            return FillEvaluationResult(is_filled=False, is_cancelled=False)

        # 1. Evaluate BUY_STOP / BUY_STOP_LIMIT orders (Breakout Entries)
        if order.order_type in (OrderType.BUY_STOP, OrderType.BUY_STOP_LIMIT):
            # Check trigger condition
            if bar.high >= order.trigger_price:
                limit_p = order.limit_price or (order.trigger_price + self.collar_cents)

                # Collar miss: bar opens above limit price
                if self.enforce_collar and bar.open > limit_p:
                    return FillEvaluationResult(
                        is_filled=False,
                        is_cancelled=True,
                        rejection_reason="COLLAR_MISS",
                    )

                # Determine base fill print (at Ask if quote available, else max(trigger, open))
                if quote is not None and quote.ask > 0:
                    raw_fill = max(order.trigger_price, quote.ask)
                else:
                    raw_fill = max(order.trigger_price, bar.open)

                # Check if raw fill exceeds collar limit
                if self.enforce_collar and raw_fill > limit_p:
                    return FillEvaluationResult(
                        is_filled=False,
                        is_cancelled=True,
                        rejection_reason="COLLAR_MISS",
                    )

                # Apply slippage
                eff_fill = round(raw_fill + self.slippage_per_share, 4)

                # Calculate filled quantity
                qty = order.quantity
                if self.allow_partial_fills and self.partial_fill_ratio < 1.0:
                    qty = max(1, int(order.quantity * self.partial_fill_ratio))

                return FillEvaluationResult(
                    is_filled=True,
                    is_cancelled=False,
                    fill_price=eff_fill,
                    fill_quantity=qty,
                    slippage=self.slippage_per_share,
                    latency_ms=self.latency_ms,
                )

        # 2. Evaluate SELL_LIMIT (Target exits, e.g. +2R partial)
        elif order.order_type == OrderType.SELL_LIMIT:
            limit_p = order.limit_price or order.trigger_price
            if bar.high >= limit_p:
                if quote is not None and quote.bid > 0:
                    raw_fill = max(limit_p, quote.bid)
                else:
                    raw_fill = max(limit_p, bar.open)

                eff_fill = round(raw_fill - self.slippage_per_share, 4)
                return FillEvaluationResult(
                    is_filled=True,
                    is_cancelled=False,
                    fill_price=eff_fill,
                    fill_quantity=order.quantity,
                    slippage=self.slippage_per_share,
                    latency_ms=self.latency_ms,
                )

        # 3. Evaluate SELL_STOP (Structural Stop exits)
        elif order.order_type == OrderType.SELL_STOP:
            stop_p = order.stop_loss_price or order.trigger_price
            if bar.low <= stop_p:
                if quote is not None and quote.bid > 0:
                    raw_fill = min(stop_p, quote.bid)
                else:
                    raw_fill = min(stop_p, bar.open)

                eff_fill = round(raw_fill - self.slippage_per_share, 4)
                return FillEvaluationResult(
                    is_filled=True,
                    is_cancelled=False,
                    fill_price=eff_fill,
                    fill_quantity=order.quantity,
                    slippage=self.slippage_per_share,
                    latency_ms=self.latency_ms,
                )

        # 4. Evaluate MARKET_EXIT (EOD liquidation or immediate market close)
        elif order.order_type == OrderType.MARKET_EXIT:
            if quote is not None and quote.bid > 0:
                raw_fill = quote.bid
            else:
                raw_fill = bar.close

            eff_fill = round(raw_fill - self.slippage_per_share, 4)
            return FillEvaluationResult(
                is_filled=True,
                is_cancelled=False,
                fill_price=eff_fill,
                fill_quantity=order.quantity,
                slippage=self.slippage_per_share,
                latency_ms=self.latency_ms,
            )

        return FillEvaluationResult(is_filled=False, is_cancelled=False)
