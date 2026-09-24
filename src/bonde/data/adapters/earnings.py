"""
Historical Earnings Data Adapter (Phase 1)
Parses historical corporate earnings announcements (e.g. Zacks / FMP format).
Enforces BMO/AMC release timing and microsecond availability timestamps.
"""

from datetime import date, datetime, time
from pathlib import Path
from typing import Dict, List, Optional, Union
import pandas as pd
import zoneinfo

from ..catalysts import EarningsEvent
from ..security_master import SecurityMasterProvider

NY_TZ = zoneinfo.ZoneInfo("America/New_York")


class HistoricalEarningsAdapter:
    """
    Adapter for historical earnings calendars.
    """

    @staticmethod
    def parse_earnings_csv(
        file_path: Union[str, Path],
        security_master: Optional[SecurityMasterProvider] = None,
    ) -> List[EarningsEvent]:
        """
        Parses earnings announcement CSV.
        Expected columns:
          ticker, event_date, timing (BMO / AMC / UNKNOWN), announcement_time (optional), source
        """
        df = pd.read_csv(file_path)
        events = []

        for _, row in df.iterrows():
            ticker = str(row["ticker"]).strip().upper()
            ev_date = date.fromisoformat(str(row["event_date"]).strip())

            # Resolve canonical security_id
            sec_id = ticker
            if security_master:
                resolved = security_master.resolve_security_id(ticker, ev_date)
                if resolved:
                    sec_id = resolved

            timing = str(row.get("timing", "UNKNOWN")).strip().upper()
            source = str(row.get("source", "HISTORICAL_EARNINGS")).strip()

            # Determine announcement and availability timestamps
            if "announcement_time" in row and pd.notna(row["announcement_time"]):
                t_str = str(row["announcement_time"]).strip()
                if "T" in t_str or " " in t_str:
                    event_dt = datetime.fromisoformat(t_str)
                    if event_dt.tzinfo is None:
                        event_dt = event_dt.replace(tzinfo=NY_TZ)
                else:
                    t_val = time.fromisoformat(t_str)
                    event_dt = datetime.combine(ev_date, t_val, tzinfo=NY_TZ)
            else:
                # Default based on timing code
                if timing == "BMO":
                    event_dt = datetime.combine(ev_date, time(7, 0, 0), tzinfo=NY_TZ)
                elif timing == "AMC":
                    event_dt = datetime.combine(ev_date, time(16, 5, 0), tzinfo=NY_TZ)
                else:
                    # Conservative fallback: after market close
                    event_dt = datetime.combine(ev_date, time(16, 30, 0), tzinfo=NY_TZ)

            # Availability timestamp matches public announcement timestamp
            avail_dt = event_dt

            ev = EarningsEvent(
                security_id=sec_id,
                event_timestamp=event_dt,
                event_date=ev_date,
                timing=timing,
                source=source,
                availability_timestamp=avail_dt,
            )
            events.append(ev)

        events.sort(key=lambda e: e.availability_timestamp)
        return events
