"""
FirstRate Data Provider Adapter (Phase 1)
Parses FirstRate 1-Minute Historical US Equities data files.
Handles America/New_York session timing, Daylight Saving Time (EDT/EST) transitions,
normalizes timestamps to UTC, and produces canonical IntradayBarRecord objects.
"""

from datetime import datetime, time, timezone
from pathlib import Path
from typing import List, Optional, Union
import pandas as pd
import zoneinfo

from ..intraday import IntradayBarRecord

NY_TZ = zoneinfo.ZoneInfo("America/New_York")
UTC = timezone.utc


class FirstRateIntradayAdapter:
    """
    Adapter for FirstRate Data 1-minute historical intraday CSV files.
    """

    @staticmethod
    def parse_1m_csv(
        file_path: Union[str, Path],
        security_id: str,
        symbol: str,
        filter_rth: bool = True,
    ) -> List[IntradayBarRecord]:
        """
        Parses FirstRate 1-minute CSV.
        Expected format:
          DateTime, Open, High, Low, Close, Volume
          e.g. 2024-03-15 09:30:00, 150.25, 150.50, 150.10, 150.30, 25400
        """
        # FirstRate files may have headers or be headerless
        df = pd.read_csv(file_path)
        # Normalize column names
        df.columns = [str(c).strip().title() for c in df.columns]

        dt_col = None
        for col in ["Datetime", "Timestamp", "Date_Time", "Date"]:
            if col in df.columns:
                dt_col = col
                break

        if not dt_col:
            # Handle headerless standard FirstRate format: col 0 = dt, 1 = O, 2 = H, 3 = L, 4 = C, 5 = V
            df = pd.read_csv(file_path, header=None)
            df.columns = ["Datetime", "Open", "High", "Low", "Close", "Volume"]
            dt_col = "Datetime"

        records = []
        for _, row in df.iterrows():
            dt_str = str(row[dt_col]).strip()
            # Parse datetime
            naive_dt = datetime.fromisoformat(dt_str)
            # Localize to America/New_York (handles DST automatically)
            localized_dt = naive_dt.replace(tzinfo=NY_TZ)

            # RTH filter: 09:30:00 to 15:59:59 ET
            if filter_rth:
                t = localized_dt.time()
                if t < time(9, 30, 0) or t >= time(16, 0, 0):
                    continue

            # Normalize to UTC
            utc_dt = localized_dt.astimezone(UTC)

            rec = IntradayBarRecord(
                security_id=security_id,
                symbol=symbol.upper(),
                timestamp_utc=utc_dt,
                open=float(row["Open"]),
                high=float(row["High"]),
                low=float(row["Low"]),
                close=float(row["Close"]),
                volume=float(row["Volume"]),
            )
            records.append(rec)

        # Sort strictly chronologically by UTC timestamp
        records.sort(key=lambda r: r.timestamp_utc)
        return records
