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
from .broker import PaperExecutionBroker, PaperFillRecord
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


VALID_SESSION_TRANSITIONS = {
    LiveSessionState.PRE_MARKET: {LiveSessionState.OPENING, LiveSessionState.SESSION_CLOSED},
    LiveSessionState.OPENING: {LiveSessionState.ORB_COLLECTION, LiveSessionState.ORDER_STAGING, LiveSessionState.ACTIVE_SESSION, LiveSessionState.SESSION_CLOSED},
    LiveSessionState.ORB_COLLECTION: {LiveSessionState.ORDER_STAGING, LiveSessionState.ACTIVE_SESSION, LiveSessionState.SESSION_CLOSED},
    LiveSessionState.ORDER_STAGING: {LiveSessionState.ACTIVE_SESSION, LiveSessionState.SESSION_CLOSED},
    LiveSessionState.ACTIVE_SESSION: {LiveSessionState.STALE_ORDER_CUTOFF, LiveSessionState.POSITION_MANAGEMENT, LiveSessionState.EOD_AUDIT, LiveSessionState.SESSION_CLOSED},
    LiveSessionState.STALE_ORDER_CUTOFF: {LiveSessionState.POSITION_MANAGEMENT, LiveSessionState.EOD_AUDIT, LiveSessionState.SESSION_CLOSED},
    LiveSessionState.POSITION_MANAGEMENT: {LiveSessionState.EOD_AUDIT, LiveSessionState.SESSION_CLOSED},
    LiveSessionState.EOD_AUDIT: {LiveSessionState.SESSION_CLOSED},
    LiveSessionState.SESSION_CLOSED: set(),
}


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

    def transition_to(self, new_state: str):
        """Transitions session state with strict fail-closed validation."""
        if new_state == self.session.state:
            return
        allowed = VALID_SESSION_TRANSITIONS.get(self.session.state, set())
        if new_state not in allowed:
            raise SafetyError(
                f"INVALID_STATE_TRANSITION: Cannot transition from {self.session.state} to {new_state}. Allowed: {allowed}"
            )
        self.session.state = new_state

    def run_premarket(self) -> DailyFocusList:
        """Step 1: 08:00 - 09:29 ET Pre-Market Preparation."""
        self.session.state = LiveSessionState.PRE_MARKET
        self.focus_list = self.prep_pipeline.run_prep(
            session_date=self.session_date,
            portfolio_equity=self.portfolio.total_equity,
            open_positions=list(self.portfolio.open_positions.values()),
            risk_governor=self.risk_governor,
        )
        self.checkpoint()
        return self.focus_list

    def open_session(self):
        """Step 2: 09:30 ET Opening Bell."""
        LiveSafetyGovernor.assert_regime_valid(self.focus_list.regime if self.focus_list else None)
        self.transition_to(LiveSessionState.OPENING)

        # Increment days held for carried overnight positions
        for pos in self.portfolio.open_positions.values():
            pos.days_held += 1

    def process_live_bar(self, bar: LiveBar, quote: Optional[Quote] = None):
        """
        Main chronological bar processor.
        Dispatches according to current session time and state.
        """
        if self.session.state == LiveSessionState.PRE_MARKET:
            raise SafetyError("INVALID_SESSION_STATE: Session is in PRE_MARKET state. Call open_session() before processing bars.")
        if self.session.state == LiveSessionState.SESSION_CLOSED:
            raise SafetyError("INVALID_SESSION_STATE: Session is SESSION_CLOSED. No new bars permitted.")

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
            if self.session.state == LiveSessionState.OPENING:
                self.transition_to(LiveSessionState.ORB_COLLECTION)
            self.orb_bars.setdefault(sym, []).append(bar)

        # 3. State Transition: >= 09:35:00 Order Staging
        elif bar_time >= time(9, 35) and self.session.state in (LiveSessionState.OPENING, LiveSessionState.ORB_COLLECTION):
            self.transition_to(LiveSessionState.ORDER_STAGING)
            self._stage_orders_at_0935()
            self.transition_to(LiveSessionState.ACTIVE_SESSION)

        # 4. State Transition: 10:15:00 Stale Order Cutoff
        elif bar_time >= time(10, 15) and self.session.state == LiveSessionState.ACTIVE_SESSION:
            self._purge_stale_orders()
            self.transition_to(LiveSessionState.POSITION_MANAGEMENT)

        # 5. State Transition: EOD Audit (15:55 regular, 12:55 early close)
        audit_time = (self.session.close_time - timedelta(minutes=5)).time()
        if bar_time >= audit_time and self.session.state in (LiveSessionState.ACTIVE_SESSION, LiveSessionState.POSITION_MANAGEMENT):
            self.transition_to(LiveSessionState.EOD_AUDIT)
            self._evaluate_eod_audit(bar)

        # Intraday Execution & Management logic
        self._evaluate_order_fills_and_exits(bar, quote)

    def _stage_orders_at_0935(self):
        """Stages BUY_STOP_LIMIT orders for approved candidates."""
        if not self.focus_list:
            return

        for c in self.focus_list.approved_candidates:
            sym = c.ticker or c.security_id
            if sym in self.portfolio.open_positions or sym in self._staged_orders:
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
        self.checkpoint()

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

                # Immediate entry-bar check (STOP FIRST precedence)
                if bar.low <= new_pos.current_stop:
                    self._close_position_internal(new_pos, bar, new_pos.current_stop, "ENTRY_BAR_STOP_BREACH", quote=quote)
                elif new_pos.partial_target_price is not None and bar.high >= new_pos.partial_target_price:
                    exit_p = max(new_pos.partial_target_price, bar.open) - self.fill_model.slippage_per_share
                    new_pos.execute_partial_exit(exit_p, bar.timestamp, ratio=self.config.partial_exit_ratio)

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

    def checkpoint(self, checkpoint_name: Optional[str] = None):
        """Checkpoints live state to disk."""
        self.output_dir.mkdir(parents=True, exist_ok=True)
        if self.focus_list:
            self.focus_list.save_parquet(self.output_dir / "focus_list.parquet")
        orders_df = self.broker.orders_to_dataframe()
        if not orders_df.empty:
            orders_df.to_parquet(self.output_dir / "orders.parquet", index=False)
        fills_df = self.broker.fills_to_dataframe()
        if not fills_df.empty:
            fills_df.to_parquet(self.output_dir / "fills.parquet", index=False)

    def close_session(self) -> Dict[str, Any]:
        """Step 9: 16:00 ET Session Close, Reconciliation & Artifact Export."""
        self.transition_to(LiveSessionState.SESSION_CLOSED)

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

    @classmethod
    def recover_session(
        cls,
        session_date: date,
        data_root: Path = Path("data/stage1d"),
        output_dir: Path = Path("data/paper"),
        initial_equity: float = 100_000.0,
        config: Optional[StrategyConfig] = None,
        fill_model: Optional[PaperFillModel] = None,
    ) -> "LiveSessionEngine":
        """
        Deterministically recovers session state from persisted parquet checkpoints.
        """
        engine = cls(
            session_date=session_date,
            data_root=data_root,
            output_dir=output_dir,
            initial_equity=initial_equity,
            config=config,
            fill_model=fill_model,
        )
        target_dir = Path(output_dir) / session_date.strftime("%Y-%m-%d")

        # 1. Recover Focus List
        fl_path = target_dir / "focus_list.parquet"
        if fl_path.exists():
            engine.focus_list = DailyFocusList.load_parquet(fl_path)
            engine.session.state = LiveSessionState.OPENING

        # 2. Recover Orders
        ord_path = target_dir / "orders.parquet"
        if ord_path.exists():
            df_ord = pd.read_parquet(ord_path)
            for _, r in df_ord.iterrows():
                o = Order(
                    symbol=str(r["symbol"]),
                    side=OrderSide(r["side"]),
                    order_type=OrderType(r["order_type"]),
                    quantity=int(r["quantity"]),
                    trigger_price=float(r["trigger_price"]),
                    limit_price=float(r["limit_price"]) if not pd.isna(r["limit_price"]) else None,
                    stop_loss_price=float(r["stop_loss_price"]) if not pd.isna(r["stop_loss_price"]) else None,
                    status=OrderStatus(r["status"]),
                    created_at=r["created_at"].to_pydatetime() if hasattr(r["created_at"], "to_pydatetime") else r["created_at"],
                    tag=str(r.get("tag", "")),
                )
                o.order_id = str(r["order_id"])
                engine.broker._orders[o.order_id] = o
                engine.broker._order_security_map[o.order_id] = str(r.get("security_id", f"SEC_{o.symbol}"))
                if o.status == OrderStatus.PENDING:
                    engine._staged_orders[o.symbol] = o
            engine.session.state = LiveSessionState.ACTIVE_SESSION

        # 3. Recover Fills & Positions
        fills_path = target_dir / "fills.parquet"
        if fills_path.exists():
            df_fills = pd.read_parquet(fills_path)
            for _, r in df_fills.iterrows():
                fill_rec = PaperFillRecord(
                    fill_id=str(r["fill_id"]),
                    order_id=str(r["order_id"]),
                    symbol=str(r["symbol"]),
                    security_id=str(r["security_id"]),
                    timestamp=r["timestamp"].to_pydatetime() if hasattr(r["timestamp"], "to_pydatetime") else r["timestamp"],
                    side=str(r["side"]),
                    fill_quantity=int(r["fill_quantity"]),
                    fill_price=float(r["fill_price"]),
                    commission=float(r["commission"]),
                    slippage=float(r["slippage"]),
                    effective_price=float(r["effective_price"]),
                )
                engine.broker._fills.append(fill_rec)

                # If BUY fill, reconstruct position in portfolio
                if fill_rec.side == "BUY":
                    stop_p = fill_rec.fill_price * 0.96
                    ord_obj = engine.broker.get_order(fill_rec.order_id)
                    if ord_obj and ord_obj.stop_loss_price:
                        stop_p = ord_obj.stop_loss_price
                    new_pos = Position(
                        symbol=fill_rec.symbol,
                        side="LONG",
                        entry_price=fill_rec.fill_price,
                        entry_timestamp=fill_rec.timestamp,
                        quantity=fill_rec.fill_quantity,
                        initial_stop=stop_p,
                        current_stop=stop_p,
                        initial_risk_dollars=fill_rec.fill_quantity * (fill_rec.fill_price - stop_p),
                        engine="CATALYST",
                        setup_type=ord_obj.tag if ord_obj else "RECOVERED",
                        regime_at_entry=engine.focus_list.regime if engine.focus_list else MarketRegime.GREEN,
                    )
                    engine.portfolio.add_position(new_pos)
                    engine._staged_orders.pop(fill_rec.symbol, None)

        return engine
