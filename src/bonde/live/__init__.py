"""
Live & Paper-Trading Infrastructure Module (Stage 2, Stage 3 & Stage 3.1)
"""

from .broker import PaperExecutionBroker
from .calendar import USMarketCalendar
from .fill_model import PaperFillModel
from .models import DataQualityStatus, LiveBar, MarketEvent, Quote, RejectedEvent, TradingSession
from .prep import DailyFocusList, DailyPrepPipeline
from .reconciliation import Discrepancy, OrderStateReconciler, ReconciliationError
from .safety import LiveSafetyGovernor, SafetyError
from .session import LiveSessionEngine, LiveSessionState
from .synthetic_session import SyntheticSessionGenerator, SyntheticSessionReplayer
from .telemetry import LiveTelemetryLogger, LiveTelemetryRecord
from .validation import LiveDataValidator
from .runner import LivePaperRunner
from .operational_modes import (
    DailyOperationalReport,
    DecisionRecord,
    DecisionType,
    LiveDataHealth,
    OperationalDecisionJournal,
    OperationalMode,
    ProviderMetadata,
)
from .adapters.alpaca import (
    AlpacaConfig,
    AlpacaMarketDataAdapter,
    AlpacaConnectionManager,
    normalize_alpaca_bar,
    normalize_alpaca_quote,
    AlpacaConnectionError,
    AlpacaDataError,
    AlpacaAuthError,
)

from .multi_session import (
    CandidateDecisionAudit,
    FeedQualityTelemetry,
    IEXSymbolDiagnostics,
    MultiSessionAggregateReport,
    MultiSessionRunner,
    PersistentSessionLedger,
    SessionLedgerEntry,
)

__all__ = [
    "USMarketCalendar",
    "LiveDataValidator",
    "PaperExecutionBroker",
    "PaperFillModel",
    "DailyFocusList",
    "DailyPrepPipeline",
    "LiveSessionEngine",
    "LiveSessionState",
    "OrderStateReconciler",
    "ReconciliationError",
    "LiveSafetyGovernor",
    "SafetyError",
    "LiveTelemetryLogger",
    "LiveTelemetryRecord",
    "SyntheticSessionGenerator",
    "SyntheticSessionReplayer",
    "LiveBar",
    "Quote",
    "TradingSession",
    "RejectedEvent",
    "DataQualityStatus",
    "LivePaperRunner",
    "OperationalMode",
    "LiveDataHealth",
    "DecisionType",
    "DecisionRecord",
    "ProviderMetadata",
    "OperationalDecisionJournal",
    "DailyOperationalReport",
    "AlpacaConfig",
    "AlpacaMarketDataAdapter",
    "AlpacaConnectionManager",
    "normalize_alpaca_bar",
    "normalize_alpaca_quote",
    "AlpacaConnectionError",
    "AlpacaDataError",
    "AlpacaAuthError",
    "CandidateDecisionAudit",
    "FeedQualityTelemetry",
    "IEXSymbolDiagnostics",
    "MultiSessionAggregateReport",
    "MultiSessionRunner",
    "PersistentSessionLedger",
    "SessionLedgerEntry",
]
