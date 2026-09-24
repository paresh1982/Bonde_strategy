"""
Daily Pre-Market Pipeline (Stage 2)
Generates the deterministic Daily Focus List before market open using existing frozen rules.
"""

from dataclasses import dataclass
from datetime import date, datetime, time, timedelta
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple
import json
import pandas as pd

from ..backtest.multi_year_runner import PointInTimeCatalystEngine
from ..backtest.waterfall import CandidateMetadata, PortfolioAllocationWaterfall
from ..config.strategy_config import StrategyConfig
from ..data.breadth import InMemoryMarketBreadthProvider, MarketBreadthRecord, PointInTimeMarketRegimeProvider
from ..data.catalysts import EarningsEvent, InMemoryEarningsProvider, InMemoryFilingProvider, SECFilingEvent
from ..data.dual_price import DailyBar, InMemoryDailyBarProvider
from ..data.indicators import calculate_10ema, calculate_65d_high, calculate_adv50
from ..data.screener import UniverseScreener
from ..data.sectors import HistoricalSectorRecord, PointInTimeSectorProvider
from ..data.security_master import InMemorySecurityMaster, Security, SecurityHistoryRecord
from ..data.storage import LocalDataStorage
from ..portfolio.portfolio import Position
from ..regime.market_regime import MarketRegime
from ..risk.governors import CompositeRiskGovernor, HeatGovernor, InternalLossGovernor, RegimeGovernor, SectorGovernor, SingleTickerGovernor
from .calendar import USMarketCalendar


@dataclass
class DailyFocusList:
    """Deterministic snapshot of candidates evaluated before market open."""
    session_date: date
    regime: MarketRegime
    daily_budget_r: float
    total_allocated_r: float
    approved_candidates: List[CandidateMetadata]
    rejected_candidates: List[CandidateMetadata]
    all_candidates: List[CandidateMetadata]

    def to_dataframe(self) -> pd.DataFrame:
        if not self.all_candidates:
            return pd.DataFrame()
        records = []
        for c in self.all_candidates:
            d = c.__dict__.copy()
            d["regime"] = self.regime.value
            d["session_date"] = self.session_date.isoformat()
            records.append(d)
        return pd.DataFrame(records)

    def save_parquet(self, path: Path):
        df = self.to_dataframe()
        path.parent.mkdir(parents=True, exist_ok=True)
        if not df.empty:
            df.to_parquet(path, index=False)
        else:
            pd.DataFrame([{"session_date": self.session_date.isoformat(), "regime": self.regime.value}]).to_parquet(path, index=False)

    def save_json(self, path: Path):
        path.parent.mkdir(parents=True, exist_ok=True)
        df = self.to_dataframe()
        records = df.to_dict(orient="records") if not df.empty else []
        summary = {
            "session_date": self.session_date.isoformat(),
            "regime": self.regime.value,
            "daily_budget_r": self.daily_budget_r,
            "total_allocated_r": self.total_allocated_r,
            "approved_count": len(self.approved_candidates),
            "rejected_count": len(self.rejected_candidates),
            "candidates": records,
        }
        with open(path, "w", encoding="utf-8") as fh:
            json.dump(summary, fh, indent=2)


class DailyPrepPipeline:
    """
    Executes the deterministic 08:00 AM - 09:15 AM ET pre-market preparation pipeline.
    """

    def __init__(
        self,
        data_root: Path = Path("data/stage1d"),
        config: Optional[StrategyConfig] = None,
        security_master: Optional[InMemorySecurityMaster] = None,
        daily_provider: Optional[InMemoryDailyBarProvider] = None,
        sector_provider: Optional[PointInTimeSectorProvider] = None,
        breadth_provider: Optional[InMemoryMarketBreadthProvider] = None,
        catalyst_engine: Optional[PointInTimeCatalystEngine] = None,
    ):
        self.data_root = Path(data_root)
        self.config = config or StrategyConfig()
        self.calendar = USMarketCalendar()

        if security_master and daily_provider and sector_provider and breadth_provider:
            self.security_master = security_master
            self.daily_provider = daily_provider
            self.sector_provider = sector_provider
            self.breadth_provider = breadth_provider
            self.regime_provider = PointInTimeMarketRegimeProvider(self.breadth_provider)
            self.catalyst_engine = catalyst_engine or PointInTimeCatalystEngine()
        else:
            self._load_from_storage()

        self.screener = UniverseScreener(
            config=self.config,
            security_master=self.security_master,
            daily_provider=self.daily_provider,
        )

        self.waterfall = PortfolioAllocationWaterfall(
            risk_fraction=0.005,
            daily_green_r=3.0,
            daily_yellow_r=1.0,
            max_sector_r=2.0,
            max_heat_r=6.0,
            adv_participation_cap=self.config.adv_participation_cap,
            min_allocation_ratio=self.config.min_allocation_ratio,
        )

    def _load_from_storage(self):
        storage = LocalDataStorage(data_root=self.data_root)
        securities = storage.load_securities()
        history = storage.load_security_history()
        self.security_master = InMemorySecurityMaster(securities=securities, history=history)

        daily_parquet = self.data_root / "processed" / "daily" / "daily_bars.parquet"
        bars = storage.read_daily_parquet(daily_parquet) if daily_parquet.exists() else []
        self.daily_provider = InMemoryDailyBarProvider(bars)

        sec_csv = self.data_root / "raw" / "sectors" / "us_equities_sectors.csv"
        sec_records = []
        if sec_csv.exists():
            df_sec = pd.read_csv(sec_csv)
            for _, r in df_sec.iterrows():
                sec_records.append(
                    HistoricalSectorRecord(
                        security_id=r["security_id"],
                        sector=r["sector"],
                        industry_group=r["industry"],
                        effective_from=date(2018, 1, 1),
                        effective_to=None,
                    )
                )
        self.sector_provider = PointInTimeSectorProvider(sec_records)

        breadth_csv = self.data_root / "raw" / "breadth" / "market_breadth_2018_2023.csv"
        b_records = []
        if breadth_csv.exists():
            df_b = pd.read_csv(breadth_csv)
            for _, r in df_b.iterrows():
                b_records.append(
                    MarketBreadthRecord(
                        session_date=date.fromisoformat(r["session_date"]),
                        universe_size=int(r["universe_size"]),
                        gainers_4pct_count=int(r["gainers_4pct_count"]),
                        losers_4pct_count=int(r["losers_4pct_count"]),
                        t2108_percent=float(r["t2108_percent"]),
                        regime_state=r["regime_state"],
                    )
                )
        b_dict = {r.session_date: r for r in b_records}
        self.breadth_provider = InMemoryMarketBreadthProvider(b_dict)
        self.regime_provider = PointInTimeMarketRegimeProvider(self.breadth_provider)

        # Catalyst providers
        earn_file = self.data_root / "processed" / "earnings_events.json"
        earn_prov = None
        if earn_file.exists():
            with open(earn_file, "r", encoding="utf-8") as fh:
                data = json.load(fh)
                events = [
                    EarningsEvent(
                        security_id=item["security_id"],
                        event_timestamp=datetime.fromisoformat(item["availability_timestamp"]),
                        event_date=date.fromisoformat(item["event_date"]),
                        timing=item["timing"],
                        source=item["source"],
                        availability_timestamp=datetime.fromisoformat(item["availability_timestamp"]),
                    )
                    for item in data
                ]
                earn_prov = InMemoryEarningsProvider(events)

        sec_f_file = self.data_root / "processed" / "sec_8k_filings.json"
        sec_f_prov = None
        if sec_f_file.exists():
            with open(sec_f_file, "r", encoding="utf-8") as fh:
                data = json.load(fh)
                filings = [
                    SECFilingEvent(
                        security_id=item["security_id"],
                        cik=item["cik"],
                        accession_number=item["accession_number"],
                        filing_type="8-K",
                        filing_timestamp=datetime.fromisoformat(item["acceptance_datetime"]),
                        acceptance_datetime=datetime.fromisoformat(item["acceptance_datetime"]),
                        form=item["form"],
                        items=item["items"].split(";") if isinstance(item["items"], str) else item["items"],
                        source_url=item["source_url"],
                        availability_timestamp=datetime.fromisoformat(item["availability_timestamp"]),
                    )
                    for item in data
                ]
                sec_f_prov = InMemoryFilingProvider(filings)

        self.catalyst_engine = PointInTimeCatalystEngine(
            earnings_provider=earn_prov,
            filing_provider=sec_f_prov,
        )
        storage.close()

    def run_prep(
        self,
        session_date: date,
        portfolio_equity: float = 100_000.0,
        open_positions: Optional[List[Position]] = None,
        risk_governor: Optional[CompositeRiskGovernor] = None,
    ) -> DailyFocusList:
        """
        Executes pre-market screening, candidate generation, and waterfall allocation.
        """
        open_positions = open_positions or []
        governor = risk_governor or CompositeRiskGovernor()

        # 1. Market Regime determination
        regime = self.regime_provider.get_regime(session_date)

        # 2. Daily risk budget
        daily_budget = 3.0 if regime == MarketRegime.GREEN else (1.0 if regime == MarketRegime.YELLOW else 0.0)

        # 3. Active universe screening as of t-1 close
        active_securities = self.security_master.get_all_active_securities(session_date)
        session_candidates: List[CandidateMetadata] = []

        for sec in active_securities:
            prior_bars = self.daily_provider.get_prior_completed_bars(sec.security_id, session_date, 1)
            if not prior_bars:
                continue

            prior_close = prior_bars[-1].close
            adv50 = calculate_adv50(sec.security_id, session_date, self.daily_provider) or 0.0
            dollar_adv = prior_close * adv50
            h65 = calculate_65d_high(sec.security_id, session_date, self.daily_provider)
            sec_info = self.sector_provider.get_sector(sec.security_id, datetime.combine(session_date, time(9, 30))) or "GENERAL"

            # Apply frozen screener filters
            if prior_close < self.config.price_floor:
                continue
            if adv50 < self.config.adv50_min:
                continue
            if dollar_adv < self.config.dollar_adv_min:
                continue

            # Candidate Generation
            has_track_a, _ = self.catalyst_engine.is_track_a_qualified(sec.ticker, session_date)
            has_track_b, _ = self.catalyst_engine.is_track_b_qualified(sec.ticker, session_date)

            if has_track_a or has_track_b:
                cat_track = "TRACK_A_EARNINGS" if has_track_a else "TRACK_B_PR"
                module_name = "TRACK_A" if has_track_a else "TRACK_B"
                est_trigger = round(prior_close * 1.02 + 0.01, 2)
                est_stop = round(prior_close * 0.99 - 0.01, 2)
                geom = (est_trigger - est_stop) / est_trigger

                geom_rej = None
                if geom > self.config.max_risk_geometry_pct:
                    geom_rej = f"ORB_GEOMETRY_FAIL ({geom*100:.2f}% > {self.config.max_risk_geometry_pct*100:.1f}%)"

                cand = CandidateMetadata(
                    candidate_id=f"CAND_{sec.ticker}_{session_date.strftime('%Y%m%d')}_CAT",
                    security_id=sec.security_id,
                    session_date=session_date,
                    engine="CATALYST",
                    module=module_name,
                    catalyst_track=cat_track,
                    trigger_price=est_trigger,
                    structural_stop=est_stop,
                    planned_risk_pct=geom,
                    risk_geometry=geom,
                    adv50=adv50,
                    liquidity_cap=adv50 * self.config.adv_participation_cap,
                    planned_shares=0,
                    allocated_shares=0,
                    fractional_r=0.0,
                    rejection_reason=geom_rej,
                    sector=sec_info,
                    ticker=sec.ticker,
                )
                session_candidates.append(cand)

            elif h65 is not None:
                adj_prior_close = prior_bars[-1].adjusted_close
                if adj_prior_close >= (h65 * 0.96):
                    raw_factor = prior_bars[-1].close / max(0.01, prior_bars[-1].adjusted_close)
                    raw_h65 = h65 * raw_factor
                    trigger_p = round(raw_h65 + self.config.tick_size, 2)
                    stop_p = round(raw_h65 * 0.97 - self.config.tick_size, 2)
                    geom = (trigger_p - stop_p) / trigger_p

                    geom_rej = None
                    if geom > self.config.max_risk_geometry_pct:
                        geom_rej = f"RISK_GEOMETRY_EXCEEDED ({geom*100:.2f}% > {self.config.max_risk_geometry_pct*100:.1f}%)"

                    cand = CandidateMetadata(
                        candidate_id=f"CAND_{sec.ticker}_{session_date.strftime('%Y%m%d')}_BH",
                        security_id=sec.security_id,
                        session_date=session_date,
                        engine="BASE_HIT",
                        module="BREAKOUT_65D",
                        catalyst_track="NONE",
                        trigger_price=trigger_p,
                        structural_stop=stop_p,
                        planned_risk_pct=geom,
                        risk_geometry=geom,
                        adv50=adv50,
                        liquidity_cap=adv50 * self.config.adv_participation_cap,
                        planned_shares=0,
                        allocated_shares=0,
                        fractional_r=0.0,
                        rejection_reason=geom_rej,
                        sector=sec_info,
                        ticker=sec.ticker,
                    )
                    session_candidates.append(cand)

        # 4. Allocation Waterfall
        valid_candidates = [c for c in session_candidates if c.rejection_reason is None]
        rejected_early = [c for c in session_candidates if c.rejection_reason is not None]

        approved, rejected_by_waterfall = self.waterfall.allocate_candidates(
            candidates=valid_candidates,
            regime=regime,
            portfolio_equity=portfolio_equity,
            open_positions=open_positions,
            risk_governor=governor,
            catalyst_seniority=True,
        )

        all_rejected = rejected_early + rejected_by_waterfall
        total_allocated_r = sum(c.fractional_r for c in approved)

        return DailyFocusList(
            session_date=session_date,
            regime=regime,
            daily_budget_r=daily_budget,
            total_allocated_r=round(total_allocated_r, 3),
            approved_candidates=approved,
            rejected_candidates=all_rejected,
            all_candidates=session_candidates,
        )
