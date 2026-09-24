"""
Point-in-Time Indicators Engine (Section 4)
Strictly enforces the invariant:
For any trade decision on session t, ALL daily indicators must use information
available no later than the start of session t (completed sessions through t-1).
No session-t high, close, or volume may leak into pre-entry calculations.
"""

from datetime import date
from typing import Optional
from .dual_price import DailyBarProvider
from .models import ADVProvider, DailyIndicatorProvider


def calculate_65d_high(
    security_id: str,
    session_date: date,
    daily_provider: DailyBarProvider,
    lookback_sessions: int = 65,
) -> Optional[float]:
    """
    Computes Point-in-Time 65-Day High resistance level:
    MAX(adjusted_high) over completed sessions [t-65, t-1].
    - Requires exactly `lookback_sessions` prior completed sessions.
    - Excludes session t completely.
    - Returns None if fewer than `lookback_sessions` prior sessions exist (fail closed).
    """
    prior_bars = daily_provider.get_prior_completed_bars(
        security_id=security_id,
        as_of_date=session_date,
        count=lookback_sessions,
    )
    if len(prior_bars) < lookback_sessions:
        return None

    # Calculate max across completed split-adjusted highs
    highest = max(b.adjusted_high for b in prior_bars)
    return round(highest, 4)


def calculate_adv50(
    security_id: str,
    session_date: date,
    daily_provider: DailyBarProvider,
    lookback_sessions: int = 50,
) -> Optional[float]:
    """
    Computes Point-in-Time 50-day Average Daily Volume:
    AVG(adjusted_volume) over completed sessions [t-50, t-1].
    - Requires exactly `lookback_sessions` prior completed sessions.
    - Excludes session t completely.
    - Returns None if fewer than `lookback_sessions` prior sessions exist (fail closed).
    """
    prior_bars = daily_provider.get_prior_completed_bars(
        security_id=security_id,
        as_of_date=session_date,
        count=lookback_sessions,
    )
    if len(prior_bars) < lookback_sessions:
        return None

    avg_vol = sum(b.adjusted_volume for b in prior_bars) / float(lookback_sessions)
    return round(avg_vol, 2)


def calculate_10ema(
    security_id: str,
    session_date: date,
    daily_provider: DailyBarProvider,
    period: int = 10,
    min_history: int = 10,
) -> Optional[float]:
    """
    Computes Point-in-Time 10-day Exponential Moving Average of adjusted_close:
    Computed strictly over completed sessions through t-1.
    - Requires at least `min_history` prior completed sessions.
    - Excludes session t completely.
    - Returns None if fewer than `min_history` prior sessions exist (fail closed).
    """
    # Fetch all prior bars up to reasonable depth (e.g., 200 bars for EMA convergence)
    prior_bars = daily_provider.get_prior_completed_bars(
        security_id=security_id,
        as_of_date=session_date,
        count=200,
    )
    if len(prior_bars) < min_history:
        return None

    closes = [b.adjusted_close for b in prior_bars]
    multiplier = 2.0 / (period + 1.0)
    # Seed with SMA of the first `period` closes
    ema = sum(closes[:period]) / float(period)
    for c in closes[period:]:
        ema = (c - ema) * multiplier + ema

    return round(ema, 4)


from .security_master import SecurityMasterProvider


class PointInTimeIndicatorEngine(DailyIndicatorProvider, ADVProvider):
    """
    Integrated Indicator Engine conforming to Stage 0 engine interfaces
    (DailyIndicatorProvider, ADVProvider) backed by Point-in-Time DailyBarProvider.
    Resolves symbol to canonical security_id via SecurityMasterProvider if available.
    """

    def __init__(
        self,
        daily_provider: DailyBarProvider,
        security_master: Optional[SecurityMasterProvider] = None,
    ):
        self.daily_provider = daily_provider
        self.security_master = security_master

    def _resolve(self, symbol: str, as_of_date: date) -> str:
        if self.security_master:
            sec_id = self.security_master.resolve_security_id(symbol, as_of_date)
            if sec_id:
                return sec_id
        return symbol

    def get_ema(self, symbol: str, as_of_date: date, period: int = 10) -> Optional[float]:
        """Strictly computes EMA over sessions prior to as_of_date."""
        sec_id = self._resolve(symbol, as_of_date)
        return calculate_10ema(
            security_id=sec_id,
            session_date=as_of_date,
            daily_provider=self.daily_provider,
            period=period,
        )

    def get_adv_50(self, symbol: str, as_of_date: date) -> Optional[float]:
        """Strictly computes ADV50 over sessions prior to as_of_date."""
        sec_id = self._resolve(symbol, as_of_date)
        return calculate_adv50(
            security_id=sec_id,
            session_date=as_of_date,
            daily_provider=self.daily_provider,
            lookback_sessions=50,
        )

    def get_65d_high(self, symbol: str, as_of_date: date) -> Optional[float]:
        """Strictly computes 65D High over sessions prior to as_of_date."""
        sec_id = self._resolve(symbol, as_of_date)
        return calculate_65d_high(
            security_id=sec_id,
            session_date=as_of_date,
            daily_provider=self.daily_provider,
            lookback_sessions=65,
        )
