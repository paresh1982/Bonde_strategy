"""
Live / Paper Session Engine & Chronological State Machine (Stage 2)
Coordinates real-time transitions:
PRE_MARKET -> OPENING -> ORB_COLLECTION -> ORDER_STAGING -> ACTIVE_SESSION
-> STALE_ORDER_CUTOFF -> POSITION_MANAGEMENT -> EOD_AUDIT -> SESSION_CLOSED
"""

from dataclasses import dataclass
from datetime import date, datetime, time, timedelta
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple
import json
import pandas as pd

from ..backtest.waterfall import CandidateMetadata
from ..config.strategy_config import StrategyConfig
from ..data.models import Bar, NY_TZ
from ..execution.orders import Order, OrderSide, OrderStatus, OrderType
from ..portfolio.portfolio import Portfolio, Position, PositionStatus
from ..regime.market_regime import MarketRegime
from ..risk.governors import CompositeRiskGovernor
from ..telemetry.trade_log import TradeJournal
from .broker import PaperExecutionBroker
from .calendar import USMarketCalendar
from .fill_model import PaperFillModel
from .models import DataQualityStatus, LiveBar, Quote, TradingSession
from .prep import DailyFocusList, DailyPrepPipeline
from .reconciliation import OrderStateReconciler
from .safety import LiveSafetyGovernor, SafetyError
from .telemetry import LiveTelemetryLogger, LiveTelemetryRecord
from .validation import LiveDataValidator


class LiveSessionState:
    PRE_MARKET = "PRE_MARKET"
    OPENING = "OPENING"
    ORB_COLLECTION = "ORB_COLLECTION"
    ORDER_STAGING = "ORDER_STAGING"
    ACTIVE_SESSION = "ACTIVE_SESSION"
    STALE_ORDER_CUTOFF = "STALE_ORDER_CUTOFF"
    POSITION_MANAGEMENT = "POSITION_MANAGEMENT"
    EOD_AUDIT = "EOD_AUDIT"
    SESSION_CLOSED = "SESSION_CLOSED"


class LiveSessionEngine:
    """
    Coordinates real-time paper trading session using existing deterministic strategy invariants.
    """

    def __init__(
        self,
        session_date: date,
        data_root: Path = Path("data/stage1d"),
        output_dir: Path = Path("data/paper"),
        initial_equity: float = 100_000.0,
        config: Optional[StrategyConfig] = None,
        fill_model: Optional[PaperFillModel] = None,
    ):
        self.session_date = session_date
        self.data_root = Path(data_root)
        self.output_dir = Path(output_dir) / session_date.strftime("%Y-%m-%d")
        self.config = config or StrategyConfig()
        self.fill_model = fill_model or PaperFillModel(
            slippage_per_share=0.01,
            latency_ms=25.0,
            enforce_collar=True,
            collar_cents=self.config.default_collar_cents,
        )

        self.calendar = USMarketCalendar()
        open_dt, close_dt = self.calendar.get_session_hours(session_date)
        self.session = TradingSession(
            session_date=session_date,
            open_time=open_dt,
            close_time=close_dt,
            is_early_close=self.calendar.is_early_close(session_date),
            state=LiveSessionState.PRE_MARKET,
        )

        # Core Components
        self.prep_pipeline = DailyPrepPipeline(data_root=self.data_root, config=self.config)
        self.validator = LiveDataValidator()
        self.broker = PaperExecutionBroker()
        self.portfolio = Portfolio(initial_equity=initial_equity)
        self.journal = TradeJournal()
        self.telemetry = LiveTelemetryLogger()
        self.reconciler = OrderStateReconciler()
        self.risk_governor = CompositeRiskGovernor()

        self.focus_list: Optional[DailyFocusList] = None
        self.orb_bars: Dict[str, List[LiveBar]] = {}
        self.current_time = datetime.combine(session_date, time(8, 0), tzinfo=NY_TZ)
        self._staged_orders: Dict[str, Order] = {}
        self._events_processed = 0

    def run_premarket(self) -> DailyFocusList:
        """Step 1: 08:00 - 09:29 ET Pre-Market Preparation."""
        self.session.state = LiveSessionState.PRE_MARKET
        self.focus_list = self.prep_pipeline.run_prep(
            session_date=self.session_date,
            portfolio_equity=self.portfolio.total_equity,
            open_positions=list(self.portfolio.open_positions.values()),
            risk_governor=self.risk_governor,
        )
        return self.focus_list

    def open_session(self):
        """Step 2: 09:30 ET Opening Bell."""
        LiveSafetyGovernor.assert_regime_valid(self.focus_list.regime if self.focus_list else None)
        self.session.state = LiveSessionState.OPENING

        # Increment days held for carried overnight positions
        for pos in self.portfolio.open_positions.values():
            pos.days_held += 1

    def process_live_bar(self, bar: LiveBar, quote: Optional[Quote] = None):
        """
        Main chronological bar processor.
        Dispatches according to current session time and state.
        """
        # 1. Fail-closed data validation
        is_valid, rej = self.validator.validate_bar(bar, self.session, current_clock=bar.timestamp)
        if not is_valid:
            return

        if quote is not None:
            q_valid, q_rej = self.validator.validate_quote(quote, self.session, current_clock=quote.timestamp)
            if not q_valid:
                quote = None

        self.current_time = bar.timestamp
        bar_time = bar.timestamp.time()
        sym = bar.symbol
        self._events_processed += 1

        # 2. State Transition: 09:30 - 09:34:59 ORB Collection
        if time(9, 30) <= bar_time < time(9, 35):
            self.session.state = LiveSessionState.ORB_COLLECTION
            self.orb_bars.setdefault(sym, []).append(bar)

        # 3. State Transition: 09:35:00 Order Staging
        elif bar_time == time(9, 35) and self.session.state == LiveSessionState.ORB_COLLECTION:
            self._stage_orders_at_0935()
            self.session.state = LiveSessionState.ACTIVE_SESSION

        # 4. State Transition: 10:15:00 Stale Order Cutoff
        elif bar_time >= time(10, 15) and self.session.state == LiveSessionState.ACTIVE_SESSION:
            self._purge_stale_orders()
            self.session.state = LiveSessionState.POSITION_MANAGEMENT

        # 5. State Transition: 15:55:00 EOD Audit
        elif bar_time >= time(15, 55) and self.session.state in (LiveSessionState.ACTIVE_SESSION, LiveSessionState.POSITION_MANAGEMENT):
            self.session.state = LiveSessionState.EOD_AUDIT
            self._evaluate_eod_audit(bar)

        # Intraday Execution & Management logic
        self._evaluate_order_fills_and_exits(bar, quote)

    def _stage_orders_at_0935(self):
        """Stages BUY_STOP_LIMIT orders for approved candidates."""
        if not self.focus_list:
            return

        for c in self.focus_list.approved_candidates:
            sym = c.ticker or c.security_id
            if sym in self.portfolio.open_positions:
                continue

            # For Catalyst candidates, calculate trigger/stop from actual 09:30-09:34 bars
            if c.engine == "CATALYST" and sym in self.orb_bars and len(self.orb_bars[sym]) >= 3:
                bars = self.orb_bars[sym]
                actual_orh = max(b.high for b in bars)
                actual_orl = min(b.low for b in bars)
                c.trigger_price = round(actual_orh + self.config.tick_size, 2)
                c.structural_stop = round(actual_orl - self.config.tick_size, 2)

            collar_limit = round(c.trigger_price + self.config.default_collar_cents, 2)
            order = Order(
                symbol=sym,
                side=OrderSide.BUY,
                order_type=OrderType.BUY_STOP_LIMIT,
                quantity=c.allocated_shares,
                trigger_price=c.trigger_price,
                limit_price=collar_limit,
                stop_loss_price=c.structural_stop,
                created_at=self.current_time,
                tag=f"ENTRY_{c.module}",
            )
            order_id = self.broker.submit_order(order, security_id=c.security_id)
            self._staged_orders[sym] = order

    def _purge_stale_orders(self):
        """10:15 AM Stale Order Cutoff: cancels untriggered entry orders."""
        open_orders = self.broker.get_open_orders()
        for o in open_orders:
            if o.side == OrderSide.BUY and "ENTRY" in o.tag:
                self.broker.cancel_order(o.order_id, reason="STALE_ORDER_PURGE_1015")
                self.journal.record_rejection(
                    timestamp=self.current_time,
                    symbol=o.symbol,
                    setup_type=o.tag,
                    regime=self.focus_list.regime.value if self.focus_list else "GREEN",
                    rejection_reason="STALE_ORDER_PURGE_1015",
                )

    def _evaluate_order_fills_and_exits(self, bar: LiveBar, quote: Optional[Quote]):
        sym = bar.symbol

        # A. Evaluate Open Position Exits (Target, Stop, Runner)
        pos = self.portfolio.get_position(sym)
        if pos and pos.status == PositionStatus.OPEN:
            pos.update_price(bar.close)

            # Check stop breach and target touch
            stop_hit = bar.low <= pos.current_stop
            target_hit = (
                pos.partial_target_price is not None
                and not pos.has_partial_filled
                and bar.high >= pos.partial_target_price
            )

            # MANDATORY D2 RULE: STOP FIRST
            if stop_hit and target_hit:
                exit_p = min(pos.current_stop, bar.open) - self.fill_model.slippage_per_share
                self._close_position_internal(pos, bar, exit_p, "SAME_BAR_STOP_FIRST", quote=quote)
                return
            elif stop_hit:
                exit_p = min(pos.current_stop, bar.open) - self.fill_model.slippage_per_share
                reason = "ENTRY_BAR_STOP_BREACH" if pos.entry_timestamp == bar.timestamp else "STRUCTURAL_STOP"
                self._close_position_internal(pos, bar, exit_p, reason, quote=quote)
                return
            elif target_hit:
                # +2R Partial Exit
                exit_p = max(pos.partial_target_price, bar.open) - self.fill_model.slippage_per_share
                pos.execute_partial_exit(exit_p, bar.timestamp, ratio=self.config.partial_exit_ratio)
                return

            # Cushioned Runner 10 EMA Check
            if pos.is_cushioned:
                # Check runner trailing
                ema10 = self.prep_pipeline.daily_provider.get_prior_completed_bars(pos.symbol, self.session_date, 10)
                if ema10 and len(ema10) >= 10:
                    recent_closes = [b.close for b in ema10]
                    ema10_val = sum(recent_closes) / len(recent_closes)
                    if bar.close < ema10_val:
                        self._close_position_internal(pos, bar, bar.close, "RUNNER_CLOSE_BELOW_10_EMA", quote=quote)
                        return

        # B. Evaluate Pending Entry Order Fills
        order = self._staged_orders.get(sym)
        if order and order.status == OrderStatus.PENDING:
            eval_res = self.fill_model.evaluate_order(order, bar, quote)
            if eval_res.is_cancelled:
                self.broker.cancel_order(order.order_id, reason=eval_res.rejection_reason or "CANCELLED")
                self.journal.record_rejection(
                    timestamp=bar.timestamp,
                    symbol=sym,
                    setup_type=order.tag,
                    regime=self.focus_list.regime.value if self.focus_list else "GREEN",
                    rejection_reason=eval_res.rejection_reason or "CANCELLED",
                )
                del self._staged_orders[sym]
            elif eval_res.is_filled:
                fill_rec = self.broker.record_fill(
                    order_id=order.order_id,
                    timestamp=bar.timestamp,
                    fill_price=eval_res.fill_price,
                    fill_qty=eval_res.fill_quantity,
                    slippage=eval_res.slippage,
                )
                cand_meta = next((c for c in self.focus_list.approved_candidates if (c.ticker or c.security_id) == sym), None) if self.focus_list else None
                stop_p = order.stop_loss_price or (eval_res.fill_price * 0.96)
                sec_info = cand_meta.sector if cand_meta else "GENERAL"

                new_pos = Position(
                    symbol=sym,
                    side="LONG",
                    entry_price=eval_res.fill_price,
                    entry_timestamp=bar.timestamp,
                    quantity=eval_res.fill_quantity,
                    initial_stop=stop_p,
                    current_stop=stop_p,
                    initial_risk_dollars=eval_res.fill_quantity * (eval_res.fill_price - stop_p),
                    engine="CATALYST" if "ORB" in order.tag or "TRACK" in order.tag else "BASE_HIT",
                    setup_type=order.tag,
                    regime_at_entry=self.focus_list.regime if self.focus_list else MarketRegime.GREEN,
                    sector=sec_info,
                )
                self.portfolio.add_position(new_pos)
                del self._staged_orders[sym]

                # Immediate entry-bar stop breach check
                if bar.low <= new_pos.current_stop:
                    self._close_position_internal(new_pos, bar, new_pos.current_stop, "ENTRY_BAR_STOP_BREACH", quote=quote)

    def _evaluate_eod_audit(self, bar: LiveBar):
        """03:55 PM EOD audit: liquidates failing/stalling uncushioned positions."""
        pos = self.portfolio.get_position(bar.symbol)
        if not pos or pos.status != PositionStatus.OPEN:
            return

        # T1 liquidation if close <= entry
        if pos.days_held == 0 and not pos.is_cushioned and bar.close <= pos.entry_price:
            self._close_position_internal(pos, bar, bar.close, "EOD_AUDIT_T1_CLOSE_BELOW_ENTRY")
        # T2 stall liquidation
        elif pos.days_held == 1 and not pos.is_cushioned and bar.close <= pos.entry_price:
            self._close_position_internal(pos, bar, bar.close, "EOD_AUDIT_T2_STALL_CLOSE_BELOW_ENTRY")

    def _close_position_internal(
        self,
        pos: Position,
        bar: LiveBar,
        exit_price: float,
        reason: str,
        quote: Optional[Quote] = None,
    ):
        """Closes active position, records broker fill, and writes telemetry."""
        eff_exit = round(exit_price, 4)
        self.portfolio.close_position(
            symbol=pos.symbol,
            exit_price=eff_exit,
            timestamp=bar.timestamp,
            reason=reason,
        )

        initial_risk = pos.initial_risk_dollars if pos.initial_risk_dollars > 0 else 1.0
        r_mult = pos.realized_pnl / initial_risk

        mae = max(0.0, (pos.entry_price - bar.low) * pos.quantity)
        mfe = max(0.0, (bar.high - pos.entry_price) * pos.quantity)

        trade_rec = self.journal.record_trade(
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
            r_multiple=r_mult,
            exit_reason=reason,
            mae_dollars=mae,
            mfe_dollars=mfe,
            holding_period_bars=pos.days_held * 390,
            eod_exit_flag=("EOD_AUDIT" in reason),
        )

        # Extended Live Telemetry
        live_telemetry_rec = LiveTelemetryRecord.from_trade_record(
            base=trade_rec,
            data_source="PAPER_SESSION",
            feed_latency_ms=self.fill_model.latency_ms,
            decision_timestamp=bar.timestamp - timedelta(milliseconds=self.fill_model.latency_ms),
            order_submission_timestamp=bar.timestamp,
            simulated_fill_timestamp=bar.timestamp,
            bid_at_fill=quote.bid if quote else eff_exit,
            ask_at_fill=quote.ask if quote else eff_exit,
            simulated_slippage=self.fill_model.slippage_per_share,
        )
        self.telemetry.record_live_trade(live_telemetry_rec)

    def close_session(self) -> Dict[str, Any]:
        """Step 9: 16:00 ET Session Close, Reconciliation & Artifact Export."""
        self.session.state = LiveSessionState.SESSION_CLOSED

        # Run state reconciliation
        discrepancies = self.reconciler.reconcile(
            portfolio=self.portfolio,
            broker=self.broker,
            current_time=self.current_time,
            fail_closed=False,
        )

        # Export artifacts to data/paper/YYYY-MM-DD/
        self.output_dir.mkdir(parents=True, exist_ok=True)

        if self.focus_list:
            self.focus_list.save_parquet(self.output_dir / "focus_list.parquet")

        orders_df = self.broker.orders_to_dataframe()
        if not orders_df.empty:
            orders_df.to_parquet(self.output_dir / "orders.parquet", index=False)

        fills_df = self.broker.fills_to_dataframe()
        if not fills_df.empty:
            fills_df.to_parquet(self.output_dir / "fills.parquet", index=False)

        rejections_df = self.journal.rejections_to_dataframe()
        if not rejections_df.empty:
            rejections_df.to_parquet(self.output_dir / "rejections.parquet", index=False)

        rej_events_df = self.validator.get_rejected_events_dataframe()
        if not rej_events_df.empty:
            rej_events_df.to_parquet(self.output_dir / "rejected_events.parquet", index=False)

        self.telemetry.export_parquet(self.output_dir / "telemetry.parquet")

        summary = {
            "session_date": self.session_date.isoformat(),
            "regime": self.focus_list.regime.value if self.focus_list else "UNKNOWN",
            "events_processed": self._events_processed,
            "total_trades": len(self.journal.trades),
            "realized_pnl": sum(t.realized_pnl for t in self.journal.trades),
            "open_positions": len(self.portfolio.open_positions),
            "ending_equity": round(self.portfolio.total_equity, 2),
            "discrepancies_count": len(discrepancies),
        }
        with open(self.output_dir / "session_summary.json", "w", encoding="utf-8") as fh:
            json.dump(summary, fh, indent=2)

        return summary
