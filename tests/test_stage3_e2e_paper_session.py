"""
Stage 3 End-to-End Paper Session Test:
Validates complete pipeline from Alpaca IEX data feed down to portfolio and telemetry:

    Alpaca/IEX Raw Data
            ↓
    AlpacaMarketDataAdapter (Normalizer UTC -> NY_TZ)
            ↓
    LiveDataValidator (Safety Gates)
            ↓
    LivePaperRunner
            ↓
    LiveSessionEngine
            ↓
    PaperExecutionBroker
            ↓
    Portfolio
            ↓
    Telemetry / Session Summary (IEX Tagged)
"""

from datetime import date, datetime, time, timezone
from pathlib import Path
import pytest

from bonde.data.models import NY_TZ
from bonde.execution.orders import OrderStatus
from bonde.live.adapters.alpaca.adapter import AlpacaMarketDataAdapter
from bonde.live.adapters.alpaca.config import AlpacaConfig
from bonde.live.broker import PaperExecutionBroker
from bonde.live.runner import LivePaperRunner
from bonde.live.session import LiveSessionEngine, LiveSessionState
from bonde.live.synthetic_session import SyntheticSessionGenerator
from bonde.live.validation import LiveDataValidator


def test_stage3_e2e_paper_session(tmp_path):
    """Executes a complete Stage 3 live paper trading session with Alpaca/IEX adapter."""
    session_date = date(2023, 6, 15)

    # 1. Generate synthetic stream
    bars, quotes, catalyst = SyntheticSessionGenerator.create_deterministic_session_stream(session_date)

    # 2. Set up Alpaca adapter configured for IEX feed
    config = AlpacaConfig(
        api_key="TEST_API_KEY",
        secret_key="TEST_SECRET_KEY",
        feed="iex",
        data_source_label="IEX",
        symbols=["TSLA"],
    )
    adapter = AlpacaMarketDataAdapter(config, security_id_map={"TSLA": "SEC_TSLA"})

    # 3. Set up LiveSessionEngine with local paper broker and temp output directory
    output_dir = tmp_path / "paper_stage3"
    engine = LiveSessionEngine(
        session_date=session_date,
        data_root=Path("data/stage1d"),
        output_dir=output_dir,
        initial_equity=100_000.0,
    )

    # Inject earnings catalyst for TSLA premarket prep
    if engine.prep_pipeline.catalyst_engine and engine.prep_pipeline.catalyst_engine.earnings_provider:
        engine.prep_pipeline.catalyst_engine.earnings_provider.add_event(catalyst)

    # 4. Set up Validator and LivePaperRunner
    validator = LiveDataValidator()
    runner = LivePaperRunner(
        adapter=adapter,
        engine=engine,
        validator=validator,
        data_source_label="IEX",
        session_date=session_date,
    )

    # 5. Run Pre-Market Preparation
    focus_list = engine.run_premarket()
    assert len(focus_list.approved_candidates) > 0
    assert "SEC_TSLA" in [c.security_id for c in focus_list.approved_candidates]

    # 6. Opening Bell
    engine.open_session()
    assert engine.session.state == LiveSessionState.OPENING

    # 7. Feed raw Alpaca market data through adapter -> runner -> engine
    quote_map = {q.timestamp: q for q in quotes}

    for bar in bars:
        # Construct raw Alpaca bar (UTC timestamp)
        utc_ts = bar.timestamp.astimezone(timezone.utc)
        raw_alpaca_bar = {
            "symbol": bar.symbol,
            "timestamp": utc_ts.isoformat(),
            "open": bar.open,
            "high": bar.high,
            "low": bar.low,
            "close": bar.close,
            "volume": bar.volume,
        }
        adapter.handle_raw_bar(raw_alpaca_bar)

        # Accompanying quote if present
        matching_quote = quote_map.get(bar.timestamp)
        if matching_quote:
            raw_alpaca_quote = {
                "symbol": matching_quote.symbol,
                "timestamp": utc_ts.isoformat(),
                "bid_price": matching_quote.bid,
                "ask_price": matching_quote.ask,
                "bid_size": 100,
                "ask_size": 100,
            }
            adapter.handle_raw_quote(raw_alpaca_quote)

        # Runner steps: drains adapter, validates, feeds engine
        runner.step()

    # 8. Close session
    summary = engine.close_session()
    runner_summary = runner.session_summary

    # Assertions
    # A. All valid bars were processed
    assert runner_summary["bars_processed"] == len(bars)
    assert runner_summary["bars_rejected"] == 0

    # B. Telemetry & data source label
    assert runner_summary["data_source"] == "IEX"
    assert "IEX single-exchange feed" in runner_summary["data_source_note"]
    assert "Infrastructure validation only" in runner_summary["data_source_note"]

    # C. Paper execution was performed
    assert summary["events_processed"] > 0
    assert engine.session.state == LiveSessionState.SESSION_CLOSED
    assert len(engine.broker.get_all_orders()) > 0
    orders = engine.broker.get_all_orders()
    assert any(o.symbol == "TSLA" for o in orders)
    # TSLA order was evaluated against collar limit rules (fail-closed collar enforcement)
    tsla_order = next(o for o in orders if o.symbol == "TSLA")
    assert tsla_order.status in (OrderStatus.FILLED, OrderStatus.CANCELLED)
