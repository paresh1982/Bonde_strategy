"""
Walk-Forward Validation Suite (Phase 13)
Implements chronological partitioning without trade shuffling:
- TRAIN (In-Sample): 2018-01-02 to 2020-12-31
- VALIDATE (Validation): 2021-01-04 to 2022-12-30
- TEST (Out-of-Sample): 2023-01-03 to 2023-12-29
Evaluates out-of-sample stability and degradation.
"""

from dataclasses import dataclass
from datetime import date
from pathlib import Path
from typing import Dict, List, Optional, Tuple
import pandas as pd

from .analytics import BacktestAnalyticsEngine, PerformanceSummary
from .costs import ConservativeActiveTraderCostModel
from .multi_year_runner import MultiYearBacktestRunner


@dataclass
class WalkForwardPeriodResult:
    phase_name: str
    date_range: str
    start_date: str
    end_date: str
    total_trades: int
    win_rate: float
    avg_r: float
    expectancy_r: float
    profit_factor: float
    total_realized_pnl: float
    max_drawdown_pct: float
    cagr_pct: float
    sharpe_ratio: float


class WalkForwardSuite:
    """Executes chronological walk-forward partitions."""

    def __init__(self, data_root: Path = Path("data/stage1d")):
        self.data_root = data_root

    def run_walk_forward(self) -> Tuple[List[WalkForwardPeriodResult], pd.DataFrame]:
        periods = [
            ("TRAIN (In-Sample)", date(2018, 1, 2), date(2020, 12, 31)),
            ("VALIDATE (Validation)", date(2021, 1, 4), date(2022, 12, 30)),
            ("TEST (Out-of-Sample)", date(2023, 1, 3), date(2023, 12, 29)),
        ]

        cost_model = ConservativeActiveTraderCostModel()
        results: List[WalkForwardPeriodResult] = []

        for phase, s_dt, e_dt in periods:
            runner = MultiYearBacktestRunner(
                data_root=self.data_root,
                cost_scenario=cost_model,
            )
            runner.run_backtest(start_date=s_dt, end_date=e_dt)
            trades_df = runner.get_trades_dataframe()
            equity_df = runner.get_equity_dataframe()

            summary = BacktestAnalyticsEngine.calculate_performance(
                trades_df=trades_df,
                equity_df=equity_df,
                name=phase,
            )

            results.append(
                WalkForwardPeriodResult(
                    phase_name=phase,
                    date_range=f"{s_dt.isoformat()} to {e_dt.isoformat()}",
                    start_date=s_dt.isoformat(),
                    end_date=e_dt.isoformat(),
                    total_trades=summary.total_trades,
                    win_rate=summary.win_rate,
                    avg_r=summary.avg_r,
                    expectancy_r=summary.expectancy_r,
                    profit_factor=summary.profit_factor,
                    total_realized_pnl=summary.total_realized_pnl,
                    max_drawdown_pct=summary.max_drawdown_pct,
                    cagr_pct=summary.cagr_pct,
                    sharpe_ratio=summary.sharpe_ratio,
                )
            )

        df = pd.DataFrame([r.__dict__ for r in results])
        return results, df
