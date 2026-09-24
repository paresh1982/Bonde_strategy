"""
Base-Hit Setup Detection Engine (D1, Section 11)
Separates setup qualification, trigger level calculation, and structural stop determination.
"""

from dataclasses import dataclass
from typing import Optional


@dataclass(frozen=True)
class BaseHitCandidate:
    symbol: str
    is_qualified: bool
    trigger_price: float
    stop_price: float
    risk_geometry_pct: float
    rejection_reason: Optional[str] = None


class BaseHitSetup:
    """
    Base-Hit 65-Day High Breakout Detector.
    Qualification criteria:
      - 65-day high resistance level identified
      - Volume expansion >= 1.5x 50 SMA
      - Price >= $5.00
      - Risk geometry <= 4.0%
    """
    def __init__(
        self,
        price_floor: float = 5.0,
        max_risk_geometry_pct: float = 0.040,
        tick_size: float = 0.01,
    ):
        self.price_floor = price_floor
        self.max_risk_geometry_pct = max_risk_geometry_pct
        self.tick_size = tick_size

    def evaluate(
        self,
        symbol: str,
        current_price: float,
        highest_high_65: float,
        lowest_low_shelf: float,
        adv_50: float,
        recent_volume: float,
        volume_expansion_ratio: float = 1.5,
    ) -> BaseHitCandidate:
        """
        Evaluates Base-Hit setup and calculates trigger and stop.
        """
        if current_price < self.price_floor:
            return BaseHitCandidate(
                symbol=symbol,
                is_qualified=False,
                trigger_price=0.0,
                stop_price=0.0,
                risk_geometry_pct=0.0,
                rejection_reason=f"PRICE_BELOW_FLOOR ({current_price} < {self.price_floor})",
            )

        if adv_50 > 0 and (recent_volume / adv_50) < volume_expansion_ratio:
            return BaseHitCandidate(
                symbol=symbol,
                is_qualified=False,
                trigger_price=0.0,
                stop_price=0.0,
                risk_geometry_pct=0.0,
                rejection_reason=f"INSUFFICIENT_VOLUME_EXPANSION ({recent_volume / adv_50:.2f}x < {volume_expansion_ratio}x)",
            )

        trigger_price = highest_high_65 + self.tick_size
        stop_price = lowest_low_shelf - self.tick_size

        if stop_price >= trigger_price:
            return BaseHitCandidate(
                symbol=symbol,
                is_qualified=False,
                trigger_price=trigger_price,
                stop_price=stop_price,
                risk_geometry_pct=0.0,
                rejection_reason="INVALID_STOP_PRICE_ABOVE_TRIGGER",
            )

        geometry_pct = (trigger_price - stop_price) / trigger_price

        if geometry_pct > self.max_risk_geometry_pct:
            return BaseHitCandidate(
                symbol=symbol,
                is_qualified=False,
                trigger_price=trigger_price,
                stop_price=stop_price,
                risk_geometry_pct=geometry_pct,
                rejection_reason=f"RISK_GEOMETRY_EXCEEDED ({geometry_pct*100:.2f}% > {self.max_risk_geometry_pct*100:.1f}%)",
            )

        return BaseHitCandidate(
            symbol=symbol,
            is_qualified=True,
            trigger_price=trigger_price,
            stop_price=stop_price,
            risk_geometry_pct=geometry_pct,
            rejection_reason=None,
        )
