"""
SEC EDGAR 8-K Data Adapter (Phase 1)
Parses SEC EDGAR submission archives and daily index files.
Extracts 8-K filings with microsecond acceptanceDateTime headers.
"""

from datetime import date, datetime
import json
from pathlib import Path
from typing import Dict, List, Optional, Union
import pandas as pd
import zoneinfo

from ..catalysts import SECFilingEvent
from ..security_master import SecurityMasterProvider

NY_TZ = zoneinfo.ZoneInfo("America/New_York")


class SecEdgarFilingAdapter:
    """
    Adapter for SEC EDGAR 8-K filings metadata.
    """

    @staticmethod
    def parse_sec_submissions_json(
        file_path: Union[str, Path],
        security_master: Optional[SecurityMasterProvider] = None,
    ) -> List[SECFilingEvent]:
        """
        Parses an SEC EDGAR company submissions JSON file (e.g., CIK0001234567.json).
        """
        with open(file_path, "r", encoding="utf-8") as fh:
            data = json.load(fh)

        cik = str(data.get("cik", "")).zfill(10)
        ticker = str(data.get("tickers", [""]))[0] if data.get("tickers") else ""
        recent = data.get("filings", {}).get("recent", {})

        if not recent:
            return []

        forms = recent.get("form", [])
        accessions = recent.get("accessionNumber", [])
        filing_dates = recent.get("filingDate", [])
        acceptances = recent.get("acceptanceDateTime", [])
        items_list = recent.get("items", [])
        primary_docs = recent.get("primaryDocument", [])

        events = []
        for i in range(len(forms)):
            form = forms[i]
            if form != "8-K":
                continue

            acc_num = accessions[i]
            f_date = date.fromisoformat(filing_dates[i])
            acc_dt_str = acceptances[i]

            # Parse acceptance datetime (UTC format e.g. 2024-03-15T12:15:22.000Z)
            acc_dt = datetime.fromisoformat(acc_dt_str.replace("Z", "+00:00")).astimezone(NY_TZ)

            # Extract items
            raw_items = items_list[i] if i < len(items_list) else ""
            items = [item.strip() for item in str(raw_items).split(",") if item.strip()]

            # Resolve canonical security_id
            sec_id = ticker or f"CIK_{cik}"
            if security_master and ticker:
                resolved = security_master.resolve_security_id(ticker, f_date)
                if resolved:
                    sec_id = resolved

            primary_doc = primary_docs[i] if i < len(primary_docs) else ""
            source_url = f"https://www.sec.gov/Archives/edgar/data/{int(cik)}/{acc_num.replace('-', '')}/{primary_doc}"

            ev = SECFilingEvent(
                security_id=sec_id,
                cik=cik,
                accession_number=acc_num,
                filing_type="8-K",
                filing_timestamp=acc_dt,
                acceptance_datetime=acc_dt,
                form="8-K",
                items=items,
                source_url=source_url,
                availability_timestamp=acc_dt,
            )
            events.append(ev)

        events.sort(key=lambda e: e.availability_timestamp)
        return events

    @staticmethod
    def parse_sec_index_csv(
        file_path: Union[str, Path],
        security_master: Optional[SecurityMasterProvider] = None,
    ) -> List[SECFilingEvent]:
        """
        Parses processed SEC index CSV with columns:
          cik, ticker, accession_number, filing_date, acceptance_datetime, form, items, source_url
        """
        df = pd.read_csv(file_path)
        events = []
        for _, row in df.iterrows():
            if str(row.get("form", "")).strip() != "8-K":
                continue

            cik = str(row["cik"]).zfill(10)
            ticker = str(row.get("ticker", "")).strip().upper()
            f_date = date.fromisoformat(str(row["filing_date"]).strip())
            acc_num = str(row["accession_number"]).strip()
            acc_dt_str = str(row["acceptance_datetime"]).strip()
            acc_dt = datetime.fromisoformat(acc_dt_str.replace("Z", "+00:00")).astimezone(NY_TZ)

            raw_items = row.get("items", "")
            items = [it.strip() for it in str(raw_items).split(";") if it.strip()]

            sec_id = ticker or f"CIK_{cik}"
            if security_master and ticker:
                resolved = security_master.resolve_security_id(ticker, f_date)
                if resolved:
                    sec_id = resolved

            ev = SECFilingEvent(
                security_id=sec_id,
                cik=cik,
                accession_number=acc_num,
                filing_type="8-K",
                filing_timestamp=acc_dt,
                acceptance_datetime=acc_dt,
                form="8-K",
                items=items,
                source_url=str(row.get("source_url", "")).strip(),
                availability_timestamp=acc_dt,
            )
            events.append(ev)

        events.sort(key=lambda e: e.availability_timestamp)
        return events
