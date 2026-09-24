"""
Trade Journal & Telemetry Engine (Section 17, Section 21)
Deterministic trade auditing, R-multiple accounting, and rejection tracking.
"""

from dataclasses import dataclass, asdict
from datetime import datetime
from typing import List, Optional
import pandas as pd
import uuid


@dataclass(frozen=True)
class TradeRecord:
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


@dataclass(frozen=True)
class RejectionRecord:
    timestamp: str
    symbol: str
    setup_type: str
    regime: str
    rejection_reason: str
    details: str = ""


class TradeJournal:
    """Stores all completed trades and rejected signals for deterministic audit."""
    def __init__(self):
        self.trades: List[TradeRecord] = []
        self.rejections: List[RejectionRecord] = []

    def record_trade(
        self,
        symbol: str,
        engine: str,
        setup_type: str,
        regime: str,
        sector: str,
        entry_timestamp: datetime,
        entry_price: float,
        initial_stop_price: float,
        exit_timestamp: datetime,
        exit_price: float,
        quantity: int,
        initial_risk_dollars: float,
        realized_pnl: float,
        r_multiple: float,
        exit_reason: str,
        order_status: str = "FILLED",
        mae_dollars: float = 0.0,
        mfe_dollars: float = 0.0,
        trade_id: Optional[str] = None,
        catalyst_track: str = "",
        catalyst_timestamp: str = "",
        planned_risk_pct: float = 0.0,
        actual_risk_pct: float = 0.0,
        time_to_1r_bars: Optional[int] = None,
        time_to_2r_bars: Optional[int] = None,
        partial_exit_price: Optional[float] = None,
        holding_period_bars: int = 0,
        eod_exit_flag: bool = False,
        governor_exit_flag: bool = False,
    ) -> TradeRecord:
        record = TradeRecord(
            trade_id=trade_id or str(uuid.uuid4())[:8],
            symbol=symbol,
            engine=engine,
            setup_type=setup_type,
            regime=regime,
            sector=sector,
            entry_timestamp=entry_timestamp.isoformat(),
            entry_price=round(entry_price, 4),
            initial_stop_price=round(initial_stop_price, 4),
            exit_timestamp=exit_timestamp.isoformat(),
            exit_price=round(exit_price, 4),
            quantity=quantity,
            initial_risk_dollars=round(initial_risk_dollars, 2),
            realized_pnl=round(realized_pnl, 2),
            r_multiple=round(r_multiple, 4),
            exit_reason=exit_reason,
            order_status=order_status,
            mae_dollars=round(mae_dollars, 2),
            mfe_dollars=round(mfe_dollars, 2),
            catalyst_track=catalyst_track,
            catalyst_timestamp=catalyst_timestamp,
            planned_risk_pct=round(planned_risk_pct, 4),
            actual_risk_pct=round(actual_risk_pct, 4),
            time_to_1r_bars=time_to_1r_bars,
            time_to_2r_bars=time_to_2r_bars,
            partial_exit_price=round(partial_exit_price, 4) if partial_exit_price is not None else None,
            holding_period_bars=holding_period_bars,
            eod_exit_flag=eod_exit_flag,
            governor_exit_flag=governor_exit_flag,
        )
        self.trades.append(record)
        return record

    def record_rejection(
        self,
        timestamp: datetime,
        symbol: str,
        setup_type: str,
        regime: str,
        rejection_reason: str,
        details: str = "",
    ) -> RejectionRecord:
        record = RejectionRecord(
            timestamp=timestamp.isoformat(),
            symbol=symbol,
            setup_type=setup_type,
            regime=regime,
            rejection_reason=rejection_reason,
            details=details,
        )
        self.rejections.append(record)
        return record

    def to_dataframe(self) -> pd.DataFrame:
        if not self.trades:
            return pd.DataFrame()
        return pd.DataFrame([asdict(t) for t in self.trades])

    def rejections_to_dataframe(self) -> pd.DataFrame:
        if not self.rejections:
            return pd.DataFrame()
        return pd.DataFrame([asdict(r) for r in self.rejections])
