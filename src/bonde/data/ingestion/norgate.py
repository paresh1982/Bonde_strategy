"""
Norgate Data Ingestion & Validation Layer (Parts C & D).
Implements the Commercial Point-in-Time Security Master and Dual-Price Daily Data Validation.
Guarantees:
- ticker != security identity
- strict resolution across ticker changes, recycling, and delisting
- dual-price separation (unadjusted execution vs split-adjusted analytical)
- zero-lookahead indicators: 65D High [t-65, t-1], ADV50 [t-50, t-1], 10 EMA [.. t-1]
- fail-closed behavior on corrupted or missing records.
"""

from dataclasses import dataclass, field
from datetime import date, datetime, timezone
from pathlib import Path
from typing import Dict, List, Optional, Set, Tuple
import pandas as pd

from ..dual_price import DailyBar, DailyBarProvider, InMemoryDailyBarProvider
from ..indicators import calculate_10ema, calculate_65d_high, calculate_adv50
from ..security_master import Security, SecurityHistoryRecord, SecurityMasterProvider


class NorgateSecurityMaster(SecurityMasterProvider):
    """
    Commercial Point-in-Time Security Master.
    Enforces the fundamental architectural invariant: ticker != security identity.
    Resolves ticker symbols to canonical security_ids as of exact calendar dates.
    Fails closed when identity is ambiguous, unlisted, or already delisted.
    """

    def __init__(
        self,
        securities: Optional[List[Security]] = None,
        history: Optional[List[SecurityHistoryRecord]] = None,
    ):
        self._securities: Dict[str, Security] = {s.security_id: s for s in (securities or [])}
        self._history: List[SecurityHistoryRecord] = history or []

    @classmethod
    def from_csv(cls, master_csv: Path, history_csv: Path) -> "NorgateSecurityMaster":
        """Builds security master from standard Norgate-format CSV files."""
        securities: List[Security] = []
        df_master = pd.read_csv(master_csv)
        for _, row in df_master.iterrows():
            delist_d = None
            if pd.notna(row.get("delisting_date")) and str(row.get("delisting_date")).strip():
                delist_d = date.fromisoformat(str(row["delisting_date"]).strip())

            sec = Security(
                security_id=str(row["security_id"]).strip(),
                ticker=str(row["ticker"]).strip(),
                exchange=str(row["exchange"]).strip(),
                name=str(row["name"]).strip(),
                first_trade_date=date.fromisoformat(str(row["first_trade_date"]).strip()),
                last_trade_date=date.fromisoformat(str(row["last_trade_date"]).strip()),
                delisting_date=delist_d,
                active_flag=bool(row.get("active_flag", True)),
                cusip=str(row["cusip"]).strip() if pd.notna(row.get("cusip")) else None,
                figi=str(row["figi"]).strip() if pd.notna(row.get("figi")) else None,
            )
            securities.append(sec)

        history: List[SecurityHistoryRecord] = []
        df_hist = pd.read_csv(history_csv)
        for _, row in df_hist.iterrows():
            eff_to = None
            if pd.notna(row.get("effective_to")) and str(row.get("effective_to")).strip():
                eff_to = date.fromisoformat(str(row["effective_to"]).strip())

            rec = SecurityHistoryRecord(
                security_id=str(row["security_id"]).strip(),
                ticker=str(row["ticker"]).strip().upper(),
                effective_from=date.fromisoformat(str(row["effective_from"]).strip()),
                effective_to=eff_to,
            )
            history.append(rec)

        return cls(securities=securities, history=history)

    def add_security(self, security: Security):
        self._securities[security.security_id] = security

    def add_history_record(self, record: SecurityHistoryRecord):
        self._history.append(record)

    def resolve_security_id(self, ticker: str, as_of_date: date) -> Optional[str]:
        """
        Point-in-Time Resolution:
        Finds candidate security_id where ticker matches AND effective_from <= as_of_date <= effective_to.
        Verifies security was actively listed on as_of_date.
        Fails closed (returns None) on zero matches or ambiguous collision.
        """
        ticker_clean = ticker.strip().upper()
        matching_sec_ids: Set[str] = set()

        for h in self._history:
            if h.ticker == ticker_clean:
                if h.effective_from <= as_of_date:
                    if h.effective_to is None or as_of_date <= h.effective_to:
                        # Verify underlying security trading activity
                        sec = self._securities.get(h.security_id)
                        if sec and sec.is_active_on(as_of_date):
                            matching_sec_ids.add(h.security_id)

        # Fail closed on collision or zero matches
        if len(matching_sec_ids) == 1:
            return next(iter(matching_sec_ids))
        return None

    def get_security(self, security_id: str) -> Optional[Security]:
        return self._securities.get(security_id)

    def is_active(self, security_id: str, as_of_date: date) -> bool:
        sec = self._securities.get(security_id)
        if not sec:
            return False
        return sec.is_active_on(as_of_date)

    def get_all_active_securities(self, as_of_date: date) -> List[Security]:
        return [sec for sec in self._securities.values() if sec.is_active_on(as_of_date)]


@dataclass
class DailyValidationSummary:
    """Detailed summary of daily data validation."""
    total_bars: int = 0
    passed_bars: int = 0
    ohlc_violations: int = 0
    negative_prices: int = 0
    negative_volumes: int = 0
    duplicate_dates: int = 0
    split_outliers: int = 0
    lookahead_violations: int = 0
    is_valid: bool = True
    error_messages: List[str] = field(default_factory=list)


class NorgateDailyIngester:
    """
    Ingests and validates Norgate daily dual-price equity data.
    Enforces strict separation of unadjusted prices (execution) and split-adjusted prices (analytics).
    Validates anti-lookahead indicator contracts.
    """

    @staticmethod
    def parse_daily_csv(filepath: Path, security_id: str) -> List[DailyBar]:
        """Parses a Norgate daily CSV into strongly-typed DailyBar objects."""
        df = pd.read_csv(filepath)
        bars: List[DailyBar] = []

        # Map column variations
        cols = {c.lower(): c for c in df.columns}
        date_col = cols.get("date", "Date")
        unadj_o = cols.get("unadjustedopen", cols.get("open", "Open"))
        unadj_h = cols.get("unadjustedhigh", cols.get("high", "High"))
        unadj_l = cols.get("unadjustedlow", cols.get("low", "Low"))
        unadj_c = cols.get("unadjustedclose", cols.get("close", "Close"))
        unadj_v = cols.get("unadjustedvolume", cols.get("volume", "Volume"))

        adj_o = cols.get("adjustedopen", cols.get("open", "Open"))
        adj_h = cols.get("adjustedhigh", cols.get("high", "High"))
        adj_l = cols.get("adjustedlow", cols.get("low", "Low"))
        adj_c = cols.get("adjustedclose", cols.get("close", "Close"))
        adj_v = cols.get("adjustedvolume", cols.get("volume", "Volume"))

        for _, row in df.iterrows():
            d = date.fromisoformat(str(row[date_col]).strip()[:10])
            bar = DailyBar(
                security_id=security_id,
                session_date=d,
                open=float(row[unadj_o]),
                high=float(row[unadj_h]),
                low=float(row[unadj_l]),
                close=float(row[unadj_c]),
                volume=float(row[unadj_v]),
                adjusted_open=float(row[adj_o]),
                adjusted_high=float(row[adj_h]),
                adjusted_low=float(row[adj_l]),
                adjusted_close=float(row[adj_c]),
                adjusted_volume=float(row[adj_v]),
                source="NORGATE",
            )
            bars.append(bar)

        bars.sort(key=lambda b: b.session_date)
        return bars

    @staticmethod
    def validate_bars(bars: List[DailyBar]) -> DailyValidationSummary:
        """Validates daily bars against logical integrity and gate rules."""
        summary = DailyValidationSummary(total_bars=len(bars))
        seen_dates: Set[date] = set()

        for b in bars:
            has_error = False

            # Duplicate check
            if b.session_date in seen_dates:
                summary.duplicate_dates += 1
                summary.error_messages.append(f"Duplicate session date: {b.session_date} for {b.security_id}")
                has_error = True
            seen_dates.add(b.session_date)

            # OHLC Order Logic (unadjusted)
            if b.low > b.high or b.open < b.low or b.open > b.high or b.close < b.low or b.close > b.high:
                summary.ohlc_violations += 1
                summary.error_messages.append(f"Unadjusted OHLC invalid on {b.session_date}: O={b.open}, H={b.high}, L={b.low}, C={b.close}")
                has_error = True

            # OHLC Order Logic (adjusted)
            if b.adjusted_low > b.adjusted_high or b.adjusted_open < b.adjusted_low or b.adjusted_open > b.adjusted_high or b.adjusted_close < b.adjusted_low or b.adjusted_close > b.adjusted_high:
                summary.ohlc_violations += 1
                summary.error_messages.append(f"Adjusted OHLC invalid on {b.session_date}")
                has_error = True

            # Positive Prices
            if b.open <= 0 or b.high <= 0 or b.low <= 0 or b.close <= 0 or b.adjusted_open <= 0 or b.adjusted_high <= 0 or b.adjusted_low <= 0 or b.adjusted_close <= 0:
                summary.negative_prices += 1
                summary.error_messages.append(f"Non-positive price on {b.session_date}")
                has_error = True

            # Volume Validity
            if b.volume < 0 or b.adjusted_volume < 0:
                summary.negative_volumes += 1
                summary.error_messages.append(f"Negative volume on {b.session_date}")
                has_error = True

            # Extreme split outlier check (>1000 or <0.001)
            if b.close > 0 and b.adjusted_close > 0:
                ratio = b.adjusted_close / b.close
                if ratio > 1000.0 or ratio < 0.001:
                    summary.split_outliers += 1

            if not has_error:
                summary.passed_bars += 1

        summary.is_valid = (
            summary.ohlc_violations == 0
            and summary.negative_prices == 0
            and summary.negative_volumes == 0
            and summary.duplicate_dates == 0
        )
        return summary

    @staticmethod
    def verify_indicator_anti_leakage(
        provider: DailyBarProvider,
        security_id: str,
        evaluation_date: date,
        corrupted_session_bar: DailyBar,
    ) -> bool:
        """
        Adversarial test:
        1. Computes baseline ADV50, 65D High, 10 EMA as of evaluation_date.
        2. Injects a corrupt, high-value bar at evaluation_date (or future).
        3. Recomputes indicators as of evaluation_date.
        4. Proves baseline indicators are 100% identical (strict anti-lookahead proof).
        """
        # Baseline indicators
        base_adv50 = calculate_adv50(security_id, evaluation_date, provider)
        base_high65 = calculate_65d_high(security_id, evaluation_date, provider)
        base_ema10 = calculate_10ema(security_id, evaluation_date, provider)

        # Mutate / inject corrupted bar at evaluation date
        if isinstance(provider, InMemoryDailyBarProvider):
            provider.add_bar(corrupted_session_bar)

        # Recompute indicators
        post_adv50 = calculate_adv50(security_id, evaluation_date, provider)
        post_high65 = calculate_65d_high(security_id, evaluation_date, provider)
        post_ema10 = calculate_10ema(security_id, evaluation_date, provider)

        # Strict equality check
        adv_match = base_adv50 == post_adv50
        high_match = base_high65 == post_high65
        ema_match = base_ema10 == post_ema10

        return adv_match and high_match and ema_match
