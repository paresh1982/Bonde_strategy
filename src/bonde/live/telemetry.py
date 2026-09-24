"""
Real-Time Telemetry & Latency Logging (Stage 2)
Extends canonical 27-field trade schema with microstructure latency, spread, and quote analytics.
"""

from dataclasses import dataclass, asdict
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional
import json
import pandas as pd

from ..telemetry.trade_log import TradeRecord


@dataclass(frozen=True)
class LiveTelemetryRecord:
    """
    Backward-compatible extension of the canonical 27-field TradeRecord
    adding real-time execution, latency, and quote context.
    """
    # Core canonical fields (27 fields)
    trade_id: str
    symbol: str
    engine: str
    setup_type: str
    regime: str
    sector: str
    entry_timestamp: str
    entry_price: float
    initial_stop_price: float
    exit_timestamp: str
    exit_price: float
    quantity: int
    initial_risk_dollars: float
    realized_pnl: float
    r_multiple: float
    exit_reason: str
    order_status: str
    mae_dollars: float = 0.0
    mfe_dollars: float = 0.0
    catalyst_track: str = ""
    catalyst_timestamp: str = ""
    planned_risk_pct: float = 0.0
    actual_risk_pct: float = 0.0
    time_to_1r_bars: Optional[int] = None
    time_to_2r_bars: Optional[int] = None
    partial_exit_price: Optional[float] = None
    holding_period_bars: int = 0
    eod_exit_flag: bool = False
    governor_exit_flag: bool = False

    # Stage 2 Live Real-Time Extensions (14 fields)
    data_source: str = "LIVE_STREAM"
    feed_latency_ms: float = 0.0
    decision_timestamp: str = ""
    order_submission_timestamp: str = ""
    simulated_fill_timestamp: str = ""
    decision_to_order_latency_ms: float = 0.0
    order_to_fill_latency_ms: float = 0.0
    bid_at_decision: Optional[float] = None
    ask_at_decision: Optional[float] = None
    bid_at_fill: Optional[float] = None
    ask_at_fill: Optional[float] = None
    simulated_slippage: float = 0.0
    spread_at_fill: Optional[float] = None
    fill_status: str = "FILLED"

    @classmethod
    def from_trade_record(
        cls,
        base: TradeRecord,
        data_source: str = "LIVE_STREAM",
        feed_latency_ms: float = 0.0,
        decision_timestamp: Optional[datetime] = None,
        order_submission_timestamp: Optional[datetime] = None,
        simulated_fill_timestamp: Optional[datetime] = None,
        bid_at_decision: Optional[float] = None,
        ask_at_decision: Optional[float] = None,
        bid_at_fill: Optional[float] = None,
        ask_at_fill: Optional[float] = None,
        simulated_slippage: float = 0.0,
        fill_status: str = "FILLED",
    ) -> "LiveTelemetryRecord":
        d_ts = decision_timestamp.isoformat() if decision_timestamp else base.entry_timestamp
        o_ts = order_submission_timestamp.isoformat() if order_submission_timestamp else base.entry_timestamp
        f_ts = simulated_fill_timestamp.isoformat() if simulated_fill_timestamp else base.entry_timestamp

        d_to_o = 0.0
        if decision_timestamp and order_submission_timestamp:
            d_to_o = round((order_submission_timestamp - decision_timestamp).total_seconds() * 1000.0, 2)

        o_to_f = 0.0
        if order_submission_timestamp and simulated_fill_timestamp:
            o_to_f = round((simulated_fill_timestamp - order_submission_timestamp).total_seconds() * 1000.0, 2)

        spread = None
        if bid_at_fill is not None and ask_at_fill is not None:
            spread = round(ask_at_fill - bid_at_fill, 4)

        base_dict = asdict(base)
        return cls(
            **base_dict,
            data_source=data_source,
            feed_latency_ms=feed_latency_ms,
            decision_timestamp=d_ts,
            order_submission_timestamp=o_ts,
            simulated_fill_timestamp=f_ts,
            decision_to_order_latency_ms=d_to_o,
            order_to_fill_latency_ms=o_to_f,
            bid_at_decision=bid_at_decision,
            ask_at_decision=ask_at_decision,
            bid_at_fill=bid_at_fill,
            ask_at_fill=ask_at_fill,
            simulated_slippage=simulated_slippage,
            spread_at_fill=spread,
            fill_status=fill_status,
        )


class LiveTelemetryLogger:
    """Stores extended live telemetry records and handles session persistence."""

    def __init__(self):
        self.records: List[LiveTelemetryRecord] = []

    def record_live_trade(self, record: LiveTelemetryRecord):
        self.records.append(record)

    def to_dataframe(self) -> pd.DataFrame:
        if not self.records:
            return pd.DataFrame()
        return pd.DataFrame([asdict(r) for r in self.records])

    def export_parquet(self, filepath: Path):
        df = self.to_dataframe()
        if not df.empty:
            filepath.parent.mkdir(parents=True, exist_ok=True)
            df.to_parquet(filepath, index=False)
