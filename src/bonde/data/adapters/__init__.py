"""
Provider Adapters Package (Phase 1)
Decouples vendor-specific data formats from the strategy engine.
"""

from .norgate import NorgateSecurityMasterAdapter, NorgateDailyAdapter
from .firstrate import FirstRateIntradayAdapter
from .earnings import HistoricalEarningsAdapter
from .sec_edgar import SecEdgarFilingAdapter

__all__ = [
    "NorgateSecurityMasterAdapter",
    "NorgateDailyAdapter",
    "FirstRateIntradayAdapter",
    "HistoricalEarningsAdapter",
    "SecEdgarFilingAdapter",
]
