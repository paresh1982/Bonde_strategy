"""
Unit Tests for Position Sizing and Liquidity Engine (Tests 5, 6, 8)
"""

import pytest
from bonde.risk.sizing import calculate_position_size, calculate_liquidity_cap


def test_green_regime_sizing():
    """Test 5: Green regime 1.0% equity risk with floor division."""
    equity = 100_000.0
    entry = 50.00
    stop = 48.00  # $2.00 stop distance (4.0%)
    risk_fraction = 0.010  # Green = 1.0%

    result = calculate_position_size(
        account_equity=equity,
        entry_price=entry,
        stop_price=stop,
        risk_fraction=risk_fraction,
    )

    # 1R = $1,000. Stop distance = $2.00. Shares = floor(1000 / 2) = 500
    assert result.risk_dollars == 1000.0
    assert result.planned_shares == 500
    assert result.allocated_shares == 500
    assert result.actual_risk_dollars == 1000.0
    assert result.is_liquid is True
    assert result.allocation_ratio == 1.0


def test_yellow_regime_sizing():
    """Test 6: Yellow regime 0.5% equity risk."""
    equity = 100_000.0
    entry = 50.00
    stop = 48.50  # $1.50 stop distance (3.0%)
    risk_fraction = 0.005  # Yellow = 0.5%

    result = calculate_position_size(
        account_equity=equity,
        entry_price=entry,
        stop_price=stop,
        risk_fraction=risk_fraction,
    )

    # 1R = $500. Stop distance = $1.50. Shares = floor(500 / 1.50) = 333
    assert result.risk_dollars == 500.0
    assert result.planned_shares == 333
    assert result.allocated_shares == 333
    assert result.actual_risk_dollars == 333 * 1.50
    assert result.is_liquid is True


def test_liquidity_cap_rejection():
    """Test 8: Liquidity allocation_ratio < 0.60 triggers rejection."""
    equity = 100_000.0
    entry = 30.00
    stop = 29.50  # $0.50 stop distance (1.67%)
    risk_fraction = 0.010  # 1R = $1,000 -> Planned shares = 2,000

    # ADV50 = 50,000 shares. Participation cap = 1.5% -> LiquidCap = 750 shares
    # Allocation ratio = 750 / 2,000 = 0.375 < 0.60 -> REJECT
    adv_50 = 50_000.0
    result = calculate_position_size(
        account_equity=equity,
        entry_price=entry,
        stop_price=stop,
        risk_fraction=risk_fraction,
        adv_50=adv_50,
        participation_cap=0.015,
        min_allocation_ratio=0.60,
    )

    assert result.planned_shares == 2000
    assert result.allocated_shares == 750
    assert result.allocation_ratio == 0.375
    assert result.is_liquid is False
    assert "INSUFFICIENT_LIQUIDITY" in (result.rejection_reason or "")


def test_liquidity_cap_fractional_accepted():
    """Verifies that allocation_ratio between 0.60 and 1.0 is accepted as fractional deployment."""
    equity = 100_000.0
    entry = 20.00
    stop = 19.00  # $1.00 stop distance -> Planned shares = 1,000
    risk_fraction = 0.010

    # ADV50 = 50,000 shares -> LiquidCap = 750 shares (Ratio = 0.75 >= 0.60) -> ACCEPTED
    adv_50 = 50_000.0
    result = calculate_position_size(
        account_equity=equity,
        entry_price=entry,
        stop_price=stop,
        risk_fraction=risk_fraction,
        adv_50=adv_50,
        participation_cap=0.015,
        min_allocation_ratio=0.60,
    )

    assert result.planned_shares == 1000
    assert result.allocated_shares == 750
    assert result.allocation_ratio == 0.75
    assert result.is_liquid is True
    assert result.rejection_reason is None


def test_sizing_validation_errors():
    """Validates negative equity, negative risk, and entry <= stop."""
    with pytest.raises(ValueError, match="Account equity must be positive"):
        calculate_position_size(account_equity=-1000, entry_price=10, stop_price=9, risk_fraction=0.01)

    with pytest.raises(ValueError, match="Entry price .* must exceed stop price"):
        calculate_position_size(account_equity=10000, entry_price=10, stop_price=10, risk_fraction=0.01)

    with pytest.raises(ValueError, match="Entry price .* must exceed stop price"):
        calculate_position_size(account_equity=10000, entry_price=9, stop_price=10, risk_fraction=0.01)
