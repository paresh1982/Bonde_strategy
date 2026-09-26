"""
FirstRate 1-Minute Historical Data Ingestion & Validation (Part E).
Ingests historical 1-minute US equity bars, validates regular trading hours (09:30–16:00 ET),
verifies NYSE/Nasdaq trading calendar boundaries and early closes,
and classifies missing bars into PASS / WARN / BLOCKER without interpolating data.
"""

from dataclasses import dataclass, field
from datetime import date, datetime, time, timedelta, timezone
from enum import Enum
from pathlib import Path
from typing import Dict, List, Optional, Set, Tuple
import pandas as pd
import zoneinfo

from ..intraday import IntradayBarRecord
from ..models import Bar, NY_TZ


class MissingBarSeverity(str, Enum):
    PASS = "PASS"
    WARN = "WARN"
    BLOCKER = "BLOCKER"


@dataclass
class IntradayValidationResult:
    """Detailed quality validation result for a session's 1-minute bars."""
    security_id: str
    symbol: str
    session_date: date
    total_bars: int
    expected_bars: int
    missing_bars: int
    severity: MissingBarSeverity
    is_early_close: bool
    duplicate_timestamps: int = 0
    monotonicity_violations: int = 0
    ohlc_violations: int = 0
    negative_prices: int = 0
    negative_volumes: int = 0
    missing_minute_timestamps: List[str] = field(default_factory=list)
    rejection_reason: Optional[str] = None

    @property
    def can_simulate_execution(self) -> bool:
        """Execution simulation must fail closed if severity is BLOCKER."""
        return self.severity != MissingBarSeverity.BLOCKER and self.ohlc_violations == 0 and self.duplicate_timestamps == 0


class FirstRateIntradayIngester:
    """
    Ingests and validates FirstRate Data 1-minute historical equity bars.
    Strictly adheres to:
    - 09:30:00 to 16:00:00 America/New_York session window
    - 390 bars for full sessions, 210 bars for 13:00 early closes
    - Fail-closed execution gate on missing critical bars
    - Zero interpolation / synthetic gap-filling.
    """

    EARLY_CLOSE_DATES = {
        # Known holiday early closes (13:00 ET): Day after Thanksgiving, Christmas Eve (when applicable), July 3 (when applicable)
        date(2018, 7, 3), date(2018, 11, 23), date(2018, 12, 24),
        date(2019, 7, 3), date(2019, 11, 29), date(2019, 12, 24),
        date(2020, 11, 27), date(2020, 12, 24),
        date(2021, 11, 26),
        date(2022, 11, 25),
        date(2023, 7, 3), date(2023, 11, 24),
        date(2024, 7, 3), date(2024, 11, 29), date(2024, 12, 24),
    }

    @classmethod
    def is_early_close_session(cls, session_date: date) -> bool:
        return session_date in cls.EARLY_CLOSE_DATES

    @classmethod
    def get_expected_bar_count(cls, session_date: date) -> int:
        return 210 if cls.is_early_close_session(session_date) else 390

    @classmethod
    def parse_csv(
        cls,
        filepath: Path,
        security_id: str,
        symbol: str,
        session_date: Optional[date] = None,
    ) -> List[IntradayBarRecord]:
        """
        Parses FirstRate CSV format: DateTime,Open,High,Low,Close,Volume.
        Localizes naive timestamps to America/New_York, converts to UTC for storage.
        """
        df = pd.read_csv(filepath)
        records: List[IntradayBarRecord] = []

        cols = {c.lower(): c for c in df.columns}
        dt_col = cols.get("datetime", cols.get("timestamp", "DateTime"))
        o_col = cols.get("open", "Open")
        h_col = cols.get("high", "High")
        l_col = cols.get("low", "Low")
        c_col = cols.get("close", "Close")
        v_col = cols.get("volume", "Volume")

        for _, row in df.iterrows():
            raw_dt_str = str(row[dt_col]).strip()
            # Parse datetime
            dt = datetime.fromisoformat(raw_dt_str)
            # FirstRate timestamps are recorded in America/New_York (local exchange time)
            if dt.tzinfo is None:
                dt_ny = dt.replace(tzinfo=NY_TZ)
            else:
                dt_ny = dt.astimezone(NY_TZ)

            # Filter for RTH: 09:30:00 <= time <= 16:00:00 (or 13:00 on early close)
            bar_t = dt_ny.time()
            if bar_t < time(9, 30, 0) or bar_t > time(16, 0, 0):
                continue

            if session_date is not None and dt_ny.date() != session_date:
                continue

            dt_utc = dt_ny.astimezone(timezone.utc)

            record = IntradayBarRecord(
                security_id=security_id,
                symbol=symbol,
                timestamp_utc=dt_utc,
                open=float(row[o_col]),
                high=float(row[h_col]),
                low=float(row[l_col]),
                close=float(row[c_col]),
                volume=float(row[v_col]),
            )
            records.append(record)

        records.sort(key=lambda r: r.timestamp_utc)
        return records

    @classmethod
    def validate_session_bars(
        cls,
        bars: List[IntradayBarRecord],
        session_date: date,
        has_active_order_or_candidate: bool = True,
    ) -> IntradayValidationResult:
        """
        Validates 1-minute intraday bars for a specific security on session_date.
        Enforces:
        - Exact bar count (390 regular, 210 early close)
        - Timestamp monotonicity
        - Duplicate detection
        - OHLC consistency and non-negative volume
        - Severity categorization: PASS, WARN, BLOCKER.
        """
        sec_id = bars[0].security_id if bars else "UNKNOWN"
        sym = bars[0].symbol if bars else "UNKNOWN"
        is_early = cls.is_early_close_session(session_date)
        expected_count = cls.get_expected_bar_count(session_date)

        result = IntradayValidationResult(
            security_id=sec_id,
            symbol=sym,
            session_date=session_date,
            total_bars=len(bars),
            expected_bars=expected_count,
            missing_bars=max(0, expected_count - len(bars)),
            severity=MissingBarSeverity.PASS,
            is_early_close=is_early,
        )

        if not bars:
            result.severity = MissingBarSeverity.BLOCKER
            result.rejection_reason = f"No intraday bars found for {sec_id} on {session_date}"
            return result

        # Check expected minute intervals
        close_hour = 13 if is_early else 16
        expected_minutes: Set[time] = set()
        curr_t = datetime.combine(session_date, time(9, 30, 0))
        end_t = datetime.combine(session_date, time(close_hour, 0, 0))
        while curr_t < end_t:
            expected_minutes.add(curr_t.time())
            curr_t += timedelta(minutes=1)

        present_minutes: Set[time] = set()
        seen_timestamps: Set[datetime] = set()
        last_ts: Optional[datetime] = None

        for b in bars:
            ts_ny = b.timestamp_utc.astimezone(NY_TZ)
            bar_time = ts_ny.time()

            # Monotonicity
            if last_ts is not None and b.timestamp_utc <= last_ts:
                result.monotonicity_violations += 1
            last_ts = b.timestamp_utc

            # Uniqueness
            if b.timestamp_utc in seen_timestamps:
                result.duplicate_timestamps += 1
            seen_timestamps.add(b.timestamp_utc)
            present_minutes.add(bar_time)

            # OHLC Order Logic
            if b.low > b.high or b.open < b.low or b.open > b.high or b.close < b.low or b.close > b.high:
                result.ohlc_violations += 1

            # Prices & Volume
            if b.open <= 0 or b.high <= 0 or b.low <= 0 or b.close <= 0:
                result.negative_prices += 1
            if b.volume < 0:
                result.negative_volumes += 1

        missing_times = sorted(list(expected_minutes - present_minutes))
        result.missing_minute_timestamps = [t.strftime("%H:%M") for t in missing_times]
        result.missing_bars = len(missing_times)

        # Categorize Severity:
        # Check if missing bars fall in ORB window (09:30 to 09:35)
        orb_window = {time(9, 30), time(9, 31), time(9, 32), time(9, 33), time(9, 34)}
        missing_orb = orb_window.intersection(missing_times)

        if result.ohlc_violations > 0 or result.duplicate_timestamps > 0:
            result.severity = MissingBarSeverity.BLOCKER
            result.rejection_reason = "Corrupted intraday bars: OHLC or duplicate timestamp violations"
        elif len(missing_times) == 0:
            result.severity = MissingBarSeverity.PASS
        elif len(missing_orb) > 0 and has_active_order_or_candidate:
            # Missing ORB bars on a candidate security = BLOCKER (prohibits guessing breakout geometry)
            result.severity = MissingBarSeverity.BLOCKER
            result.rejection_reason = f"Missing {len(missing_orb)} critical bars in ORB window (09:30-09:35)"
        elif len(missing_times) > 10:
            # Heavy session degradation
            result.severity = MissingBarSeverity.BLOCKER
            result.rejection_reason = f"Excessive missing bars ({len(missing_times)} > 10)"
        else:
            # Non-critical missing bars outside ORB
            result.severity = MissingBarSeverity.WARN
            result.rejection_reason = f"Minor gap: {len(missing_times)} non-critical bars missing"

        return result
