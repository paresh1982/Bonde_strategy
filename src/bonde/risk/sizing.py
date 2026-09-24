"""
Position Sizing & Liquidity Engine (D3, D4, Section 9, Section 10)
Deterministic 1R calculation with strict integer floor sizing and ADV liquidity capping.
"""

from dataclasses import dataclass
import math
from typing import Optional


@dataclass(frozen=True)
class PositionSizingResult:
    planned_shares: int
    allocated_shares: int
    risk_dollars: float
    actual_risk_dollars: float
    stop_distance: float
    risk_fraction: float
    allocation_ratio: float
    is_liquid: bool
    rejection_reason: Optional[str] = None


def calculate_liquidity_cap(adv_50: float, participation_cap: float = 0.015) -> int:
    """Calculates maximum allowed position size based on ADV50 (default 1.5%)."""
    if adv_50 < 0:
        raise ValueError(f"ADV50 cannot be negative: {adv_50}")
    return math.floor(adv_50 * participation_cap)


def calculate_position_size(
    account_equity: float,
    entry_price: float,
    stop_price: float,
    risk_fraction: float,
    adv_50: Optional[float] = None,
    participation_cap: float = 0.015,
    min_allocation_ratio: float = 0.60,
) -> PositionSizingResult:
    """
    Deterministic position sizing formula:
    risk_dollars = account_equity * risk_fraction
    planned_shares = floor(risk_dollars / abs(entry_price - stop_price))

    If adv_50 is provided:
    liquidity_cap = floor(adv_50 * participation_cap)
    allocated_shares = min(planned_shares, liquidity_cap)
    if allocated_shares / planned_shares < min_allocation_ratio:
        trade rejected due to insufficient liquidity
    """
    if account_equity <= 0:
        raise ValueError(f"Account equity must be positive, got {account_equity}")
    if risk_fraction <= 0:
        raise ValueError(f"Risk fraction must be positive, got {risk_fraction}")
    if entry_price <= stop_price:
        raise ValueError(f"Entry price ({entry_price}) must exceed stop price ({stop_price}) for long positions")

    stop_distance = entry_price - stop_price
    if stop_distance <= 0:
        raise ValueError(f"Stop distance must be strictly positive, got {stop_distance}")

    risk_dollars = account_equity * risk_fraction
    planned_shares = math.floor(risk_dollars / stop_distance)

    if planned_shares <= 0:
        return PositionSizingResult(
            planned_shares=0,
            allocated_shares=0,
            risk_dollars=risk_dollars,
            actual_risk_dollars=0.0,
            stop_distance=stop_distance,
            risk_fraction=risk_fraction,
            allocation_ratio=0.0,
            is_liquid=False,
            rejection_reason="PLANNED_SHARES_ZERO",
        )

    allocated_shares = planned_shares
    allocation_ratio = 1.0
    is_liquid = True
    rejection_reason = None

    if adv_50 is not None:
        liquid_cap = calculate_liquidity_cap(adv_50, participation_cap)
        allocated_shares = min(planned_shares, liquid_cap)
        allocation_ratio = allocated_shares / planned_shares if planned_shares > 0 else 0.0

        if allocation_ratio < min_allocation_ratio:
            is_liquid = False
            rejection_reason = f"INSUFFICIENT_LIQUIDITY (Ratio {allocation_ratio:.2f} < {min_allocation_ratio:.2f})"

    actual_risk_dollars = allocated_shares * stop_distance

    return PositionSizingResult(
        planned_shares=planned_shares,
        allocated_shares=allocated_shares,
        risk_dollars=risk_dollars,
        actual_risk_dollars=actual_risk_dollars,
        stop_distance=stop_distance,
        risk_fraction=risk_fraction,
        allocation_ratio=allocation_ratio,
        is_liquid=is_liquid,
        rejection_reason=rejection_reason,
    )
