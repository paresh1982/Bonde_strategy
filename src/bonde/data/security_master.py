"""
Security Master & Point-in-Time Security Identity Resolution (Section 2)
Enforces the invariant: ticker != security identity.
Resolves security identities across ticker recycling, delisting, and corporate symbol changes.
"""

from abc import ABC, abstractmethod
from dataclasses import dataclass
from datetime import date
from typing import Dict, List, Optional


@dataclass(frozen=True)
class Security:
    """Canonical Security Master record."""
    security_id: str
    ticker: str
    exchange: str
    name: str
    first_trade_date: date
    last_trade_date: date
    delisting_date: Optional[date] = None
    active_flag: bool = True
    cusip: Optional[str] = None
    figi: Optional[str] = None

    def is_active_on(self, as_of_date: date) -> bool:
        """Determines if the security was actively trading on as_of_date."""
        if as_of_date < self.first_trade_date:
            return False
        if self.delisting_date is not None and as_of_date > self.delisting_date:
            return False
        if as_of_date > self.last_trade_date:
            return False
        return True


@dataclass(frozen=True)
class SecurityHistoryRecord:
    """Historical ticker-to-security_id mapping window."""
    security_id: str
    ticker: str
    effective_from: date
    effective_to: Optional[date]  # None indicates currently active


class SecurityMasterProvider(ABC):
    """Abstract interface for Point-in-Time Security Identity Resolution."""

    @abstractmethod
    def resolve_security_id(self, ticker: str, as_of_date: date) -> Optional[str]:
        """
        Resolves canonical security_id for ticker as of date.
        Must return None (fail closed) if no valid mapping exists for that date.
        """
        pass

    @abstractmethod
    def get_security(self, security_id: str) -> Optional[Security]:
        """Retrieves canonical security record by security_id."""
        pass

    @abstractmethod
    def is_active(self, security_id: str, as_of_date: date) -> bool:
        """Checks if security was actively trading on as_of_date."""
        pass

    @abstractmethod
    def get_all_active_securities(self, as_of_date: date) -> List[Security]:
        """Returns all securities actively trading on as_of_date."""
        pass


class InMemorySecurityMaster(SecurityMasterProvider):
    """
    In-memory reference implementation of SecurityMasterProvider.
    Enforces strict point-in-time identity resolution without lookahead.
    """

    def __init__(
        self,
        securities: Optional[List[Security]] = None,
        history: Optional[List[SecurityHistoryRecord]] = None,
    ):
        self._securities: Dict[str, Security] = {s.security_id: s for s in (securities or [])}
        self._history: List[SecurityHistoryRecord] = history or []

    def add_security(self, security: Security):
        self._securities[security.security_id] = security

    def add_history_record(self, record: SecurityHistoryRecord):
        self._history.append(record)

    def resolve_security_id(self, ticker: str, as_of_date: date) -> Optional[str]:
        """
        Point-in-time resolution:
        Matches ticker where effective_from <= as_of_date <= effective_to (or None).
        Fails closed on collision or missing record.
        """
        ticker_upper = ticker.upper().strip()
        matches = []
        for rec in self._history:
            if rec.ticker.upper() == ticker_upper:
                if rec.effective_from <= as_of_date:
                    if rec.effective_to is None or as_of_date <= rec.effective_to:
                        # Also ensure the underlying security was not already delisted
                        sec = self._securities.get(rec.security_id)
                        if sec and sec.is_active_on(as_of_date):
                            matches.append(rec.security_id)

        # Fail closed on collisions or no matches
        if len(matches) == 1:
            return matches[0]
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
