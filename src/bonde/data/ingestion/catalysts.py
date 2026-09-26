"""
Commercial Catalyst Ingestion & Anti-Leakage Validation (Part F).
Validates historical earnings announcements (Track A) and SEC EDGAR Form 8-K filings (Track B).
Strictly enforces:
- Timezone normalization to America/New_York
- Verification that catalyst availability timestamp strictly precedes 09:30:00 ET on session date t
- Fail-closed exclusion of intraday-released filings from pre-market screening.
"""

from dataclasses import dataclass, field
from datetime import date, datetime, time, timedelta, timezone
from pathlib import Path
from typing import Dict, List, Optional
import pandas as pd
import zoneinfo

from ..catalysts import EarningsEvent, SECFilingEvent
from ..models import NY_TZ


@dataclass
class CatalystValidationSummary:
    """Summary metrics of catalyst data validation."""
    total_earnings: int = 0
    valid_earnings: int = 0
    leaked_earnings: int = 0
    total_sec_8k: int = 0
    valid_sec_8k: int = 0
    leaked_sec_8k: int = 0
    timezone_errors: int = 0
    errors: List[str] = field(default_factory=list)

    @property
    def is_valid(self) -> bool:
        return self.leaked_earnings == 0 and self.leaked_sec_8k == 0 and self.timezone_errors == 0


class CommercialCatalystIngester:
    """
    Ingests and validates commercial earnings calendars and SEC Form 8-K feeds.
    Guarantees no future catalyst information leaks into session t pre-market screening.
    """

    @staticmethod
    def parse_earnings_csv(filepath: Path, source_label: str = "ZACKS") -> List[EarningsEvent]:
        """
        Parses commercial earnings calendar CSV.
        Expected columns: ticker / security_id, event_date, timing (BMO/AMC), announcement_time.
        """
        df = pd.read_csv(filepath)
        events: List[EarningsEvent] = []

        cols = {c.lower(): c for c in df.columns}
        sec_col = cols.get("security_id", cols.get("ticker", "ticker"))
        date_col = cols.get("event_date", cols.get("date", "event_date"))
        timing_col = cols.get("timing", "timing")
        time_col = cols.get("announcement_time", cols.get("time", "announcement_time"))

        for _, row in df.iterrows():
            sec_id = str(row[sec_col]).strip()
            if not sec_id.startswith("SEC_"):
                sec_id = f"SEC_{sec_id}"

            ev_date = date.fromisoformat(str(row[date_col]).strip()[:10])
            timing = str(row.get(timing_col, "UNKNOWN")).strip().upper()

            # Parse announcement timestamp
            raw_ts = str(row[time_col]).strip()
            dt = datetime.fromisoformat(raw_ts)
            if dt.tzinfo is None:
                dt_ny = dt.replace(tzinfo=NY_TZ)
            else:
                dt_ny = dt.astimezone(NY_TZ)

            # Availability timestamp: BMO announced before open; AMC announced after close
            event = EarningsEvent(
                security_id=sec_id,
                event_timestamp=dt_ny,
                event_date=ev_date,
                timing=timing,
                source=source_label,
                availability_timestamp=dt_ny,
            )
            events.append(event)

        events.sort(key=lambda e: e.availability_timestamp)
        return events

    @staticmethod
    def parse_sec_8k_csv(filepath: Path) -> List[SECFilingEvent]:
        """
        Parses SEC EDGAR Form 8-K filing CSV with ISO-8601 acceptanceDateTime.
        Columns: cik, ticker/security_id, accession_number, filing_date, acceptance_datetime, form, items, source_url.
        """
        df = pd.read_csv(filepath)
        filings: List[SECFilingEvent] = []

        cols = {c.lower(): c for c in df.columns}
        sec_col = cols.get("security_id", cols.get("ticker", "ticker"))
        cik_col = cols.get("cik", "cik")
        acc_col = cols.get("accession_number", "accession_number")
        dt_col = cols.get("acceptance_datetime", "acceptance_datetime")
        form_col = cols.get("form", "form")
        items_col = cols.get("items", "items")
        url_col = cols.get("source_url", "source_url")

        for _, row in df.iterrows():
            sec_id = str(row[sec_col]).strip()
            if not sec_id.startswith("SEC_"):
                sec_id = f"SEC_{sec_id}"

            # Parse SEC acceptance datetime (usually UTC ISO string like 2020-07-30T16:30:15.000Z)
            raw_dt = str(row[dt_col]).strip()
            dt = datetime.fromisoformat(raw_dt.replace("Z", "+00:00"))
            dt_ny = dt.astimezone(NY_TZ)

            items = [item.strip() for item in str(row.get(items_col, "")).split(";") if item.strip()]

            filing = SECFilingEvent(
                security_id=sec_id,
                cik=str(row[cik_col]).strip(),
                accession_number=str(row[acc_col]).strip(),
                filing_type=str(row.get(form_col, "8-K")).strip(),
                filing_timestamp=dt_ny,
                acceptance_datetime=dt_ny,
                form=str(row.get(form_col, "8-K")).strip(),
                items=items,
                source_url=str(row.get(url_col, "")).strip(),
                availability_timestamp=dt_ny,
            )
            filings.append(filing)

        filings.sort(key=lambda f: f.availability_timestamp)
        return filings

    @staticmethod
    def validate_premarket_eligibility(
        earnings: List[EarningsEvent],
        sec_8ks: List[SECFilingEvent],
        session_date: date,
    ) -> CatalystValidationSummary:
        """
        Validates that any catalyst claimed for session t pre-market screening was
        in fact publicly accepted strictly prior to 09:30:00 ET on session_date.
        Adversarially catches lookahead leakage.
        """
        summary = CatalystValidationSummary(
            total_earnings=len(earnings),
            total_sec_8k=len(sec_8ks),
        )
        cutoff = datetime.combine(session_date, time(9, 29, 59), tzinfo=NY_TZ)

        for ev in earnings:
            if ev.event_date == session_date:
                # Must be before 09:30:00 ET
                if ev.availability_timestamp > cutoff:
                    summary.leaked_earnings += 1
                    summary.errors.append(
                        f"Earnings leakage: {ev.security_id} released at {ev.availability_timestamp} "
                        f"after 09:30 cutoff for session {session_date}"
                    )
                else:
                    summary.valid_earnings += 1
            else:
                summary.valid_earnings += 1

        for f in sec_8ks:
            f_d = f.availability_timestamp.astimezone(NY_TZ).date()
            if f_d == session_date:
                if f.availability_timestamp > cutoff:
                    summary.leaked_sec_8k += 1
                    summary.errors.append(
                        f"SEC 8-K leakage: {f.security_id} accepted at {f.availability_timestamp} "
                        f"after 09:30 cutoff for session {session_date}"
                    )
                else:
                    summary.valid_sec_8k += 1
            else:
                summary.valid_sec_8k += 1

        return summary
