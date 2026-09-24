"""
Real-Time Data Validator & Fail-Closed Gate (Stage 2)
Validates incoming live bars, quotes, and timestamps before they enter strategy calculations.
"""

from datetime import datetime, timedelta
from typing import Dict, List, Optional, Tuple
import pandas as pd

from ..data.models import NY_TZ
from .models import DataQualityStatus, LiveBar, Quote, RejectedEvent, TradingSession


class LiveDataValidator:
    """
    Fail-closed validator enforcing data integrity invariants on streaming market events.
    """

    def __init__(self, max_stale_seconds: float = 300.0, max_allowed_gap_minutes: int = 5):
        self.max_stale_seconds = max_stale_seconds
        self.max_allowed_gap_minutes = max_allowed_gap_minutes
        self._last_bar_timestamps: Dict[str, datetime] = {}
        self._last_quote_timestamps: Dict[str, datetime] = {}
        self.rejected_events: List[RejectedEvent] = []

    def reset(self):
        self._last_bar_timestamps.clear()
        self._last_quote_timestamps.clear()
        self.rejected_events.clear()

    def validate_bar(
        self,
        bar: LiveBar,
        session: TradingSession,
        current_clock: Optional[datetime] = None,
        source: str = "LIVE_FEED",
    ) -> Tuple[bool, Optional[RejectedEvent]]:
        """
        Validates 1-minute OHLCV bar against monotonic time, session boundaries,
        price positivity, OHLC consistency, staleness, and gaps.
        """
        sec_id = bar.security_id or f"SEC_{bar.symbol}"
        sym = bar.symbol

        # 1. Non-empty symbol & security ID
        if not sym or not sec_id:
            rej = RejectedEvent(
                timestamp=bar.timestamp,
                security_id=sec_id or "UNKNOWN",
                symbol=sym or "UNKNOWN",
                reason="INVALID_SECURITY_OR_SYMBOL",
                source=source,
                severity="ERROR",
                payload={"open": bar.open, "close": bar.close},
            )
            self.rejected_events.append(rej)
            return False, rej

        # 2. Session boundary verification (must fall between open_time and close_time)
        bar_ny = bar.timestamp.astimezone(NY_TZ)
        if bar_ny < session.open_time or bar_ny > session.close_time:
            rej = RejectedEvent(
                timestamp=bar.timestamp,
                security_id=sec_id,
                symbol=sym,
                reason=f"SESSION_BOUNDARY_VIOLATION ({bar_ny.time()} outside {session.open_time.time()}-{session.close_time.time()})",
                source=source,
                severity="ERROR",
                payload={"session_open": session.open_time.isoformat(), "session_close": session.close_time.isoformat()},
            )
            self.rejected_events.append(rej)
            return False, rej

        # 3. Monotonic timestamp ordering & duplicate check per security
        last_ts = self._last_bar_timestamps.get(sec_id)
        if last_ts is not None:
            if bar.timestamp == last_ts:
                rej = RejectedEvent(
                    timestamp=bar.timestamp,
                    security_id=sec_id,
                    symbol=sym,
                    reason=f"DUPLICATE_BAR_TIMESTAMP ({bar.timestamp.isoformat()} already processed)",
                    source=source,
                    severity="ERROR",
                    payload={"last_timestamp": last_ts.isoformat()},
                )
                self.rejected_events.append(rej)
                return False, rej
            elif bar.timestamp < last_ts:
                rej = RejectedEvent(
                    timestamp=bar.timestamp,
                    security_id=sec_id,
                    symbol=sym,
                    reason=f"MONOTONIC_TIMESTAMP_VIOLATION ({bar.timestamp.isoformat()} < {last_ts.isoformat()})",
                    source=source,
                    severity="ERROR",
                    payload={"last_timestamp": last_ts.isoformat()},
                )
                self.rejected_events.append(rej)
                return False, rej

            # Unexpected timestamp gap (> 5 minutes during open session)
            diff_mins = (bar.timestamp - last_ts).total_seconds() / 60.0
            if diff_mins > self.max_allowed_gap_minutes:
                rej = RejectedEvent(
                    timestamp=bar.timestamp,
                    security_id=sec_id,
                    symbol=sym,
                    reason=f"UNEXPECTED_TIMESTAMP_GAP ({diff_mins:.1f}m gap > {self.max_allowed_gap_minutes}m threshold)",
                    source=source,
                    severity="WARN",
                    payload={"gap_minutes": diff_mins, "prior_timestamp": last_ts.isoformat()},
                )
                # Keep record of gap warning
                self.rejected_events.append(rej)

        # 4. Positive prices and non-negative volume
        if bar.open <= 0 or bar.high <= 0 or bar.low <= 0 or bar.close <= 0:
            rej = RejectedEvent(
                timestamp=bar.timestamp,
                security_id=sec_id,
                symbol=sym,
                reason=f"NON_POSITIVE_PRICE (O={bar.open}, H={bar.high}, L={bar.low}, C={bar.close})",
                source=source,
                severity="CRITICAL",
                payload={"open": bar.open, "high": bar.high, "low": bar.low, "close": bar.close},
            )
            self.rejected_events.append(rej)
            return False, rej

        if bar.volume < 0:
            rej = RejectedEvent(
                timestamp=bar.timestamp,
                security_id=sec_id,
                symbol=sym,
                reason=f"NEGATIVE_VOLUME ({bar.volume})",
                source=source,
                severity="ERROR",
                payload={"volume": bar.volume},
            )
            self.rejected_events.append(rej)
            return False, rej

        # 5. OHLC structural geometry
        if bar.high < max(bar.open, bar.close) - 1e-4:
            rej = RejectedEvent(
                timestamp=bar.timestamp,
                security_id=sec_id,
                symbol=sym,
                reason=f"OHLC_HIGH_LESS_THAN_OPEN_OR_CLOSE (H={bar.high} < max({bar.open}, {bar.close}))",
                source=source,
                severity="CRITICAL",
                payload={"high": bar.high, "open": bar.open, "close": bar.close},
            )
            self.rejected_events.append(rej)
            return False, rej

        if bar.low > min(bar.open, bar.close) + 1e-4:
            rej = RejectedEvent(
                timestamp=bar.timestamp,
                security_id=sec_id,
                symbol=sym,
                reason=f"OHLC_LOW_GREATER_THAN_OPEN_OR_CLOSE (L={bar.low} > min({bar.open}, {bar.close}))",
                source=source,
                severity="CRITICAL",
                payload={"low": bar.low, "open": bar.open, "close": bar.close},
            )
            self.rejected_events.append(rej)
            return False, rej

        # 6. Staleness check against current clock (if provided)
        if current_clock is not None:
            age_sec = (current_clock - bar.timestamp).total_seconds()
            if age_sec > self.max_stale_seconds:
                rej = RejectedEvent(
                    timestamp=bar.timestamp,
                    security_id=sec_id,
                    symbol=sym,
                    reason=f"STALE_BAR_DATA ({age_sec:.1f}s old > {self.max_stale_seconds}s limit)",
                    source=source,
                    severity="ERROR",
                    payload={"age_seconds": age_sec, "current_clock": current_clock.isoformat()},
                )
                self.rejected_events.append(rej)
                return False, rej

        # All checks passed
        self._last_bar_timestamps[sec_id] = bar.timestamp
        return True, None

    def validate_quote(
        self,
        quote: Quote,
        session: TradingSession,
        current_clock: Optional[datetime] = None,
        source: str = "LIVE_FEED",
    ) -> Tuple[bool, Optional[RejectedEvent]]:
        """
        Validates streaming top-of-book quote for positivity, non-inversion, and staleness.
        """
        sec_id = quote.security_id or f"SEC_{quote.symbol}"
        sym = quote.symbol

        # 1. Non-empty symbol
        if not sym or not sec_id:
            rej = RejectedEvent(
                timestamp=quote.timestamp,
                security_id=sec_id or "UNKNOWN",
                symbol=sym or "UNKNOWN",
                reason="INVALID_SECURITY_OR_SYMBOL",
                source=source,
                severity="ERROR",
                payload={"bid": quote.bid, "ask": quote.ask},
            )
            self.rejected_events.append(rej)
            return False, rej

        # 2. Positive quote prices
        if quote.bid <= 0 or quote.ask <= 0:
            rej = RejectedEvent(
                timestamp=quote.timestamp,
                security_id=sec_id,
                symbol=sym,
                reason=f"NON_POSITIVE_QUOTE (Bid={quote.bid}, Ask={quote.ask})",
                source=source,
                severity="CRITICAL",
                payload={"bid": quote.bid, "ask": quote.ask},
            )
            self.rejected_events.append(rej)
            return False, rej

        # 3. Non-inverted spread (Ask >= Bid)
        if quote.ask < quote.bid - 1e-4:
            rej = RejectedEvent(
                timestamp=quote.timestamp,
                security_id=sec_id,
                symbol=sym,
                reason=f"INVERTED_BID_ASK_SPREAD (Ask={quote.ask} < Bid={quote.bid})",
                source=source,
                severity="CRITICAL",
                payload={"bid": quote.bid, "ask": quote.ask},
            )
            self.rejected_events.append(rej)
            return False, rej

        # 4. Sizes must be positive
        if quote.bid_size < 0 or quote.ask_size < 0:
            rej = RejectedEvent(
                timestamp=quote.timestamp,
                security_id=sec_id,
                symbol=sym,
                reason=f"NEGATIVE_QUOTE_SIZE (BidSize={quote.bid_size}, AskSize={quote.ask_size})",
                source=source,
                severity="ERROR",
                payload={"bid_size": quote.bid_size, "ask_size": quote.ask_size},
            )
            self.rejected_events.append(rej)
            return False, rej

        # 5. Monotonic timestamp per security
        last_ts = self._last_quote_timestamps.get(sec_id)
        if last_ts is not None and quote.timestamp < last_ts:
            rej = RejectedEvent(
                timestamp=quote.timestamp,
                security_id=sec_id,
                symbol=sym,
                reason=f"MONOTONIC_QUOTE_VIOLATION ({quote.timestamp.isoformat()} < {last_ts.isoformat()})",
                source=source,
                severity="ERROR",
                payload={"last_timestamp": last_ts.isoformat()},
            )
            self.rejected_events.append(rej)
            return False, rej

        self._last_quote_timestamps[sec_id] = quote.timestamp
        return True, None

    def get_rejected_events_dataframe(self) -> pd.DataFrame:
        if not self.rejected_events:
            return pd.DataFrame()
        return pd.DataFrame([r.__dict__ for r in self.rejected_events])
