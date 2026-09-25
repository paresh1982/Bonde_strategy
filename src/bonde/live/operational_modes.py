"""
Operational Modes, Live Data Health & Strategy Decision Telemetry (Stage 3.1)

Provides explicit operational gating, live data health states, and complete
strategy decision auditing for controlled live US paper-trading validation.
"""

from dataclasses import asdict, dataclass, field
from datetime import date, datetime
from enum import Enum
import json
from pathlib import Path
from typing import Any, Dict, List, Optional
import uuid

from bonde.data.models import NY_TZ


class OperationalMode(str, Enum):
    """Execution mode for live data sessions."""
    OBSERVE = "OBSERVE"   # Ingest live data, run candidates & sizing, no paper positions
    PAPER = "PAPER"       # Ingest live data, execute local paper orders & positions
    HALTED = "HALTED"     # Ingest stopped, entries blocked, protective stops preserved


class LiveDataHealth(str, Enum):
    """Health classification for the live data feed."""
    HEALTHY = "HEALTHY"   # Normal monotonic feed within staleness limits (< 60s)
    DEGRADED = "DEGRADED" # Stale warning (60s-90s) or reconnecting
    HALTED = "HALTED"     # Feed halted (> 90s staleness, reconnect failure, or invariant breach)


class DecisionType(str, Enum):
    """Categorization of every strategy decision."""
    CANDIDATE_GENERATED = "CANDIDATE_GENERATED"
    CANDIDATE_REJECTED = "CANDIDATE_REJECTED"
    GOVERNOR_VETO = "GOVERNOR_VETO"
    LIQUIDITY_REJECTION = "LIQUIDITY_REJECTION"
    RISK_GEOMETRY_REJECTION = "RISK_GEOMETRY_REJECTION"
    ORDER_STAGED = "ORDER_STAGED"
    ORDER_FILLED = "ORDER_FILLED"
    COLLAR_MISS = "COLLAR_MISS"
    ORDER_CANCELLED = "ORDER_CANCELLED"
    STOP_TRIGGERED = "STOP_TRIGGERED"
    TARGET_TRIGGERED = "TARGET_TRIGGERED"
    EOD_EXIT = "EOD_EXIT"
    FEED_DEGRADATION = "FEED_DEGRADATION"
    FEED_RECOVERY = "FEED_RECOVERY"


@dataclass
class ProviderMetadata:
    """Metadata recorded for each live market event and decision."""
    data_source: str = "IEX"
    provider_timestamp: Optional[str] = None
    normalized_timestamp: Optional[str] = None
    reception_timestamp: Optional[str] = None
    feed_latency_ms: Optional[float] = None
    connection_state: str = "CONNECTED"

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


@dataclass
class DecisionRecord:
    """Structured record of an individual strategy decision."""
    decision_id: str
    timestamp: datetime
    decision_type: DecisionType
    symbol: str
    details: Dict[str, Any]
    mode: OperationalMode
    provider_metadata: Optional[ProviderMetadata] = None

    def to_dict(self) -> Dict[str, Any]:
        return {
            "decision_id": self.decision_id,
            "timestamp": self.timestamp.isoformat(),
            "decision_type": self.decision_type.value,
            "symbol": self.symbol,
            "details": self.details,
            "mode": self.mode.value,
            "provider_metadata": self.provider_metadata.to_dict() if self.provider_metadata else None,
        }


class OperationalDecisionJournal:
    """Audit log recording every strategy decision and provider health transition."""

    def __init__(self):
        self.decisions: List[DecisionRecord] = []

    def record(
        self,
        decision_type: DecisionType,
        symbol: str,
        details: Dict[str, Any],
        mode: OperationalMode,
        timestamp: Optional[datetime] = None,
        provider_metadata: Optional[ProviderMetadata] = None,
    ) -> DecisionRecord:
        rec = DecisionRecord(
            decision_id=f"DEC_{uuid.uuid4().hex[:8]}",
            timestamp=timestamp or datetime.now(NY_TZ),
            decision_type=decision_type,
            symbol=symbol,
            details=details,
            mode=mode,
            provider_metadata=provider_metadata,
        )
        self.decisions.append(rec)
        return rec

    def get_by_type(self, decision_type: DecisionType) -> List[DecisionRecord]:
        return [d for d in self.decisions if d.decision_type == decision_type]

    def export_json(self, path: Path) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        data = [d.to_dict() for d in self.decisions]
        with open(path, "w", encoding="utf-8") as f:
            json.dump(data, f, indent=2)


@dataclass
class DailyOperationalReport:
    """Comprehensive daily operational summary for controlled live-paper validation."""
    session_date: str
    operational_mode: str
    feed_health: str
    data_source: str
    candidates_detected: int
    candidates_rejected: int
    orders_staged: int
    orders_filled: int
    paper_positions: int
    realized_pnl: float
    unrealized_pnl: float
    r_multiples: List[float]
    governor_rejections: int
    liquidity_rejections: int
    data_quality_events: int
    disconnect_reconnect_events: int
    final_eod_state: str
    decisions_count: int
    notes: List[str] = field(default_factory=list)

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)

    def to_json(self, path: Optional[Path] = None) -> str:
        s = json.dumps(self.to_dict(), indent=2)
        if path:
            path.parent.mkdir(parents=True, exist_ok=True)
            with open(path, "w", encoding="utf-8") as f:
                f.write(s)
        return s

    def to_markdown(self) -> str:
        lines = [
            f"# Daily Operational Report — {self.session_date}",
            "",
            f"- **Operational Mode**: `{self.operational_mode}`",
            f"- **Feed Health**: `{self.feed_health}`",
            f"- **Data Source**: `{self.data_source}` (IEX single-exchange feed)",
            f"- **Final Session State**: `{self.final_eod_state}`",
            "",
            "## Decision & Order Metrics",
            f"- **Candidates Detected**: {self.candidates_detected}",
            f"- **Candidates Rejected**: {self.candidates_rejected}",
            f"- **Orders Staged**: {self.orders_staged}",
            f"- **Orders Filled**: {self.orders_filled}",
            f"- **Paper Positions Open**: {self.paper_positions}",
            "",
            "## Risk & P&L Telemetry",
            f"- **Realized P&L**: ${self.realized_pnl:,.2f}",
            f"- **Unrealized P&L**: ${self.unrealized_pnl:,.2f}",
            f"- **R-Multiples**: {self.r_multiples}",
            f"- **Governor Rejections**: {self.governor_rejections}",
            f"- **Liquidity Rejections**: {self.liquidity_rejections}",
            "",
            "## Data Integrity & Connection Events",
            f"- **Data Quality Events**: {self.data_quality_events}",
            f"- **Disconnect / Reconnect Events**: {self.disconnect_reconnect_events}",
            f"- **Total Audited Decisions**: {self.decisions_count}",
        ]
        if self.notes:
            lines.extend(["", "## Notes"] + [f"- {n}" for n in self.notes])
        return "\n".join(lines)
