"""
Deterministic Synthetic Test Scenarios (Section 19)
Generates canonical 1-minute OHLCV bars across 10 specific test conditions.
"""

from datetime import datetime, timedelta
from typing import Dict, List
from bonde.data.models import Bar, NY_TZ


def generate_scenario_bars() -> Dict[str, List[Bar]]:
    """
    Generates deterministic bar series for each test scenario on 2026-01-05.
    """
    base_date = datetime(2026, 1, 5, 0, 0, 0, tzinfo=NY_TZ)
    scenarios = {}

    # Scenario 1: Valid ORB (09:30-09:34 range = 100.00 to 98.00 = 2.0% <= 4.0%; 09:36 triggers 100.01)
    bars_s1 = []
    # 09:30 to 09:34 opening range
    bars_s1.append(Bar(base_date.replace(hour=9, minute=30), "SCENARIO_1", 98.50, 99.50, 98.00, 99.00, 20_000))
    bars_s1.append(Bar(base_date.replace(hour=9, minute=31), "SCENARIO_1", 99.00, 99.80, 98.50, 99.30, 15_000))
    bars_s1.append(Bar(base_date.replace(hour=9, minute=32), "SCENARIO_1", 99.30, 99.90, 99.00, 99.50, 10_000))
    bars_s1.append(Bar(base_date.replace(hour=9, minute=33), "SCENARIO_1", 99.50, 100.00, 99.20, 99.80, 25_000))
    bars_s1.append(Bar(base_date.replace(hour=9, minute=34), "SCENARIO_1", 99.80, 99.95, 99.40, 99.90, 12_000))
    # 09:35 staging bar (ORH=100.00, ORL=98.00 -> Trigger=100.01, Stop=97.99)
    bars_s1.append(Bar(base_date.replace(hour=9, minute=35), "SCENARIO_1", 99.90, 99.95, 99.70, 99.80, 8_000))
    # 09:36 trigger bar: touches 100.05 within collar ($100.11) -> FILLS at 100.01
    bars_s1.append(Bar(base_date.replace(hour=9, minute=36), "SCENARIO_1", 99.85, 100.10, 99.80, 100.05, 30_000))
    # 09:37-09:40 drift up
    bars_s1.append(Bar(base_date.replace(hour=9, minute=37), "SCENARIO_1", 100.05, 100.50, 100.00, 100.40, 20_000))
    scenarios["valid_orb"] = bars_s1

    # Scenario 2: ORB Geometry > 4.0% (ORH = 100.00, ORL = 94.00 -> Range = 6.0% -> REJECT)
    bars_s2 = []
    bars_s2.append(Bar(base_date.replace(hour=9, minute=30), "SCENARIO_2", 98.00, 100.00, 95.00, 96.00, 50_000))
    bars_s2.append(Bar(base_date.replace(hour=9, minute=31), "SCENARIO_2", 96.00, 97.00, 94.00, 95.00, 40_000))
    bars_s2.append(Bar(base_date.replace(hour=9, minute=32), "SCENARIO_2", 95.00, 96.00, 94.50, 95.50, 20_000))
    bars_s2.append(Bar(base_date.replace(hour=9, minute=33), "SCENARIO_2", 95.50, 98.00, 95.00, 97.00, 30_000))
    bars_s2.append(Bar(base_date.replace(hour=9, minute=34), "SCENARIO_2", 97.00, 98.50, 96.50, 98.00, 25_000))
    bars_s2.append(Bar(base_date.replace(hour=9, minute=35), "SCENARIO_2", 98.00, 98.50, 97.50, 98.00, 15_000))
    scenarios["orb_geometry_fail"] = bars_s2

    # Scenario 3: Stop-Limit Collar Miss (09:36 opens above limit collar of $100.11 -> COLLAR_MISS)
    bars_s3 = []
    for b in bars_s1[:6]:
        bars_s3.append(Bar(b.timestamp, "SCENARIO_3", b.open, b.high, b.low, b.close, b.volume))
    # 09:36 opens at 100.35 (gapped past $100.11 limit)
    bars_s3.append(Bar(base_date.replace(hour=9, minute=36), "SCENARIO_3", 100.35, 100.60, 100.30, 100.50, 40_000))
    scenarios["collar_miss"] = bars_s3

    # Scenario 9: Stale Order 10:15 purge (ORB staged at 09:35, never touched by 10:15 -> CANCELLED)
    bars_s9 = []
    for b in bars_s1[:6]:
        bars_s9.append(Bar(b.timestamp, "SCENARIO_9", b.open, b.high, b.low, b.close, b.volume))
    # Fill intermediate minutes from 09:36 to 10:15 hovering below trigger ($100.01)
    for m in range(36, 60):
        bars_s9.append(Bar(base_date.replace(hour=9, minute=m), "SCENARIO_9", 99.00, 99.50, 98.80, 99.20, 5_000))
    for m in range(0, 16):
        bars_s9.append(Bar(base_date.replace(hour=10, minute=m), "SCENARIO_9", 99.10, 99.40, 98.90, 99.15, 5_000))
    scenarios["stale_order"] = bars_s9

    return scenarios
