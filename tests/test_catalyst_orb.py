"""
Unit Tests for Opening Range Breakout (ORB) & Catalyst Setup (Test 2, Section 6, Section 12)
"""

from datetime import datetime
from bonde.data.models import Bar, NY_TZ
from bonde.setups.catalyst import CatalystORBSetup, InsideDaySetup


def test_orb_geometry_pass():
    """Valid 5-minute ORB range <= 4.0% qualifies."""
    setup = CatalystORBSetup(max_risk_geometry_pct=0.040, collar_cents=0.10, tick_size=0.01)

    # 5 bars from 09:30 to 09:34. ORH = 100.00, ORL = 98.00. Range = 2.0%
    bars = [
        Bar(datetime(2026, 1, 5, 9, 30, tzinfo=NY_TZ), "ORB_PASS", 98.50, 99.20, 98.00, 99.00, 20_000),
        Bar(datetime(2026, 1, 5, 9, 31, tzinfo=NY_TZ), "ORB_PASS", 99.00, 99.50, 98.50, 99.20, 15_000),
        Bar(datetime(2026, 1, 5, 9, 32, tzinfo=NY_TZ), "ORB_PASS", 99.20, 99.80, 99.00, 99.60, 10_000),
        Bar(datetime(2026, 1, 5, 9, 33, tzinfo=NY_TZ), "ORB_PASS", 99.60, 100.00, 99.30, 99.70, 25_000),
        Bar(datetime(2026, 1, 5, 9, 34, tzinfo=NY_TZ), "ORB_PASS", 99.70, 99.90, 99.40, 99.85, 12_000),
    ]

    candidate = setup.evaluate_first_5_minutes("ORB_PASS", bars)

    assert candidate.is_qualified is True
    assert candidate.orh == 100.00
    assert candidate.orl == 98.00
    assert candidate.trigger_price == 100.01
    assert candidate.stop_price == 97.99
    assert candidate.limit_price == 100.11  # +$0.10 collar
    assert candidate.risk_geometry_pct == 0.02  # 2.0% <= 4.0%
    assert candidate.rejection_reason is None


def test_orb_geometry_rejection():
    """Test 2: ORB range > 4.0% triggers rejection (ORB_GEOMETRY_FAIL)."""
    setup = CatalystORBSetup(max_risk_geometry_pct=0.040)

    # 5 bars where ORH = 100.00, ORL = 94.00. Range = (100 - 94) / 100 = 6.0% > 4.0%
    bars = [
        Bar(datetime(2026, 1, 5, 9, 30, tzinfo=NY_TZ), "ORB_FAIL", 98.00, 100.00, 95.00, 96.00, 50_000),
        Bar(datetime(2026, 1, 5, 9, 31, tzinfo=NY_TZ), "ORB_FAIL", 96.00, 97.00, 94.00, 95.00, 40_000),
        Bar(datetime(2026, 1, 5, 9, 32, tzinfo=NY_TZ), "ORB_FAIL", 95.00, 96.00, 94.50, 95.50, 20_000),
        Bar(datetime(2026, 1, 5, 9, 33, tzinfo=NY_TZ), "ORB_FAIL", 95.50, 98.00, 95.00, 97.00, 30_000),
        Bar(datetime(2026, 1, 5, 9, 34, tzinfo=NY_TZ), "ORB_FAIL", 97.00, 98.50, 96.50, 98.00, 25_000),
    ]

    candidate = setup.evaluate_first_5_minutes("ORB_FAIL", bars)

    assert candidate.is_qualified is False
    assert candidate.risk_geometry_pct == 0.06
    assert "ORB_GEOMETRY_FAIL" in (candidate.rejection_reason or "")


def test_inside_day_setup():
    """Inside day compression evaluation."""
    setup = InsideDaySetup(max_risk_geometry_pct=0.040, collar_cents=0.10, tick_size=0.01)

    mother_bar = Bar(datetime(2026, 1, 4, 16, 0, tzinfo=NY_TZ), "ID_TEST", 50.0, 53.0, 49.0, 52.0, 500_000)
    inside_bar = Bar(datetime(2026, 1, 5, 16, 0, tzinfo=NY_TZ), "ID_TEST", 51.0, 52.5, 50.5, 51.8, 200_000)

    candidate = setup.evaluate("ID_TEST", mother_bar, inside_bar)

    assert candidate.is_qualified is True
    assert candidate.trigger_price == 52.51
    assert candidate.stop_price == 50.49
    assert candidate.limit_price == 52.61
    assert candidate.risk_geometry_pct < 0.040
