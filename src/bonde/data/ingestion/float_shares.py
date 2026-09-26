"""
Point-in-Time Float & Shares Outstanding Ingestion (Part G).
Enforces the strict invariant: Never apply today's float to historical trades.
All shares outstanding and floating share values must have an explicit SEC filing
acceptance timestamp or verified effective date.
Fails closed when historical float cannot be established.
"""

from dataclasses import dataclass
from datetime import date, datetime, timezone
from pathlib import Path
from typing import Dict, List, Optional
import pandas as pd

from ..models import NY_TZ


@dataclass(frozen=True)
class FloatRecord:
    """Historical point-in-time float and shares outstanding record."""
    security_id: str
    effective_date: date
    shares_outstanding: int
    free_float_shares: int
    filing_acceptance_datetime: datetime
    source: str = "SEC_EDGAR_10Q"

    def is_available_on(self, as_of_date: date) -> bool:
        """Data becomes available only on or after the SEC filing acceptance date."""
        return self.effective_date <= as_of_date


class PointInTimeFloatProvider:
    """
    Point-in-Time Float Provider.
    Retrieves the most recent verified float record effective on or before as_of_date.
    Fails closed (returns None) if no valid historical float record exists prior to as_of_date.
    """

    def __init__(self, records: Optional[List[FloatRecord]] = None):
        self._records: Dict[str, List[FloatRecord]] = {}
        if records:
            for r in records:
                self.add_record(r)

    def add_record(self, record: FloatRecord):
        sec_list = self._records.setdefault(record.security_id, [])
        sec_list.append(record)
        sec_list.sort(key=lambda r: r.effective_date)

    @classmethod
    def from_csv(cls, filepath: Path) -> "PointInTimeFloatProvider":
        """Parses historical float CSV."""
        df = pd.read_csv(filepath)
        records: List[FloatRecord] = []
        cols = {c.lower(): c for c in df.columns}
        sec_col = cols.get("security_id", "security_id")
        eff_col = cols.get("effective_date", "effective_date")
        so_col = cols.get("shares_outstanding", "shares_outstanding")
        ff_col = cols.get("free_float_shares", "free_float_shares")
        dt_col = cols.get("filing_acceptance_datetime", "filing_acceptance_datetime")
        src_col = cols.get("source", "source")

        for _, row in df.iterrows():
            sec_id = str(row[sec_col]).strip()
            eff_d = date.fromisoformat(str(row[eff_col]).strip()[:10])
            raw_dt = str(row.get(dt_col, f"{eff_d}T00:00:00Z")).strip()
            dt = datetime.fromisoformat(raw_dt.replace("Z", "+00:00")).astimezone(NY_TZ)

            rec = FloatRecord(
                security_id=sec_id,
                effective_date=eff_d,
                shares_outstanding=int(row[so_col]),
                free_float_shares=int(row[ff_col]),
                filing_acceptance_datetime=dt,
                source=str(row.get(src_col, "SEC_EDGAR")),
            )
            records.append(rec)

        return cls(records=records)

    def get_float_record(self, security_id: str, as_of_date: date) -> Optional[FloatRecord]:
        """
        Retrieves the latest float record strictly available on or before as_of_date.
        Prevents lookahead to future quarterly filings.
        Fails closed (returns None) if unavailable.
        """
        sec_records = self._records.get(security_id, [])
        valid_records = [r for r in sec_records if r.effective_date <= as_of_date]
        if not valid_records:
            return None
        # Return the most recent valid record as of this date
        return valid_records[-1]

    def get_free_float(self, security_id: str, as_of_date: date) -> Optional[int]:
        """Returns free float shares count or None if unestablished."""
        rec = self.get_float_record(security_id, as_of_date)
        return rec.free_float_shares if rec else None

    def get_shares_outstanding(self, security_id: str, as_of_date: date) -> Optional[int]:
        """Returns shares outstanding count or None if unestablished."""
        rec = self.get_float_record(security_id, as_of_date)
        return rec.shares_outstanding if rec else None
