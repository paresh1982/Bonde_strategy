"""
End-to-End Point-in-Time Backtest Pipeline (Section 16)
Orchestrates:
Data Providers
  ↓
Point-in-Time Data Layer
  ↓
Historical Universe Scanner
  ↓
Candidate Generator
  ↓
Candidate-Targeted Intraday Extraction
  ↓
Stage 0.2 Event-Driven Execution Engine
  ↓
Portfolio / Governors
  ↓
Trade Journal
"""

from datetime import date, datetime
from typing import Dict, List, Optional

from ..config.strategy_config import StrategyConfig
from .breadth import MarketBreadthProvider, PointInTimeMarketRegimeProvider
from .dual_price import DailyBarProvider
from .intraday import IntradayBarProvider
from .indicators import PointInTimeIndicatorEngine
from .screener import UniverseScreener, ScreenedCandidate
from .sectors import PointInTimeSectorProvider
from .security_master import SecurityMasterProvider


class HistoricalBacktestPipeline:
    """
    Point-in-Time End-to-End Backtest Orchestrator.
    Feeds real or synthetic historical data into the Stage 0.2 execution engine
    while strictly preserving point-in-time constraints.
    """

    def __init__(
        self,
        config: Optional[StrategyConfig] = None,
        security_master: Optional[SecurityMasterProvider] = None,
        daily_provider: Optional[DailyBarProvider] = None,
        intraday_provider: Optional[IntradayBarProvider] = None,
        sector_provider: Optional[PointInTimeSectorProvider] = None,
        breadth_provider: Optional[MarketBreadthProvider] = None,
        initial_equity: float = 100_000.0,
    ):
        self.config = config or StrategyConfig()
        self.security_master = security_master
        self.daily_provider = daily_provider
        self.intraday_provider = intraday_provider
        self.sector_provider = sector_provider
        self.breadth_provider = breadth_provider
        self.initial_equity = initial_equity

        # Initialize Indicator Engine
        self.indicator_engine = (
            PointInTimeIndicatorEngine(self.daily_provider, self.security_master)
            if self.daily_provider
            else None
        )

        # Initialize Regime Provider
        self.regime_provider = (
            PointInTimeMarketRegimeProvider(self.breadth_provider)
            if self.breadth_provider
            else None
        )

        # Initialize Universe Screener
        self.screener = UniverseScreener(
            config=self.config,
            security_master=self.security_master,
            daily_provider=self.daily_provider,
        )

        # Instantiate Stage 0.2 Backtest Engine
        from ..engine.backtest import Stage0BacktestEngine
        self.engine = Stage0BacktestEngine(
            config=self.config,
            regime_provider=self.regime_provider,
            sector_provider=self.sector_provider,
            daily_indicator_provider=self.indicator_engine,
            adv_provider=self.indicator_engine,
            initial_equity=self.initial_equity,
        )

    def run_session(self, session_date: date) -> List[ScreenedCandidate]:
        """
        Executes a single session chronologically:
        1. Run daily screen before open using t-1 metrics.
        2. Extract targeted intraday 1m bars ONLY for qualifying candidates + open positions.
        3. Feed bars to the execution engine.
        """
        # 1. Screen Universe as of t-1
        candidates = self.screener.screen_universe(session_date)

        # Collect securities needing intraday execution bars
        symbols_to_feed = set()
        for cand in candidates:
            symbols_to_feed.add(cand.ticker)

        # Also add any currently open positions needing intraday trailing stops
        for pos_symbol in self.engine.portfolio.open_positions.keys():
            symbols_to_feed.add(pos_symbol)

        # 2. Extract targeted intraday bars
        intraday_bars = []
        if self.intraday_provider and self.security_master:
            for sym in symbols_to_feed:
                sec_id = self.security_master.resolve_security_id(sym, session_date)
                if sec_id:
                    bars = self.intraday_provider.get_intraday_bars(sec_id, session_date)
                    intraday_bars.extend(bars)

        # 3. Feed intraday bars to Stage 0.2 engine
        if intraday_bars:
            self.engine.run(intraday_bars)

        return candidates

    def run_date_range(self, trading_dates: List[date]):
        """Executes simulation across a sequence of trading dates."""
        sorted_dates = sorted(trading_dates)
        for d in sorted_dates:
            self.run_session(d)
