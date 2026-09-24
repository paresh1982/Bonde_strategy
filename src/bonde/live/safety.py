"""
Failure Safety & Fail-Closed Gateways (Stage 2)
Guarantees that live trade generation fails closed on missing, invalid, or inconsistent state.
"""

from datetime import date, datetime
from typing import Any, List, Optional

from ..regime.market_regime import MarketRegime
from .models import TradingSession


class SafetyError(Exception):
    """Raised when an explicit fail-closed safety check fails."""
    pass


class LiveSafetyGovernor:
    """
    Evaluates fail-closed safety criteria before permitting trade generation or order staging.
    """

    @staticmethod
    def assert_session_valid(session: Optional[TradingSession], current_time: datetime):
        if session is None:
            raise SafetyError("SESSION_STATE_UNKNOWN: Trading session is None. Failing closed.")
        if not (session.open_time <= current_time <= session.close_time):
            raise SafetyError(
                f"SESSION_BOUNDARY_BREACH: Current time {current_time} outside session ({session.open_time}-{session.close_time}). Failing closed."
            )

    @staticmethod
    def assert_regime_valid(regime: Optional[MarketRegime]):
        if regime is None:
            raise SafetyError("REGIME_STATE_UNKNOWN: Market regime is None. Failing closed.")
        if regime not in (MarketRegime.GREEN, MarketRegime.YELLOW, MarketRegime.RED):
            raise SafetyError(f"REGIME_STATE_INVALID: Unrecognized regime value {regime}. Failing closed.")

    @staticmethod
    def assert_bars_available(bars: List[Any], required_count: int, symbol: str):
        if len(bars) < required_count:
            raise SafetyError(
                f"MISSING_BARS_FAIL_CLOSED: {symbol} has {len(bars)} bars, requires {required_count}. Failing closed."
            )

    @staticmethod
    def assert_security_resolved(security_id: Optional[str], symbol: str):
        if not security_id or security_id.strip() == "":
            raise SafetyError(f"UNRESOLVED_SECURITY_FAIL_CLOSED: Unable to resolve security_id for symbol {symbol}.")

    @staticmethod
    def assert_sizing_inputs_valid(unit_1r: float, planned_shares: int, trigger: float, stop: float):
        if unit_1r <= 0:
            raise SafetyError(f"INVALID_SIZING_INPUT: unit_1r ({unit_1r}) must be positive.")
        if trigger <= 0 or stop <= 0:
            raise SafetyError(f"INVALID_PRICE_INPUT: trigger ({trigger}) and stop ({stop}) must be positive.")
        if trigger <= stop:
            raise SafetyError(f"INVERTED_GEOMETRY_INPUT: trigger ({trigger}) must be strictly greater than stop ({stop}).")
        if planned_shares < 0:
            raise SafetyError(f"INVALID_SHARES_INPUT: planned_shares ({planned_shares}) cannot be negative.")

    @staticmethod
    def assert_governor_state_valid(risk_governor: Any):
        if risk_governor is None:
            raise SafetyError("RISK_GOVERNOR_STATE_UNKNOWN: Risk governor is None. Failing closed.")
