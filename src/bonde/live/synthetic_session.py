"""
Deterministic Synthetic Streaming Replay Session (Stage 2)
Replays complete pre-market, ORB formation, breakout fills, +2R partial exits, and EOD management.
"""

from datetime import date, datetime, time, timedelta
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple
import zoneinfo

from ..data.catalysts import EarningsEvent
from ..data.dual_price import DailyBar, InMemoryDailyBarProvider
from ..data.models import Bar, NY_TZ
from ..data.sectors import HistoricalSectorRecord, PointInTimeSectorProvider
from ..data.security_master import InMemorySecurityMaster, Security
from .models import LiveBar, Quote
from .providers import SyntheticCatalystProvider, SyntheticMarketDataProvider
from .session import LiveSessionEngine


class SyntheticSessionGenerator:
    """
    Constructs a deterministic sequence of streaming events for a test session.
    """

    @staticmethod
    def create_deterministic_session_stream(
        session_date: date = date(2023, 6, 15),
    ) -> Tuple[List[LiveBar], List[Quote], EarningsEvent]:
        """
        Creates a reproducible streaming fixture:
        - 07:00 ET: Track A BMO earnings announcement for TSLA
        - 09:30 - 09:34 ET: 5-minute ORB formation for TSLA (High: $250.00, Low: $246.00)
        - 09:35 ET: Breakout bar triggers stop-limit at $250.01 (Order fills at $250.02)
        - 09:40 ET: Spikes to $258.50, crossing +2R target ($258.03) -> 50% partial exit, stop ratchets to $250.03
        - 15:55 ET: Cushioned runner holds into close at $260.00
        """
        # Catalyst event
        catalyst = EarningsEvent(
            security_id="SEC_TSLA",
            event_timestamp=datetime.combine(session_date, time(7, 0), tzinfo=NY_TZ),
            event_date=session_date,
            timing="BMO",
            source="PR_NEWSWIRE",
            availability_timestamp=datetime.combine(session_date, time(7, 5), tzinfo=NY_TZ),
        )

        bars = []
        quotes = []

        # 1. 09:30 - 09:34: ORB formation bars (5 minutes)
        orb_data = [
            (9, 30, 247.00, 248.50, 246.50, 248.00, 150_000),
            (9, 31, 248.00, 249.20, 247.50, 248.80, 120_000),
            (9, 32, 248.80, 249.80, 248.00, 249.50, 110_000),
            (9, 33, 249.50, 250.00, 248.50, 249.00, 105_000),
            (9, 34, 249.00, 249.60, 246.00, 248.50, 95_000),
        ]
        # ORB High = 250.00, ORB Low = 246.00, Trigger = 250.01, Stop = 245.99 (Risk = 4.02, +2R = 258.05)

        for hr, mn, o, h, l, c, v in orb_data:
            ts = datetime.combine(session_date, time(hr, mn), tzinfo=NY_TZ)
            bars.append(LiveBar(timestamp=ts, symbol="TSLA", security_id="SEC_TSLA", open=o, high=h, low=l, close=c, volume=v))
            quotes.append(Quote(timestamp=ts, symbol="TSLA", security_id="SEC_TSLA", bid=c - 0.05, ask=c + 0.05))

        # 2. 09:35 - Breakout bar (crosses 250.01 trigger)
        ts_35 = datetime.combine(session_date, time(9, 35), tzinfo=NY_TZ)
        bars.append(LiveBar(timestamp=ts_35, symbol="TSLA", security_id="SEC_TSLA", open=249.50, high=251.50, low=249.20, close=251.00, volume=350_000))
        quotes.append(Quote(timestamp=ts_35, symbol="TSLA", security_id="SEC_TSLA", bid=250.95, ask=251.05))

        # 3. 09:36 to 09:39 - Continuation
        for mn in range(36, 40):
            ts = datetime.combine(session_date, time(9, mn), tzinfo=NY_TZ)
            bars.append(LiveBar(timestamp=ts, symbol="TSLA", security_id="SEC_TSLA", open=251.00 + (mn - 35), high=252.50 + (mn - 35), low=250.80 + (mn - 35), close=252.00 + (mn - 35), volume=100_000))
            quotes.append(Quote(timestamp=ts, symbol="TSLA", security_id="SEC_TSLA", bid=251.95, ask=252.05))

        # 4. 09:40 - Spike reaching +2R partial target (high = 259.00 > 258.05)
        ts_40 = datetime.combine(session_date, time(9, 40), tzinfo=NY_TZ)
        bars.append(LiveBar(timestamp=ts_40, symbol="TSLA", security_id="SEC_TSLA", open=255.00, high=259.00, low=254.50, close=258.50, volume=400_000))
        quotes.append(Quote(timestamp=ts_40, symbol="TSLA", security_id="SEC_TSLA", bid=258.45, ask=258.55))

        # 5. 15:55 - EOD bar closing near highs ($260.00)
        ts_eod = datetime.combine(session_date, time(15, 55), tzinfo=NY_TZ)
        bars.append(LiveBar(timestamp=ts_eod, symbol="TSLA", security_id="SEC_TSLA", open=259.50, high=260.50, low=259.00, close=260.00, volume=200_000))
        quotes.append(Quote(timestamp=ts_eod, symbol="TSLA", security_id="SEC_TSLA", bid=259.95, ask=260.05))

        return bars, quotes, catalyst


class SyntheticSessionReplayer:
    """
    Executes a deterministic end-to-end synthetic streaming session.
    """

    @staticmethod
    def run_synthetic_session(
        session_date: date = date(2023, 6, 15),
        data_root: Path = Path("data/stage1d"),
        output_dir: Path = Path("data/paper"),
    ) -> Dict[str, Any]:
        bars, quotes, catalyst = SyntheticSessionGenerator.create_deterministic_session_stream(session_date)

        # Initialize engine
        engine = LiveSessionEngine(
            session_date=session_date,
            data_root=data_root,
            output_dir=output_dir,
            initial_equity=100_000.0,
        )

        # Inject synthetic catalyst event into engine's prep pipeline
        if engine.prep_pipeline.catalyst_engine and engine.prep_pipeline.catalyst_engine.earnings_provider:
            engine.prep_pipeline.catalyst_engine.earnings_provider.add_event(catalyst)

        # 1. Pre-Market Prep
        focus_list = engine.run_premarket()

        # 2. Opening Bell
        engine.open_session()

        # 3. Stream bars & quotes chronologically
        quote_map = {q.timestamp: q for q in quotes}
        for b in bars:
            q = quote_map.get(b.timestamp)
            engine.process_live_bar(b, quote=q)

        # 4. Close Session & Export
        summary = engine.close_session()
        return {
            "summary": summary,
            "engine": engine,
            "focus_list": focus_list,
        }
