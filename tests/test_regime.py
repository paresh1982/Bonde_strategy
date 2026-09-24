"""
Unit Tests for Market Regime FSM & Governors (Test 7, D3, D4, Section 15)
"""

from datetime import datetime
from bonde.data.models import NY_TZ
from bonde.regime.market_regime import MarketRegime, StaticRegimeProvider
from bonde.risk.governors import RegimeGovernor


def test_regime_risk_fractions():
    """Validates Green (1.0%), Yellow (0.5%), and Red (0.0%) risk fractions."""
    schedule = {
        "2026-01-05": MarketRegime.GREEN,
        "2026-01-06": MarketRegime.YELLOW,
        "2026-01-07": MarketRegime.RED,
    }
    provider = StaticRegimeProvider(schedule=schedule)

    ts_green = datetime(2026, 1, 5, 10, 0, 0, tzinfo=NY_TZ)
    ts_yellow = datetime(2026, 1, 6, 10, 0, 0, tzinfo=NY_TZ)
    ts_red = datetime(2026, 1, 7, 10, 0, 0, tzinfo=NY_TZ)

    assert provider.get_regime(ts_green) == MarketRegime.GREEN
    assert provider.get_risk_fraction(ts_green) == 0.010

    assert provider.get_regime(ts_yellow) == MarketRegime.YELLOW
    assert provider.get_risk_fraction(ts_yellow) == 0.005

    assert provider.get_regime(ts_red) == MarketRegime.RED
    assert provider.get_risk_fraction(ts_red) == 0.000


def test_red_regime_rejects_new_trades():
    """Test 7: Red regime governor unconditionally rejects new trades."""
    governor = RegimeGovernor()

    allowed_green, reason_green = governor.evaluate(
        symbol="TEST",
        planned_risk_dollars=1000.0,
        unit_1r_dollars=1000.0,
        regime=MarketRegime.GREEN,
        sector="TECH",
        open_positions=[],
    )
    assert allowed_green is True
    assert reason_green is None

    allowed_red, reason_red = governor.evaluate(
        symbol="TEST",
        planned_risk_dollars=1000.0,
        unit_1r_dollars=1000.0,
        regime=MarketRegime.RED,
        sector="TECH",
        open_positions=[],
    )
    assert allowed_red is False
    assert reason_red == "RED_REGIME_NEW_TRADES_DISABLED"
