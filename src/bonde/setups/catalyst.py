"""
Catalyst & Opening Range Breakout (ORB) Engine (Section 6, Section 12)
Constructs 5-minute Opening Range (09:30–09:35 EST) and enforces the <= 4.0% risk geometry gate.
"""

from dataclasses import dataclass
from typing import List, Optional
from ..data.models import Bar


@dataclass(frozen=True)
class ORBCandidate:
    symbol: str
    is_qualified: bool
    orh: float
    orl: float
    trigger_price: float
    stop_price: float
    limit_price: float
    risk_geometry_pct: float
    rejection_reason: Optional[str] = None


class CatalystORBSetup:
    """
    5-Minute Opening Range Breakout (ORB) Evaluator.
    Constructs range from 09:30:00 to 09:34:59 EST.
    Enforces <= 4.0% geometry gate at 09:35:00 EST.
    """
    def __init__(
        self,
        max_risk_geometry_pct: float = 0.040,
        collar_cents: float = 0.10,
        tick_size: float = 0.01,
    ):
        self.max_risk_geometry_pct = max_risk_geometry_pct
        self.collar_cents = collar_cents
        self.tick_size = tick_size

    def evaluate_first_5_minutes(self, symbol: str, opening_bars: List[Bar]) -> ORBCandidate:
        """
        Evaluates the first 5 minutes of trading.
        """
        if not opening_bars:
            return ORBCandidate(
                symbol=symbol,
                is_qualified=False,
                orh=0.0,
                orl=0.0,
                trigger_price=0.0,
                stop_price=0.0,
                limit_price=0.0,
                risk_geometry_pct=0.0,
                rejection_reason="NO_OPENING_BARS_PROVIDED",
            )

        orh = max(bar.high for bar in opening_bars)
        orl = min(bar.low for bar in opening_bars)

        if orh <= 0 or orl <= 0:
            return ORBCandidate(
                symbol=symbol,
                is_qualified=False,
                orh=orh,
                orl=orl,
                trigger_price=0.0,
                stop_price=0.0,
                limit_price=0.0,
                risk_geometry_pct=0.0,
                rejection_reason="INVALID_OPENING_PRICES_NON_POSITIVE",
            )

        geometry_pct = (orh - orl) / orh

        trigger_price = round(orh + self.tick_size, 2)
        stop_price = round(orl - self.tick_size, 2)
        limit_price = round(trigger_price + self.collar_cents, 2)

        if geometry_pct > self.max_risk_geometry_pct:
            return ORBCandidate(
                symbol=symbol,
                is_qualified=False,
                orh=orh,
                orl=orl,
                trigger_price=trigger_price,
                stop_price=stop_price,
                limit_price=limit_price,
                risk_geometry_pct=geometry_pct,
                rejection_reason=f"ORB_GEOMETRY_FAIL ({geometry_pct*100:.2f}% > {self.max_risk_geometry_pct*100:.1f}%)",
            )

        return ORBCandidate(
            symbol=symbol,
            is_qualified=True,
            orh=orh,
            orl=orl,
            trigger_price=trigger_price,
            stop_price=stop_price,
            limit_price=limit_price,
            risk_geometry_pct=geometry_pct,
            rejection_reason=None,
        )


@dataclass(frozen=True)
class InsideDayCandidate:
    symbol: str
    is_qualified: bool
    trigger_price: float
    stop_price: float
    limit_price: float
    risk_geometry_pct: float
    rejection_reason: Optional[str] = None


class InsideDaySetup:
    """
    Inside-Day Volatility Squeeze Evaluator.
    High < Previous High and Low > Previous Low.
    """
    def __init__(
        self,
        max_risk_geometry_pct: float = 0.040,
        collar_cents: float = 0.10,
        tick_size: float = 0.01,
    ):
        self.max_risk_geometry_pct = max_risk_geometry_pct
        self.collar_cents = collar_cents
        self.tick_size = tick_size

    def evaluate(self, symbol: str, mother_bar: Bar, inside_bar: Bar) -> InsideDayCandidate:
        is_inside = (inside_bar.high < mother_bar.high) and (inside_bar.low > mother_bar.low)
        if not is_inside:
            return InsideDayCandidate(
                symbol=symbol,
                is_qualified=False,
                trigger_price=0.0,
                stop_price=0.0,
                limit_price=0.0,
                risk_geometry_pct=0.0,
                rejection_reason="NOT_AN_INSIDE_DAY",
            )

        trigger_price = round(inside_bar.high + self.tick_size, 2)
        stop_price = round(inside_bar.low - self.tick_size, 2)
        limit_price = round(trigger_price + self.collar_cents, 2)

        geometry_pct = (trigger_price - stop_price) / trigger_price

        if geometry_pct > self.max_risk_geometry_pct:
            return InsideDayCandidate(
                symbol=symbol,
                is_qualified=False,
                trigger_price=trigger_price,
                stop_price=stop_price,
                limit_price=limit_price,
                risk_geometry_pct=geometry_pct,
                rejection_reason=f"RISK_GEOMETRY_EXCEEDED ({geometry_pct*100:.2f}% > {self.max_risk_geometry_pct*100:.1f}%)",
            )

        return InsideDayCandidate(
            symbol=symbol,
            is_qualified=True,
            trigger_price=trigger_price,
            stop_price=stop_price,
            limit_price=limit_price,
            risk_geometry_pct=geometry_pct,
            rejection_reason=None,
        )
