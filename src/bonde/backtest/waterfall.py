"""
Portfolio Allocation Waterfall & Candidate Specification (Phases 3 & 7)
Implements:
- 15-field Candidate Metadata Contract
- Priority waterfall: Catalyst seniority over Base-Hit
- Daily risk limits: GREEN (up to 3.0R), YELLOW (1.0R Catalyst only), RED (0R)
- Sector cap (2.0R), Heat cap (6.0R), Single-ticker deduplication (1.0R), Internal Loss Governor
"""

from dataclasses import dataclass
from datetime import date
import math
from typing import Dict, List, Optional, Tuple

from ..regime.market_regime import MarketRegime
from ..risk.governors import CompositeRiskGovernor, RiskGovernor
from ..risk.sizing import calculate_position_size


@dataclass
class CandidateMetadata:
    """Mandatory 15-field candidate metadata record (Phase 3)."""
    candidate_id: str
    security_id: str
    session_date: date
    engine: str                  # 'CATALYST' or 'BASE_HIT'
    module: str                  # 'TRACK_A', 'TRACK_B', 'EP', 'EP9M', 'BREAKOUT_65D', 'INSIDE_DAY'
    catalyst_track: str          # 'TRACK_A_EARNINGS', 'TRACK_B_PR', or 'NONE'
    trigger_price: float
    structural_stop: float
    planned_risk_pct: float      # (trigger - stop) / trigger
    risk_geometry: float         # risk geometry ratio
    adv50: float
    liquidity_cap: float         # adv50 * participation_cap
    planned_shares: int
    allocated_shares: int
    fractional_r: float          # allocated_shares / planned_shares
    rejection_reason: Optional[str] = None
    sector: Optional[str] = "GENERAL"
    ticker: Optional[str] = None


class PortfolioAllocationWaterfall:
    """
    Simulates the capital-allocation waterfall across candidate signals on session T.
    Enforces seniority, daily regime risk budgets, and portfolio limits.
    """

    def __init__(
        self,
        risk_fraction: float = 0.005,           # 0.5% default 1R
        daily_green_r: float = 3.0,
        daily_yellow_r: float = 1.0,
        max_sector_r: float = 2.0,
        max_heat_r: float = 6.0,
        adv_participation_cap: float = 0.015,   # 1.5% ADV
        min_allocation_ratio: float = 0.60,     # 0.60R minimum viable allocation
    ):
        self.risk_fraction = risk_fraction
        self.daily_green_r = daily_green_r
        self.daily_yellow_r = daily_yellow_r
        self.max_sector_r = max_sector_r
        self.max_heat_r = max_heat_r
        self.adv_participation_cap = adv_participation_cap
        self.min_allocation_ratio = min_allocation_ratio

    def allocate_candidates(
        self,
        candidates: List[CandidateMetadata],
        regime: MarketRegime,
        portfolio_equity: float,
        open_positions: list,
        risk_governor: Optional[RiskGovernor] = None,
        catalyst_seniority: bool = True,
    ) -> Tuple[List[CandidateMetadata], List[CandidateMetadata]]:
        """
        Processes candidate signals through the capital waterfall.
        Returns:
            (approved_candidates: List[CandidateMetadata], rejected_candidates: List[CandidateMetadata])
        """
        approved: List[CandidateMetadata] = []
        rejected: List[CandidateMetadata] = []

        unit_1r_dollars = portfolio_equity * self.risk_fraction
        if unit_1r_dollars <= 0:
            for c in candidates:
                c.rejection_reason = "INVALID_PORTFOLIO_EQUITY"
                rejected.append(c)
            return approved, rejected

        # Daily Regime Budget Cap
        if regime == MarketRegime.RED:
            for c in candidates:
                c.rejection_reason = "RED_REGIME_NEW_TRADES_DISABLED"
                rejected.append(c)
            return approved, rejected

        daily_budget_r = self.daily_green_r if regime == MarketRegime.GREEN else self.daily_yellow_r
        current_allocated_r = 0.0

        # Sort by Seniority: Catalyst first, then Base-Hit (if catalyst_seniority enabled)
        if catalyst_seniority:
            sorted_candidates = sorted(
                candidates,
                key=lambda c: (0 if c.engine == "CATALYST" else 1, -c.adv50)
            )
        else:
            # Ablation 10: Equal priority
            sorted_candidates = sorted(candidates, key=lambda c: -c.adv50)

        # Track existing ticker exposures and simulated newly allocated sectors/tickers
        allocated_tickers = set(pos.symbol for pos in open_positions)
        allocated_sector_risk: Dict[str, float] = {}

        # Pre-seed current sector uncushioned risk
        for pos in open_positions:
            sec = getattr(pos, "sector", "GENERAL") or "GENERAL"
            if not getattr(pos, "is_cushioned", False):
                allocated_sector_risk[sec] = allocated_sector_risk.get(sec, 0.0) + pos.current_risk_dollars

        # Pre-seed current total heat
        current_heat_dollars = sum(
            pos.current_risk_dollars for pos in open_positions if not getattr(pos, "is_cushioned", False)
        )

        for cand in sorted_candidates:
            sym = cand.ticker or cand.security_id

            # 1. Regime Module Gates: In YELLOW, only Catalyst is permitted
            if regime == MarketRegime.YELLOW and cand.engine != "CATALYST":
                cand.rejection_reason = "YELLOW_REGIME_BASE_HIT_DISABLED"
                rejected.append(cand)
                continue

            # 2. Daily Risk Budget Check
            if current_allocated_r >= daily_budget_r - 1e-6:
                cand.rejection_reason = f"DAILY_REGIME_BUDGET_EXHAUSTED ({daily_budget_r:.1f}R reached)"
                rejected.append(cand)
                continue

            # 3. Single-Ticker Deduplication Check (Max 1.0R per ticker)
            if sym in allocated_tickers:
                cand.rejection_reason = f"SINGLE_TICKER_EXPOSURE_EXCEEDED (Active position or prior signal exists for {sym})"
                rejected.append(cand)
                continue

            # 4. Sizing and Liquidity Cap Check
            risk_per_share = cand.trigger_price - cand.structural_stop
            if risk_per_share <= 0:
                cand.rejection_reason = "INVALID_RISK_PER_SHARE_NON_POSITIVE"
                rejected.append(cand)
                continue

            planned_shares = math.floor(unit_1r_dollars / risk_per_share)
            liquidity_cap_shares = math.floor(cand.adv50 * self.adv_participation_cap)
            allocated_shares = min(planned_shares, liquidity_cap_shares)

            if planned_shares <= 0 or allocated_shares <= 0:
                cand.rejection_reason = "INSUFFICIENT_SHARES_FOR_RISK"
                rejected.append(cand)
                continue

            frac_r = allocated_shares / planned_shares
            if frac_r < self.min_allocation_ratio:
                cand.rejection_reason = f"BELOW_MIN_VIABLE_ALLOCATION ({frac_r:.2f}R < {self.min_allocation_ratio:.2f}R)"
                rejected.append(cand)
                continue

            cand.planned_shares = planned_shares
            cand.allocated_shares = allocated_shares
            cand.fractional_r = frac_r

            proposed_risk_dollars = allocated_shares * risk_per_share
            proposed_r = proposed_risk_dollars / unit_1r_dollars

            # Check if this trade exceeds daily risk budget
            if current_allocated_r + proposed_r > daily_budget_r + 1e-4:
                # Can we scale down or reject? Under strict rules, if below 0.60R reject
                scaled_shares = math.floor((daily_budget_r - current_allocated_r) * unit_1r_dollars / risk_per_share)
                if scaled_shares / planned_shares >= self.min_allocation_ratio:
                    allocated_shares = scaled_shares
                    cand.allocated_shares = allocated_shares
                    cand.fractional_r = allocated_shares / planned_shares
                    proposed_risk_dollars = allocated_shares * risk_per_share
                    proposed_r = proposed_risk_dollars / unit_1r_dollars
                else:
                    cand.rejection_reason = "DAILY_BUDGET_REMAINDER_INSUFFICIENT"
                    rejected.append(cand)
                    continue

            # 5. Sector Concentration Cap (Max 2.0R uncushioned)
            sector_name = cand.sector or "GENERAL"
            current_sec_dollars = allocated_sector_risk.get(sector_name, 0.0)
            proposed_sec_r = (current_sec_dollars + proposed_risk_dollars) / unit_1r_dollars
            if sector_name != "GENERAL" and proposed_sec_r > self.max_sector_r + 1e-6:
                cand.rejection_reason = f"SECTOR_HEAT_EXCEEDED ({sector_name}: {proposed_sec_r:.2f}R > {self.max_sector_r:.1f}R)"
                rejected.append(cand)
                continue

            # 6. Portfolio Total Heat Cap (Max 6.0R uncushioned)
            proposed_total_heat_r = (current_heat_dollars + proposed_risk_dollars) / unit_1r_dollars
            if proposed_total_heat_r > self.max_heat_r + 1e-6:
                cand.rejection_reason = f"PORTFOLIO_HEAT_EXCEEDED ({proposed_total_heat_r:.2f}R > {self.max_heat_r:.1f}R)"
                rejected.append(cand)
                continue

            # 7. Risk Governor Check (Internal Loss Circuit Breaker)
            if risk_governor is not None:
                allowed, reason = risk_governor.evaluate(
                    symbol=sym,
                    planned_risk_dollars=proposed_risk_dollars,
                    unit_1r_dollars=unit_1r_dollars,
                    regime=regime,
                    sector=cand.sector,
                    open_positions=open_positions,
                )
                if not allowed:
                    cand.rejection_reason = reason or "GOVERNOR_VETO"
                    rejected.append(cand)
                    continue

            # Approved! Commit allocation
            cand.rejection_reason = None
            approved.append(cand)
            allocated_tickers.add(sym)
            allocated_sector_risk[sector_name] = current_sec_dollars + proposed_risk_dollars
            current_heat_dollars += proposed_risk_dollars
            current_allocated_r += proposed_r

        return approved, rejected
