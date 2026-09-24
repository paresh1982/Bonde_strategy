"""
Historical Point-in-Time Sector Classification (Section 12)
Enforces date-bounded sector and industry assignments.
Prevents lookahead bias from applying current GICS classifications to historical trades.
Fails closed when historical sector is unmapped.
"""

from dataclasses import dataclass
from datetime import date, datetime
from typing import Dict, List, Optional

from .models import SectorProvider
from .security_master import SecurityMasterProvider


@dataclass(frozen=True)
class HistoricalSectorRecord:
    """Historical sector/industry classification record with date boundaries."""
    security_id: str
    sector: str
    industry_group: str
    effective_from: date
    effective_to: Optional[date] = None  # None indicates actively ongoing


class PointInTimeSectorProvider(SectorProvider):
    """
    Point-in-Time Sector Provider conforming to engine's SectorProvider interface.
    Fails closed (returns None) if no classification was effective on as-of date.
    """

    def __init__(
        self,
        records: Optional[List[HistoricalSectorRecord]] = None,
        security_master: Optional[SecurityMasterProvider] = None,
    ):
        self._records: List[HistoricalSectorRecord] = records or []
        self._security_master = security_master

    def add_record(self, record: HistoricalSectorRecord):
        self._records.append(record)

    def _resolve_sec_id(self, symbol: str, as_of_date: date) -> Optional[str]:
        if self._security_master:
            resolved = self._security_master.resolve_security_id(symbol, as_of_date)
            if resolved:
                return resolved
        # Fallback to direct symbol match
        return symbol

    def _find_record(self, symbol: str, as_of_date: date) -> Optional[HistoricalSectorRecord]:
        sec_id = self._resolve_sec_id(symbol, as_of_date)
        if not sec_id:
            return None

        for rec in self._records:
            if rec.security_id == sec_id:
                if rec.effective_from <= as_of_date:
                    if rec.effective_to is None or as_of_date <= rec.effective_to:
                        return rec
        return None

    def get_sector(self, symbol: str, timestamp: datetime) -> Optional[str]:
        rec = self._find_record(symbol, timestamp.date())
        return rec.sector if rec else None

    def get_industry_group(self, symbol: str, timestamp: datetime) -> Optional[str]:
        rec = self._find_record(symbol, timestamp.date())
        return rec.industry_group if rec else None
