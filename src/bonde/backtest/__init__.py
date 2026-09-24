"""
Stage 1D Full-Scale Historical Backtesting Framework
"""

from .costs import (
    BaseCostScenario,
    ZeroCostModel,
    ConservativeActiveTraderCostModel,
    StressCostModel,
)
from .waterfall import (
    CandidateMetadata,
    PortfolioAllocationWaterfall,
)
from .analytics import (
    BacktestAnalyticsEngine,
    PerformanceSummary,
    DistributionMetrics,
)
from .multi_year_runner import (
    MultiYearBacktestRunner,
    DailyUniverseSnapshot,
    DailyPortfolioState,
)
from .ablations import AblationSuite, AblationResult
from .sensitivity import ParameterSensitivitySuite, SensitivityResult
from .walkforward import WalkForwardSuite, WalkForwardPeriodResult
from .capacity import CapacityAnalysisSuite, CapacityLevelResult
from .runner import Stage1DBacktestOrchestrator

__all__ = [
    "BaseCostScenario",
    "ZeroCostModel",
    "ConservativeActiveTraderCostModel",
    "StressCostModel",
    "CandidateMetadata",
    "PortfolioAllocationWaterfall",
    "BacktestAnalyticsEngine",
    "PerformanceSummary",
    "DistributionMetrics",
    "MultiYearBacktestRunner",
    "DailyUniverseSnapshot",
    "DailyPortfolioState",
    "AblationSuite",
    "AblationResult",
    "ParameterSensitivitySuite",
    "SensitivityResult",
    "WalkForwardSuite",
    "WalkForwardPeriodResult",
    "CapacityAnalysisSuite",
    "CapacityLevelResult",
    "Stage1DBacktestOrchestrator",
]
