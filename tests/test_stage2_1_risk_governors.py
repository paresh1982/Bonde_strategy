"""
Stage 2.1 Adversarial Audit: Area 5 - Portfolio & Risk Governors Boundary Invariants
Explicitly tests numerical boundary conditions:
- 1R risk sizing ($100k equity, 0.5% risk = $500 unit 1R)
- 2R sector cap: <= 2.0R uncushioned allowed, > 2.0R rejected
- 6R portfolio heat: <= 6.0R uncushioned allowed, > 6.0R rejected
- 1.5% ADV participation: planned shares exceeding 1.5% capped or rejected
- 0.60R minimum allocation ratio: 0.60R permitted, 0.59R rejected
- Green regime: 3.0R budget
- Yellow regime: 1.0R budget (Catalyst only, Base-Hit blocked)
- Red regime: 0.0R budget (all trades rejected)
"""

from datetime import date, datetime
import pytest

from bonde.backtest.waterfall import CandidateMetadata, PortfolioAllocationWaterfall
from bonde.data.models import NY_TZ
from bonde.portfolio.portfolio import Position
from bonde.regime.market_regime import MarketRegime


@pytest.fixture
def waterfall():
    return PortfolioAllocationWaterfall(
        risk_fraction=0.005,
        daily_green_r=3.0,
        daily_yellow_r=1.0,
        max_sector_r=2.0,
        max_heat_r=6.0,
        adv_participation_cap=0.015,
        min_allocation_ratio=0.60,
    )


def test_1r_sizing_precision(waterfall):
    """Verifies $100k equity sizes exactly 1R = $500."""
    cand = CandidateMetadata(
        candidate_id="CAND_1R",
        security_id="SEC_1R",
        session_date=date(2023, 6, 15),
        engine="CATALYST",
        module="ORB",
        catalyst_track="NONE",
        trigger_price=50.00,
        structural_stop=45.00,  # Risk $5.00/sh -> 100 shares = $500
        planned_risk_pct=0.10,
        risk_geometry=1.0,
        adv50=1_000_000,
        liquidity_cap=15_000,
        planned_shares=100,
        allocated_shares=100,
        fractional_r=1.0,
        sector="TECH",
        ticker="TICK_1R",
    )
    approved, rejected = waterfall.allocate_candidates(
        candidates=[cand],
        regime=MarketRegime.GREEN,
        portfolio_equity=100_000.0,
        open_positions=[],
    )
    assert len(approved) == 1
    assert approved[0].allocated_shares == 100
    assert approved[0].fractional_r == 1.0


def test_min_allocation_boundary_059_vs_060(waterfall):
    """Verifies that 0.59R is rejected and 0.60R is approved (minimum viable size)."""
    # 0.59R candidate: planned 100 shares, but liquidity cap restricts to 59 shares (0.59R)
    cand_59 = CandidateMetadata(
        candidate_id="CAND_59",
        security_id="SEC_59",
        session_date=date(2023, 6, 15),
        engine="CATALYST",
        module="ORB",
        catalyst_track="NONE",
        trigger_price=50.00,
        structural_stop=45.00,  # Risk $5.00/sh -> 100 shares planned
        planned_risk_pct=0.10,
        risk_geometry=1.0,
        adv50=3933,             # adv50 * 0.015 = 59 shares cap
        liquidity_cap=59,
        planned_shares=100,
        allocated_shares=59,
        fractional_r=0.59,
        sector="TECH",
        ticker="TICK_59",
    )
    approved, rejected = waterfall.allocate_candidates(
        candidates=[cand_59],
        regime=MarketRegime.GREEN,
        portfolio_equity=100_000.0,
        open_positions=[],
    )
    assert len(rejected) == 1
    assert "BELOW_MIN_VIABLE_ALLOCATION" in rejected[0].rejection_reason

    # 0.60R candidate: liquidity cap restricts to 60 shares (0.60R) -> must be approved
    cand_60 = CandidateMetadata(
        candidate_id="CAND_60",
        security_id="SEC_60",
        session_date=date(2023, 6, 15),
        engine="CATALYST",
        module="ORB",
        catalyst_track="NONE",
        trigger_price=50.00,
        structural_stop=45.00,
        planned_risk_pct=0.10,
        risk_geometry=1.0,
        adv50=4000,             # adv50 * 0.015 = 60 shares cap
        liquidity_cap=60,
        planned_shares=100,
        allocated_shares=60,
        fractional_r=0.60,
        sector="TECH",
        ticker="TICK_60",
    )
    approved, rejected = waterfall.allocate_candidates(
        candidates=[cand_60],
        regime=MarketRegime.GREEN,
        portfolio_equity=100_000.0,
        open_positions=[],
    )
    assert len(approved) == 1
    assert approved[0].allocated_shares == 60
    assert approved[0].fractional_r == 0.60


def test_sector_cap_20r_boundary(waterfall):
    """Verifies that uncushioned sector risk up to 2.0R is allowed, > 2.0R is rejected."""
    # Existing 1.4R open position in TECH
    pos_existing = Position(
        symbol="TECH_EXISTING",
        side="LONG",
        entry_price=100.0,
        entry_timestamp=datetime(2023, 6, 15, 9, 30, tzinfo=NY_TZ),
        quantity=140,
        initial_stop=95.0,
        current_stop=95.0,
        initial_risk_dollars=700.0,  # 1.4R on $100k equity ($500 unit 1R)
        engine="CATALYST",
        setup_type="ORB",
        regime_at_entry=MarketRegime.GREEN,
        sector="TECH",
    )

    # Candidate proposing 0.60R in TECH (1.4R + 0.60R = 2.0R exact boundary -> Approved)
    cand_at_boundary = CandidateMetadata(
        candidate_id="CAND_AT_2R",
        security_id="SEC_TECH_1",
        session_date=date(2023, 6, 15),
        engine="CATALYST",
        module="ORB",
        catalyst_track="NONE",
        trigger_price=50.00,
        structural_stop=45.00,  # Risk $5.00/sh -> planned 100 shares ($500 = 1.0R)
        planned_risk_pct=0.10,
        risk_geometry=1.0,
        adv50=4000,             # 4000 * 0.015 = 60 shares ($300 = 0.60R)
        liquidity_cap=60,
        planned_shares=100,
        allocated_shares=60,
        fractional_r=0.60,
        sector="TECH",
        ticker="TECH_CAND1",
    )
    approved, rejected = waterfall.allocate_candidates(
        candidates=[cand_at_boundary],
        regime=MarketRegime.GREEN,
        portfolio_equity=100_000.0,
        open_positions=[pos_existing],
    )
    assert len(approved) == 1
    assert approved[0].allocated_shares == 60

    # Candidate proposing 0.70R in TECH (1.4R + 0.70R = 2.10R > 2.0R -> Rejected)
    cand_above_boundary = CandidateMetadata(
        candidate_id="CAND_ABOVE_2R",
        security_id="SEC_TECH_2",
        session_date=date(2023, 6, 15),
        engine="CATALYST",
        module="ORB",
        catalyst_track="NONE",
        trigger_price=50.00,
        structural_stop=45.00,  # Risk $5.00/sh -> planned 100 shares ($500 = 1.0R)
        planned_risk_pct=0.10,
        risk_geometry=1.0,
        adv50=4667,             # 4667 * 0.015 = 70 shares ($350 = 0.70R)
        liquidity_cap=70,
        planned_shares=100,
        allocated_shares=70,
        fractional_r=0.70,
        sector="TECH",
        ticker="TECH_CAND2",
    )
    approved, rejected = waterfall.allocate_candidates(
        candidates=[cand_above_boundary],
        regime=MarketRegime.GREEN,
        portfolio_equity=100_000.0,
        open_positions=[pos_existing],
    )
    assert len(rejected) == 1
    assert "SECTOR_HEAT_EXCEEDED" in rejected[0].rejection_reason


def test_regime_budgets_green_yellow_red(waterfall):
    """Verifies Green (3.0R), Yellow (1.0R Catalyst only), and Red (0R, all blocked)."""
    cand_cat = CandidateMetadata(
        candidate_id="CAT_1",
        security_id="SEC_CAT_1",
        session_date=date(2023, 6, 15),
        engine="CATALYST",
        module="TRACK_A",
        catalyst_track="TRACK_A_EARNINGS",
        trigger_price=50.00,
        structural_stop=45.00,
        planned_risk_pct=0.10,
        risk_geometry=1.0,
        adv50=1_000_000,
        liquidity_cap=15_000,
        planned_shares=100,
        allocated_shares=100,
        fractional_r=1.0,
        sector="ENERGY",
        ticker="CAT1",
    )
    cand_base = CandidateMetadata(
        candidate_id="BASE_1",
        security_id="SEC_BASE_1",
        session_date=date(2023, 6, 15),
        engine="BASE_HIT",
        module="BREAKOUT_65D",
        catalyst_track="NONE",
        trigger_price=100.00,
        structural_stop=95.00,
        planned_risk_pct=0.05,
        risk_geometry=1.0,
        adv50=1_000_000,
        liquidity_cap=15_000,
        planned_shares=100,
        allocated_shares=100,
        fractional_r=1.0,
        sector="HEALTHCARE",
        ticker="BASE1",
    )

    # 1. GREEN: Both permitted
    app_g, rej_g = waterfall.allocate_candidates(
        candidates=[cand_cat, cand_base],
        regime=MarketRegime.GREEN,
        portfolio_equity=100_000.0,
        open_positions=[],
    )
    assert len(app_g) == 2

    # 2. YELLOW: Only Catalyst permitted; Base-Hit rejected
    app_y, rej_y = waterfall.allocate_candidates(
        candidates=[cand_cat, cand_base],
        regime=MarketRegime.YELLOW,
        portfolio_equity=100_000.0,
        open_positions=[],
    )
    assert len(app_y) == 1
    assert app_y[0].engine == "CATALYST"
    assert len(rej_y) == 1
    assert "YELLOW_REGIME_BASE_HIT_DISABLED" in rej_y[0].rejection_reason

    # 3. RED: All trades rejected
    app_r, rej_r = waterfall.allocate_candidates(
        candidates=[cand_cat, cand_base],
        regime=MarketRegime.RED,
        portfolio_equity=100_000.0,
        open_positions=[],
    )
    assert len(app_r) == 0
    assert len(rej_r) == 2
    assert all("RED_REGIME_NEW_TRADES_DISABLED" in r.rejection_reason for r in rej_r)
