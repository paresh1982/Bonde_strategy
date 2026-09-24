"""
Event-Driven Chronological Backtest Engine (Section 20)
Processes bars in strict chronological order with zero lookahead bias.
"""

from datetime import datetime, time
from typing import Dict, List, Optional
import zoneinfo

from ..config.strategy_config import StrategyConfig
from ..data.models import ADVProvider, Bar, DailyIndicatorProvider, SectorProvider, StaticSectorProvider, NY_TZ
from ..execution.orders import Order, OrderSide, OrderType, OrderStatus
from ..execution.simulator import ExecutionSimulator
from ..portfolio.portfolio import Portfolio, Position, PositionStatus
from ..regime.market_regime import MarketRegime, MarketRegimeProvider, StaticRegimeProvider
from ..risk.governors import CompositeRiskGovernor, RiskGovernor
from ..risk.sizing import calculate_position_size
from ..setups.catalyst import CatalystORBSetup, ORBCandidate
from ..setups.base_hit import BaseHitSetup, BaseHitCandidate
from ..telemetry.trade_log import TradeJournal


class Stage0BacktestEngine:
    def __init__(
        self,
        config: Optional[StrategyConfig] = None,
        regime_provider: Optional[MarketRegimeProvider] = None,
        sector_provider: Optional[SectorProvider] = None,
        risk_governor: Optional[RiskGovernor] = None,
        daily_indicator_provider: Optional[DailyIndicatorProvider] = None,
        adv_provider: Optional[ADVProvider] = None,
        initial_equity: float = 100_000.0,
    ):
        self.config = config or StrategyConfig()
        self.regime_provider = regime_provider or StaticRegimeProvider()
        self.sector_provider = sector_provider or StaticSectorProvider()
        self.risk_governor = risk_governor or CompositeRiskGovernor()
        self.daily_indicator_provider = daily_indicator_provider
        self.adv_provider = adv_provider
        self.portfolio = Portfolio(initial_equity=initial_equity)
        self.journal = TradeJournal()
        self.simulator = ExecutionSimulator()

        self.pending_orders: List[Order] = []
        self._opening_bars_cache: Dict[str, List[Bar]] = {}
        self._orb_staged_today: Dict[str, bool] = {}
        self._current_date: Optional[str] = None

    def run(self, bars: List[Bar], adv_50_map: Optional[Dict[str, float]] = None):
        """
        Executes event-driven simulation over chronologically sorted bars.
        """
        adv_50_map = adv_50_map or {}
        sorted_bars = sorted(bars, key=lambda b: b.timestamp)

        for bar in sorted_bars:
            if self.adv_provider is not None:
                adv_50 = self.adv_provider.get_adv_50(bar.symbol, bar.timestamp.date())
            else:
                adv_50 = adv_50_map.get(bar.symbol, 500_000.0)
            self._process_bar(bar, adv_50)

    def _process_bar(self, bar: Bar, adv_50: Optional[float]):
        ts = bar.timestamp
        bar_time = ts.time()
        date_str = ts.strftime("%Y-%m-%d")

        # Reset daily state on new date
        if date_str != self._current_date:
            self._current_date = date_str
            self._opening_bars_cache.clear()
            self._orb_staged_today.clear()
            # Increment days held on open positions
            for pos in self.portfolio.open_positions.values():
                pos.days_held += 1

        regime = self.regime_provider.get_regime(ts)
        risk_fraction = self.regime_provider.get_risk_fraction(ts)
        sector = self.sector_provider.get_industry_group(bar.symbol, ts)

        # 1. Evaluate open positions for exits on this bar
        self._evaluate_position_exits(bar)

        # 2. Check 03:55 PM EOD audit (Section 14)
        if bar_time >= time(15, 55, 0):
            self._evaluate_eod_audit(bar)

        # 3. Process pending orders
        self._process_pending_orders(bar, sector)

        # 4. Opening Range Bar Caching (09:30:00 to 09:34:59)
        if time(9, 30, 0) <= bar_time < time(9, 35, 0):
            if bar.symbol not in self._opening_bars_cache:
                self._opening_bars_cache[bar.symbol] = []
            self._opening_bars_cache[bar.symbol].append(bar)

        # 5. At 09:35:00, evaluate 5-minute ORB (Section 6, 12)
        if bar_time == time(9, 35, 0) and not self._orb_staged_today.get(bar.symbol, False):
            self._evaluate_and_stage_orb(bar, adv_50, regime, risk_fraction, sector)

    def _evaluate_position_exits(self, bar: Bar):
        """Evaluates structural stops, partial targets, and same-bar collisions (D2)."""
        position = self.portfolio.get_position(bar.symbol)
        if not position or position.status != PositionStatus.OPEN:
            return

        position.update_price(bar.close)

        exit_type, exit_price, is_same_bar = self.simulator.evaluate_position_exits(
            current_stop=position.current_stop,
            partial_target=position.partial_target_price,
            bar=bar,
            has_partial_filled=position.has_partial_filled,
        )

        if exit_type == "STOP":
            if is_same_bar:
                exit_reason = "SAME_BAR_STOP_FIRST"
            elif position.entry_timestamp == bar.timestamp:
                exit_reason = "ENTRY_BAR_STOP_BREACH"
            else:
                exit_reason = "STRUCTURAL_STOP"

            self.portfolio.close_position(
                symbol=bar.symbol,
                exit_price=exit_price,
                timestamp=bar.timestamp,
                reason=exit_reason,
            )
            self.journal.record_trade(
                symbol=position.symbol,
                engine=position.engine,
                setup_type=position.setup_type,
                regime=position.regime_at_entry.value,
                sector=position.sector or "GENERAL",
                entry_timestamp=position.entry_timestamp,
                entry_price=position.entry_price,
                initial_stop_price=position.initial_stop,
                exit_timestamp=bar.timestamp,
                exit_price=exit_price,
                quantity=position.quantity,
                initial_risk_dollars=position.initial_risk_dollars,
                realized_pnl=position.realized_pnl,
                r_multiple=position.r_multiple,
                exit_reason=exit_reason,
            )
            if hasattr(self.risk_governor, "record_closed_trade"):
                self.risk_governor.record_closed_trade(position.realized_pnl)

        elif exit_type == "TARGET":
            # Partial profit-taking (+2.0R, 50% exit, BE ratchet)
            position.execute_partial_exit(
                price=exit_price,
                timestamp=bar.timestamp,
                ratio=self.config.partial_exit_ratio,
            )

    def _close_eod_position(self, position: Position, bar: Bar, reason: str):
        self.portfolio.close_position(
            symbol=bar.symbol,
            exit_price=bar.close,
            timestamp=bar.timestamp,
            reason=reason,
        )
        self.journal.record_trade(
            symbol=position.symbol,
            engine=position.engine,
            setup_type=position.setup_type,
            regime=position.regime_at_entry.value,
            sector=position.sector or "GENERAL",
            entry_timestamp=position.entry_timestamp,
            entry_price=position.entry_price,
            initial_stop_price=position.initial_stop,
            exit_timestamp=bar.timestamp,
            exit_price=bar.close,
            quantity=position.quantity,
            initial_risk_dollars=position.initial_risk_dollars,
            realized_pnl=position.realized_pnl,
            r_multiple=position.r_multiple,
            exit_reason=reason,
            eod_exit_flag=True,
        )
        if hasattr(self.risk_governor, "record_closed_trade"):
            self.risk_governor.record_closed_trade(position.realized_pnl)

    def _evaluate_eod_audit(self, bar: Bar):
        """Mandatory 03:55 PM EOD audit (Section 14)."""
        position = self.portfolio.get_position(bar.symbol)
        if not position or position.status != PositionStatus.OPEN:
            return

        # Record Day 1 close for tracking
        if position.days_held == 0 and position.day1_close is None:
            position.day1_close = bar.close

        # 1. Fresh T1 liquidation if uncushioned and Close <= Entry
        if position.days_held == 0 and not position.is_cushioned and bar.close <= position.entry_price:
            self._close_eod_position(position, bar, "EOD_AUDIT_T1_CLOSE_BELOW_ENTRY")
            return

        # 2. T2 Stall liquidation if uncushioned and Close <= Entry (Stage 0.2 Requirement 3)
        elif position.days_held == 1 and not position.is_cushioned and bar.close <= position.entry_price:
            self._close_eod_position(position, bar, "EOD_AUDIT_T2_STALL_CLOSE_BELOW_ENTRY")
            return

        # 3. Base-Hit max holding period exit (Day 3-5)
        elif position.engine == "BASE_HIT" and position.days_held >= self.config.base_hit_max_holding_days:
            self._close_eod_position(position, bar, "BASE_HIT_TIME_STOP_DAY_5")
            return

        # 4. Cushioned Runner 10 EMA management (Stage 0.2 Requirement 4)
        elif position.is_cushioned and self.daily_indicator_provider is not None:
            ema_10 = self.daily_indicator_provider.get_ema(bar.symbol, bar.timestamp.date(), period=10)
            if ema_10 is not None and bar.close < ema_10:
                self._close_eod_position(position, bar, "RUNNER_CLOSE_BELOW_10_EMA")
                return

    def _process_pending_orders(self, bar: Bar, sector: Optional[str]):
        """Processes staged entry orders against the current bar."""
        active_pending = [o for o in self.pending_orders if o.symbol == bar.symbol and o.status == OrderStatus.PENDING]

        for order in active_pending:
            fill_event = self.simulator.process_entry_order(order, bar)

            if fill_event is not None:
                stop_price = order.stop_loss_price if order.stop_loss_price is not None else (order.trigger_price * 0.96)
                # Open position
                position = Position(
                    symbol=order.symbol,
                    side="LONG",
                    entry_price=fill_event.fill_price,
                    entry_timestamp=fill_event.timestamp,
                    quantity=fill_event.quantity,
                    initial_stop=stop_price,
                    current_stop=stop_price,
                    initial_risk_dollars=fill_event.quantity * (fill_event.fill_price - stop_price),
                    engine="CATALYST" if "ORB" in order.tag else "BASE_HIT",
                    setup_type=order.tag,
                    regime_at_entry=self.regime_provider.get_regime(bar.timestamp),
                    sector=sector or "GENERAL",
                )
                self.portfolio.add_position(position)

                # CONSERVATIVE ENTRY-BAR POST-FILL EVALUATION (Stage 0.2 Requirement 1)
                self._evaluate_position_exits(bar)
            elif order.status == OrderStatus.CANCELLED:
                self.journal.record_rejection(
                    timestamp=bar.timestamp,
                    symbol=order.symbol,
                    setup_type=order.tag,
                    regime=self.regime_provider.get_regime(bar.timestamp).value,
                    rejection_reason=order.rejection_reason or "CANCELLED",
                )

        # Remove finished orders
        self.pending_orders = [o for o in self.pending_orders if o.status == OrderStatus.PENDING]

    def _evaluate_and_stage_orb(
        self,
        bar: Bar,
        adv_50: Optional[float],
        regime: MarketRegime,
        risk_fraction: float,
        sector: Optional[str],
    ):
        """Evaluates 5-minute ORB candidate and stages Stop-Limit order if approved."""
        self._orb_staged_today[bar.symbol] = True
        opening_bars = self._opening_bars_cache.get(bar.symbol, [])

        orb_setup = CatalystORBSetup(
            max_risk_geometry_pct=self.config.max_risk_geometry_pct,
            collar_cents=self.config.default_collar_cents,
            tick_size=self.config.tick_size,
        )
        candidate: ORBCandidate = orb_setup.evaluate_first_5_minutes(bar.symbol, opening_bars)

        if not candidate.is_qualified:
            self.journal.record_rejection(
                timestamp=bar.timestamp,
                symbol=bar.symbol,
                setup_type="CATALYST_ORB",
                regime=regime.value,
                rejection_reason=candidate.rejection_reason or "ORB_REJECTED",
            )
            return

        # Check Universal Risk-Geometry Filter (Stage 0.2 Requirement 6)
        planned_risk_pct = (candidate.trigger_price - candidate.stop_price) / candidate.trigger_price
        if planned_risk_pct > self.config.max_risk_geometry_pct:
            self.journal.record_rejection(
                timestamp=bar.timestamp,
                symbol=bar.symbol,
                setup_type="CATALYST_ORB",
                regime=regime.value,
                rejection_reason=f"UNIVERSAL_RISK_GEOMETRY_EXCEEDED ({planned_risk_pct*100:.2f}% > {self.config.max_risk_geometry_pct*100:.1f}%)",
            )
            return

        # Check regime gate
        if regime == MarketRegime.RED or risk_fraction <= 0:
            self.journal.record_rejection(
                timestamp=bar.timestamp,
                symbol=bar.symbol,
                setup_type="CATALYST_ORB",
                regime=regime.value,
                rejection_reason="RED_REGIME_NEW_TRADES_DISABLED",
            )
            return

        # Check missing ADV data if strict provider is active
        if adv_50 is None and self.adv_provider is not None:
            self.journal.record_rejection(
                timestamp=bar.timestamp,
                symbol=bar.symbol,
                setup_type="CATALYST_ORB",
                regime=regime.value,
                rejection_reason="MISSING_ADV50_DATA",
            )
            return

        # Sizing and liquidity cap
        sizing = calculate_position_size(
            account_equity=self.portfolio.total_equity,
            entry_price=candidate.trigger_price,
            stop_price=candidate.stop_price,
            risk_fraction=risk_fraction,
            adv_50=adv_50,
            participation_cap=self.config.adv_participation_cap,
            min_allocation_ratio=self.config.min_allocation_ratio,
        )

        if not sizing.is_liquid or sizing.allocated_shares <= 0:
            self.journal.record_rejection(
                timestamp=bar.timestamp,
                symbol=bar.symbol,
                setup_type="CATALYST_ORB",
                regime=regime.value,
                rejection_reason=sizing.rejection_reason or "INSUFFICIENT_LIQUIDITY",
            )
            return

        # Check Portfolio Risk Governors (Heat, Sector, Single Ticker)
        unit_1r_dollars = self.portfolio.total_equity * risk_fraction
        allowed, gov_reason = self.risk_governor.evaluate(
            symbol=bar.symbol,
            planned_risk_dollars=sizing.actual_risk_dollars,
            unit_1r_dollars=unit_1r_dollars,
            regime=regime,
            sector=sector,
            open_positions=list(self.portfolio.open_positions.values()),
        )

        if not allowed:
            self.journal.record_rejection(
                timestamp=bar.timestamp,
                symbol=bar.symbol,
                setup_type="CATALYST_ORB",
                regime=regime.value,
                rejection_reason=gov_reason or "GOVERNOR_REJECTION",
            )
            return

        # Stage BUY_STOP_LIMIT order
        order = Order(
            symbol=bar.symbol,
            side=OrderSide.BUY,
            order_type=OrderType.BUY_STOP_LIMIT,
            quantity=sizing.allocated_shares,
            trigger_price=candidate.trigger_price,
            limit_price=candidate.limit_price,
            stop_loss_price=candidate.stop_price,
            created_at=bar.timestamp,
            tag="CATALYST_ORB",
        )
        self.pending_orders.append(order)
