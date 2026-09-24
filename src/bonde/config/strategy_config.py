"""
Strategy Configuration - Stage 0 Baseline Parameters
Note: Parameters are testable hypotheses frozen for Stage 0 execution verification.
"""

from dataclasses import dataclass
from typing import Optional


@dataclass(frozen=True)
class StrategyConfig:
    # Timezone and Market Hours (America/New_York)
    timezone: str = "America/New_York"
    market_open_time: str = "09:30:00"
    orb_window_end_time: str = "09:35:00"
    stale_order_cutoff_time: str = "10:15:00"
    eod_audit_time: str = "15:55:00"
    market_close_time: str = "16:00:00"

    # Universe & Liquidity Filters
    price_floor: float = 5.00
    adv50_min: float = 100_000.0
    dollar_adv_min: float = 2_500_000.0
    min_adv_50: float = 100_000.0  # Backward compatibility alias
    min_dollar_volume: float = 2_500_000.0  # Backward compatibility alias
    market_cap_min: Optional[float] = None
    market_cap_max: Optional[float] = None
    float_max: Optional[float] = 50_000_000.0  # 50M float cap

    # Data Infrastructure Configuration
    data_root: str = "data"

    # Risk Geometry & Execution
    max_risk_geometry_pct: float = 0.040  # Hard 4.0% gate
    default_collar_cents: float = 0.10     # Stop-limit execution collar
    tick_size: float = 0.01

    # Position Sizing & Liquidity Cap (Hypotheses D3, D4, D47)
    green_risk_fraction: float = 0.010    # 1.0% equity risk
    yellow_risk_fraction: float = 0.005   # 0.5% equity risk
    adv_participation_cap: float = 0.015  # 1.5% of ADV50
    min_allocation_ratio: float = 0.60    # 0.60R cutoff

    # Portfolio Governors
    sector_cap_max_r: float = 2.0        # Max 2.0R uncushioned in same sector
    portfolio_heat_cap_r: float = 6.0    # Max 6.0R uncushioned portfolio heat
    single_ticker_max_r: float = 1.0     # Max 1.0R per ticker

    # Trade Management & Exits
    partial_target_r: float = 2.0        # +2.0R profit-taking level
    partial_exit_ratio: float = 0.50     # 50% tranche
    base_hit_max_holding_days: int = 5   # Max 5 days for Base Hits
    parabolic_climax_pct: float = 0.25   # 25% above 10 EMA
