"""
Norgate Data Provider Adapter (Phase 1)
Parses Norgate Daily US Equities exports and security history.
Translates Norgate format into canonical Security, SecurityHistoryRecord, and DailyBar models.
Isolates vendor-specific logic from the strategy engine.
"""

from datetime import date, datetime, timezone
from pathlib import Path
from typing import Dict, List, Optional, Union
import pandas as pd

from ..dual_price import DailyBar
from ..security_master import Security, SecurityHistoryRecord


class NorgateSecurityMasterAdapter:
    """
    Adapter for Norgate US Equities Security Master & Historical Renames.
    Handles active listings, delisted entities, and ticker renames.
    """

    @staticmethod
    def parse_security_master_csv(file_path: Union[str, Path]) -> List[Security]:
        """
        Parses Norgate security master export CSV.
        Expected columns:
          security_id, ticker, exchange, name, first_trade_date, last_trade_date, delisting_date, active_flag, cusip, figi
        """
        df = pd.read_csv(file_path)
        securities = []
        for _, row in df.iterrows():
            delist_d = None
            if pd.notna(row.get("delisting_date")) and str(row["delisting_date"]).strip():
                delist_d = date.fromisoformat(str(row["delisting_date"]).strip())

            first_d = date.fromisoformat(str(row["first_trade_date"]).strip())
            last_d = date.fromisoformat(str(row["last_trade_date"]).strip())
            active = bool(row.get("active_flag", delist_d is None))

            sec = Security(
                security_id=str(row["security_id"]).strip(),
                ticker=str(row["ticker"]).strip().upper(),
                exchange=str(row.get("exchange", "NASDAQ")).strip().upper(),
                name=str(row.get("name", "")).strip(),
                first_trade_date=first_d,
                last_trade_date=last_d,
                delisting_date=delist_d,
                active_flag=active,
                cusip=str(row["cusip"]).strip() if pd.notna(row.get("cusip")) else None,
                figi=str(row["figi"]).strip() if pd.notna(row.get("figi")) else None,
            )
            securities.append(sec)
        return securities

    @staticmethod
    def parse_ticker_history_csv(file_path: Union[str, Path]) -> List[SecurityHistoryRecord]:
        """
        Parses historical ticker rename records from Norgate.
        Expected columns: security_id, ticker, effective_from, effective_to
        """
        df = pd.read_csv(file_path)
        records = []
        for _, row in df.iterrows():
            eff_from = date.fromisoformat(str(row["effective_from"]).strip())
            eff_to = None
            if pd.notna(row.get("effective_to")) and str(row["effective_to"]).strip():
                eff_to = date.fromisoformat(str(row["effective_to"]).strip())

            rec = SecurityHistoryRecord(
                security_id=str(row["security_id"]).strip(),
                ticker=str(row["ticker"]).strip().upper(),
                effective_from=eff_from,
                effective_to=eff_to,
            )
            records.append(rec)
        return records


class NorgateDailyAdapter:
    """
    Adapter for Norgate Daily US Equities price series.
    Strictly preserves unadjusted vs split-adjusted price isolation.
    """

    @staticmethod
    def parse_daily_bars_csv(
        file_path: Union[str, Path],
        security_id: str,
    ) -> List[DailyBar]:
        """
        Parses Norgate daily dual-price export CSV.
        Expected columns:
          Date, Open, High, Low, Close, Volume,
          UnadjustedOpen, UnadjustedHigh, UnadjustedLow, UnadjustedClose, UnadjustedVolume
          (or columns with adjusted/unadjusted variants)
        """
        df = pd.read_csv(file_path)
        bars = []

        for _, row in df.iterrows():
            d_val = str(row["Date"]).strip()
            session_d = date.fromisoformat(d_val)

            # Extract unadjusted prices (for execution)
            unadj_open = float(row.get("UnadjustedOpen", row.get("Open")))
            unadj_high = float(row.get("UnadjustedHigh", row.get("High")))
            unadj_low = float(row.get("UnadjustedLow", row.get("Low")))
            unadj_close = float(row.get("UnadjustedClose", row.get("Close")))
            unadj_vol = float(row.get("UnadjustedVolume", row.get("Volume")))

            # Extract split-adjusted prices (for indicators)
            adj_open = float(row.get("AdjustedOpen", row.get("Open")))
            adj_high = float(row.get("AdjustedHigh", row.get("High")))
            adj_low = float(row.get("AdjustedLow", row.get("Low")))
            adj_close = float(row.get("AdjustedClose", row.get("Close")))
            adj_vol = float(row.get("AdjustedVolume", row.get("Volume")))

            bar = DailyBar(
                security_id=security_id,
                session_date=session_d,
                open=unadj_open,
                high=unadj_high,
                low=unadj_low,
                close=unadj_close,
                volume=unadj_vol,
                adjusted_open=adj_open,
                adjusted_high=adj_high,
                adjusted_low=adj_low,
                adjusted_close=adj_close,
                adjusted_volume=adj_vol,
                source="NORGATE",
                strict_validation=False,
            )
            bars.append(bar)

        # Sort strictly chronologically
        bars.sort(key=lambda b: b.session_date)
        return bars
