"""
Local Storage Engine: DuckDB + Parquet (Section 1)
Provides local-first storage using DuckDB for metadata and indices,
and Parquet for high-speed columnar persistence of daily and intraday series.
"""

from datetime import date, datetime
from pathlib import Path
from typing import Dict, List, Optional
import duckdb
import pandas as pd

from .dual_price import DailyBar
from .intraday import IntradayBarRecord
from .security_master import Security, SecurityHistoryRecord


class LocalDataStorage:
    """
    Local DuckDB and Parquet Storage Manager.
    Allows configuring data root directory dynamically.
    """

    def __init__(self, data_root: Optional[Path] = None, in_memory: bool = False):
        self.data_root = Path(data_root or "data")
        self.metadata_dir = self.data_root / "metadata"
        self.raw_dir = self.data_root / "raw"
        self.processed_dir = self.data_root / "processed"
        self.quality_dir = self.data_root / "quality"

        if not in_memory:
            self.metadata_dir.mkdir(parents=True, exist_ok=True)
            db_path = str(self.metadata_dir / "market_metadata.duckdb")
            self.conn = duckdb.connect(db_path)
        else:
            self.conn = duckdb.connect(":memory:")

        self._init_metadata_tables()

    def _init_metadata_tables(self):
        """Initializes relational tables in DuckDB."""
        self.conn.execute("""
            CREATE TABLE IF NOT EXISTS security_master (
                security_id VARCHAR PRIMARY KEY,
                ticker VARCHAR NOT NULL,
                exchange VARCHAR NOT NULL,
                name VARCHAR NOT NULL,
                first_trade_date DATE NOT NULL,
                last_trade_date DATE NOT NULL,
                delisting_date DATE,
                active_flag BOOLEAN NOT NULL DEFAULT TRUE,
                cusip VARCHAR,
                figi VARCHAR
            );
        """)
        self.conn.execute("""
            CREATE TABLE IF NOT EXISTS security_history (
                security_id VARCHAR NOT NULL,
                ticker VARCHAR NOT NULL,
                effective_from DATE NOT NULL,
                effective_to DATE,
                PRIMARY KEY (security_id, ticker, effective_from)
            );
        """)

    def save_securities(self, securities: List[Security]):
        """Persists security master records into DuckDB."""
        records = [
            (
                s.security_id,
                s.ticker,
                s.exchange,
                s.name,
                s.first_trade_date,
                s.last_trade_date,
                s.delisting_date,
                s.active_flag,
                s.cusip,
                s.figi,
            )
            for s in securities
        ]
        self.conn.executemany("""
            INSERT OR REPLACE INTO security_master VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """, records)

    def save_security_history(self, history: List[SecurityHistoryRecord]):
        """Persists historical ticker mapping windows into DuckDB."""
        records = [
            (h.security_id, h.ticker, h.effective_from, h.effective_to)
            for h in history
        ]
        self.conn.executemany("""
            INSERT OR REPLACE INTO security_history VALUES (?, ?, ?, ?)
        """, records)

    def write_daily_parquet(self, bars: List[DailyBar], filename: str = "daily_bars.parquet") -> Path:
        """Writes DailyBar objects to Parquet in data/processed/daily."""
        out_dir = self.processed_dir / "daily"
        out_dir.mkdir(parents=True, exist_ok=True)
        out_path = out_dir / filename

        records = [
            {
                "security_id": b.security_id,
                "session_date": b.session_date.isoformat(),
                "open": b.open,
                "high": b.high,
                "low": b.low,
                "close": b.close,
                "volume": b.volume,
                "adjusted_open": b.adjusted_open,
                "adjusted_high": b.adjusted_high,
                "adjusted_low": b.adjusted_low,
                "adjusted_close": b.adjusted_close,
                "adjusted_volume": b.adjusted_volume,
                "source": b.source,
                "ingested_at": b.ingested_at.isoformat(),
            }
            for b in bars
        ]
        df = pd.DataFrame(records)
        df.to_parquet(out_path, index=False)
        return out_path

    def read_daily_parquet(self, filepath: Path) -> List[DailyBar]:
        """Reads DailyBar objects from a Parquet file."""
        if not filepath.exists():
            return []
        df = pd.read_parquet(filepath)
        bars = []
        for _, row in df.iterrows():
            d_val = row["session_date"]
            if isinstance(d_val, str):
                s_date = date.fromisoformat(d_val)
            elif hasattr(d_val, "date"):
                s_date = d_val.date()
            else:
                s_date = d_val

            b = DailyBar(
                security_id=row["security_id"],
                session_date=s_date,
                open=float(row["open"]),
                high=float(row["high"]),
                low=float(row["low"]),
                close=float(row["close"]),
                volume=float(row["volume"]),
                adjusted_open=float(row["adjusted_open"]),
                adjusted_high=float(row["adjusted_high"]),
                adjusted_low=float(row["adjusted_low"]),
                adjusted_close=float(row["adjusted_close"]),
                adjusted_volume=float(row["adjusted_volume"]),
                source=row.get("source", "PARQUET"),
            )
            bars.append(b)
        return bars

    def load_securities(self) -> List[Security]:
        """Loads all Security records from DuckDB."""
        rows = self.conn.execute("""
            SELECT security_id, ticker, exchange, name, first_trade_date, last_trade_date, delisting_date, active_flag, cusip, figi
            FROM security_master
        """).fetchall()
        result = []
        for r in rows:
            delist_d = r[6]
            if hasattr(delist_d, "date"):
                delist_d = delist_d.date()
            first_d = r[4].date() if hasattr(r[4], "date") else r[4]
            last_d = r[5].date() if hasattr(r[5], "date") else r[5]
            sec = Security(
                security_id=r[0],
                ticker=r[1],
                exchange=r[2],
                name=r[3],
                first_trade_date=first_d,
                last_trade_date=last_d,
                delisting_date=delist_d,
                active_flag=bool(r[7]),
                cusip=r[8],
                figi=r[9],
            )
            result.append(sec)
        return result

    def load_security_history(self) -> List[SecurityHistoryRecord]:
        """Loads all SecurityHistoryRecord records from DuckDB."""
        rows = self.conn.execute("""
            SELECT security_id, ticker, effective_from, effective_to
            FROM security_history
        """).fetchall()
        result = []
        for r in rows:
            eff_from = r[2].date() if hasattr(r[2], "date") else r[2]
            eff_to = r[3]
            if eff_to is not None and hasattr(eff_to, "date"):
                eff_to = eff_to.date()
            rec = SecurityHistoryRecord(
                security_id=r[0],
                ticker=r[1],
                effective_from=eff_from,
                effective_to=eff_to,
            )
            result.append(rec)
        return result

    def write_intraday_parquet(self, records: List[IntradayBarRecord], filename: str = "intraday_bars.parquet") -> Path:
        """Writes IntradayBarRecord objects to Parquet."""
        out_dir = self.processed_dir / "intraday"
        out_dir.mkdir(parents=True, exist_ok=True)
        out_path = out_dir / filename

        rows = [
            {
                "security_id": r.security_id,
                "symbol": r.symbol,
                "timestamp_utc": r.timestamp_utc.isoformat(),
                "open": r.open,
                "high": r.high,
                "low": r.low,
                "close": r.close,
                "volume": r.volume,
            }
            for r in records
        ]
        df = pd.DataFrame(rows)
        df.to_parquet(out_path, index=False)
        return out_path

    def read_intraday_parquet(self, filepath: Path) -> List[IntradayBarRecord]:
        """Reads IntradayBarRecord objects from Parquet."""
        if not filepath.exists():
            return []
        df = pd.read_parquet(filepath)
        result = []
        for _, row in df.iterrows():
            ts_str = row["timestamp_utc"]
            ts = datetime.fromisoformat(ts_str) if isinstance(ts_str, str) else ts_str
            rec = IntradayBarRecord(
                security_id=row["security_id"],
                symbol=row["symbol"],
                timestamp_utc=ts,
                open=float(row["open"]),
                high=float(row["high"]),
                low=float(row["low"]),
                close=float(row["close"]),
                volume=float(row["volume"]),
            )
            result.append(rec)
        return result

    def close(self):
        self.conn.close()
