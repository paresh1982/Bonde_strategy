"""
Unit Tests for Base-Hit Setup Detection (Test 10, D1, Section 11)
"""

from bonde.setups.base_hit import BaseHitSetup


def test_valid_base_hit_qualification():
    """Test 10: Setup qualifies -> trigger = 65D High + $0.01 -> structural stop established."""
    setup = BaseHitSetup(price_floor=5.0, max_risk_geometry_pct=0.040, tick_size=0.01)

    # 65-day high is $50.00. Shelf low is $48.50. Volume is 2.0x ADV50.
    candidate = setup.evaluate(
        symbol="BASE_TEST",
        current_price=50.05,
        highest_high_65=50.00,
        lowest_low_shelf=48.50,
        adv_50=200_000.0,
        recent_volume=400_000.0,
    )

    assert candidate.is_qualified is True
    assert candidate.trigger_price == 50.01
    assert candidate.stop_price == 48.49
    # Geometry = (50.01 - 48.49) / 50.01 = 1.52 / 50.01 = 3.04% <= 4.0%
    assert candidate.risk_geometry_pct < 0.040
    assert candidate.rejection_reason is None


def test_base_hit_price_floor_rejection():
    """Rejection when price < $5.00."""
    setup = BaseHitSetup(price_floor=5.0)

    candidate = setup.evaluate(
        symbol="PENNY",
        current_price=4.50,
        highest_high_65=4.40,
        lowest_low_shelf=4.20,
        adv_50=100_000.0,
        recent_volume=200_000.0,
    )

    assert candidate.is_qualified is False
    assert "PRICE_BELOW_FLOOR" in candidate.rejection_reason


def test_base_hit_volume_expansion_rejection():
    """Rejection when volume < 1.5x ADV50."""
    setup = BaseHitSetup(price_floor=5.0)

    candidate = setup.evaluate(
        symbol="LOW_VOL",
        current_price=25.00,
        highest_high_65=24.50,
        lowest_low_shelf=24.00,
        adv_50=200_000.0,
        recent_volume=220_000.0,  # 1.1x ADV50 < 1.5x
    )

    assert candidate.is_qualified is False
    assert "INSUFFICIENT_VOLUME_EXPANSION" in candidate.rejection_reason


def test_base_hit_risk_geometry_rejection():
    """Rejection when (trigger - stop) / trigger > 4.0%."""
    setup = BaseHitSetup(price_floor=5.0, max_risk_geometry_pct=0.040)

    # 65D High = $50.00, Shelf low = $47.00 -> Stop = $46.99
    # Geometry = (50.01 - 46.99) / 50.01 = 3.02 / 50.01 = 6.04% > 4.0%
    candidate = setup.evaluate(
        symbol="WIDE_RANGE",
        current_price=50.05,
        highest_high_65=50.00,
        lowest_low_shelf=47.00,
        adv_50=200_000.0,
        recent_volume=350_000.0,
    )

    assert candidate.is_qualified is False
    assert "RISK_GEOMETRY_EXCEEDED" in candidate.rejection_reason
