"""
Multi-Year Historical Backtest Runner (Phases 2, 3, 4, 5, 6, 7, 8)
Executes point-in-time, multi-year backtest with candidate tracking,
portfolio waterfall, targeted intraday extraction, cost models, and telemetry.
"""

import json
from dataclasses import dataclass
from datetime import date, datetime, time, timedelta, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional, Set, Tuple
import pandas as pd

from ..config.strategy_config import StrategyConfig
from ..data.breadth import InMemoryMarketBreadthProvider, MarketBreadthRecord, PointInTimeMarketRegimeProvider
from ..data.catalysts import EarningsEvent, InMemoryEarningsProvider, InMemoryFilingProvider, SECFilingEvent
from ..data.dual_price import DailyBar, InMemoryDailyBarProvider
from ..data.indicators import PointInTimeIndicatorEngine, calculate_10ema, calculate_65d_high, calculate_adv50
from ..data.intraday import InMemoryIntradayBarProvider, IntradayBarRecord
from ..data.models import Bar, NY_TZ
from ..data.screener import UniverseScreener
from ..data.sectors import HistoricalSectorRecord, PointInTimeSectorProvider
from ..data.security_master import InMemorySecurityMaster, Security, SecurityHistoryRecord
from ..data.storage import LocalDataStorage
from ..engine.backtest import Stage0BacktestEngine
from ..execution.orders import Order, OrderSide, OrderStatus, OrderType
from ..portfolio.portfolio import Portfolio, Position, PositionStatus
from ..regime.market_regime import MarketRegime
from ..risk.governors import CompositeRiskGovernor, HeatGovernor, InternalLossGovernor, RegimeGovernor, SectorGovernor, SingleTickerGovernor
from ..risk.sizing import calculate_position_size
from ..telemetry.trade_log import TradeJournal, TradeRecord
from .costs import BaseCostScenario, ConservativeActiveTraderCostModel, StressCostModel, ZeroCostModel
from .waterfall import CandidateMetadata, PortfolioAllocationWaterfall


@dataclass
class DailyUniverseSnapshot:
    """Phase 2 snapshot record."""
    session_date: str
    security_id: str
    ticker_as_of_date: str
    price: float
    adv50: float
    dollar_adv50: float
    high_65: Optional[float]
    ema_10: Optional[float]
    shares_float: Optional[float]
    market_cap: Optional[float]
    sector: str
    eligibility: bool
    rejection_reason: Optional[str]


@dataclass
class DailyPortfolioState:
    session_date: str
    total_equity: float
    cash: float
    cash_pct: float
    uncushioned_risk_dollars: float
    heat_r: float
    open_positions_count: int
    daily_allocated_r: float
    regime: str
    daily_turnover: float


class PointInTimeCatalystEngine:
    """Evaluates Track A and Track B point-in-time catalyst qualification."""
    def __init__(
        self,
        earnings_provider: Optional[InMemoryEarningsProvider] = None,
        filing_provider: Optional[InMemoryFilingProvider] = None,
    ):
        self.earnings_provider = earnings_provider
        self.filing_provider = filing_provider

    def is_track_a_qualified(self, symbol: str, session_date: date) -> Tuple[bool, Optional[EarningsEvent]]:
        if not self.earnings_provider:
            return False, None
        sec_id = f"SEC_{symbol}" if not symbol.startswith("SEC_") else symbol
        ev = self.earnings_provider.get_earnings_event(sec_id, session_date)
        return (ev is not None), ev

    def is_track_b_qualified(self, symbol: str, session_date: date) -> Tuple[bool, Optional[SECFilingEvent]]:
        if not self.filing_provider:
            return False, None
        sec_id = f"SEC_{symbol}" if not symbol.startswith("SEC_") else symbol
        cutoff = datetime.combine(session_date, time(9, 29, 59), tzinfo=NY_TZ)
        filings = self.filing_provider.get_filings_before(sec_id, cutoff)
        recent = [f for f in filings if f.availability_timestamp >= cutoff - timedelta(hours=24)]
        return (len(recent) > 0), (recent[-1] if recent else None)


class MultiYearBacktestRunner:
    """
    Coordinates multi-year simulation across datasets, applying exact rules from Stage 0 to Stage 1D.
    """

    def __init__(
        self,
        data_root: Path = Path("data/stage1d"),
        config: Optional[StrategyConfig] = None,
        cost_scenario: Optional[BaseCostScenario] = None,
        initial_equity: float = 100_000.0,
        catalyst_seniority: bool = True,
        enforce_market_monitor: bool = True,
        enforce_eod_governor: bool = True,
        enforce_derisking: bool = True,
        enforce_geometry_gate: bool = True,
        enforce_10ema_runner: bool = True,
        enforce_sector_cap: bool = True,
        enforce_internal_governor: bool = True,
        enforce_liquidity_cap: bool = True,
        enforce_collar: bool = True,
    ):
        self.data_root = Path(data_root)
        self.config = config or StrategyConfig()
        self.cost_scenario = cost_scenario or ZeroCostModel()
        self.initial_equity = initial_equity

        # Architectural ablation toggles
        self.catalyst_seniority = catalyst_seniority
        self.enforce_market_monitor = enforce_market_monitor
        self.enforce_eod_governor = enforce_eod_governor
        self.enforce_derisking = enforce_derisking
        self.enforce_geometry_gate = enforce_geometry_gate
        self.enforce_10ema_runner = enforce_10ema_runner
        self.enforce_sector_cap = enforce_sector_cap
        self.enforce_internal_governor = enforce_internal_governor
        self.enforce_liquidity_cap = enforce_liquidity_cap
        self.enforce_collar = enforce_collar

        self._load_data()
        self._init_engine()

        self.universe_snapshots: List[DailyUniverseSnapshot] = []
        self.all_candidates: List[CandidateMetadata] = []
        self.daily_states: List[DailyPortfolioState] = []

    def _load_data(self):
        """Loads data from data_root into memory providers."""
        storage = LocalDataStorage(data_root=self.data_root)

        # 1. Security master
        securities = storage.load_securities()
        history = storage.load_security_history()
        self.security_master = InMemorySecurityMaster(securities=securities, history=history)

        # 2. Daily bars
        daily_parquet = self.data_root / "processed" / "daily" / "daily_bars.parquet"
        bars = storage.read_daily_parquet(daily_parquet) if daily_parquet.exists() else []
        self.daily_provider = InMemoryDailyBarProvider(bars)
        self.indicator_engine = PointInTimeIndicatorEngine(self.daily_provider, self.security_master)

        # 3. Intraday bars
        intra_parquet = self.data_root / "processed" / "intraday" / "intraday_bars.parquet"
        intra_records = storage.read_intraday_parquet(intra_parquet) if intra_parquet.exists() else []
        self.intraday_provider = InMemoryIntradayBarProvider(intra_records)

        # 4. Sectors
        sec_csv = self.data_root / "raw" / "sectors" / "us_equities_sectors.csv"
        sector_records = []
        if sec_csv.exists():
            df_sec = pd.read_csv(sec_csv)
            for _, r in df_sec.iterrows():
                sector_records.append(
                    HistoricalSectorRecord(
                        security_id=r["security_id"],
                        sector=r["sector"],
                        industry_group=r["industry"],
                        effective_from=date(2018, 1, 1),
                        effective_to=None,
                    )
                )
        self.sector_provider = PointInTimeSectorProvider(sector_records)

        # 5. Breadth
        breadth_csv = self.data_root / "raw" / "breadth" / "market_breadth_2018_2023.csv"
        breadth_records = []
        if breadth_csv.exists():
            df_b = pd.read_csv(breadth_csv)
            for _, r in df_b.iterrows():
                breadth_records.append(
                    MarketBreadthRecord(
                        session_date=date.fromisoformat(r["session_date"]),
                        universe_size=int(r["universe_size"]),
                        gainers_4pct_count=int(r["gainers_4pct_count"]),
                        losers_4pct_count=int(r["losers_4pct_count"]),
                        t2108_percent=float(r["t2108_percent"]),
                        regime_state=r["regime_state"],
                    )
                )
        breadth_dict = {r.session_date: r for r in breadth_records}
        self.breadth_provider = InMemoryMarketBreadthProvider(breadth_dict)
        self.regime_provider = PointInTimeMarketRegimeProvider(self.breadth_provider)

        # 6. Catalysts
        earn_file = self.data_root / "processed" / "earnings_events.json"
        earn_prov = None
        if earn_file.exists():
            with open(earn_file, "r", encoding="utf-8") as fh:
                data = json.load(fh)
                events = []
                for item in data:
                    events.append(
                        EarningsEvent(
                            security_id=item["security_id"],
                            event_timestamp=datetime.fromisoformat(item["availability_timestamp"]),
                            event_date=date.fromisoformat(item["event_date"]),
                            timing=item["timing"],
                            source=item["source"],
                            availability_timestamp=datetime.fromisoformat(item["availability_timestamp"]),
                        )
                    )
                earn_prov = InMemoryEarningsProvider(events)

        sec_f_file = self.data_root / "processed" / "sec_8k_filings.json"
        sec_f_prov = None
        if sec_f_file.exists():
            with open(sec_f_file, "r", encoding="utf-8") as fh:
                data = json.load(fh)
                filings = []
                for item in data:
                    filings.append(
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
                    )
                sec_f_prov = InMemoryFilingProvider(filings)

        self.catalyst_engine = PointInTimeCatalystEngine(
            earnings_provider=earn_prov,
            filing_provider=sec_f_prov,
        )

        storage.close()

    def _init_engine(self):
        """Initializes portfolio, risk governors, and trade journal."""
        self.portfolio = Portfolio(initial_equity=self.initial_equity)
        self.journal = TradeJournal()

        # Build risk governors
        govs = []
        if self.enforce_market_monitor:
            govs.append(RegimeGovernor())
        if self.enforce_internal_governor:
            govs.append(InternalLossGovernor(max_consecutive_losses=3))
        govs.append(SingleTickerGovernor())
        govs.append(HeatGovernor(max_heat_r=6.0))
        if self.enforce_sector_cap:
            govs.append(SectorGovernor(max_sector_r=2.0))

        self.risk_governor = CompositeRiskGovernor(govs)
        self.waterfall = PortfolioAllocationWaterfall(
            risk_fraction=0.005,
            daily_green_r=3.0,
            daily_yellow_r=1.0,
            max_sector_r=2.0 if self.enforce_sector_cap else 999.0,
            max_heat_r=6.0,
            adv_participation_cap=self.config.adv_participation_cap if self.enforce_liquidity_cap else 1.0,
            min_allocation_ratio=self.config.min_allocation_ratio,
        )

    def run_backtest(
        self,
        start_date: Optional[date] = None,
        end_date: Optional[date] = None,
    ) -> TradeJournal:
        """
        Runs the multi-year event-driven backtest over the specified date window.
        """
        all_dates = sorted(list(self.breadth_provider._records.keys()))
        if start_date:
            all_dates = [d for d in all_dates if d >= start_date]
        if end_date:
            all_dates = [d for d in all_dates if d <= end_date]

        for session_date in all_dates:
            self._process_session(session_date)

        return self.journal

    def _process_session(self, session_date: date):
        """Processes a single trading session chronologically."""
        if hasattr(self.risk_governor, "on_new_session"):
            self.risk_governor.on_new_session(session_date)

        # 1. Determine point-in-time Market Regime
        if self.enforce_market_monitor:
            regime = self.regime_provider.get_regime(session_date)
            risk_fraction = self.regime_provider.get_risk_fraction(session_date)
        else:
            regime = MarketRegime.GREEN
            risk_fraction = 0.005

        # 2. Phase 2: Universe Snapshot & Screening as of t-1 close
        active_securities = self.security_master.get_all_active_securities(session_date)
        session_candidates: List[CandidateMetadata] = []

        for sec in active_securities:
            prior_bars = self.daily_provider.get_prior_completed_bars(sec.security_id, session_date, 1)
            if not prior_bars:
                self.universe_snapshots.append(
                    DailyUniverseSnapshot(
                        session_date=session_date.isoformat(),
                        security_id=sec.security_id,
                        ticker_as_of_date=sec.ticker,
                        price=0.0, adv50=0.0, dollar_adv50=0.0,
                        high_65=None, ema_10=None, shares_float=None, market_cap=None,
                        sector="GENERAL", eligibility=False, rejection_reason="MISSING_PRIOR_DATA",
                    )
                )
                continue

            prior_close = prior_bars[-1].close
            adv50 = calculate_adv50(sec.security_id, session_date, self.daily_provider) or 0.0
            dollar_adv = prior_close * adv50
            h65 = calculate_65d_high(sec.security_id, session_date, self.daily_provider)
            ema10 = calculate_10ema(sec.security_id, session_date, self.daily_provider)
            sec_info = self.sector_provider.get_sector(sec.security_id, datetime.combine(session_date, time(9, 30))) or "GENERAL"

            # Filter evaluation
            is_eligible = True
            rejection_reason = None

            if prior_close < self.config.price_floor:
                is_eligible = False
                rejection_reason = f"PRICE_FLOOR_FAIL (${prior_close:.2f} < ${self.config.price_floor:.2f})"
            elif adv50 < self.config.adv50_min:
                is_eligible = False
                rejection_reason = f"ADV50_FAIL ({adv50:,.0f} < {self.config.adv50_min:,.0f})"
            elif dollar_adv < self.config.dollar_adv_min:
                is_eligible = False
                rejection_reason = f"DOLLAR_ADV_FAIL (${dollar_adv:,.0f} < ${self.config.dollar_adv_min:,.0f})"

            self.universe_snapshots.append(
                DailyUniverseSnapshot(
                    session_date=session_date.isoformat(),
                    security_id=sec.security_id,
                    ticker_as_of_date=sec.ticker,
                    price=prior_close,
                    adv50=adv50,
                    dollar_adv50=dollar_adv,
                    high_65=h65,
                    ema_10=ema10,
                    shares_float=None,
                    market_cap=None,
                    sector=sec_info,
                    eligibility=is_eligible,
                    rejection_reason=rejection_reason,
                )
            )

            if not is_eligible:
                continue

            # 3. Phase 3: Candidate Generation (Catalyst and Base-Hit)
            # A. Catalyst Engine Check
            has_track_a, track_a_ev = self.catalyst_engine.is_track_a_qualified(sec.ticker, session_date)
            has_track_b, track_b_ev = self.catalyst_engine.is_track_b_qualified(sec.ticker, session_date)

            if has_track_a or has_track_b:
                cat_track = "TRACK_A_EARNINGS" if has_track_a else "TRACK_B_PR"
                module_name = "TRACK_A" if has_track_a else "TRACK_B"

                # Trigger based on opening range geometry (evaluated at 09:35)
                # Estimate pre-market trigger/stop geometry
                est_trigger = round(prior_close * 1.02 + 0.01, 2)
                est_stop = round(prior_close * 0.99 - 0.01, 2)
                geom = (est_trigger - est_stop) / est_trigger

                # Universal Risk-Geometry Filter check
                geom_rejected = None
                if self.enforce_geometry_gate and geom > self.config.max_risk_geometry_pct:
                    geom_rejected = f"ORB_GEOMETRY_FAIL ({geom*100:.2f}% > {self.config.max_risk_geometry_pct*100:.1f}%)"

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
                    rejection_reason=geom_rejected,
                    sector=sec_info,
                    ticker=sec.ticker,
                )
                session_candidates.append(cand)
                self.all_candidates.append(cand)

            # B. Base-Hit Engine Check (65D Breakout within proximity)
            elif h65 is not None:
                adj_prior_close = prior_bars[-1].adjusted_close
                if adj_prior_close >= (h65 * 0.96):
                    raw_factor = prior_bars[-1].close / max(0.01, prior_bars[-1].adjusted_close)
                    raw_h65 = h65 * raw_factor
                    trigger_p = round(raw_h65 + self.config.tick_size, 2)
                    stop_p = round(raw_h65 * 0.97 - self.config.tick_size, 2)
                    geom = (trigger_p - stop_p) / trigger_p

                    geom_rejected = None
                    if self.enforce_geometry_gate and geom > self.config.max_risk_geometry_pct:
                        geom_rejected = f"RISK_GEOMETRY_EXCEEDED ({geom*100:.2f}% > {self.config.max_risk_geometry_pct*100:.1f}%)"

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
                        rejection_reason=geom_rejected,
                        sector=sec_info,
                        ticker=sec.ticker,
                    )
                    session_candidates.append(cand)
                    self.all_candidates.append(cand)

        # 4. Phase 7: Portfolio Allocation Waterfall
        valid_candidates = [c for c in session_candidates if c.rejection_reason is None]
        rejected_early = [c for c in session_candidates if c.rejection_reason is not None]

        approved_candidates, rejected_by_waterfall = self.waterfall.allocate_candidates(
            candidates=valid_candidates,
            regime=regime,
            portfolio_equity=self.portfolio.total_equity,
            open_positions=list(self.portfolio.open_positions.values()),
            risk_governor=self.risk_governor,
            catalyst_seniority=self.catalyst_seniority,
        )

        for rej in rejected_early + rejected_by_waterfall:
            self.journal.record_rejection(
                timestamp=datetime.combine(session_date, time(9, 30)),
                symbol=rej.ticker or rej.security_id,
                setup_type=rej.module,
                regime=regime.value,
                rejection_reason=rej.rejection_reason or "WATERFALL_REJECTION",
            )

        # 5. Phase 4 & 5: Intraday Bars Extraction & Order Execution
        # Extract 1-minute bars for approved candidates + open positions
        symbols_to_execute = set(c.ticker for c in approved_candidates if c.ticker)
        for pos_sym in self.portfolio.open_positions.keys():
            symbols_to_execute.add(pos_sym)

        # Days held increment for overnight open positions
        for pos in self.portfolio.open_positions.values():
            pos.days_held += 1

        # Check if intraday bars are available in the provider
        session_intraday_bars: List[Bar] = []
        for sym in symbols_to_execute:
            sec_id = self.security_master.resolve_security_id(sym, session_date)
            if sec_id:
                bars = self.intraday_provider.get_intraday_bars(sec_id, session_date)
                session_intraday_bars.extend(bars)

        # Sort bars chronologically
        session_intraday_bars.sort(key=lambda b: b.timestamp)

        # Execute intraday event simulation
        if session_intraday_bars:
            self._simulate_intraday_session(
                session_date=session_date,
                intraday_bars=session_intraday_bars,
                approved_candidates=approved_candidates,
                regime=regime,
            )
        else:
            # Daily bar fallback if intraday bar not targeted/available
            self._simulate_daily_bar_session(
                session_date=session_date,
                approved_candidates=approved_candidates,
                regime=regime,
            )

        # 6. Record Daily Portfolio State
        eq = self.portfolio.total_equity
        cash = self.portfolio.cash
        cash_pct = (cash / eq * 100.0) if eq > 0 else 100.0
        heat_dollars = self.portfolio.total_uncushioned_risk_dollars
        unit_1r = eq * risk_fraction
        heat_r = (heat_dollars / unit_1r) if unit_1r > 0 else 0.0

        daily_allocated_r = sum(c.fractional_r for c in approved_candidates)
        self.daily_states.append(
            DailyPortfolioState(
                session_date=session_date.isoformat(),
                total_equity=round(eq, 2),
                cash=round(cash, 2),
                cash_pct=round(cash_pct, 2),
                uncushioned_risk_dollars=round(heat_dollars, 2),
                heat_r=round(heat_r, 2),
                open_positions_count=len(self.portfolio.open_positions),
                daily_allocated_r=round(daily_allocated_r, 2),
                regime=regime.value,
                daily_turnover=round(daily_allocated_r * unit_1r, 2),
            )
        )

    def _simulate_intraday_session(
        self,
        session_date: date,
        intraday_bars: List[Bar],
        approved_candidates: List[CandidateMetadata],
        regime: MarketRegime,
    ):
        """Simulates 1-minute execution with exact Stage 0.2 invariants and cost model."""
        pending_orders: Dict[str, Order] = {}

        # Stage BUY_STOP_LIMIT orders for approved candidates
        for c in approved_candidates:
            sym = c.ticker or c.security_id
            # Compute actual opening range from 09:30-09:34 bars if available
            sym_opening = [b for b in intraday_bars if b.symbol == sym and b.timestamp.time() < time(9, 35)]
            if sym_opening and c.engine == "CATALYST":
                actual_orh = max(b.high for b in sym_opening)
                actual_orl = min(b.low for b in sym_opening)
                c.trigger_price = round(actual_orh + self.config.tick_size, 2)
                c.structural_stop = round(actual_orl - self.config.tick_size, 2)

            collar_limit = (c.trigger_price + self.config.default_collar_cents) if self.enforce_collar else (c.trigger_price + 99.0)
            order = Order(
                symbol=sym,
                side=OrderSide.BUY,
                order_type=OrderType.BUY_STOP_LIMIT if self.enforce_collar else OrderType.BUY_STOP,
                quantity=c.allocated_shares,
                trigger_price=c.trigger_price,
                limit_price=collar_limit,
                stop_loss_price=c.structural_stop,
                created_at=datetime.combine(session_date, time(9, 35)),
                tag=c.module,
            )
            pending_orders[sym] = order

        # Group bars by symbol for chronological processing
        for bar in intraday_bars:
            sym = bar.symbol
            bar_time = bar.timestamp.time()

            # 1. Evaluate open position exits on this bar
            pos = self.portfolio.get_position(sym)
            if pos and pos.status == PositionStatus.OPEN:
                pos.update_price(bar.close)

                # Check Stop & Target exits with STOP-FIRST rule (D2)
                stop_hit = bar.low <= pos.current_stop
                target_hit = (
                    self.enforce_derisking
                    and pos.partial_target_price is not None
                    and not pos.has_partial_filled
                    and bar.high >= pos.partial_target_price
                )

                if stop_hit and target_hit:
                    # RULE D2: STOP FIRST
                    exit_raw_p = min(pos.current_stop, bar.open)
                    self._execute_position_close(pos, bar, exit_raw_p, "SAME_BAR_STOP_FIRST", is_stop=True)
                    continue
                elif stop_hit:
                    exit_raw_p = min(pos.current_stop, bar.open)
                    is_entry_bar = (pos.entry_timestamp == bar.timestamp)
                    reason = "ENTRY_BAR_STOP_BREACH" if is_entry_bar else "STRUCTURAL_STOP"
                    self._execute_position_close(pos, bar, exit_raw_p, reason, is_stop=True)
                    continue
                elif target_hit:
                    # +2R Partial Exit
                    target_p = max(pos.partial_target_price, bar.open)
                    eff_exit_p, comm = self.cost_scenario.calculate_exit_cost(pos.quantity // 2, target_p, is_stop=False)
                    pos.execute_partial_exit(eff_exit_p, bar.timestamp, ratio=self.config.partial_exit_ratio)
                    continue

                # 2. Check 03:55 PM EOD audit
                if self.enforce_eod_governor and bar_time >= time(15, 55):
                    # T1 liquidation if uncushioned and close <= entry
                    if pos.days_held == 0 and not pos.is_cushioned and bar.close <= pos.entry_price:
                        self._execute_position_close(pos, bar, bar.close, "EOD_AUDIT_T1_CLOSE_BELOW_ENTRY", is_stop=False)
                        continue
                    # T2 stall liquidation
                    elif pos.days_held == 1 and not pos.is_cushioned and bar.close <= pos.entry_price:
                        self._execute_position_close(pos, bar, bar.close, "EOD_AUDIT_T2_STALL_CLOSE_BELOW_ENTRY", is_stop=False)
                        continue
                    # Cushioned runner 10 EMA check
                    elif self.enforce_10ema_runner and pos.is_cushioned:
                        ema10 = self.indicator_engine.get_ema(sym, session_date, period=10)
                        if ema10 and bar.close < ema10:
                            self._execute_position_close(pos, bar, bar.close, "RUNNER_CLOSE_BELOW_10_EMA", is_stop=False)
                            continue

            # 2. Evaluate pending entry orders
            if sym in pending_orders and bar_time >= time(9, 35):
                order = pending_orders[sym]
                if order.status == OrderStatus.PENDING:
                    # Purge stale orders at 10:15
                    if bar_time >= time(10, 15):
                        order.cancel("STALE_ORDER_PURGE")
                        self.journal.record_rejection(
                            timestamp=bar.timestamp,
                            symbol=sym,
                            setup_type=order.tag,
                            regime=regime.value,
                            rejection_reason="STALE_ORDER_PURGE_1015",
                        )
                        del pending_orders[sym]
                        continue

                    # Stop-Limit collar check
                    if bar.high >= order.trigger_price:
                        limit_p = order.limit_price or (order.trigger_price + 0.10)
                        if self.enforce_collar and bar.open > limit_p:
                            order.cancel("COLLAR_MISS")
                            self.journal.record_rejection(
                                timestamp=bar.timestamp,
                                symbol=sym,
                                setup_type=order.tag,
                                regime=regime.value,
                                rejection_reason="COLLAR_MISS",
                            )
                            del pending_orders[sym]
                            continue

                        fill_raw = max(order.trigger_price, bar.open)
                        if self.enforce_collar and fill_raw > limit_p:
                            order.cancel("COLLAR_MISS")
                            self.journal.record_rejection(
                                timestamp=bar.timestamp,
                                symbol=sym,
                                setup_type=order.tag,
                                regime=regime.value,
                                rejection_reason="COLLAR_MISS",
                            )
                            del pending_orders[sym]
                            continue

                        # Apply cost model to entry
                        eff_fill, comm = self.cost_scenario.calculate_entry_cost(order.quantity, fill_raw)
                        order.fill(bar.timestamp, eff_fill)

                        cand_meta = next((c for c in approved_candidates if (c.ticker or c.security_id) == sym), None)
                        stop_p = order.stop_loss_price or (eff_fill * 0.96)
                        sec_info = cand_meta.sector if cand_meta else "GENERAL"

                        pos = Position(
                            symbol=sym,
                            side="LONG",
                            entry_price=eff_fill,
                            entry_timestamp=bar.timestamp,
                            quantity=order.quantity,
                            initial_stop=stop_p,
                            current_stop=stop_p,
                            initial_risk_dollars=order.quantity * (eff_fill - stop_p),
                            engine="CATALYST" if "ORB" in order.tag or "TRACK" in order.tag else "BASE_HIT",
                            setup_type=order.tag,
                            regime_at_entry=regime,
                            sector=sec_info,
                        )
                        self.portfolio.add_position(pos)
                        del pending_orders[sym]

                        # Entry-bar stop check immediately
                        if bar.low <= pos.current_stop:
                            self._execute_position_close(pos, bar, pos.current_stop, "ENTRY_BAR_STOP_BREACH", is_stop=True)

    def _execute_position_close(self, pos: Position, bar: Bar, raw_exit_price: float, reason: str, is_stop: bool):
        """Closes position, applies cost model, and logs 27-field trade record."""
        eff_exit, comm = self.cost_scenario.calculate_exit_cost(pos.shares_remaining, raw_exit_price, is_stop=is_stop)
        self.portfolio.close_position(
            symbol=pos.symbol,
            exit_price=eff_exit,
            timestamp=bar.timestamp,
            reason=reason,
        )

        initial_risk = pos.initial_risk_dollars if pos.initial_risk_dollars > 0 else 1.0
        r_multiple = pos.realized_pnl / initial_risk

        mae = max(0.0, (pos.entry_price - bar.low) * pos.quantity)
        mfe = max(0.0, (bar.high - pos.entry_price) * pos.quantity)

        # Slippage & commission cost dollar estimate
        raw_pnl = (raw_exit_price - pos.entry_price) * pos.quantity
        total_frictions = abs(pos.realized_pnl - raw_pnl)
        comm_estimate = self.cost_scenario.calculate_commission(pos.quantity, eff_exit)

        record = self.journal.record_trade(
            symbol=pos.symbol,
            engine=pos.engine,
            setup_type=pos.setup_type,
            regime=pos.regime_at_entry.value,
            sector=pos.sector or "GENERAL",
            entry_timestamp=pos.entry_timestamp,
            entry_price=pos.entry_price,
            initial_stop_price=pos.initial_stop,
            exit_timestamp=bar.timestamp,
            exit_price=eff_exit,
            quantity=pos.quantity,
            initial_risk_dollars=initial_risk,
            realized_pnl=pos.realized_pnl,
            r_multiple=r_multiple,
            exit_reason=reason,
            mae_dollars=mae,
            mfe_dollars=mfe,
            holding_period_bars=pos.days_held * 390,
            eod_exit_flag=("EOD_AUDIT" in reason),
        )

        if hasattr(self.risk_governor, "record_closed_trade"):
            self.risk_governor.record_closed_trade(pos.realized_pnl)

    def _simulate_daily_bar_session(
        self,
        session_date: date,
        approved_candidates: List[CandidateMetadata],
        regime: MarketRegime,
    ):
        """Processes positions and candidate entries when full intraday bars are not available."""
        # Check active positions against completed daily bar
        for sym in list(self.portfolio.open_positions.keys()):
            pos = self.portfolio.get_position(sym)
            if not pos:
                continue

            sec_id = self.security_master.resolve_security_id(sym, session_date)
            daily_bars = self.daily_provider.get_prior_completed_bars(sec_id, session_date + timedelta(days=1), 1)
            if not daily_bars:
                continue

            d_bar = daily_bars[-1]
            pos.update_price(d_bar.close)

            # Check stop hit
            if d_bar.low <= pos.current_stop:
                exit_p = min(pos.current_stop, d_bar.open)
                synthetic_bar = Bar(
                    timestamp=datetime.combine(session_date, time(10, 0)),
                    symbol=sym,
                    open=d_bar.open, high=d_bar.high, low=d_bar.low, close=d_bar.close, volume=d_bar.volume,
                )
                self._execute_position_close(pos, synthetic_bar, exit_p, "STRUCTURAL_STOP", is_stop=True)
                continue

            # Check partial target
            if self.enforce_derisking and pos.partial_target_price and not pos.has_partial_filled and d_bar.high >= pos.partial_target_price:
                eff_exit, comm = self.cost_scenario.calculate_exit_cost(pos.quantity // 2, pos.partial_target_price, is_stop=False)
                pos.execute_partial_exit(eff_exit, datetime.combine(session_date, time(11, 0)), ratio=self.config.partial_exit_ratio)

            # EOD T1/T2 check
            if self.enforce_eod_governor:
                synthetic_bar = Bar(
                    timestamp=datetime.combine(session_date, time(15, 55)),
                    symbol=sym,
                    open=d_bar.open, high=d_bar.high, low=d_bar.low, close=d_bar.close, volume=d_bar.volume,
                )
                if pos.days_held == 0 and not pos.is_cushioned and d_bar.close <= pos.entry_price:
                    self._execute_position_close(pos, synthetic_bar, d_bar.close, "EOD_AUDIT_T1_CLOSE_BELOW_ENTRY", is_stop=False)
                    continue
                elif pos.days_held == 1 and not pos.is_cushioned and d_bar.close <= pos.entry_price:
                    self._execute_position_close(pos, synthetic_bar, d_bar.close, "EOD_AUDIT_T2_STALL_CLOSE_BELOW_ENTRY", is_stop=False)
                    continue
                elif self.enforce_10ema_runner and pos.is_cushioned:
                    ema10 = self.indicator_engine.get_ema(sym, session_date, period=10)
                    if ema10 and d_bar.close < ema10:
                        self._execute_position_close(pos, synthetic_bar, d_bar.close, "RUNNER_CLOSE_BELOW_10_EMA", is_stop=False)
                        continue

        # Process entries for approved candidates on daily bars
        for c in approved_candidates:
            sym = c.ticker or c.security_id
            if sym in self.portfolio.open_positions:
                continue

            sec_id = self.security_master.resolve_security_id(sym, session_date)
            d_bars = self.daily_provider.get_prior_completed_bars(sec_id, session_date + timedelta(days=1), 1)
            if not d_bars:
                continue
            d_bar = d_bars[-1]

            if d_bar.high >= c.trigger_price:
                collar_limit = (c.trigger_price + self.config.default_collar_cents) if self.enforce_collar else (c.trigger_price + 99.0)
                if self.enforce_collar and d_bar.open > collar_limit:
                    self.journal.record_rejection(
                        timestamp=datetime.combine(session_date, time(9, 35)),
                        symbol=sym,
                        setup_type=c.module,
                        regime=regime.value,
                        rejection_reason="COLLAR_MISS",
                    )
                    continue

                raw_fill = max(c.trigger_price, d_bar.open)
                eff_fill, comm = self.cost_scenario.calculate_entry_cost(c.allocated_shares, raw_fill)
                stop_p = c.structural_stop

                pos = Position(
                    symbol=sym,
                    side="LONG",
                    entry_price=eff_fill,
                    entry_timestamp=datetime.combine(session_date, time(9, 36)),
                    quantity=c.allocated_shares,
                    initial_stop=stop_p,
                    current_stop=stop_p,
                    initial_risk_dollars=c.allocated_shares * (eff_fill - stop_p),
                    engine=c.engine,
                    setup_type=c.module,
                    regime_at_entry=regime,
                    sector=c.sector or "GENERAL",
                )
                self.portfolio.add_position(pos)

                # Check if stopped out on entry day
                if d_bar.low <= stop_p:
                    exit_p = min(stop_p, d_bar.open)
                    synthetic_bar = Bar(
                        timestamp=datetime.combine(session_date, time(14, 0)),
                        symbol=sym,
                        open=d_bar.open, high=d_bar.high, low=d_bar.low, close=d_bar.close, volume=d_bar.volume,
                    )
                    self._execute_position_close(pos, synthetic_bar, exit_p, "ENTRY_BAR_STOP_BREACH", is_stop=True)

    def get_trades_dataframe(self) -> pd.DataFrame:
        df = self.journal.to_dataframe()
        if not df.empty:
            # Attach friction columns if missing
            if "slippage_cost" not in df:
                df["slippage_cost"] = df["quantity"] * getattr(self.cost_scenario, "per_share_slippage", 0.0) * 2.0
            if "commission_cost" not in df:
                df["commission_cost"] = df["quantity"] * getattr(self.cost_scenario, "per_share_commission", 0.0) * 2.0
        return df

    def get_equity_dataframe(self) -> pd.DataFrame:
        if not self.daily_states:
            return pd.DataFrame()
        return pd.DataFrame([s.__dict__ for s in self.daily_states])

    def get_rejections_dataframe(self) -> pd.DataFrame:
        return self.journal.rejections_to_dataframe()

    def get_candidates_dataframe(self) -> pd.DataFrame:
        if not self.all_candidates:
            return pd.DataFrame()
        return pd.DataFrame([c.__dict__ for c in self.all_candidates])

    def get_universe_snapshots_dataframe(self) -> pd.DataFrame:
        if not self.universe_snapshots:
            return pd.DataFrame()
        return pd.DataFrame([s.__dict__ for s in self.universe_snapshots])
