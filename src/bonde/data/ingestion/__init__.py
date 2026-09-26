"""
Stage 4.1 — Commercial US Historical Data Ingestion & Quality Validation Layer.
Provides vendor-specific parsers, point-in-time security master resolution,
data integrity verification, and formal data quality gating for US historical research.
"""

from .inventory import VendorFileEntry, VendorInventoryScanner
from .norgate import NorgateSecurityMaster, NorgateDailyIngester
from .firstrate import FirstRateIntradayIngester, MissingBarSeverity, IntradayValidationResult
from .catalysts import CommercialCatalystIngester
from .float_shares import PointInTimeFloatProvider, FloatRecord
from .sectors import CommercialSectorIngester
from .breadth import MarketBreadthValidator, BreadthValidationResult
from .quality_gate import Stage41DataQualityGate, BacktestGateStatus, DataQualityReport41

__all__ = [
    "VendorFileEntry",
    "VendorInventoryScanner",
    "NorgateSecurityMaster",
    "NorgateDailyIngester",
    "FirstRateIntradayIngester",
    "MissingBarSeverity",
    "IntradayValidationResult",
    "CommercialCatalystIngester",
    "PointInTimeFloatProvider",
    "FloatRecord",
    "CommercialSectorIngester",
    "MarketBreadthValidator",
    "BreadthValidationResult",
    "Stage41DataQualityGate",
    "BacktestGateStatus",
    "DataQualityReport41",
]
