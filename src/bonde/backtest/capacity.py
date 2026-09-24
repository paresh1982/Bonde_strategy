"""
Capacity & Liquidity Scaling Analysis Suite (Phase 14)
Simulates strategy scaling across 8 hypothetical account equity levels:
$25K, $50K, $100K, $250K, $500K, $1M, $1.5M, $2.5M.
Measures:
- % trades fully sized (1.0R)
- % fractional trades (< 1.0R allocated due to 1.5% ADV ceiling)
- % rejected for liquidity (< 0.60R minimum viable allocation)
- Average ADV participation %
- Annual turnover
- Slippage cost
- Expectancy degradation
- CAGR degradation
"""

from dataclasses import dataclass
from pathlib import Path
from typing import Dict, List, Optional, Tuple
import pandas as pd

from .analytics import BacktestAnalyticsEngine, PerformanceSummary
from .costs import ConservativeActiveTraderCostModel
from .multi_year_runner import MultiYearBacktestRunner


@dataclass
class CapacityLevelResult:
    account_size_dollars: float
    account_size_label: str
    total_candidates: int
    fully_sized_trades_pct: float
    fractional_trades_pct: float
    liquidity_rejections_pct: float
    avg_participation_pct: float
    annual_turnover: float
    total_slippage_cost: float
    expectancy_r: float
    cagr_pct: float
    expectancy_degradation_pct: float


class CapacityAnalysisSuite:
    """Executes capacity scaling tests across varying capital baselines."""

    def __init__(self, data_root: Path = Path("data/stage1d")):
        self.data_root = data_root

    def run_capacity_analysis(self) -> Tuple[List[CapacityLevelResult], pd.DataFrame]:
        equity_tiers = [
            (25_000.0, "$25K"),
            (50_000.0, "$50K"),
            (100_000.0, "$100K (Baseline)"),
            (250_000.0, "$250K"),
            (500_000.0, "$500K"),
            (1_000_000.0, "$1.0M"),
            (1_500_000.0, "$1.5M"),
            (2_500_000.0, "$2.5M"),
        ]

        cost_model = ConservativeActiveTraderCostModel()
        results: List[CapacityLevelResult] = []
        baseline_expectancy: Optional[float] = None

        for eq_size, label in equity_tiers:
            runner = MultiYearBacktestRunner(
                data_root=self.data_root,
                initial_equity=eq_size,
                cost_scenario=cost_model,
            )
            runner.run_backtest()
            trades_df = runner.get_trades_dataframe()
            equity_df = runner.get_equity_dataframe()
            cand_df = runner.get_candidates_dataframe()
            rej_df = runner.get_rejections_dataframe()

            summary = BacktestAnalyticsEngine.calculate_performance(
                trades_df=trades_df,
                equity_df=equity_df,
                name=label,
                initial_equity=eq_size,
            )

            if baseline_expectancy is None and eq_size == 100_000.0:
                baseline_expectancy = summary.expectancy_r
            elif baseline_expectancy is None:
                baseline_expectancy = summary.expectancy_r

            # Sizing breakdown
            n_cand = len(cand_df) if not cand_df.empty else 1
            if not cand_df.empty:
                approved_cands = cand_df[cand_df["rejection_reason"].isna()]
                n_app = len(approved_cands)
                full_count = len(approved_cands[approved_cands["fractional_r"] >= 0.99])
                frac_count = len(approved_cands[approved_cands["fractional_r"] < 0.99])

                liq_rejs = rej_df[rej_df["rejection_reason"].str.contains("BELOW_MIN_VIABLE|INSUFFICIENT", na=False)]
                liq_count = len(liq_rejs)

                pct_full = (full_count / n_app * 100.0) if n_app > 0 else 0.0
                pct_frac = (frac_count / n_app * 100.0) if n_app > 0 else 0.0
                pct_liq_rej = (liq_count / n_cand * 100.0) if n_cand > 0 else 0.0

                # Avg participation
                avg_part = float((approved_cands["allocated_shares"] / approved_cands["adv50"]).mean() * 100.0) if n_app > 0 else 0.0
            else:
                pct_full = 100.0
                pct_frac = 0.0
                pct_liq_rej = 0.0
                avg_part = 0.50

            deg_pct = 0.0
            if baseline_expectancy and baseline_expectancy > 0:
                deg_pct = round(((baseline_expectancy - summary.expectancy_r) / baseline_expectancy) * 100.0, 2)

            results.append(
                CapacityLevelResult(
                    account_size_dollars=eq_size,
                    account_size_label=label,
                    total_candidates=n_cand,
                    fully_sized_trades_pct=round(pct_full, 1),
                    fractional_trades_pct=round(pct_frac, 1),
                    liquidity_rejections_pct=round(pct_liq_rej, 1),
                    avg_participation_pct=round(avg_part, 2),
                    annual_turnover=summary.annual_turnover,
                    total_slippage_cost=summary.total_slippage_cost,
                    expectancy_r=summary.expectancy_r,
                    cagr_pct=summary.cagr_pct,
                    expectancy_degradation_pct=deg_pct,
                )
            )

        df = pd.DataFrame([r.__dict__ for r in results])
        return results, df
