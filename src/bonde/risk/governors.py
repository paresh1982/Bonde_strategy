"""
Portfolio & Account Risk Governors (Section 16, D5)
Provides hierarchical veto authority across macro regime, portfolio heat, sector caps, and performance circuit breakers.
"""

from abc import ABC, abstractmethod
from typing import List, Optional, Tuple, Any
from ..regime.market_regime import MarketRegime


class RiskGovernor(ABC):
    """Abstract interface for portfolio risk gates."""
    @abstractmethod
    def evaluate(
        self,
        symbol: str,
        planned_risk_dollars: float,
        unit_1r_dollars: float,
        regime: MarketRegime,
        sector: Optional[str],
        open_positions: List[Any],
    ) -> Tuple[bool, Optional[str]]:
        """
        Returns (is_allowed: bool, rejection_reason: Optional[str]).
        """
        pass


class RegimeGovernor(RiskGovernor):
    """Rejects all new trades in MarketRegime.RED."""
    def evaluate(
        self,
        symbol: str,
        planned_risk_dollars: float,
        unit_1r_dollars: float,
        regime: MarketRegime,
        sector: Optional[str],
        open_positions: List[Any],
    ) -> Tuple[bool, Optional[str]]:
        if regime == MarketRegime.RED:
            return False, "RED_REGIME_NEW_TRADES_DISABLED"
        return True, None


class HeatGovernor(RiskGovernor):
    """Enforces total portfolio uncushioned heat cap (default 6.0R)."""
    def __init__(self, max_heat_r: float = 6.0):
        self.max_heat_r = max_heat_r

    def evaluate(
        self,
        symbol: str,
        planned_risk_dollars: float,
        unit_1r_dollars: float,
        regime: MarketRegime,
        sector: Optional[str],
        open_positions: List[Any],
    ) -> Tuple[bool, Optional[str]]:
        if unit_1r_dollars <= 0:
            return False, "INVALID_1R_DOLLARS"

        # Sum uncushioned risk (positions where stop is still below breakeven)
        uncushioned_dollars = sum(
            pos.current_risk_dollars for pos in open_positions if not pos.is_cushioned
        )
        total_proposed_heat_r = (uncushioned_dollars + planned_risk_dollars) / unit_1r_dollars

        if total_proposed_heat_r > self.max_heat_r + 1e-6:
            return False, f"PORTFOLIO_HEAT_EXCEEDED ({total_proposed_heat_r:.2f}R > {self.max_heat_r:.1f}R)"

        return True, None


class SectorGovernor(RiskGovernor):
    """Enforces sector concentration cap (default max 2.0R uncushioned in same industry group)."""
    def __init__(self, max_sector_r: float = 2.0):
        self.max_sector_r = max_sector_r

    def evaluate(
        self,
        symbol: str,
        planned_risk_dollars: float,
        unit_1r_dollars: float,
        regime: MarketRegime,
        sector: Optional[str],
        open_positions: List[Any],
    ) -> Tuple[bool, Optional[str]]:
        if sector is None or sector == "" or sector == "GENERAL":
            return True, None  # Unassigned or neutral sector does not block

        if unit_1r_dollars <= 0:
            return False, "INVALID_1R_DOLLARS"

        sector_uncushioned_dollars = sum(
            pos.current_risk_dollars
            for pos in open_positions
            if pos.sector == sector and not pos.is_cushioned
        )
        total_proposed_sector_r = (sector_uncushioned_dollars + planned_risk_dollars) / unit_1r_dollars

        if total_proposed_sector_r > self.max_sector_r + 1e-6:
            return False, f"SECTOR_HEAT_EXCEEDED ({sector}: {total_proposed_sector_r:.2f}R > {self.max_sector_r:.1f}R)"

        return True, None


class SingleTickerGovernor(RiskGovernor):
    """Enforces max 1.0R per ticker (deduplicates multiple signals on same symbol)."""
    def evaluate(
        self,
        symbol: str,
        planned_risk_dollars: float,
        unit_1r_dollars: float,
        regime: MarketRegime,
        sector: Optional[str],
        open_positions: List[Any],
    ) -> Tuple[bool, Optional[str]]:
        if any(pos.symbol == symbol for pos in open_positions):
            return False, f"SINGLE_TICKER_EXPOSURE_EXCEEDED (Active position exists for {symbol})"
        return True, None


class InternalLossGovernor(RiskGovernor):
    """Tracks consecutive losses and trips pilot or pause state (Document 06, Section 16)."""
    def __init__(self, max_consecutive_losses: int = 3, cooldown_days: int = 3):
        self.max_consecutive_losses = max_consecutive_losses
        self.cooldown_days = cooldown_days
        self.consecutive_losses: int = 0
        self.is_halted: bool = False
        self.halt_remaining_days: int = 0

    def record_closed_trade(self, realized_pnl: float):
        if realized_pnl < 0:
            self.consecutive_losses += 1
            if self.consecutive_losses >= self.max_consecutive_losses:
                self.is_halted = True
                self.halt_remaining_days = self.cooldown_days
        else:
            self.consecutive_losses = 0
            self.is_halted = False
            self.halt_remaining_days = 0

    def on_new_session(self, session_date: Optional[Any] = None):
        """Called at the start of each new trading session to tick cooldown."""
        if self.is_halted:
            if self.halt_remaining_days > 1:
                self.halt_remaining_days -= 1
            else:
                self.is_halted = False
                self.halt_remaining_days = 0
                self.consecutive_losses = 0

    def evaluate(
        self,
        symbol: str,
        planned_risk_dollars: float,
        unit_1r_dollars: float,
        regime: MarketRegime,
        sector: Optional[str],
        open_positions: List[Any],
    ) -> Tuple[bool, Optional[str]]:
        if self.is_halted:
            return False, f"INTERNAL_GOVERNOR_HALTED ({self.consecutive_losses} consecutive losses, {self.halt_remaining_days} cooldown days remaining)"
        return True, None


class CompositeRiskGovernor(RiskGovernor):
    """Evaluates a list of governors in strict hierarchical order."""
    def __init__(self, governors: Optional[List[RiskGovernor]] = None):
        self.governors = governors or [
            RegimeGovernor(),
            InternalLossGovernor(),
            SingleTickerGovernor(),
            HeatGovernor(),
            SectorGovernor(),
        ]

    def record_closed_trade(self, realized_pnl: float):
        """Propagates closed trade outcomes to internal performance governors."""
        for gov in self.governors:
            if hasattr(gov, "record_closed_trade"):
                gov.record_closed_trade(realized_pnl)

    def on_new_session(self, session_date: Optional[Any] = None):
        """Propagates new trading session notifications to all governors."""
        for gov in self.governors:
            if hasattr(gov, "on_new_session"):
                gov.on_new_session(session_date)

    def evaluate(
        self,
        symbol: str,
        planned_risk_dollars: float,
        unit_1r_dollars: float,
        regime: MarketRegime,
        sector: Optional[str],
        open_positions: List[Any],
    ) -> Tuple[bool, Optional[str]]:
        for gov in self.governors:
            allowed, reason = gov.evaluate(
                symbol=symbol,
                planned_risk_dollars=planned_risk_dollars,
                unit_1r_dollars=unit_1r_dollars,
                regime=regime,
                sector=sector,
                open_positions=open_positions,
            )
            if not allowed:
                return False, reason
        return True, None
