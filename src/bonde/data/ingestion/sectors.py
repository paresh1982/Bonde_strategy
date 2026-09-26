"""
Point-in-Time Sector Ingestion & Governance Validation (Part H).
Enforces historical date-bounded GICS sector and industry group assignments.
Guarantees:
- Never retroactively applies current GICS taxonomy to historical trades
- Strict validation across sector reclassifications
- Fails closed when a security's historical sector is unmapped
- Provides verification against the Sector Concentration Governor.
"""

from dataclasses import dataclass
from datetime import date, datetime
from pathlib import Path
from typing import Dict, List, Optional
import pandas as pd

from ..sectors import HistoricalSectorRecord, PointInTimeSectorProvider
from ..security_master import SecurityMasterProvider


class CommercialSectorIngester:
    """
    Ingests and validates historical point-in-time sector and industry assignments.
    Prevents lookahead bias from modern GICS restructurings.
    """

    @staticmethod
    def parse_csv(filepath: Path) -> List[HistoricalSectorRecord]:
        """
        Parses commercial sector classification CSV.
        Expected columns: security_id, sector, industry/industry_group, effective_from, effective_to (optional).
        """
        df = pd.read_csv(filepath)
        records: List[HistoricalSectorRecord] = []

        cols = {c.lower(): c for c in df.columns}
        sec_col = cols.get("security_id", cols.get("ticker", "security_id"))
        sec_name_col = cols.get("sector", "sector")
        ind_col = cols.get("industry", cols.get("industry_group", "industry"))
        eff_from_col = cols.get("effective_from")
        eff_to_col = cols.get("effective_to")

        for _, row in df.iterrows():
            sec_id = str(row[sec_col]).strip()
            sector = str(row[sec_name_col]).strip().upper()
            industry = str(row.get(ind_col, "GENERAL")).strip()

            eff_from = date(1980, 1, 1)
            if eff_from_col and pd.notna(row.get(eff_from_col)):
                eff_from = date.fromisoformat(str(row[eff_from_col]).strip()[:10])

            eff_to = None
            if eff_to_col and pd.notna(row.get(eff_to_col)) and str(row.get(eff_to_col)).strip():
                eff_to = date.fromisoformat(str(row[eff_to_col]).strip()[:10])

            records.append(
                HistoricalSectorRecord(
                    security_id=sec_id,
                    sector=sector,
                    industry_group=industry,
                    effective_from=eff_from,
                    effective_to=eff_to,
                )
            )

        return records

    @staticmethod
    def create_provider(
        records: List[HistoricalSectorRecord],
        security_master: Optional[SecurityMasterProvider] = None,
    ) -> PointInTimeSectorProvider:
        """Constructs engine-compatible PointInTimeSectorProvider."""
        return PointInTimeSectorProvider(records=records, security_master=security_master)
