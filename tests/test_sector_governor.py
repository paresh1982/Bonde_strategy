"""
Unit Tests for Sector & Correlation Governor (D5, Section 10)
Enforces max 2.0R uncushioned risk in the same industry group and cushion unlock.
"""

from datetime import datetime
from bonde.data.models import NY_TZ
from bonde.portfolio.portfolio import Position
from bonde.regime.market_regime import MarketRegime
from bonde.risk.governors import SectorGovernor


def test_sector_governor_enforces_2r_cap():
    """Sector governor allows up to 2.0R uncushioned risk, then rejects."""
    governor = SectorGovernor(max_sector_r=2.0)
    unit_1r_dollars = 1000.0

    # Position 1: 1.0R in SEMICONDUCTORS
    pos1 = Position(
        symbol="NVDA",
        side="LONG",
        entry_price=100.0,
        entry_timestamp=datetime(2026, 1, 5, 9, 36, tzinfo=NY_TZ),
        quantity=500,
        initial_stop=98.0,
        current_stop=98.0,
        initial_risk_dollars=1000.0,  # 1.0R
        engine="CATALYST",
        setup_type="ORB",
        regime_at_entry=MarketRegime.GREEN,
        sector="SEMICONDUCTORS",
    )

    # Proposed trade: 1.0R in SEMICONDUCTORS (Total = 2.0R <= 2.0R -> ALLOWED)
    allowed1, reason1 = governor.evaluate(
        symbol="AMD",
        planned_risk_dollars=1000.0,
        unit_1r_dollars=unit_1r_dollars,
        regime=MarketRegime.GREEN,
        sector="SEMICONDUCTORS",
        open_positions=[pos1],
    )
    assert allowed1 is True
    assert reason1 is None

    # Position 2 added: now 2.0R open in SEMICONDUCTORS
    pos2 = Position(
        symbol="AMD",
        side="LONG",
        entry_price=80.0,
        entry_timestamp=datetime(2026, 1, 5, 9, 38, tzinfo=NY_TZ),
        quantity=500,
        initial_stop=78.0,
        current_stop=78.0,
        initial_risk_dollars=1000.0,  # 1.0R
        engine="CATALYST",
        setup_type="ORB",
        regime_at_entry=MarketRegime.GREEN,
        sector="SEMICONDUCTORS",
    )

    # Proposed trade 3: another 1.0R in SEMICONDUCTORS (Total = 3.0R > 2.0R -> REJECTED)
    allowed2, reason2 = governor.evaluate(
        symbol="AVGO",
        planned_risk_dollars=1000.0,
        unit_1r_dollars=unit_1r_dollars,
        regime=MarketRegime.GREEN,
        sector="SEMICONDUCTORS",
        open_positions=[pos1, pos2],
    )
    assert allowed2 is False
    assert "SECTOR_HEAT_EXCEEDED" in (reason2 or "")


def test_sector_governor_cushion_unlock():
    """Cushioned position (stop at Breakeven, open risk = 0) reopens sector capacity."""
    governor = SectorGovernor(max_sector_r=2.0)
    unit_1r_dollars = 1000.0

    # Position 1 in SEMICONDUCTORS has hit +2.0R and is cushioned!
    pos1 = Position(
        symbol="NVDA",
        side="LONG",
        entry_price=100.0,
        entry_timestamp=datetime(2026, 1, 5, 9, 36, tzinfo=NY_TZ),
        quantity=500,
        initial_stop=98.0,
        current_stop=100.01,  # Breakeven stop!
        initial_risk_dollars=1000.0,
        engine="CATALYST",
        setup_type="ORB",
        regime_at_entry=MarketRegime.GREEN,
        sector="SEMICONDUCTORS",
        is_cushioned=True,
    )

    # Position 2 is uncushioned (1.0R)
    pos2 = Position(
        symbol="AMD",
        side="LONG",
        entry_price=80.0,
        entry_timestamp=datetime(2026, 1, 5, 9, 38, tzinfo=NY_TZ),
        quantity=500,
        initial_stop=78.0,
        current_stop=78.0,
        initial_risk_dollars=1000.0,
        engine="CATALYST",
        setup_type="ORB",
        regime_at_entry=MarketRegime.GREEN,
        sector="SEMICONDUCTORS",
        is_cushioned=False,
    )

    # Total uncushioned risk in SEMICONDUCTORS is only 1.0R (NVDA is 0.0R)
    # Proposed trade 3: 1.0R in SEMICONDUCTORS (1.0 + 1.0 = 2.0R <= 2.0R -> ALLOWED)
    allowed, reason = governor.evaluate(
        symbol="AVGO",
        planned_risk_dollars=1000.0,
        unit_1r_dollars=unit_1r_dollars,
        regime=MarketRegime.GREEN,
        sector="SEMICONDUCTORS",
        open_positions=[pos1, pos2],
    )
    assert allowed is True
    assert reason is None
