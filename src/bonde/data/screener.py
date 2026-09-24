"""
Daily Universe Screener & Candidate Generation (Sections 5 & 6)
Enforces Point-in-Time screening rules prior to market open on session t.
Separates candidate discovery from order execution.
"""

from dataclasses import dataclass
from datetime import date
from typing import Dict, List, Optional

from ..config.strategy_config import StrategyConfig
from .dual_price import DailyBarProvider
from .indicators import calculate_65d_high, calculate_adv50, calculate_10ema
from .security_master import SecurityMasterProvider


@dataclass(frozen=True)
class ScreenedCandidate:
    """Represents a security that has passed point-in-time daily universe filters."""
    security_id: str
    ticker: str
    session_date: date
    prior_close: float
    adv50: float
    dollar_adv: float
    high_65: Optional[float]
    ema_10: Optional[float]
    market_cap: Optional[float] = None
    shares_float: Optional[float] = None
    is_qualified: bool = True
    rejection_reason: Optional[str] = None


@dataclass(frozen=True)
class BaseHitBreakoutCandidate:
    """
    Deterministic Base-Hit Breakout setup candidate identified from daily screening.
    Ready to feed into the intraday execution simulator without lookahead.
    """
    security_id: str
    ticker: str
    session_date: date
    trigger_price: float       # 65-day high + 0.01
    structural_stop: float     # Estimated shelf low or conservative stop
    risk_geometry_pct: float
    adv50: float
    is_qualified: bool
    rejection_reason: Optional[str] = None


class UniverseScreener:
    """
    Point-in-Time Daily Universe Screener.
    Filters candidate pool before market open of session t using t-1 metrics.
    """

    def __init__(
        self,
        config: Optional[StrategyConfig] = None,
        security_master: Optional[SecurityMasterProvider] = None,
        daily_provider: Optional[DailyBarProvider] = None,
        float_map: Optional[Dict[str, float]] = None,
        market_cap_map: Optional[Dict[str, float]] = None,
    ):
        self.config = config or StrategyConfig()
        self.security_master = security_master
        self.daily_provider = daily_provider
        self._float_map = float_map or {}
        self._market_cap_map = market_cap_map or {}

    def screen_universe(self, session_date: date) -> List[ScreenedCandidate]:
        """
        Screens all active securities for session_date using data through session t-1.
        Returns list of qualifying ScreenedCandidate objects.
        """
        if not self.security_master or not self.daily_provider:
            return []

        active_securities = self.security_master.get_all_active_securities(session_date)
        candidates: List[ScreenedCandidate] = []

        for sec in active_securities:
            # 1. Fetch t-1 completed daily bar
            prior_bars = self.daily_provider.get_prior_completed_bars(
                security_id=sec.security_id,
                as_of_date=session_date,
                count=1,
            )
            if not prior_bars:
                continue

            t_minus_1_bar = prior_bars[-1]
            prior_close = t_minus_1_bar.close

            # 2. Check Price Floor (>= $5.00)
            if prior_close < self.config.price_floor:
                continue

            # 3. Calculate Point-in-Time ADV50
            adv50 = calculate_adv50(
                security_id=sec.security_id,
                session_date=session_date,
                daily_provider=self.daily_provider,
                lookback_sessions=50,
            )
            if adv50 is None or adv50 < self.config.adv50_min:
                continue

            # 4. Dollar ADV Gate (>= $2.5M)
            dollar_adv = prior_close * adv50
            if dollar_adv < self.config.dollar_adv_min:
                continue

            # 5. Shares Float Filter (<= 50M shares if specified)
            shares_float = self._float_map.get(sec.security_id)
            if self.config.float_max is not None and shares_float is not None:
                if shares_float > self.config.float_max:
                    continue

            # 6. Market Cap Filter (if specified)
            market_cap = self._market_cap_map.get(sec.security_id)
            if self.config.market_cap_min is not None and market_cap is not None:
                if market_cap < self.config.market_cap_min:
                    continue
            if self.config.market_cap_max is not None and market_cap is not None:
                if market_cap > self.config.market_cap_max:
                    continue

            # Compute technical levels
            high_65 = calculate_65d_high(sec.security_id, session_date, self.daily_provider)
            ema_10 = calculate_10ema(sec.security_id, session_date, self.daily_provider)

            candidates.append(
                ScreenedCandidate(
                    security_id=sec.security_id,
                    ticker=sec.ticker,
                    session_date=session_date,
                    prior_close=prior_close,
                    adv50=adv50,
                    dollar_adv=dollar_adv,
                    high_65=high_65,
                    ema_10=ema_10,
                    market_cap=market_cap,
                    shares_float=shares_float,
                    is_qualified=True,
                )
            )

        return candidates


class BaseHitCandidateGenerator:
    """
    Identifies 65-Day High Breakout Candidates from screened universe.
    Separates setup discovery from intraday execution.
    """

    def __init__(
        self,
        config: Optional[StrategyConfig] = None,
        daily_provider: Optional[DailyBarProvider] = None,
    ):
        self.config = config or StrategyConfig()
        self.daily_provider = daily_provider

    def generate_breakout_candidates(
        self,
        screened_pool: List[ScreenedCandidate],
        session_date: date,
        proximity_pct: float = 0.05,  # Within 5% of 65-day high
    ) -> List[BaseHitBreakoutCandidate]:
        """
        Filters screened pool for stocks consolidating within proximity_pct of 65-day high.
        """
        breakouts: List[BaseHitBreakoutCandidate] = []

        for candidate in screened_pool:
            if candidate.high_65 is None:
                continue

            # Check if prior close is near 65-day high
            distance_to_high = (candidate.high_65 - candidate.prior_close) / candidate.high_65
            if distance_to_high > proximity_pct:
                continue

            trigger_price = round(candidate.high_65 + self.config.tick_size, 2)

            # Determine structural stop from recent shelf or conservative 2-day low
            shelf_low = candidate.prior_close * (1.0 - 0.03)  # Conservative 3% shelf default
            if self.daily_provider:
                recent_bars = self.daily_provider.get_prior_completed_bars(
                    security_id=candidate.security_id,
                    as_of_date=session_date,
                    count=3,
                )
                if recent_bars:
                    shelf_low = min(b.low for b in recent_bars)

            stop_price = round(shelf_low - self.config.tick_size, 2)
            if stop_price >= trigger_price:
                continue

            risk_geometry = (trigger_price - stop_price) / trigger_price
            if risk_geometry > self.config.max_risk_geometry_pct:
                continue

            breakouts.append(
                BaseHitBreakoutCandidate(
                    security_id=candidate.security_id,
                    ticker=candidate.ticker,
                    session_date=session_date,
                    trigger_price=trigger_price,
                    structural_stop=stop_price,
                    risk_geometry_pct=risk_geometry,
                    adv50=candidate.adv50,
                    is_qualified=True,
                )
            )

        return breakouts
