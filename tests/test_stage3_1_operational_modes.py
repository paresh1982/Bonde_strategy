"""
Stage 3.1 Unit & Integration Test Suite:
Controlled Live US Paper-Trading Validation:
1. Operational Modes (OBSERVE, PAPER, HALTED)
2. Live Data Health Transitions (HEALTHY, DEGRADED, HALTED)
3. Strategy Decision Auditing & Provider Metadata
4. Daily Operational Report Generation
5. Crash / Restart Checkpoint Recovery
6. Local Paper-Order Routing Safety Assertions
"""

from datetime import date, datetime, timedelta, timezone
from pathlib import Path
import pytest

from bonde.data.models import NY_TZ
from bonde.execution.orders import OrderStatus, OrderType
from bonde.live.adapters.alpaca.adapter import AlpacaMarketDataAdapter
from bonde.live.adapters.alpaca.config import AlpacaConfig
from bonde.live.broker import PaperExecutionBroker
from bonde.live.models import LiveBar, Quote
from bonde.live.operational_modes import (
    DailyOperationalReport,
    DecisionType,
    LiveDataHealth,
    OperationalDecisionJournal,
    OperationalMode,
)
from bonde.live.runner import LivePaperRunner
from bonde.live.safety import SafetyError
from bonde.live.session import LiveSessionEngine, LiveSessionState
from bonde.live.synthetic_session import SyntheticSessionGenerator
from bonde.live.validation import LiveDataValidator


# =====================================================================
# 1. OPERATIONAL MODES (OBSERVE vs PAPER vs HALTED)
# =====================================================================

def test_observe_mode_calculates_hypothetical_orders_without_positions(tmp_path):
    """In OBSERVE mode, system evaluates candidates and hypothetical orders, but creates 0 paper positions."""
    session_date = date(2023, 6, 15)
    bars, quotes, catalyst = SyntheticSessionGenerator.create_deterministic_session_stream(session_date)

    config = AlpacaConfig(api_key="TEST", secret_key="TEST", feed="iex", symbols=["TSLA"])
    adapter = AlpacaMarketDataAdapter(config, security_id_map={"TSLA": "SEC_TSLA"})

    output_dir = tmp_path / "observe_test"
    engine = LiveSessionEngine(
        session_date=session_date,
        data_root=Path("data/stage1d"),
        output_dir=output_dir,
    )
    if engine.prep_pipeline.catalyst_engine and engine.prep_pipeline.catalyst_engine.earnings_provider:
        engine.prep_pipeline.catalyst_engine.earnings_provider.add_event(catalyst)

    runner = LivePaperRunner(
        adapter=adapter,
        engine=engine,
        validator=LiveDataValidator(),
        mode=OperationalMode.OBSERVE,
        session_date=session_date,
    )

    engine.run_premarket()
    engine.open_session()

    quote_map = {q.timestamp: q for q in quotes}
    for bar in bars:
        utc_ts = bar.timestamp.astimezone(timezone.utc)
        adapter.handle_raw_bar({
            "symbol": bar.symbol,
            "timestamp": utc_ts.isoformat(),
            "open": bar.open,
            "high": bar.high,
            "low": bar.low,
            "close": bar.close,
            "volume": bar.volume,
        })
        matching_quote = quote_map.get(bar.timestamp)
        if matching_quote:
            adapter.handle_raw_quote({
                "symbol": matching_quote.symbol,
                "timestamp": utc_ts.isoformat(),
                "bid_price": matching_quote.bid,
                "ask_price": matching_quote.ask,
                "bid_size": 100,
                "ask_size": 100,
            })
        runner.step()

    # STRICT ASSERTIONS FOR OBSERVE MODE:
    # 1. Zero paper positions opened
    assert len(engine.portfolio.open_positions) == 0
    # 2. Zero broker fills
    assert len(engine.broker.get_all_fills()) == 0
    # 3. Decisions recorded hypothetical orders in journal
    staged_decisions = runner.decision_journal.get_by_type(DecisionType.ORDER_STAGED)
    assert len(staged_decisions) > 0
    assert any(d.details.get("hypothetical") is True for d in staged_decisions)
    assert runner.mode == OperationalMode.OBSERVE


def test_paper_mode_executes_local_paper_orders(tmp_path):
    """In PAPER mode, orders are staged in local paper broker and tracked."""
    session_date = date(2023, 6, 15)
    bars, quotes, catalyst = SyntheticSessionGenerator.create_deterministic_session_stream(session_date)

    config = AlpacaConfig(api_key="TEST", secret_key="TEST", feed="iex", symbols=["TSLA"])
    adapter = AlpacaMarketDataAdapter(config, security_id_map={"TSLA": "SEC_TSLA"})

    output_dir = tmp_path / "paper_mode_test"
    engine = LiveSessionEngine(
        session_date=session_date,
        data_root=Path("data/stage1d"),
        output_dir=output_dir,
    )
    if engine.prep_pipeline.catalyst_engine and engine.prep_pipeline.catalyst_engine.earnings_provider:
        engine.prep_pipeline.catalyst_engine.earnings_provider.add_event(catalyst)

    runner = LivePaperRunner(
        adapter=adapter,
        engine=engine,
        validator=LiveDataValidator(),
        mode=OperationalMode.PAPER,
        session_date=session_date,
    )

    engine.run_premarket()
    engine.open_session()

    for bar in bars[:6]:  # Process up to 09:35 staging
        utc_ts = bar.timestamp.astimezone(timezone.utc)
        adapter.handle_raw_bar({
            "symbol": bar.symbol,
            "timestamp": utc_ts.isoformat(),
            "open": bar.open,
            "high": bar.high,
            "low": bar.low,
            "close": bar.close,
            "volume": bar.volume,
        })
        runner.step()

    assert runner.mode == OperationalMode.PAPER
    assert len(engine.broker.get_all_orders()) > 0
    assert any(o.symbol == "TSLA" for o in engine.broker.get_all_orders())


def test_halted_mode_blocks_new_entries(tmp_path):
    """In HALTED mode, runner rejects/ignores new entry orders and stops processing."""
    session_date = date(2023, 6, 15)
    config = AlpacaConfig(api_key="TEST", secret_key="TEST", feed="iex", symbols=["TSLA"])
    adapter = AlpacaMarketDataAdapter(config, security_id_map={"TSLA": "SEC_TSLA"})

    engine = LiveSessionEngine(session_date=session_date, data_root=Path("data/stage1d"), output_dir=tmp_path)
    runner = LivePaperRunner(adapter=adapter, engine=engine, mode=OperationalMode.HALTED, session_date=session_date)

    assert runner.is_halted
    assert runner.mode == OperationalMode.HALTED

    # Attempt to feed bar while halted
    dt = datetime(2023, 6, 15, 10, 0, tzinfo=NY_TZ)
    adapter.handle_raw_bar({"symbol": "TSLA", "timestamp": dt.astimezone(timezone.utc).isoformat(), "open": 250, "high": 251, "low": 249, "close": 250, "volume": 100})
    runner.step()

    # In HALTED mode, step skips bar ingestion
    assert runner.bars_processed == 0


# =====================================================================
# 2. LIVE DATA HEALTH TRANSITIONS (HEALTHY, DEGRADED, HALTED)
# =====================================================================

def test_feed_health_transitions_and_degradation():
    """Verifies HEALTHY -> DEGRADED -> HEALTHY recovery and HALTED states."""
    session_date = date(2023, 6, 15)
    adapter = AlpacaMarketDataAdapter(AlpacaConfig(api_key="T", secret_key="T"))
    runner = LivePaperRunner(
        adapter=adapter,
        session_date=session_date,
        staleness_warning_seconds=60.0,
        staleness_halt_seconds=90.0,
    )

    # Initial state
    assert runner.feed_health == LiveDataHealth.HEALTHY

    # Normal bar sets fresh timestamp
    now = datetime.now(NY_TZ)
    runner.last_data_time = now
    runner.check_staleness()
    assert runner.feed_health == LiveDataHealth.HEALTHY

    # 1. Staleness exceeds 60s -> DEGRADED
    runner.last_data_time = now - timedelta(seconds=65)
    runner.check_staleness()
    assert runner.feed_health == LiveDataHealth.DEGRADED
    degraded_decisions = runner.decision_journal.get_by_type(DecisionType.FEED_DEGRADATION)
    assert len(degraded_decisions) >= 1

    # 2. Fresh bar arrives -> RECOVERY back to HEALTHY
    fresh_bar = LiveBar(datetime(2023, 6, 15, 10, 0, tzinfo=NY_TZ), "AAPL", "SEC_AAPL", 150.0, 151.0, 149.0, 150.0, 100)
    runner._process_bar_batch([fresh_bar])
    assert runner.feed_health == LiveDataHealth.HEALTHY
    recovery_decisions = runner.decision_journal.get_by_type(DecisionType.FEED_RECOVERY)
    assert len(recovery_decisions) >= 1

    # 3. Staleness exceeds 90s -> HALTED
    runner.last_data_time = datetime.now(NY_TZ) - timedelta(seconds=95)
    runner.check_staleness()
    assert runner.feed_health == LiveDataHealth.HALTED
    assert runner.is_halted


# =====================================================================
# 3. DECISION AUDITING & PROVIDER METADATA
# =====================================================================

def test_provider_metadata_and_decision_auditing():
    """Verifies every market bar records provider metadata and latency."""
    adapter = AlpacaMarketDataAdapter(AlpacaConfig(api_key="T", secret_key="T"))
    runner = LivePaperRunner(adapter=adapter, data_source_label="IEX")

    bar_ts = datetime(2023, 6, 15, 10, 0, tzinfo=NY_TZ)
    bar = LiveBar(bar_ts, "NVDA", "SEC_NVDA", 400.0, 405.0, 399.0, 404.0, 5000)

    runner._process_bar_batch([bar])

    meta = runner._latest_provider_metadata
    assert meta is not None
    assert meta.data_source == "IEX"
    assert meta.provider_timestamp is not None
    assert meta.reception_timestamp is not None
    assert meta.feed_latency_ms is not None
    assert meta.connection_state == "CONNECTED"


# =====================================================================
# 4. DAILY OPERATIONAL REPORT
# =====================================================================

def test_daily_operational_report_generation(tmp_path):
    """Verifies generation of complete Stage 3.1 daily operational report."""
    session_date = date(2023, 6, 15)
    config = AlpacaConfig(api_key="T", secret_key="T", feed="iex", symbols=["TSLA"])
    adapter = AlpacaMarketDataAdapter(config)
    engine = LiveSessionEngine(session_date=session_date, data_root=Path("data/stage1d"), output_dir=tmp_path)

    runner = LivePaperRunner(adapter=adapter, engine=engine, session_date=session_date)

    report = runner.generate_daily_report()
    assert isinstance(report, DailyOperationalReport)
    assert report.session_date == "2023-06-15"
    assert report.operational_mode == "PAPER"
    assert report.feed_health == "HEALTHY"
    assert report.data_source == "IEX"

    # Verify JSON and Markdown export
    json_path = tmp_path / "report.json"
    json_str = report.to_json(json_path)
    assert json_path.exists()
    assert '"data_source": "IEX"' in json_str

    md_str = report.to_markdown()
    assert "# Daily Operational Report" in md_str
    assert "IEX single-exchange feed" in md_str


# =====================================================================
# 5. CRASH / RESTART CHECKPOINT RECOVERY
# =====================================================================

def test_crash_restart_checkpoint_recovery(tmp_path):
    """Verifies that state can be recovered from disk checkpoints during a session."""
    session_date = date(2023, 6, 15)
    out_dir = tmp_path / "recovery_test"

    # Run session 1 up to premarket and staging
    engine1 = LiveSessionEngine(session_date=session_date, data_root=Path("data/stage1d"), output_dir=out_dir)
    bars, _, catalyst = SyntheticSessionGenerator.create_deterministic_session_stream(session_date)
    if engine1.prep_pipeline.catalyst_engine and engine1.prep_pipeline.catalyst_engine.earnings_provider:
        engine1.prep_pipeline.catalyst_engine.earnings_provider.add_event(catalyst)

    engine1.run_premarket()
    engine1.open_session()
    for b in bars[:6]:  # Up to 09:35 staging
        engine1.process_live_bar(b)

    # State checkpointed to disk
    engine1.checkpoint()

    # Simulate crash and restart: create recovered engine
    engine_recovered = LiveSessionEngine.recover_session(
        session_date=session_date,
        data_root=Path("data/stage1d"),
        output_dir=out_dir,
    )

    assert engine_recovered.session.state == LiveSessionState.ACTIVE_SESSION
    assert engine_recovered.focus_list is not None
    assert len(engine_recovered.broker.get_all_orders()) == len(engine1.broker.get_all_orders())


# =====================================================================
# 6. LOCAL PAPER-ORDER ROUTING SAFETY ASSERTIONS
# =====================================================================

def test_safety_assertion_prohibits_external_broker():
    """Fails closed with SafetyError if an external or non-paper broker is configured."""
    class FakeLiveBroker:
        pass

    class FakeEngine:
        def __init__(self):
            self.broker = FakeLiveBroker()

    with pytest.raises(SafetyError, match="EXTERNAL_ROUTING_PROHIBITED"):
        LivePaperRunner(adapter=AlpacaMarketDataAdapter(AlpacaConfig(api_key="T", secret_key="T")), engine=FakeEngine())
