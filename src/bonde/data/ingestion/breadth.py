"""
Market Breadth Ingestion & Authenticity Validation (Part I).
Enforces the mandatory requirement for authentic cross-sectional market breadth.
Strictly prohibits substituting single-ticker ETF proxies (e.g., SPY/QQQ) for
cross-sectional aggregate breadth unless explicitly authorized.
Marks backtesting BLOCKED when institutional cross-sectional breadth is unavailable.
"""

from dataclasses import dataclass
from datetime import date
from enum import Enum
from pathlib import Path
from typing import Dict, List, Optional
import pandas as pd

from ..breadth import MarketBreadthRecord, InMemoryMarketBreadthProvider


class BreadthValidationStatus(str, Enum):
    VALID_CROSS_SECTIONAL = "VALID_CROSS_SECTIONAL"
    PROXY_SUBSTITUTE_BLOCKED = "PROXY_SUBSTITUTE_BLOCKED"
    MISSING_BREADTH_BLOCKED = "MISSING_BREADTH_BLOCKED"


@dataclass
class BreadthValidationResult:
    """Audit outcome for market breadth data."""
    status: BreadthValidationStatus
    is_blocked: bool
    total_sessions: int
    min_date: Optional[date]
    max_date: Optional[date]
    has_t2108: bool
    has_gainers_losers: bool
    is_synthetic_proxy: bool
    message: str


class MarketBreadthValidator:
    """
    Validates institutional cross-sectional market breadth.
    Fails closed if the supplied data is merely an index proxy or lacks true cross-sectional breadth.
    """

    @classmethod
    def validate_breadth_dataset(cls, filepath: Optional[Path]) -> BreadthValidationResult:
        """Validates market breadth file against strategy requirements."""
        if filepath is None or not filepath.exists():
            return BreadthValidationResult(
                status=BreadthValidationStatus.MISSING_BREADTH_BLOCKED,
                is_blocked=True,
                total_sessions=0,
                min_date=None,
                max_date=None,
                has_t2108=False,
                has_gainers_losers=False,
                is_synthetic_proxy=False,
                message="BLOCKER: Historical cross-sectional market breadth dataset is missing.",
            )

        try:
            df = pd.read_csv(filepath)
            cols = {c.lower(): c for c in df.columns}

            date_col = cols.get("session_date", cols.get("date"))
            if not date_col:
                return BreadthValidationResult(
                    status=BreadthValidationStatus.MISSING_BREADTH_BLOCKED,
                    is_blocked=True,
                    total_sessions=len(df),
                    min_date=None,
                    max_date=None,
                    has_t2108=False,
                    has_gainers_losers=False,
                    is_synthetic_proxy=False,
                    message="BLOCKER: Market breadth schema lacks session date column.",
                )

            s_dates = pd.to_datetime(df[date_col]).dt.date
            min_d = s_dates.min()
            max_d = s_dates.max()

            has_t2108 = "t2108_percent" in cols
            has_gl = "gainers_4pct_count" in cols and "losers_4pct_count" in cols

            # Check if this is a single ETF proxy (e.g. only contains SPY or QQQ ticker)
            is_proxy = False
            if "symbol" in cols:
                symbols = df[cols["symbol"]].unique()
                if set(symbols).issubset({"SPY", "QQQ", "IWM"}):
                    is_proxy = True

            if is_proxy:
                return BreadthValidationResult(
                    status=BreadthValidationStatus.PROXY_SUBSTITUTE_BLOCKED,
                    is_blocked=True,
                    total_sessions=len(df),
                    min_date=min_d,
                    max_date=max_d,
                    has_t2108=has_t2108,
                    has_gainers_losers=has_gl,
                    is_synthetic_proxy=True,
                    message="BLOCKER: Single-ticker ETF proxy (SPY/QQQ) cannot substitute for cross-sectional breadth.",
                )

            if not has_gl and not has_t2108:
                return BreadthValidationResult(
                    status=BreadthValidationStatus.MISSING_BREADTH_BLOCKED,
                    is_blocked=True,
                    total_sessions=len(df),
                    min_date=min_d,
                    max_date=max_d,
                    has_t2108=False,
                    has_gainers_losers=False,
                    is_synthetic_proxy=False,
                    message="BLOCKER: Missing both T2108 and 4% gainer/loser counts in breadth dataset.",
                )

            return BreadthValidationResult(
                status=BreadthValidationStatus.VALID_CROSS_SECTIONAL,
                is_blocked=False,
                total_sessions=len(df),
                min_date=min_d,
                max_date=max_d,
                has_t2108=has_t2108,
                has_gainers_losers=has_gl,
                is_synthetic_proxy=False,
                message="PASS: Verified cross-sectional market breadth dataset.",
            )

        except Exception as e:
            return BreadthValidationResult(
                status=BreadthValidationStatus.MISSING_BREADTH_BLOCKED,
                is_blocked=True,
                total_sessions=0,
                min_date=None,
                max_date=None,
                has_t2108=False,
                has_gainers_losers=False,
                is_synthetic_proxy=False,
                message=f"BLOCKER: Error parsing market breadth dataset: {str(e)}",
            )
