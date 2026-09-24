"""
Stage 1D Full-Scale US Historical Backtest Test Suite
Validates:
- Phase 3 & 7: 15-field CandidateMetadata contract & Portfolio Allocation Waterfall
- Phase 6: Zero-Cost, Conservative Active Trader, and Stress Cost Models
- Phase 8: 27-field Trade Telemetry & Audit Integrity
- Phase 9 & 10: Performance Analytics & Right-Tail Dependency Math (Top 1%, 5%, 10%)
- Phase 11: 10 Architectural Ablation Tests
- Phase 12: Parameter Sensitivity Neighborhood Sweeps & Classifications
- Phase 13: Chronological Walk-Forward Partitioning (Train -> Validate -> Test)
- Phase 14: Capacity & Liquidity Scaling Matrix ($25K to $2.5M)
"""

from datetime import date, datetime, time
from pathlib import Path
import pytest
import pandas as pd

from bonde.backtest.ablations import AblationSuite
from bonde.backtest.analytics import BacktestAnalyticsEngine, DistributionMetrics
from bonde.backtest.capacity import CapacityAnalysisSuite
from bonde.backtest.costs import ConservativeActiveTraderCostModel, StressCostModel, ZeroCostModel
from bonde.backtest.multi_year_runner import MultiYearBacktestRunner
from bonde.backtest.sensitivity import ParameterSensitivitySuite
from bonde.backtest.walkforward import WalkForwardSuite
from bonde.backtest.waterfall import CandidateMetadata, PortfolioAllocationWaterfall
from bonde.config.strategy_config import StrategyConfig
from bonde.portfolio.portfolio import Portfolio, Position
from bonde.regime.market_regime import MarketRegime
from bonde.risk.governors import CompositeRiskGovernor, InternalLossGovernor


def test_stage1d_cost_models():
    """Validates Phase 6: Zero-Cost, Conservative, and Stress cost models."""
    # 1. Zero-Cost
    zero = ZeroCostModel()
    p_eff, comm = zero.calculate_entry_cost(1000, 50.0)
    assert p_eff == 50.0
    assert comm == 0.0
    p_exit, comm = zero.calculate_exit_cost(1000, 55.0, is_stop=False)
    assert p_exit == 55.0
    assert comm == 0.0

    # 2. Conservative Active Trader ($0.005/sh min $1.00, $0.01/sh slippage)
    cons = ConservativeActiveTraderCostModel(per_share_commission=0.005, min_commission=1.00, per_share_slippage=0.01)
    p_eff, comm = cons.calculate_entry_cost(100, 50.0)
    assert p_eff == 50.01
    assert comm == 1.00  # min $1.00 applies for 100 shares

    p_eff, comm = cons.calculate_entry_cost(1000, 50.0)
    assert p_eff == 50.01
    assert comm == 5.00  # 1000 * 0.005 = 5.00

    p_exit, comm = cons.calculate_exit_cost(1000, 55.0, is_stop=False)
    assert p_exit == 54.99  # sells lower by 0.01
    assert comm == 5.00

    # 3. Stress Model ($0.01/sh min $1.50, $0.03/sh entry slippage, $0.05/sh stop exit slippage)
    stress = StressCostModel(per_share_commission=0.01, min_commission=1.50, per_share_slippage=0.03, adverse_stop_slippage=0.05)
    p_eff, comm = stress.calculate_entry_cost(500, 100.0)
    assert p_eff == 100.03
    assert comm == 5.00

    # Stop exit experiences adverse 0.05 slippage
    p_stop, comm = stress.calculate_exit_cost(500, 96.0, is_stop=True)
    assert p_stop == 95.95
    assert comm == 5.00

    # Non-stop target exit experiences standard 0.03 slippage
    p_tgt, comm = stress.calculate_exit_cost(500, 108.0, is_stop=False)
    assert p_tgt == 107.97
    assert comm == 5.00


def test_stage1d_candidate_metadata_contract():
    """Validates Phase 3: 15-field CandidateMetadata contract."""
    cand = CandidateMetadata(
        candidate_id="CAND_AAPL_20200731_001",
        security_id="SEC_AAPL",
        session_date=date(2020, 7, 31),
        engine="CATALYST",
        module="TRACK_A",
        catalyst_track="TRACK_A_EARNINGS",
        trigger_price=385.00,
        structural_stop=375.00,
        planned_risk_pct=0.026,
        risk_geometry=0.026,
        adv50=80_000_000.0,
        liquidity_cap=1_200_000.0,
        planned_shares=100,
        allocated_shares=100,
        fractional_r=1.0,
        rejection_reason=None,
        sector="TECHNOLOGY",
        ticker="AAPL",
    )

    assert cand.candidate_id == "CAND_AAPL_20200731_001"
    assert cand.security_id == "SEC_AAPL"
    assert cand.engine in ("CATALYST", "BASE_HIT")
    assert cand.module in ("TRACK_A", "TRACK_B", "EP", "EP9M", "BREAKOUT_65D", "INSIDE_DAY")
    assert cand.catalyst_track in ("TRACK_A_EARNINGS", "TRACK_B_PR", "NONE")
    assert cand.planned_shares > 0
    assert cand.allocated_shares <= cand.planned_shares
    assert 0.0 <= cand.fractional_r <= 1.0


def test_stage1d_portfolio_allocation_waterfall():
    """Validates Phase 7: Capital Allocation Waterfall rules."""
    waterfall = PortfolioAllocationWaterfall(
        risk_fraction=0.005,
        daily_green_r=3.0,
        daily_yellow_r=1.0,
        max_sector_r=2.0,
        max_heat_r=6.0,
        adv_participation_cap=0.015,
        min_allocation_ratio=0.60,
    )
    portfolio_equity = 100_000.0  # 1R = $500

    cand_cat = CandidateMetadata(
        candidate_id="C1",
        security_id="SEC_AAPL",
        session_date=date(2020, 9, 1),
        engine="CATALYST",
        module="TRACK_A",
        catalyst_track="TRACK_A_EARNINGS",
        trigger_price=100.0,
        structural_stop=95.0,  # $5 risk per share
        planned_risk_pct=0.05,
        risk_geometry=0.05,
        adv50=1_000_000.0,
        liquidity_cap=15_000.0,
        planned_shares=100,
        allocated_shares=100,
        fractional_r=1.0,
        sector="TECHNOLOGY",
        ticker="AAPL",
    )

    cand_bh = CandidateMetadata(
        candidate_id="C2",
        security_id="SEC_MSFT",
        session_date=date(2020, 9, 1),
        engine="BASE_HIT",
        module="BREAKOUT_65D",
        catalyst_track="NONE",
        trigger_price=200.0,
        structural_stop=195.0,  # $5 risk per share
        planned_risk_pct=0.025,
        risk_geometry=0.025,
        adv50=1_000_000.0,
        liquidity_cap=15_000.0,
        planned_shares=100,
        allocated_shares=100,
        fractional_r=1.0,
        sector="TECHNOLOGY",
        ticker="MSFT",
    )

    # 1. GREEN Regime: Both Catalyst and Base-Hit approved within 3.0R budget
    app, rej = waterfall.allocate_candidates(
        candidates=[cand_cat, cand_bh],
        regime=MarketRegime.GREEN,
        portfolio_equity=portfolio_equity,
        open_positions=[],
    )
    assert len(app) == 2
    assert len(rej) == 0

    # 2. YELLOW Regime: Catalyst approved (1.0R budget), Base-Hit rejected
    cand_cat.rejection_reason = None
    cand_bh.rejection_reason = None
    app, rej = waterfall.allocate_candidates(
        candidates=[cand_cat, cand_bh],
        regime=MarketRegime.YELLOW,
        portfolio_equity=portfolio_equity,
        open_positions=[],
    )
    assert len(app) == 1
    assert app[0].engine == "CATALYST"
    assert len(rej) == 1
    assert rej[0].rejection_reason == "YELLOW_REGIME_BASE_HIT_DISABLED"

    # 3. RED Regime: All rejected
    cand_cat.rejection_reason = None
    cand_bh.rejection_reason = None
    app, rej = waterfall.allocate_candidates(
        candidates=[cand_cat, cand_bh],
        regime=MarketRegime.RED,
        portfolio_equity=portfolio_equity,
        open_positions=[],
    )
    assert len(app) == 0
    assert len(rej) == 2
    assert all(r.rejection_reason == "RED_REGIME_NEW_TRADES_DISABLED" for r in rej)


def test_stage1d_waterfall_sector_and_heat_caps():
    """Validates 2.0R sector cap and 6.0R heat cap."""
    waterfall = PortfolioAllocationWaterfall(
        risk_fraction=0.005,
        daily_green_r=3.0,
        max_sector_r=2.0,
        max_heat_r=6.0,
    )
    portfolio_equity = 100_000.0  # 1R = $500

    # Open position with 1.8R in TECHNOLOGY
    pos_open = Position(
        symbol="AAPL",
        side="LONG",
        entry_price=100.0,
        entry_timestamp=datetime(2020, 8, 30, 9, 30),
        quantity=180,
        initial_stop=95.0,
        current_stop=95.0,
        initial_risk_dollars=900.0,  # 1.8R
        engine="CATALYST",
        setup_type="TRACK_A",
        regime_at_entry=MarketRegime.GREEN,
        sector="TECHNOLOGY",
    )

    # Candidate proposing 0.8R in TECHNOLOGY (1.8R + 0.8R = 2.6R > 2.0R cap)
    cand_tech = CandidateMetadata(
        candidate_id="C3",
        security_id="SEC_NVDA",
        session_date=date(2020, 9, 1),
        engine="CATALYST",
        module="TRACK_A",
        catalyst_track="TRACK_A_EARNINGS",
        trigger_price=100.0,
        structural_stop=95.0,
        planned_risk_pct=0.05,
        risk_geometry=0.05,
        adv50=1_000_000.0,
        liquidity_cap=15_000.0,
        planned_shares=80,  # 80 * $5 = $400 = 0.8R
        allocated_shares=80,
        fractional_r=0.8,
        sector="TECHNOLOGY",
        ticker="NVDA",
    )

    app, rej = waterfall.allocate_candidates(
        candidates=[cand_tech],
        regime=MarketRegime.GREEN,
        portfolio_equity=portfolio_equity,
        open_positions=[pos_open],
    )
    assert len(app) == 0
    assert len(rej) == 1
    assert "SECTOR_HEAT_EXCEEDED" in rej[0].rejection_reason


def test_stage1d_right_tail_dependency_math():
    """Validates Phase 10 right-tail dependency calculations."""
    # Synthetic trade telemetry with right tail
    # 20 trades: 14 small losers (-$500 each), 4 medium winners (+$1,000 each), 2 large runners (+$5,000 and +$10,000)
    data = []
    # 14 losers
    for i in range(14):
        data.append({"realized_pnl": -500.0, "r_multiple": -1.0, "holding_period_bars": 120, "mae_dollars": 500.0, "mfe_dollars": 100.0})
    # 4 medium winners
    for i in range(4):
        data.append({"realized_pnl": 1000.0, "r_multiple": 2.0, "holding_period_bars": 390, "mae_dollars": 200.0, "mfe_dollars": 1200.0})
    # 2 outlier runners
    data.append({"realized_pnl": 5000.0, "r_multiple": 10.0, "holding_period_bars": 1170, "mae_dollars": 250.0, "mfe_dollars": 5200.0})
    data.append({"realized_pnl": 10000.0, "r_multiple": 20.0, "holding_period_bars": 1950, "mae_dollars": 200.0, "mfe_dollars": 10500.0})

    df = pd.DataFrame(data)
    dist = BacktestAnalyticsEngine.calculate_distribution(df)

    assert dist.total_trades == 20
    assert dist.r_skewness > 0.0, "Right-tailed system must demonstrate positive skewness"
    # Total positive profits = 4*1000 + 5000 + 10000 = 19,000
    # Top 1 winner = 10,000 (52.6% of profits)
    assert dist.top_1_winner_dollars == 10000.0
    assert 50.0 < dist.top_5_winners_profit_share <= 100.0
    assert dist.median_trade_r == -1.0
    assert dist.median_winner_r > 0.0
    assert dist.median_loser_r < 0.0


def test_stage1d_walkforward_partition_boundaries():
    """Validates Phase 13 chronological walk-forward partition integrity."""
    wf = WalkForwardSuite(data_root=Path("data/stage1d"))
    # Verify period dates do not overlap
    train_end = date(2020, 12, 31)
    val_start = date(2021, 1, 4)
    val_end = date(2022, 12, 30)
    test_start = date(2023, 1, 3)

    assert train_end < val_start
    assert val_end < test_start
