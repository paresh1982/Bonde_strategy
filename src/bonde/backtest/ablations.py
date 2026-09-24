"""
Architectural Ablation Suite (Phase 11)
Executes the 10 predefined ablations without altering other variables:
1. Without Market Monitor
2. Without 03:55 EOD Governor
3. Without +2R de-risking
4. Without <= 4% geometry gate
5. Without 10 EMA runner
6. Without 2R sector cap
7. Without Internal Loss Governor
8. Without liquidity participation cap
9. Without stop-limit collar
10. Without Catalyst seniority
"""

from dataclasses import dataclass
from pathlib import Path
from typing import Dict, List, Optional, Tuple
import pandas as pd

from .analytics import BacktestAnalyticsEngine, PerformanceSummary
from .costs import ConservativeActiveTraderCostModel
from .multi_year_runner import MultiYearBacktestRunner


@dataclass
class AblationResult:
    ablation_name: str
    description: str
    total_trades: int
    win_rate: float
    avg_r: float
    expectancy_r: float
    profit_factor: float
    total_realized_pnl: float
    max_drawdown_pct: float
    cagr_pct: float
    sharpe_ratio: float
    delta_expectancy_vs_baseline: float
    delta_pnl_vs_baseline: float


class AblationSuite:
    """Executes the 10 predefined architectural ablations against the multi-year dataset."""

    def __init__(self, data_root: Path = Path("data/stage1d")):
        self.data_root = data_root

    def run_all_ablations(self) -> Tuple[List[AblationResult], pd.DataFrame]:
        ablations_config = [
            ("BASELINE", "Full System Invariants Enforced", {}),
            ("NO_MARKET_MONITOR", "Market Monitor Disabled (Always GREEN)", {"enforce_market_monitor": False}),
            ("NO_EOD_GOVERNOR", "03:55 EOD Governor Disabled", {"enforce_eod_governor": False}),
            ("NO_DERISKING", "+2R Partial Exit & Breakeven Ratchet Disabled", {"enforce_derisking": False}),
            ("NO_GEOMETRY_GATE", "<= 4.0% Risk-Geometry Gate Disabled", {"enforce_geometry_gate": False}),
            ("NO_10EMA_RUNNER", "10 EMA Trailing for Cushioned Runners Disabled", {"enforce_10ema_runner": False}),
            ("NO_SECTOR_CAP", "2.0R Sector Concentration Cap Disabled", {"enforce_sector_cap": False}),
            ("NO_INTERNAL_GOVERNOR", "Internal Loss Governor (3-loss pause) Disabled", {"enforce_internal_governor": False}),
            ("NO_LIQUIDITY_CAP", "1.5% ADV Liquidity Participation Cap Disabled", {"enforce_liquidity_cap": False}),
            ("NO_COLLAR", "Stop-Limit Collar Disabled (Execution at Market)", {"enforce_collar": False}),
            ("NO_CATALYST_SENIORITY", "Catalyst Seniority Disabled (Equal Allocation Priority)", {"catalyst_seniority": False}),
        ]

        cost_model = ConservativeActiveTraderCostModel()
        results: List[AblationResult] = []
        baseline_summary: Optional[PerformanceSummary] = None

        for name, desc, kwargs in ablations_config:
            runner = MultiYearBacktestRunner(
                data_root=self.data_root,
                cost_scenario=cost_model,
                **kwargs
            )
            runner.run_backtest()
            trades_df = runner.get_trades_dataframe()
            equity_df = runner.get_equity_dataframe()

            summary = BacktestAnalyticsEngine.calculate_performance(
                trades_df=trades_df,
                equity_df=equity_df,
                name=name,
            )

            if name == "BASELINE":
                baseline_summary = summary
                delta_exp = 0.0
                delta_pnl = 0.0
            else:
                base_exp = baseline_summary.expectancy_r if baseline_summary else 0.0
                base_pnl = baseline_summary.total_realized_pnl if baseline_summary else 0.0
                delta_exp = round(summary.expectancy_r - base_exp, 3)
                delta_pnl = round(summary.total_realized_pnl - base_pnl, 2)

            results.append(
                AblationResult(
                    ablation_name=name,
                    description=desc,
                    total_trades=summary.total_trades,
                    win_rate=summary.win_rate,
                    avg_r=summary.avg_r,
                    expectancy_r=summary.expectancy_r,
                    profit_factor=summary.profit_factor,
                    total_realized_pnl=summary.total_realized_pnl,
                    max_drawdown_pct=summary.max_drawdown_pct,
                    cagr_pct=summary.cagr_pct,
                    sharpe_ratio=summary.sharpe_ratio,
                    delta_expectancy_vs_baseline=delta_exp,
                    delta_pnl_vs_baseline=delta_pnl,
                )
            )

        df = pd.DataFrame([r.__dict__ for r in results])
        return results, df
