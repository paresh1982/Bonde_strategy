"""
Raw Data Integrity & Vendor Inventory Scanner (Part B).
Inspects supplied vendor files, computes cryptographic SHA-256 hashes,
extracts schemas, row counts, symbol sets, and date coverage, and stores
an immutable manifest without altering underlying raw data.
"""

from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple
import pandas as pd


@dataclass(frozen=True)
class VendorFileEntry:
    """Cryptographic manifest record for a supplied commercial vendor file."""
    filepath: str
    filename: str
    size_bytes: int
    sha256: str
    row_count: int
    date_range: Tuple[Optional[str], Optional[str]]
    symbols: List[str]
    symbol_count: int
    schema: List[str]
    provider: str
    data_domain: str
    ingestion_timestamp: str

    def to_dict(self) -> Dict[str, Any]:
        d = asdict(self)
        d["date_range"] = list(self.date_range)
        return d


class VendorInventoryScanner:
    """
    Scans supplied datasets, inspects schemas and metadata, computes SHA-256 checksums,
    and produces cryptographic provenance manifests. Strictly preserves raw data immutability.
    """

    def __init__(self, data_roots: Optional[List[Path]] = None):
        self.data_roots = data_roots or [Path("data/raw"), Path("data/stage1d/raw")]

    @staticmethod
    def compute_sha256(filepath: Path) -> str:
        """Calculates SHA-256 hash using chunked streaming (memory-safe)."""
        hasher = hashlib.sha256()
        with open(filepath, "rb") as fh:
            while chunk := fh.read(65536):
                hasher.update(chunk)
        return hasher.hexdigest()

    def detect_provider_and_domain(self, filepath: Path, columns: List[str]) -> Tuple[str, str]:
        """Classifies provider and data domain from file path and column schema."""
        fn = filepath.name.lower()
        cols_lower = [c.lower() for c in columns]

        if "security_master" in fn:
            return "Norgate", "SECURITY_MASTER"
        if "ticker_history" in fn:
            return "Norgate", "TICKER_HISTORY"
        if "breadth" in fn or "t2108" in cols_lower:
            return "MarketBreadth", "MARKET_BREADTH"
        if "sector" in fn or ("sector" in cols_lower and "industry" in cols_lower):
            return "SectorMaster", "SECTORS"
        if "earnings" in fn or ("timing" in cols_lower and "announcement_time" in cols_lower):
            return "EarningsProvider", "EARNINGS"
        if "8k" in fn or "acceptance_datetime" in cols_lower or "cik" in cols_lower:
            return "SEC_EDGAR", "SEC_8K"
        if "1min" in fn or "datetime" in cols_lower:
            return "FirstRate", "INTRADAY_1M"
        if "daily" in fn or "adjustedclose" in cols_lower or "unadjustedclose" in cols_lower:
            return "Norgate", "DAILY_BARS"

        return "Unknown", "UNKNOWN"

    def inspect_file(self, filepath: Path) -> VendorFileEntry:
        """Inspects a single file and extracts structural metadata and hash."""
        sha256 = self.compute_sha256(filepath)
        size_bytes = filepath.stat().st_size
        ingestion_ts = datetime.now(timezone.utc).isoformat()

        # Extract schema and rows safely
        schema: List[str] = []
        row_count: int = 0
        symbols: List[str] = []
        min_date: Optional[str] = None
        max_date: Optional[str] = None

        try:
            if filepath.suffix.lower() == ".csv":
                df = pd.read_csv(filepath, nrows=5)
                schema = list(df.columns)
                
                # Full read for row count, symbols, and dates
                full_df = pd.read_csv(filepath)
                row_count = len(full_df)

                # Look for date columns
                for date_col in ["Date", "session_date", "DateTime", "filing_date", "event_date", "effective_from"]:
                    if date_col in full_df.columns:
                        s_dates = full_df[date_col].dropna().astype(str).str[:10]
                        if not s_dates.empty:
                            min_date = str(s_dates.min())
                            max_date = str(s_dates.max())
                            break

                # Look for symbol / ticker columns
                for sym_col in ["ticker", "security_id", "symbol"]:
                    if sym_col in full_df.columns:
                        symbols = sorted(full_df[sym_col].dropna().unique().tolist())
                        break
                if not symbols:
                    # Try deriving from filename (e.g. SEC_AAPL_daily.csv or AAPL_1min_20200731.csv)
                    name_parts = filepath.stem.split("_")
                    if len(name_parts) >= 2 and name_parts[0] in ("SEC", "AAPL", "MSFT", "NVDA", "TSLA", "AMD"):
                        sym = name_parts[1] if name_parts[0] == "SEC" else name_parts[0]
                        symbols = [sym]

            elif filepath.suffix.lower() == ".parquet":
                df = pd.read_parquet(filepath)
                schema = list(df.columns)
                row_count = len(df)
                for date_col in ["Date", "session_date", "timestamp", "datetime"]:
                    if date_col in df.columns:
                        s_dates = df[date_col].dropna().astype(str).str[:10]
                        if not s_dates.empty:
                            min_date = str(s_dates.min())
                            max_date = str(s_dates.max())
                            break
                for sym_col in ["security_id", "symbol", "ticker"]:
                    if sym_col in df.columns:
                        symbols = sorted(df[sym_col].dropna().unique().tolist())
                        break

            elif filepath.suffix.lower() == ".json":
                with open(filepath, "r", encoding="utf-8") as fh:
                    data = json.load(fh)
                if isinstance(data, list):
                    row_count = len(data)
                    if row_count > 0 and isinstance(data[0], dict):
                        schema = list(data[0].keys())
                        for sym_key in ["security_id", "ticker", "symbol"]:
                            if sym_key in data[0]:
                                symbols = sorted(list({str(row[sym_key]) for row in data if sym_key in row}))
                                break
                elif isinstance(data, dict):
                    row_count = len(data)
                    schema = list(data.keys())

        except Exception as e:
            schema = [f"PARSE_ERROR: {str(e)}"]

        provider, domain = self.detect_provider_and_domain(filepath, schema)

        return VendorFileEntry(
            filepath=str(filepath).replace("\\", "/"),
            filename=filepath.name,
            size_bytes=size_bytes,
            sha256=sha256,
            row_count=row_count,
            date_range=(min_date, max_date),
            symbols=symbols,
            symbol_count=len(symbols),
            schema=schema,
            provider=provider,
            data_domain=domain,
            ingestion_timestamp=ingestion_ts,
        )

    def scan_all(self) -> List[VendorFileEntry]:
        """Scans all configured data roots and builds a full cryptographic manifest."""
        entries: List[VendorFileEntry] = []
        for root in self.data_roots:
            if not root.exists():
                continue
            for p in sorted(root.rglob("*")):
                if p.is_file() and p.suffix.lower() in (".csv", ".parquet", ".json") and not p.name.startswith("."):
                    entries.append(self.inspect_file(p))
        return entries

    def save_manifest(self, entries: List[VendorFileEntry], output_path: Path) -> Path:
        """Persists the cryptographic manifest to a JSON file."""
        output_path.parent.mkdir(parents=True, exist_ok=True)
        manifest_data = {
            "generated_at": datetime.now(timezone.utc).isoformat(),
            "total_files": len(entries),
            "total_bytes": sum(e.size_bytes for e in entries),
            "files": [e.to_dict() for e in entries],
        }
        with open(output_path, "w", encoding="utf-8") as fh:
            json.dump(manifest_data, fh, indent=2)
        return output_path
