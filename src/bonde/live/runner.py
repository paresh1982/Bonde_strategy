"""
Live Paper Trading Runner (Stage 3 & Stage 3.1)

Orchestrates the full live paper trading session lifecycle:
    Adapter → Validation → Operational Gating → Engine → Paper Execution → Telemetry

Supports explicit operational modes:
    - OBSERVE: Consumes live data, calculates candidates & hypothetical sizing, no paper positions
    - PAPER: Consumes live data, executes local paper orders & positions via PaperExecutionBroker
    - HALTED: Fail-closed mode, cancels pending entries, preserves stops, logs halt reason

Tracks explicit live data health:
    - HEALTHY: Monotonic bar flow within staleness limits (< 60s)
    - DEGRADED: Stale warning (60s-90s) or reconnecting
    - HALTED: Critical delay (> 90s), reconnect failure, or invariant violation
"""

import logging
import time
from datetime import date, datetime, timedelta
from typing import Any, Dict, List, Optional

from bonde.data.models import NY_TZ
from bonde.execution.orders import OrderStatus, OrderType
from bonde.live.broker import PaperExecutionBroker
from bonde.live.calendar import USMarketCalendar
from bonde.live.interfaces import MarketDataProvider, QuoteProvider
from bonde.live.models import DataQualityStatus, LiveBar, Quote, TradingSession
from bonde.live.operational_modes import (
    DailyOperationalReport,
    DecisionRecord,
    DecisionType,
    LiveDataHealth,
    OperationalDecisionJournal,
    OperationalMode,
    ProviderMetadata,
)
from bonde.live.safety import SafetyError
from bonde.live.session import LiveSessionEngine, LiveSessionState
from bonde.live.validation import LiveDataValidator

logger = logging.getLogger(__name__)


class LivePaperRunner:
    """Orchestrates controlled live paper trading session."""

    def __init__(
        self,
        *args,
        adapter: Optional[MarketDataProvider] = None,
        engine: Optional[LiveSessionEngine] = None,
        validator: Optional[LiveDataValidator] = None,
        mode: OperationalMode = OperationalMode.PAPER,
        data_source_label: str = "IEX",
        staleness_warning_seconds: float = 60.0,
        staleness_halt_seconds: float = 90.0,
        checkpoint_interval_seconds: float = 300.0,
        poll_interval_seconds: float = 1.0,
        session_date: Optional[date] = None,
        **kwargs,
    ):
        """Flexible constructor supporting:
        - LivePaperRunner(adapter, engine, validator, ...)
        - LivePaperRunner(config, adapter, quote_provider=...)
        """
        resolved_adapter = adapter
        resolved_engine = engine
        resolved_validator = validator

        def _is_config(obj):
            return (
                type(obj).__name__ in ("StrategyConfig", "AlpacaConfig")
                or hasattr(obj, "orb_window_end_time")
                or hasattr(obj, "risk_pct")
                or hasattr(obj, "api_key")
            )

        if len(args) == 1:
            if _is_config(args[0]):
                resolved_adapter = adapter
            else:
                resolved_adapter = args[0]
        elif len(args) == 2:
            if _is_config(args[0]):
                resolved_adapter = args[1]
            else:
                resolved_adapter = args[0]
                resolved_engine = args[1]
        elif len(args) >= 3:
            if _is_config(args[0]):
                resolved_adapter = args[1]
                if isinstance(args[2], LiveSessionEngine):
                    resolved_engine = args[2]
            else:
                resolved_adapter = args[0]
                resolved_engine = args[1]
                resolved_validator = args[2]

        self._adapter = resolved_adapter
        self._engine = resolved_engine
        self._validator = resolved_validator or LiveDataValidator()

        # Operational Mode & Feed Health
        if isinstance(mode, str):
            self._mode = OperationalMode(mode.upper())
        else:
            self._mode = mode
        self._feed_health = LiveDataHealth.HEALTHY

        self._data_source_label = data_source_label
        self._staleness_warning_s = staleness_warning_seconds
        self._staleness_halt_s = staleness_halt_seconds
        self._checkpoint_interval_s = checkpoint_interval_seconds
        self._poll_interval_s = poll_interval_seconds

        # Decision Journal & Provider Metadata
        self._decision_journal = OperationalDecisionJournal()
        self._latest_provider_metadata: Optional[ProviderMetadata] = None

        # Session state
        self._is_running = False
        self._is_recovering = False
        self._halt_reason: Optional[str] = None
        self._bars_processed = 0
        self._bars_rejected = 0
        self._quotes_processed = 0
        self._quotes_rejected = 0
        self._disconnect_count = 0
        self._backfill_count = 0
        self._observed_hypothetical_orders: List[Dict[str, Any]] = []
        self._last_bar_time: Optional[datetime] = None
        self._last_reception_time: Optional[datetime] = None
        self._last_checkpoint_time: Optional[datetime] = None
        self._session_date: Optional[date] = session_date
        self._processed_bar_keys: set = set()

        # Fail-closed local execution assertion
        self._assert_broker_is_local_paper()

    def _assert_broker_is_local_paper(self) -> None:
        """Enforces that execution is strictly internal paper trading."""
        if self._engine is not None and hasattr(self._engine, "broker"):
            if not isinstance(self._engine.broker, PaperExecutionBroker):
                raise SafetyError(
                    "EXTERNAL_ROUTING_PROHIBITED: Live real-money order routing is strictly forbidden. "
                    f"Broker must be PaperExecutionBroker, found: {type(self._engine.broker).__name__}"
                )

    # ── Properties ──────────────────────────────────────────────────

    @property
    def mode(self) -> OperationalMode:
        return self._mode

    @mode.setter
    def mode(self, val: OperationalMode) -> None:
        if isinstance(val, str):
            self._mode = OperationalMode(val.upper())
        else:
            self._mode = val

    @property
    def feed_health(self) -> LiveDataHealth:
        return self._feed_health

    @property
    def decision_journal(self) -> OperationalDecisionJournal:
        return self._decision_journal

    @property
    def market_data_provider(self) -> Any:
        return self._adapter

    @property
    def is_running(self) -> bool:
        return self._is_running

    @property
    def is_halted(self) -> bool:
        return self._halt_reason is not None or self._mode == OperationalMode.HALTED

    @property
    def is_recovering(self) -> bool:
        return self._is_recovering

    @property
    def halt_reason(self) -> Optional[str]:
        return self._halt_reason

    @property
    def bars_processed(self) -> int:
        return self._bars_processed

    @property
    def bars_rejected(self) -> int:
        return self._bars_rejected

    @property
    def last_data_time(self) -> Optional[datetime]:
        return self._last_reception_time or self._last_bar_time

    @last_data_time.setter
    def last_data_time(self, val: Optional[datetime]) -> None:
        self._last_reception_time = val
        self._last_bar_time = val

    @property
    def last_checkpoint_time(self) -> Optional[datetime]:
        return self._last_checkpoint_time

    @last_checkpoint_time.setter
    def last_checkpoint_time(self, val: Optional[datetime]) -> None:
        self._last_checkpoint_time = val

    def stop(self) -> None:
        """Stop running session."""
        self._is_running = False

    def check_and_checkpoint(self) -> None:
        """Evaluate checkpoint trigger and execute if interval elapsed."""
        if self._should_checkpoint():
            self._do_checkpoint()

    # ── Operational Gating & Decision Tracking ──────────────────────

    def record_decision(
        self,
        decision_type: DecisionType,
        symbol: str,
        details: Dict[str, Any],
        timestamp: Optional[datetime] = None,
    ) -> DecisionRecord:
        """Records an auditable strategy decision with provider metadata."""
        return self._decision_journal.record(
            decision_type=decision_type,
            symbol=symbol,
            details=details,
            mode=self._mode,
            timestamp=timestamp or self._last_bar_time or datetime.now(NY_TZ),
            provider_metadata=self._latest_provider_metadata,
        )

    def set_feed_health(self, new_health: LiveDataHealth, reason: str = "") -> None:
        """Updates feed health state and logs degradation or recovery."""
        if new_health == self._feed_health:
            return

        old_health = self._feed_health
        self._feed_health = new_health

        if new_health == LiveDataHealth.DEGRADED:
            self.record_decision(
                DecisionType.FEED_DEGRADATION,
                symbol="ALL",
                details={"from": old_health.value, "to": new_health.value, "reason": reason},
            )
        elif new_health == LiveDataHealth.HEALTHY and old_health != LiveDataHealth.HEALTHY:
            self.record_decision(
                DecisionType.FEED_RECOVERY,
                symbol="ALL",
                details={"from": old_health.value, "to": new_health.value, "reason": reason},
            )
        elif new_health == LiveDataHealth.HALTED:
            self.halt(f"FEED_HALTED: {reason}")

    # ── Main Session Execution ──────────────────────────────────────

    def run_session(
        self,
        session_date: date,
        symbols: List[str],
        open_time: Optional[datetime] = None,
        close_time: Optional[datetime] = None,
    ) -> Dict[str, Any]:
        """Execute complete paper trading session. Returns session summary."""
        self._assert_broker_is_local_paper()
        self._session_date = session_date
        if open_time is None:
            open_time = datetime(
                session_date.year, session_date.month, session_date.day,
                9, 30, 0, tzinfo=NY_TZ
            )
        if close_time is None:
            close_time = datetime(
                session_date.year, session_date.month, session_date.day,
                16, 0, 0, tzinfo=NY_TZ
            )

        self._is_running = True
        logger.info(
            f"LivePaperRunner starting session {session_date} "
            f"[{self._mode.value} | {self._data_source_label}] with {len(symbols)} symbols"
        )

        try:
            self._run_main_loop(close_time)
        except Exception as e:
            logger.error(f"Session error: {e}")
            self.halt(f"UNHANDLED_ERROR: {e}")
        finally:
            self._is_running = False

        summary = self.session_summary
        logger.info(
            f"Session complete: {summary['status']} | "
            f"Bars: {self._bars_processed} processed, {self._bars_rejected} rejected | "
            f"Mode: {self._mode.value} | Health: {self._feed_health.value}"
        )
        return summary

    def step(self) -> None:
        """Execute a single polling and validation step (for tests and stepping)."""
        self._assert_broker_is_local_paper()

        # If halted, only run health check and return
        if self._mode == OperationalMode.HALTED or self._halt_reason is not None:
            self.check_staleness()
            return

        # Drain and process bars
        bars = self._drain_adapter_bars()
        if bars:
            self._process_bar_batch(bars)

        # Drain and process quotes
        quotes = self._drain_adapter_quotes()
        if quotes:
            self._process_quote_batch(quotes)

        # Check staleness
        self.check_staleness()

        # Check connection health
        self._check_connection()

        # Periodic checkpoint
        if self._should_checkpoint():
            self._do_checkpoint()

    def _run_main_loop(self, close_time: datetime) -> None:
        """Main processing loop: drain → validate → feed engine."""
        while self._is_running:
            now = datetime.now(NY_TZ)

            if now >= close_time:
                logger.info("Market close time reached.")
                break

            if self._halt_reason is not None or self._mode == OperationalMode.HALTED:
                break

            self.step()
            time.sleep(self._poll_interval_s)

    # ── Bar/Quote Processing ────────────────────────────────────────

    def _drain_adapter_bars(self) -> List[LiveBar]:
        if hasattr(self._adapter, "drain_bars"):
            return self._adapter.drain_bars()
        return []

    def _drain_adapter_quotes(self) -> List[Quote]:
        if hasattr(self._adapter, "drain_quotes"):
            return self._adapter.drain_quotes()
        return []

    def _get_active_session(self) -> TradingSession:
        if self._engine is not None and getattr(self._engine, "session", None) is not None:
            return self._engine.session

        s_date = self._session_date or datetime.now(NY_TZ).date()
        cal = USMarketCalendar()
        open_dt, close_dt = cal.get_session_hours(s_date)
        return TradingSession(session_date=s_date, open_time=open_dt, close_time=close_dt)

    def _process_bar_batch(self, bars: List[LiveBar]) -> None:
        """Validate and process a batch of incoming bars."""
        if not bars:
            return

        if self._session_date is None and (self._engine is None or getattr(self._engine, "session", None) is None):
            self._session_date = bars[0].timestamp.date()

        session = self._get_active_session()
        reception_now = datetime.now(NY_TZ)

        for bar in bars:
            bar_key = (bar.symbol, bar.timestamp)
            if bar_key in self._processed_bar_keys:
                self._bars_rejected += 1
                continue

            # Update provider metadata
            latency_ms = (reception_now - bar.timestamp).total_seconds() * 1000.0
            is_conn = getattr(self._adapter, "is_connected", True)
            self._latest_provider_metadata = ProviderMetadata(
                data_source=self._data_source_label,
                provider_timestamp=bar.timestamp.isoformat(),
                normalized_timestamp=bar.timestamp.isoformat(),
                reception_timestamp=reception_now.isoformat(),
                feed_latency_ms=round(latency_ms, 2),
                connection_state="CONNECTED" if is_conn else "DISCONNECTED",
            )

            # Fail-closed validation
            valid, rej = self._validator.validate_bar(
                bar,
                session=session,
                source=self._data_source_label,
            )

            if valid:
                quote = None
                if hasattr(self._adapter, "get_latest_quote"):
                    raw_q = self._adapter.get_latest_quote(bar.security_id)
                    if raw_q is not None:
                        q_valid, _ = self._validator.validate_quote(
                            raw_q, session=session, source=self._data_source_label
                        )
                        if q_valid:
                            quote = raw_q
                            self._quotes_processed += 1
                        else:
                            self._quotes_rejected += 1

                # Operational Mode Enforcement
                if self._mode == OperationalMode.OBSERVE:
                    self._process_bar_observe(bar, quote)
                elif self._mode == OperationalMode.PAPER:
                    self._process_bar_paper(bar, quote)

                self._bars_processed += 1
                self._last_bar_time = bar.timestamp
                self._last_reception_time = reception_now
                self._processed_bar_keys.add(bar_key)

                # Feed recovery if previously degraded
                if self._feed_health == LiveDataHealth.DEGRADED:
                    self.set_feed_health(LiveDataHealth.HEALTHY, reason="FRESH_BAR_RECEIVED")
            else:
                self._bars_rejected += 1
                logger.debug(
                    f"Bar rejected [{bar.symbol} {bar.timestamp}]: {rej.reason if rej else 'INVALID'}"
                )

    def _process_bar_paper(self, bar: LiveBar, quote: Optional[Quote]) -> None:
        """Standard PAPER mode: feeds bar into live session engine."""
        if self._engine is not None and hasattr(self._engine, "process_live_bar"):
            try:
                prev_fill_count = len(self._engine.broker.get_all_fills())
                prev_staged_keys = set(self._engine._staged_orders.keys())

                self._engine.process_live_bar(bar, quote)

                # Record newly staged orders
                curr_staged_keys = set(self._engine._staged_orders.keys())
                for sym in curr_staged_keys - prev_staged_keys:
                    o = self._engine._staged_orders[sym]
                    self.record_decision(
                        DecisionType.ORDER_STAGED,
                        symbol=sym,
                        details={
                            "order_id": o.order_id,
                            "trigger_price": o.trigger_price,
                            "limit_price": o.limit_price,
                            "quantity": o.quantity,
                            "stop": o.stop_loss_price,
                        },
                        timestamp=bar.timestamp,
                    )

                # Record newly filled orders
                curr_fills = self._engine.broker.get_all_fills()
                if len(curr_fills) > prev_fill_count:
                    for f in curr_fills[prev_fill_count:]:
                        self.record_decision(
                            DecisionType.ORDER_FILLED,
                            symbol=f.symbol,
                            details={
                                "fill_id": f.fill_id,
                                "fill_price": f.fill_price,
                                "quantity": f.fill_quantity,
                                "slippage": f.slippage,
                            },
                            timestamp=bar.timestamp,
                        )

            except Exception as e:
                logger.error(f"Engine error processing {bar.symbol} bar: {e}")
                self._bars_rejected += 1

    def _process_bar_observe(self, bar: LiveBar, quote: Optional[Quote]) -> None:
        """OBSERVE mode: runs engine calculations, records hypothetical orders, NO paper positions."""
        if self._engine is None or not hasattr(self._engine, "process_live_bar"):
            return

        try:
            # Capture if staging would happen
            bar_time = bar.timestamp.time()
            is_staging_window = bar_time >= datetime.strptime("09:35:00", "%H:%M:%S").time()

            self._engine.process_live_bar(bar, quote)

            # In OBSERVE mode, clear any actual broker orders and open positions to guarantee 0 paper exposure
            if is_staging_window and self._engine._staged_orders:
                for sym, o in list(self._engine._staged_orders.items()):
                    self.record_decision(
                        DecisionType.ORDER_STAGED,
                        symbol=sym,
                        details={
                            "hypothetical": True,
                            "order_id": o.order_id,
                            "trigger_price": o.trigger_price,
                            "limit_price": o.limit_price,
                            "quantity": o.quantity,
                            "stop": o.stop_loss_price,
                            "mode": "OBSERVE",
                        },
                        timestamp=bar.timestamp,
                    )
                # Clear staged orders so broker never fills them
                self._engine._staged_orders.clear()

            # Ensure open positions and broker fills remain strictly empty in OBSERVE
            if hasattr(self._engine, "portfolio"):
                self._engine.portfolio.open_positions.clear()
            if hasattr(self._engine, "broker"):
                self._engine.broker.reset()

        except Exception as e:
            logger.error(f"Observe mode error processing {bar.symbol}: {e}")
            self._bars_rejected += 1

    def _process_quote_batch(self, quotes: List[Quote]) -> None:
        """Validate a batch of quotes."""
        session = self._get_active_session()
        for quote in quotes:
            valid, rej = self._validator.validate_quote(
                quote, session=session, source=self._data_source_label
            )
            if valid:
                self._quotes_processed += 1
            else:
                self._quotes_rejected += 1

    # ── Health Monitoring ───────────────────────────────────────────

    def check_staleness(self) -> None:
        """Check for stale data and degrade/HALT if thresholds exceeded."""
        ref_time = self._last_reception_time or self._last_bar_time
        if ref_time is None:
            return

        now = datetime.now(NY_TZ) if ref_time.tzinfo else datetime.now()
        elapsed = (now - ref_time).total_seconds()

        if elapsed > self._staleness_halt_s:
            logger.warning(f"Stale data halt: No bars received for {elapsed:.0f}s (threshold: {self._staleness_halt_s}s)")
            self.set_feed_health(
                LiveDataHealth.HALTED,
                reason=f"No bars received for {elapsed:.0f}s (threshold: {self._staleness_halt_s}s)",
            )
        elif elapsed > self._staleness_warning_s:
            logger.warning(f"Stale data warning: No bars received for {elapsed:.0f}s (warning threshold: {self._staleness_warning_s}s)")
            self.set_feed_health(
                LiveDataHealth.DEGRADED,
                reason=f"No bars received for {elapsed:.0f}s (warning threshold: {self._staleness_warning_s}s)",
            )

    def _check_connection(self) -> None:
        """Check adapter connection health, attempt reconnect if down."""
        is_conn = True
        if hasattr(self._adapter, "is_connected"):
            is_conn = self._adapter.is_connected
        elif hasattr(self._adapter, "connected"):
            is_conn = self._adapter.connected

        if not is_conn:
            self._disconnect_count += 1
            self.set_feed_health(
                LiveDataHealth.DEGRADED,
                reason=f"Adapter disconnect #{self._disconnect_count}",
            )
            recovered = self.handle_disconnect()
            if not recovered:
                self.set_feed_health(
                    LiveDataHealth.HALTED,
                    reason=f"Failed to reconnect after {self._disconnect_count} disconnect(s)",
                )

    def handle_disconnect(self) -> bool:
        """Handle adapter disconnect. Fail-closed on entries, preserve stops, reconnect."""
        self._is_recovering = True

        # Checkpoint before recovery
        self._do_checkpoint()

        # Cancel pending entries fail-closed, keep stops active
        self._cancel_pending_entries()

        # Reconnect
        if not hasattr(self._adapter, "reconnect"):
            self._is_recovering = False
            return False

        disconnect_time = self._last_bar_time
        success = self._adapter.reconnect()
        if not success:
            self._is_recovering = False
            self.halt("RECONNECT_FAILED")
            return False

        # Backfill missed bars
        if (
            disconnect_time is not None
            and hasattr(self._adapter, "backfill_bars")
            and hasattr(self._adapter, "subscribed_symbols")
        ):
            try:
                reconnect_time = datetime.now(NY_TZ)
                backfilled = self._adapter.backfill_bars(
                    symbols=self._adapter.subscribed_symbols,
                    start=disconnect_time,
                    end=reconnect_time,
                )
                for symbol, bars in backfilled.items():
                    self._process_bar_batch(bars)
                    self._backfill_count += len(bars)
            except Exception as e:
                logger.warning(f"Backfill error: {e}")
        elif hasattr(self._adapter, "backfill"):
            self._adapter.backfill()

        self._is_recovering = False
        return True

    def _cancel_pending_entries(self) -> None:
        """Cancels untriggered entry orders while preserving open position stops."""
        if self._engine is None:
            return

        broker = getattr(self._engine, "broker", None)
        if broker is not None and hasattr(broker, "active_orders"):
            for o in list(broker.active_orders.values()):
                if o.order_type in (OrderType.BUY_STOP, OrderType.BUY_STOP_LIMIT):
                    if o.status == OrderStatus.PENDING:
                        broker.cancel_order(o.order_id, reason="DISCONNECT_ENTRY_CANCEL")
                        self.record_decision(
                            DecisionType.ORDER_CANCELLED,
                            symbol=o.symbol,
                            details={"order_id": o.order_id, "reason": "DISCONNECT_ENTRY_CANCEL"},
                        )

    # ── Checkpoint & Halt ───────────────────────────────────────────

    def _should_checkpoint(self) -> bool:
        now = datetime.now(NY_TZ)
        if self._last_checkpoint_time is None:
            self._last_checkpoint_time = now
            return False
        elapsed = (now - self._last_checkpoint_time).total_seconds()
        return elapsed >= self._checkpoint_interval_s

    def _do_checkpoint(self) -> None:
        try:
            if self._engine is not None and hasattr(self._engine, "checkpoint"):
                self._engine.checkpoint()
            self._last_checkpoint_time = datetime.now(NY_TZ)
            logger.debug("Checkpoint completed.")
        except Exception as e:
            logger.error(f"Checkpoint error: {e}")

    def halt(self, reason: str) -> None:
        """Emergency halt — cancels pending entries, records halt state."""
        self._halt_reason = reason
        self._mode = OperationalMode.HALTED
        self._feed_health = LiveDataHealth.HALTED
        self._is_running = False
        self._cancel_pending_entries()
        self._do_checkpoint()
        logger.critical(f"SESSION HALTED [{self._mode.value}]: {reason}")

    # ── Daily Operational Report & Telemetry ────────────────────────

    def generate_daily_report(self) -> DailyOperationalReport:
        """Generates comprehensive Stage 3.1 operational report."""
        candidates_det = 0
        candidates_rej = 0
        gov_rej = 0
        liq_rej = 0
        orders_staged = 0
        orders_filled = 0
        open_pos_count = 0
        realized_pnl = 0.0
        unrealized_pnl = 0.0
        r_multiples: List[float] = []

        if self._engine is not None:
            if self._engine.focus_list:
                fl = self._engine.focus_list
                candidates_det = len(fl.all_candidates)
                candidates_rej = len(fl.rejected_candidates)
                for c in fl.rejected_candidates:
                    if getattr(c, "rejection_stage", "") == "GOVERNOR":
                        gov_rej += 1
                    elif "LIQUIDITY" in getattr(c, "rejection_reason", "").upper():
                        liq_rej += 1

            if hasattr(self._engine, "broker"):
                all_orders = self._engine.broker.get_all_orders()
                orders_staged = len(all_orders)
                all_fills = self._engine.broker.get_all_fills()
                orders_filled = len(all_fills)

            if hasattr(self._engine, "portfolio"):
                open_pos_count = len(self._engine.portfolio.open_positions)
                unrealized_pnl = sum(p.unrealized_pnl for p in self._engine.portfolio.open_positions.values())

            if hasattr(self._engine, "journal"):
                realized_pnl = sum(t.realized_pnl for t in self._engine.journal.trades)
                r_multiples = [round(t.r_multiple, 2) for t in self._engine.journal.trades if hasattr(t, "r_multiple")]

        final_state = "UNKNOWN"
        if self._engine is not None and getattr(self._engine, "session", None):
            final_state = self._engine.session.state

        report = DailyOperationalReport(
            session_date=str(self._session_date),
            operational_mode=self._mode.value,
            feed_health=self._feed_health.value,
            data_source=self._data_source_label,
            candidates_detected=candidates_det,
            candidates_rejected=candidates_rej,
            orders_staged=orders_staged,
            orders_filled=orders_filled,
            paper_positions=open_pos_count,
            realized_pnl=round(realized_pnl, 2),
            unrealized_pnl=round(unrealized_pnl, 2),
            r_multiples=r_multiples,
            governor_rejections=gov_rej,
            liquidity_rejections=liq_rej,
            data_quality_events=self._bars_rejected + self._quotes_rejected,
            disconnect_reconnect_events=self._disconnect_count,
            final_eod_state=final_state,
            decisions_count=len(self._decision_journal.decisions),
            notes=[
                f"Data source: {self._data_source_label} single-exchange feed (~2.5% US volume).",
                "Infrastructure validation only. Not comparable to consolidated SIP backtests.",
            ],
        )
        return report

    @property
    def session_summary(self) -> Dict[str, Any]:
        """Summary dictionary conforming to runner interface."""
        return {
            "session_date": str(self._session_date),
            "mode": self._mode.value,
            "feed_health": self._feed_health.value,
            "data_source": self._data_source_label,
            "data_source_note": (
                f"{self._data_source_label} single-exchange feed (~2.5% US volume). "
                "Infrastructure validation only. Not comparable to consolidated "
                "SIP backtest data."
            ),
            "bars_processed": self._bars_processed,
            "bars_rejected": self._bars_rejected,
            "quotes_processed": self._quotes_processed,
            "quotes_rejected": self._quotes_rejected,
            "disconnect_count": self._disconnect_count,
            "backfill_count": self._backfill_count,
            "halt_reason": self._halt_reason,
            "status": "HALTED" if self.is_halted else "COMPLETED",
        }
