"""
Dedicated Unit Test for Same-Bar Target + Stop Collision (D2, Section 14)
MANDATORY DETERMINISTIC INVARIANT:
If both target and stop are reached within the same bar, STOP IS ASSUMED TO OCCUR FIRST.
"""

from datetime import datetime
from bonde.data.models import Bar, NY_TZ
from bonde.execution.simulator import ExecutionSimulator


def test_same_bar_stop_precedence():
    """Test 4: Same bar contains low <= stop AND high >= target -> STOP FIRST."""
    simulator = ExecutionSimulator()

    # Entry = $30.00, Stop = $29.00, +2.0R Target = $32.00
    current_stop = 29.00
    partial_target = 32.00

    # Bar that trades between $28.50 and $32.50 (breaching BOTH stop and target)
    bar = Bar(
        timestamp=datetime(2026, 1, 5, 11, 0, 0, tzinfo=NY_TZ),
        symbol="COLLISION_TEST",
        open=30.00,
        high=32.50,  # Crosses $32.00 target
        low=28.50,   # Crosses $29.00 stop
        close=31.00,
        volume=200_000.0,
    )

    exit_type, exit_price, is_same_bar = simulator.evaluate_position_exits(
        current_stop=current_stop,
        partial_target=partial_target,
        bar=bar,
        has_partial_filled=False,
    )

    # Invariant: STOP FIRST
    assert exit_type == "STOP"
    assert is_same_bar is True
    assert exit_price == 29.00  # Stopped out, target ignored


def test_target_only_fill():
    """Bar touches target only -> TARGET filled."""
    simulator = ExecutionSimulator()

    current_stop = 29.00
    partial_target = 32.00

    bar = Bar(
        timestamp=datetime(2026, 1, 5, 11, 0, 0, tzinfo=NY_TZ),
        symbol="TARGET_TEST",
        open=30.50,
        high=32.20,  # Crosses target
        low=30.20,   # Stays well above stop
        close=32.10,
        volume=50_000.0,
    )

    exit_type, exit_price, is_same_bar = simulator.evaluate_position_exits(
        current_stop=current_stop,
        partial_target=partial_target,
        bar=bar,
        has_partial_filled=False,
    )

    assert exit_type == "TARGET"
    assert is_same_bar is False
    assert exit_price == 32.00


def test_stop_only_fill():
    """Bar touches stop only -> STOP filled."""
    simulator = ExecutionSimulator()

    current_stop = 29.00
    partial_target = 32.00

    bar = Bar(
        timestamp=datetime(2026, 1, 5, 11, 0, 0, tzinfo=NY_TZ),
        symbol="STOP_TEST",
        open=29.50,
        high=29.80,  # Below target
        low=28.90,   # Crosses stop
        close=29.10,
        volume=50_000.0,
    )

    exit_type, exit_price, is_same_bar = simulator.evaluate_position_exits(
        current_stop=current_stop,
        partial_target=partial_target,
        bar=bar,
        has_partial_filled=False,
    )

    assert exit_type == "STOP"
    assert is_same_bar is False
    assert exit_price == 29.00
