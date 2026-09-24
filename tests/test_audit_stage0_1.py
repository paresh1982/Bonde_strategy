"""
Stage 0.1 Independent Audit Tests
Adversarially probes equity conservation, gap fills, governor hierarchy, and sizing edge cases.
"""

from datetime import datetime, time
import pytest
from bonde.data.models import Bar, NY_TZ
from bonde.execution.orders import Order, OrderSide, OrderType, OrderStatus
from bonde.execution.simulator import ExecutionSimulator
from bonde.portfolio.portfolio import Portfolio, Position, PositionStatus
from bonde.regime.market_regime import MarketRegime
from bonde.risk.governors import HeatGovernor, InternalLossGovernor, SingleTickerGovernor
from bonde.risk.sizing import calculate_position_size, calculate_liquidity_cap


def test_portfolio_total_equity_with_partial_realized_gain():
    """
    Verifies that total_equity strictly conserves realized gains from partial profit-taking
    while the runner position remains open.
    """
    portfolio = Portfolio(initial_equity=100_000.0)
    pos = Position(
        symbol="EQUITY_TEST",
        side="LONG",
        entry_price=100.0,
        entry_timestamp=datetime(2026, 1, 5, 9, 36, tzinfo=NY_TZ),
        quantity=100,
        initial_stop=98.0,
        current_stop=98.0,
        initial_risk_dollars=200.0,
        engine="CATALYST",
        setup_type="ORB",
        regime_at_entry=MarketRegime.GREEN,
    )
    portfolio.add_position(pos)

    # Initial equity: 100,000
    assert portfolio.total_equity == 100_000.0

    # Stock advances to +2R ($104.00)
    pos.update_price(104.0)
    assert portfolio.total_equity == 100_400.0

    # Execute partial exit (50 shares @ $104.00 = +$200 realized)
    pos.execute_partial_exit(price=104.0, timestamp=datetime(2026, 1, 5, 10, 0, tzinfo=NY_TZ), ratio=0.5)
    pos.update_price(104.0)

    # Invariant: Total equity MUST remain 100,400.0 (not drop to 100,200.0)
    assert pos.realized_pnl == 200.0
    assert pos.unrealized_pnl == 200.0
    assert portfolio.total_equity == 100_400.0

    # Final liquidation of runner at $105.00
    portfolio.close_position("EQUITY_TEST", exit_price=105.0, timestamp=datetime(2026, 1, 5, 15, 55, tzinfo=NY_TZ), reason="EOD")
    assert portfolio.total_equity == 100_450.0
    assert portfolio.cash == 100_450.0


def test_same_bar_gap_through_stop():
    """
    Verifies that when a bar opens below the stop price (adverse gap),
    the fill occurs at bar.open (realistic gap execution), not at the higher stop price.
    """
    simulator = ExecutionSimulator()
    current_stop = 48.00

    # Bar gaps down at open to $46.50 (below $48.00 stop)
    bar = Bar(
        timestamp=datetime(2026, 1, 5, 11, 0, tzinfo=NY_TZ),
        symbol="GAP_STOP",
        open=46.50,
        high=47.50,
        low=46.00,
        close=47.00,
        volume=100_000,
    )

    exit_type, exit_price, is_same_bar = simulator.evaluate_position_exits(
        current_stop=current_stop,
        partial_target=54.00,
        bar=bar,
        has_partial_filled=False,
    )

    assert exit_type == "STOP"
    assert exit_price == 46.50  # Executed at open print, not 48.00


def test_heat_governor_enforces_6r_cap():
    """
    Verifies that HeatGovernor rejects any order that would push total portfolio
    uncushioned open heat above 6.0R.
    """
    governor = HeatGovernor(max_heat_r=6.0)
    unit_1r = 1000.0

    # 5 open uncushioned positions of 1.0R each = 5.0R heat
    positions = []
    for i in range(5):
        positions.append(
            Position(
                symbol=f"SYM_{i}",
                side="LONG",
                entry_price=50.0,
                entry_timestamp=datetime(2026, 1, 5, 9, 36, tzinfo=NY_TZ),
                quantity=500,
                initial_stop=48.0,
                current_stop=48.0,
                initial_risk_dollars=1000.0,
                engine="CATALYST",
                setup_type="ORB",
                regime_at_entry=MarketRegime.GREEN,
                is_cushioned=False,
            )
        )

    # 1.0R proposed -> Total 6.0R <= 6.0R -> ALLOWED
    allowed1, reason1 = governor.evaluate("SYM_NEW", 1000.0, unit_1r, MarketRegime.GREEN, "TECH", positions)
    assert allowed1 is True
    assert reason1 is None

    # 1.5R proposed -> Total 6.5R > 6.0R -> REJECTED
    allowed2, reason2 = governor.evaluate("SYM_NEW", 1500.0, unit_1r, MarketRegime.GREEN, "TECH", positions)
    assert allowed2 is False
    assert "PORTFOLIO_HEAT_EXCEEDED" in (reason2 or "")


def test_internal_loss_governor_circuit_breaker():
    """
    Verifies that InternalLossGovernor trips halt state after 3 consecutive losses
    and recovers upon a winning trade.
    """
    governor = InternalLossGovernor(max_consecutive_losses=3)

    # 1st loss
    governor.record_closed_trade(-500.0)
    allowed, _ = governor.evaluate("SYM", 1000.0, 1000.0, MarketRegime.GREEN, "TECH", [])
    assert allowed is True

    # 2nd loss
    governor.record_closed_trade(-200.0)
    allowed, _ = governor.evaluate("SYM", 1000.0, 1000.0, MarketRegime.GREEN, "TECH", [])
    assert allowed is True

    # 3rd consecutive loss -> HALT
    governor.record_closed_trade(-800.0)
    allowed, reason = governor.evaluate("SYM", 1000.0, 1000.0, MarketRegime.GREEN, "TECH", [])
    assert allowed is False
    assert "INTERNAL_GOVERNOR_HALTED" in (reason or "")

    # Winning trade resets consecutive losses
    governor.record_closed_trade(1500.0)
    allowed, reason = governor.evaluate("SYM", 1000.0, 1000.0, MarketRegime.GREEN, "TECH", [])
    assert allowed is True
    assert reason is None


def test_single_ticker_governor_blocks_duplicate():
    """
    Verifies that SingleTickerGovernor prevents multiple open positions in the same ticker.
    """
    governor = SingleTickerGovernor()
    pos = Position(
        symbol="AAPL",
        side="LONG",
        entry_price=150.0,
        entry_timestamp=datetime(2026, 1, 5, 9, 36, tzinfo=NY_TZ),
        quantity=100,
        initial_stop=145.0,
        current_stop=145.0,
        initial_risk_dollars=500.0,
        engine="CATALYST",
        setup_type="ORB",
        regime_at_entry=MarketRegime.GREEN,
    )

    # Evaluating AAPL again -> REJECT
    allowed, reason = governor.evaluate("AAPL", 500.0, 1000.0, MarketRegime.GREEN, "TECH", [pos])
    assert allowed is False
    assert "SINGLE_TICKER_EXPOSURE_EXCEEDED" in (reason or "")

    # Evaluating MSFT -> ALLOW
    allowed2, reason2 = governor.evaluate("MSFT", 500.0, 1000.0, MarketRegime.GREEN, "TECH", [pos])
    assert allowed2 is True


def test_sizing_adv_zero_or_negative_validation():
    """
    Verifies calculate_liquidity_cap rejects negative ADV.
    """
    with pytest.raises(ValueError, match="ADV50 cannot be negative"):
        calculate_liquidity_cap(-500.0)
