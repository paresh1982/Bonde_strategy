"""
Data Quality Engine & Automated Validation Gates (Section 13)
Implements the eight validation gates specified in Stage 1A:
1. OHLC Logical Ordering
2. Non-Zero, Positive Price & Volume Integrity
3. Timestamp Uniqueness & Collision Gate
4. Session Completeness & Missing Bar Handling
5. Unrealistic Price Spikes & Outlier Detection
6. Split Discontinuity & Adjustment Integrity
7. Timezone & DST Synchronization
8. Security Master & Ticker Recycling Validation
Produces structured PASS / WARN / FAIL quality reports.
"""

from dataclasses import dataclass, field
from datetime import date, datetime, time, timezone
from enum import Enum
import json
from pathlib import Path
from typing import Any, Dict, List, Optional
import zoneinfo

from .dual_price import DailyBar
from .intraday import IntradayBarRecord
from .security_master import Security, SecurityHistoryRecord

NY_TZ = zoneinfo.ZoneInfo("America/New_York")
UTC_TZ = timezone.utc


class QualityStatus(str, Enum):
    PASS = "PASS"
    WARN = "WARN"
    FAIL = "FAIL"


class AnomalySeverity(str, Enum):
    WARNING = "WARNING"
    ERROR = "ERROR"
    FATAL_DISCARD = "FATAL_DISCARD"


@dataclass(frozen=True)
class DataQualityAnomaly:
    """Detailed anomaly record matching data_quality_log schema."""
    data_domain: str
    anomaly_type: str
    severity: AnomalySeverity
    details: str
    security_id: Optional[str] = None
    trading_date: Optional[date] = None


@dataclass
class DataQualityReport:
    """Audit report generated per ingestion batch or dataset."""
    dataset_name: str
    status: QualityStatus = QualityStatus.PASS
    total_records: int = 0
    passed_records: int = 0
    anomalies: List[DataQualityAnomaly] = field(default_factory=list)
    generated_at: str = field(default_factory=lambda: datetime.now(timezone.utc).isoformat())

    def add_anomaly(self, anomaly: DataQualityAnomaly):
        self.anomalies.append(anomaly)
        if anomaly.severity == AnomalySeverity.FATAL_DISCARD:
            self.status = QualityStatus.FAIL
        elif anomaly.severity == AnomalySeverity.ERROR and self.status != QualityStatus.FAIL:
            self.status = QualityStatus.FAIL
        elif anomaly.severity == AnomalySeverity.WARNING and self.status == QualityStatus.PASS:
            self.status = QualityStatus.WARN

    def to_dict(self) -> Dict[str, Any]:
        return {
            "dataset_name": self.dataset_name,
            "status": self.status.value,
            "total_records": self.total_records,
            "passed_records": self.passed_records,
            "anomaly_count": len(self.anomalies),
            "anomalies": [
                {
                    "data_domain": a.data_domain,
                    "anomaly_type": a.anomaly_type,
                    "severity": a.severity.value,
                    "security_id": a.security_id,
                    "trading_date": a.trading_date.isoformat() if a.trading_date else None,
                    "details": a.details,
                }
                for a in self.anomalies
            ],
            "generated_at": self.generated_at,
        }

    def save_json(self, filepath: Path):
        filepath.parent.mkdir(parents=True, exist_ok=True)
        with open(filepath, "w", encoding="utf-8") as fh:
            json.dump(self.to_dict(), fh, indent=2)


class DataQualityValidator:
    """
    Automated Data Quality Validator implementing the 8 Validation Gates.
    """

    def validate_daily_bars(
        self,
        bars: List[DailyBar],
        dataset_name: str = "daily_bars",
    ) -> DataQualityReport:
        """Validates daily bars across Gates 1, 2, 3, and 6."""
        report = DataQualityReport(dataset_name=dataset_name, total_records=len(bars))
        seen_keys = set()

        for b in bars:
            key = (b.security_id, b.session_date)
            # Gate 3: Uniqueness
            if key in seen_keys:
                report.add_anomaly(
                    DataQualityAnomaly(
                        data_domain="DAILY_BARS",
                        anomaly_type="TIMESTAMP_COLLISION",
                        severity=AnomalySeverity.ERROR,
                        security_id=b.security_id,
                        trading_date=b.session_date,
                        details=f"Duplicate daily bar for {key}",
                    )
                )
            seen_keys.add(key)

            # Gate 1: OHLC Logic (unadjusted & adjusted)
            if b.low > b.high or b.open < b.low or b.open > b.high or b.close < b.low or b.close > b.high:
                report.add_anomaly(
                    DataQualityAnomaly(
                        data_domain="DAILY_BARS",
                        anomaly_type="BAD_OHLC_ORDER",
                        severity=AnomalySeverity.FATAL_DISCARD,
                        security_id=b.security_id,
                        trading_date=b.session_date,
                        details=f"Unadjusted OHLC invalid: O={b.open}, H={b.high}, L={b.low}, C={b.close}",
                    )
                )

            # Gate 2: Positive prices & volume
            if b.open <= 0 or b.high <= 0 or b.low <= 0 or b.close <= 0 or b.volume < 0:
                report.add_anomaly(
                    DataQualityAnomaly(
                        data_domain="DAILY_BARS",
                        anomaly_type="NEGATIVE_OR_ZERO_PRICE",
                        severity=AnomalySeverity.FATAL_DISCARD,
                        security_id=b.security_id,
                        trading_date=b.session_date,
                        details=f"Non-positive price or negative volume: C={b.close}, V={b.volume}",
                    )
                )

            # Gate 6: Split Adjustment Sanity
            if b.close > 0 and b.adjusted_close > 0:
                ratio = b.adjusted_close / b.close
                # If adjustment ratio is absurdly huge or tiny (>1000 or <0.001) without split filing
                if ratio > 1000.0 or ratio < 0.001:
                    report.add_anomaly(
                        DataQualityAnomaly(
                            data_domain="DAILY_BARS",
                            anomaly_type="SPLIT_FACTOR_OUTLIER",
                            severity=AnomalySeverity.WARNING,
                            security_id=b.security_id,
                            trading_date=b.session_date,
                            details=f"Extreme split adjustment ratio: {ratio:.4f}",
                        )
                    )

        report.passed_records = len(bars) - len(report.anomalies)
        return report

    def validate_intraday_bars(
        self,
        bars: List[IntradayBarRecord],
        expected_bars: int = 390,
        dataset_name: str = "intraday_1m",
    ) -> DataQualityReport:
        """Validates 1-minute intraday bars across Gates 1, 2, 3, 4, 5, and 7."""
        report = DataQualityReport(dataset_name=dataset_name, total_records=len(bars))
        seen_ts = set()
        prior_close: Optional[float] = None

        for b in bars:
            # Gate 7: Timezone check
            if b.timestamp_utc.tzinfo is None:
                report.add_anomaly(
                    DataQualityAnomaly(
                        data_domain="INTRADAY_1M",
                        anomaly_type="NAIVE_TIMESTAMP",
                        severity=AnomalySeverity.FATAL_DISCARD,
                        security_id=b.security_id,
                        details=f"Bar has naive timestamp: {b.timestamp_utc}",
                    )
                )
                continue

            ts_ny = b.timestamp_utc.astimezone(NY_TZ)

            # Gate 3: Unique timestamps
            if b.timestamp_utc in seen_ts:
                report.add_anomaly(
                    DataQualityAnomaly(
                        data_domain="INTRADAY_1M",
                        anomaly_type="TIMESTAMP_COLLISION",
                        severity=AnomalySeverity.ERROR,
                        security_id=b.security_id,
                        trading_date=ts_ny.date(),
                        details=f"Duplicate intraday timestamp: {b.timestamp_utc}",
                    )
                )
            seen_ts.add(b.timestamp_utc)

            # Gate 1: OHLC Logic
            if b.low > b.high or b.open < b.low or b.open > b.high or b.close < b.low or b.close > b.high:
                report.add_anomaly(
                    DataQualityAnomaly(
                        data_domain="INTRADAY_1M",
                        anomaly_type="BAD_OHLC_ORDER",
                        severity=AnomalySeverity.FATAL_DISCARD,
                        security_id=b.security_id,
                        trading_date=ts_ny.date(),
                        details=f"Intraday OHLC order violated: O={b.open}, H={b.high}, L={b.low}, C={b.close}",
                    )
                )

            # Gate 2: Positive Prices
            if b.open <= 0 or b.high <= 0 or b.low <= 0 or b.close <= 0 or b.volume < 0:
                report.add_anomaly(
                    DataQualityAnomaly(
                        data_domain="INTRADAY_1M",
                        anomaly_type="NON_POSITIVE_PRICE_OR_VOL",
                        severity=AnomalySeverity.FATAL_DISCARD,
                        security_id=b.security_id,
                        trading_date=ts_ny.date(),
                        details=f"Non-positive intraday price or vol: C={b.close}, V={b.volume}",
                    )
                )

            # Gate 5: Price Spikes (>50% jump within continuous RTH 09:31-15:59)
            bar_t = ts_ny.time()
            if time(9, 31, 0) <= bar_t <= time(15, 59, 0) and prior_close is not None and prior_close > 0:
                pct_change = abs(b.close - prior_close) / prior_close
                if pct_change > 0.50:
                    report.add_anomaly(
                        DataQualityAnomaly(
                            data_domain="INTRADAY_1M",
                            anomaly_type="EXTREME_PRICE_SPIKE",
                            severity=AnomalySeverity.ERROR,
                            security_id=b.security_id,
                            trading_date=ts_ny.date(),
                            details=f"Intraday bar-to-bar jump > 50%: {prior_close} -> {b.close} ({pct_change*100:.1f}%)",
                        )
                    )

            prior_close = b.close

        # Gate 4: Session Completeness (if bars belong to a single day)
        if bars:
            day_count = len(seen_ts)
            if expected_bars is not None and day_count < (expected_bars * 0.90):  # More than 10% bars missing
                first_ts = bars[0].timestamp_utc.astimezone(NY_TZ).date()
                report.add_anomaly(
                    DataQualityAnomaly(
                        data_domain="INTRADAY_1M",
                        anomaly_type="INCOMPLETE_SESSION",
                        severity=AnomalySeverity.WARNING,
                        security_id=bars[0].security_id,
                        trading_date=first_ts,
                        details=f"Session has only {day_count} bars (expected {expected_bars})",
                    )
                )

        report.passed_records = len(bars) - len(report.anomalies)
        return report

    def validate_security_master(
        self,
        securities: List[Security],
        history: List[SecurityHistoryRecord],
        dataset_name: str = "security_master",
    ) -> DataQualityReport:
        """Validates Security Master across Gate 8 (Recycling, Overlaps, Date Consistency)."""
        report = DataQualityReport(dataset_name=dataset_name, total_records=len(securities) + len(history))

        # Check date consistency in Security
        for sec in securities:
            if sec.delisting_date and sec.first_trade_date > sec.delisting_date:
                report.add_anomaly(
                    DataQualityAnomaly(
                        data_domain="SECURITY_MASTER",
                        anomaly_type="INVALID_SECURITY_LIFECYCLE",
                        severity=AnomalySeverity.FATAL_DISCARD,
                        security_id=sec.security_id,
                        details=f"first_trade_date ({sec.first_trade_date}) > delisting_date ({sec.delisting_date})",
                    )
                )

        # Gate 8: Ticker Recycling Overlap Check
        # Ensure that no two securities share the same ticker string during overlapping dates
        for i, rec1 in enumerate(history):
            t1_from = rec1.effective_from
            t1_to = rec1.effective_to or date.max
            for rec2 in history[i+1:]:
                if rec1.ticker.upper() == rec2.ticker.upper() and rec1.security_id != rec2.security_id:
                    t2_from = rec2.effective_from
                    t2_to = rec2.effective_to or date.max
                    # Check for overlap: max(from1, from2) <= min(to1, to2)
                    if max(t1_from, t2_from) <= min(t1_to, t2_to):
                        report.add_anomaly(
                            DataQualityAnomaly(
                                data_domain="SECURITY_MASTER",
                                anomaly_type="TICKER_COLLISION_OVERLAP",
                                severity=AnomalySeverity.FATAL_DISCARD,
                                security_id=f"{rec1.security_id} / {rec2.security_id}",
                                details=f"Ticker '{rec1.ticker}' overlaps for two securities: {rec1.security_id} and {rec2.security_id}",
                            )
                        )

        report.passed_records = (len(securities) + len(history)) - len(report.anomalies)
        return report
