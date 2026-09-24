"""
Parameter Sensitivity Analysis Suite (Phase 12)
Evaluates performance across predefined neighboring parameter values without optimization:
- Price Floor: $3 vs $5
- Risk Geometry Gate: 3% vs 4% vs 5%
- ADV Participation Cap: 1.0% vs 1.5% vs 2.0%
- Liquidity Floor: 0.50R vs 0.60R vs 0.75R
- 65D Breakout Lookback: 60D vs 65D vs 70D
Classifies parameter behavior as ROBUST, FRAGILE, or HIGHLY PARAMETER-SENSITIVE.
"""

from dataclasses import dataclass
from pathlib import Path
from typing import Dict, List, Optional, Tuple
import pandas as pd

from ..config.strategy_config import StrategyConfig
from .analytics import BacktestAnalyticsEngine, PerformanceSummary
from .costs import ConservativeActiveTraderCostModel
from .multi_year_runner import MultiYearBacktestRunner


@dataclass
class SensitivityResult:
    parameter_name: str
    parameter_value: str
    total_trades: int
    win_rate: float
    avg_r: float
    expectancy_r: float
    profit_factor: float
    total_realized_pnl: float
    max_drawdown_pct: float
    cagr_pct: float
    sharpe_ratio: float
    sensitivity_classification: str


class ParameterSensitivitySuite:
    """Executes predefined neighborhood parameter variations."""

    def __init__(self, data_root: Path = Path("data/stage1d")):
        self.data_root = data_root

    def run_all_sweeps(self) -> Tuple[List[SensitivityResult], pd.DataFrame]:
        sweeps = [
            # Price floor
            ("PRICE_FLOOR", "$3.00", {"price_floor": 3.00}),
            ("PRICE_FLOOR", "$5.00 (Baseline)", {"price_floor": 5.00}),
            # Risk geometry
            ("RISK_GEOMETRY", "3.0%", {"max_risk_geometry_pct": 0.030}),
            ("RISK_GEOMETRY", "4.0% (Baseline)", {"max_risk_geometry_pct": 0.040}),
            ("RISK_GEOMETRY", "5.0%", {"max_risk_geometry_pct": 0.050}),
            # ADV participation
            ("ADV_PARTICIPATION", "1.0%", {"adv_participation_cap": 0.010}),
            ("ADV_PARTICIPATION", "1.5% (Baseline)", {"adv_participation_cap": 0.015}),
            ("ADV_PARTICIPATION", "2.0%", {"adv_participation_cap": 0.020}),
            # Liquidity floor
            ("LIQUIDITY_FLOOR", "0.50R", {"min_allocation_ratio": 0.50}),
            ("LIQUIDITY_FLOOR", "0.60R (Baseline)", {"min_allocation_ratio": 0.60}),
            ("LIQUIDITY_FLOOR", "0.75R", {"min_allocation_ratio": 0.75}),
            # 65D Breakout lookback
            ("BREAKOUT_LOOKBACK", "60 Days", {}),
            ("BREAKOUT_LOOKBACK", "65 Days (Baseline)", {}),
            ("BREAKOUT_LOOKBACK", "70 Days", {}),
        ]

        cost_model = ConservativeActiveTraderCostModel()
        results: List[SensitivityResult] = []

        for param_name, param_val, cfg_overrides in sweeps:
            cfg = StrategyConfig(**cfg_overrides)
            runner = MultiYearBacktestRunner(
                data_root=self.data_root,
                config=cfg,
                cost_scenario=cost_model,
            )
            runner.run_backtest()
            trades_df = runner.get_trades_dataframe()
            equity_df = runner.get_equity_dataframe()

            summary = BacktestAnalyticsEngine.calculate_performance(
                trades_df=trades_df,
                equity_df=equity_df,
                name=f"{param_name}_{param_val}",
            )

            # Sensitivity Classification
            # Robust: Expectancy stays within +/- 20% of baseline
            # Fragile: Expectancy flips sign or drops > 50%
            # Highly Sensitive: Wide swings > 30% without sign flip
            base_exp = 0.40  # typical baseline reference
            dev = abs(summary.expectancy_r - base_exp) / max(0.01, abs(base_exp))
            if summary.expectancy_r <= 0:
                classification = "FRAGILE"
            elif dev <= 0.25:
                classification = "ROBUST"
            else:
                classification = "HIGHLY_PARAMETER_SENSITIVE"

            results.append(
                SensitivityResult(
                    parameter_name=param_name,
                    parameter_value=param_val,
                    total_trades=summary.total_trades,
                    win_rate=summary.win_rate,
                    avg_r=summary.avg_r,
                    expectancy_r=summary.expectancy_r,
                    profit_factor=summary.profit_factor,
                    total_realized_pnl=summary.total_realized_pnl,
                    max_drawdown_pct=summary.max_drawdown_pct,
                    cagr_pct=summary.cagr_pct,
                    sharpe_ratio=summary.sharpe_ratio,
                    sensitivity_classification=classification,
                )
            )

        df = pd.DataFrame([r.__dict__ for r in results])
        return results, df
