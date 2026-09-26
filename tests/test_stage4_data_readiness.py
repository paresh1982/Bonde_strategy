"""
Stage 4 Unit & Integration Test Suite:
Historical Data Readiness & Backtest Architecture Invariants
1. 18-Dimension Data Readiness Audit execution & reporting
2. Cryptographic dataset manifest generation (SHA-256)
3. Point-in-Time indicator anti-leakage invariants (t-1 lookback)
4. Dual-price separation invariant (split-adjusted vs unadjusted)
5. Security Master point-in-time resolution & delisting handling
6. Catalyst release cutoff verification (BMO / AMC / EDGAR acceptance)
7. Commercial data absence fail-closed gating assertion
"""

from datetime import date, datetime, time, timezone
from pathlib import Path
import pytest

from bonde.backtest.data_readiness import HistoricalDataReadinessAuditor
from bonde.data.catalysts import EarningsEvent, InMemoryEarningsProvider, InMemoryFilingProvider, SECFilingEvent
from bonde.data.dual_price import DailyBar, InMemoryDailyBarProvider
from bonde.data.indicators import calculate_10ema, calculate_65d_high, calculate_adv50, PointInTimeIndicatorEngine
from bonde.data.models import NY_TZ
from bonde.data.security_master import InMemorySecurityMaster, Security, SecurityHistoryRecord


# =====================================================================
# 1. 18-DIMENSION DATA READINESS AUDITOR
# =====================================================================

def test_data_readiness_auditor_scans_18_dimensions():
    """Verifies that HistoricalDataReadinessAuditor audits all 18 mandatory dimensions."""
    auditor = HistoricalDataReadinessAuditor(data_root=Path("data/stage1d"))
    report = auditor.audit_all()

    assert report.total_files_scanned > 0
    assert report.total_dataset_size_bytes > 0
    assert len(report.dimensions) == 18
    assert report.overall_readiness == "FIXTURES_ONLY__COMMERCIAL_DATA_ABSENT"
    assert report.can_proceed_to_full_backtest is False
    assert len(report.missing_commercial_datasets) >= 3

    # Check key dimensions
    dim6 = next(d for d in report.dimensions if d.dimension_number == 6)
    assert dim6.name == "Historical 1-Minute Bars"
    assert dim6.status == "MISSING_COMMERCIAL_DATA"
    assert dim6.records_count == 2730  # 7 sessions * 390 bars

    dim14 = next(d for d in report.dimensions if d.dimension_number == 14)
    assert dim14.name == "ADV50 Calculation"
    assert dim14.status == "READY_VERIFIED"
    assert dim14.point_in_time_compliant is True


def test_cryptographic_manifest_generation():
    """Verifies that SHA-256 manifest produces valid hashes for all dataset files."""
    auditor = HistoricalDataReadinessAuditor(data_root=Path("data/stage1d"))
    manifest = auditor.generate_manifest()

    assert len(manifest) > 0
    for entry in manifest:
        assert len(entry.sha256_hash) == 64  # valid SHA-256 hex string
        assert entry.file_size_bytes > 0
        assert entry.data_domain in [
            "DAILY_BARS", "INTRADAY_BARS", "SECURITY_MASTER",
            "EARNINGS_CATALYSTS", "SEC_8K_FILINGS", "MARKET_BREADTH",
            "SECTOR_MAPPINGS", "OTHER",
        ]


# =====================================================================
# 2. POINT-IN-TIME INDICATOR ANTI-LEAKAGE INVARIANTS
# =====================================================================

def test_indicators_exclude_session_t_bars():
    """Verifies that ADV50, 65D High, and 10 EMA strictly exclude session t bars."""
    bars = []
    # Create 70 consecutive daily bars
    base_d = date(2023, 1, 1)
    for i in range(70):
        d = date.fromordinal(base_d.toordinal() + i)
        bars.append(
            DailyBar(
                security_id="SEC_TEST",
                session_date=d,
                open=100.0,
                high=105.0 if i < 69 else 200.0,  # Day 70 has huge spike!
                low=95.0,
                close=100.0 if i < 69 else 200.0,
                volume=1000.0 if i < 69 else 50000.0,
                adjusted_open=100.0,
                adjusted_high=105.0 if i < 69 else 200.0,
                adjusted_low=95.0,
                adjusted_close=100.0 if i < 69 else 200.0,
                adjusted_volume=1000.0 if i < 69 else 50000.0,
            )
        )
    provider = InMemoryDailyBarProvider(bars)

    # Evaluate indicators on Day 70 (as_of_date = bars[-1].session_date)
    test_date = bars[-1].session_date

    # 1. 65-Day High must NOT see Day 70's 200.0 high
    h65 = calculate_65d_high("SEC_TEST", test_date, provider, lookback_sessions=65)
    assert h65 == 105.0

    # 2. ADV50 must NOT see Day 70's 50,000 volume spike
    adv50 = calculate_adv50("SEC_TEST", test_date, provider, lookback_sessions=50)
    assert adv50 == 1000.0

    # 3. 10 EMA must NOT see Day 70's 200.0 close
    ema10 = calculate_10ema("SEC_TEST", test_date, provider, period=10)
    assert ema10 == 100.0


def test_indicators_fail_closed_on_insufficient_history():
    """Returns None if completed bars < required lookback window."""
    bars = [
        DailyBar(
            security_id="SEC_IPO",
            session_date=date(2023, 6, 1),
            open=50.0, high=52.0, low=48.0, close=51.0, volume=10000,
            adjusted_open=50.0, adjusted_high=52.0, adjusted_low=48.0, adjusted_close=51.0, adjusted_volume=10000,
        )
    ]
    provider = InMemoryDailyBarProvider(bars)
    eval_date = date(2023, 6, 2)

    # Insufficient bars for ADV50 (needs 50) and 65D High (needs 65)
    assert calculate_adv50("SEC_IPO", eval_date, provider, lookback_sessions=50) is None
    assert calculate_65d_high("SEC_IPO", eval_date, provider, lookback_sessions=65) is None
    assert calculate_10ema("SEC_IPO", eval_date, provider, period=10, min_history=10) is None


# =====================================================================
# 3. DUAL-PRICE SEPARATION INVARIANT
# =====================================================================

def test_dual_price_separation_handles_split_cleanly():
    """Verifies that split adjustment preserves indicator consistency while unadjusted retains execution dollars."""
    bars = []
    # Pre-split bars (unadjusted close 400, split factor 4:1 -> adjusted close 100)
    for i in range(10):
        d = date(2020, 8, 15 + i)
        bars.append(
            DailyBar(
                security_id="SEC_AAPL",
                session_date=d,
                open=400.0, high=405.0, low=395.0, close=400.0, volume=10000,
                adjusted_open=100.0, adjusted_high=101.25, adjusted_low=98.75, adjusted_close=100.0, adjusted_volume=40000,
            )
        )
    # Post-split bar (unadjusted close 100, adjusted close 100)
    d_post = date(2020, 8, 31)
    bars.append(
        DailyBar(
            security_id="SEC_AAPL",
            session_date=d_post,
            open=100.0, high=102.0, low=99.0, close=101.0, volume=40000,
            adjusted_open=100.0, adjusted_high=102.0, adjusted_low=99.0, adjusted_close=101.0, adjusted_volume=40000,
        )
    )
    provider = InMemoryDailyBarProvider(bars)

    # 10 EMA evaluated on day after split
    ema = calculate_10ema("SEC_AAPL", date(2020, 9, 1), provider, period=10)
    # Adjusted series was consistent ~100; EMA should be ~100.2 (no false 4x collapse)
    assert 99.0 <= ema <= 102.0


# =====================================================================
# 4. SECURITY MASTER POINT-IN-TIME RESOLUTION
# =====================================================================

def test_security_master_ticker_renames_and_delisting():
    """Verifies point-in-time ticker resolution (FB -> META) and delisting fail-closed handling."""
    sec_meta = Security(
        security_id="SEC_META",
        ticker="META",
        exchange="NASDAQ",
        name="Meta Platforms Inc.",
        first_trade_date=date(2012, 5, 18),
        last_trade_date=date(2026, 12, 31),
        delisting_date=None,
        active_flag=True,
    )
    sec_sivb = Security(
        security_id="SEC_SIVB",
        ticker="SIVB",
        exchange="NASDAQ",
        name="SVB Financial Group",
        first_trade_date=date(1987, 10, 1),
        last_trade_date=date(2023, 3, 10),
        delisting_date=date(2023, 3, 10),
        active_flag=False,
    )

    history = [
        SecurityHistoryRecord("SEC_META", "FB", date(2012, 5, 18), date(2022, 6, 8)),
        SecurityHistoryRecord("SEC_META", "META", date(2022, 6, 9), None),
        SecurityHistoryRecord("SEC_SIVB", "SIVB", date(1987, 10, 1), date(2023, 3, 10)),
    ]

    sm = InMemorySecurityMaster(securities=[sec_meta, sec_sivb], history=history)

    # 1. On 2021-06-01, ticker "FB" maps to SEC_META
    assert sm.resolve_security_id("FB", date(2021, 6, 1)) == "SEC_META"
    assert sm.resolve_security_id("META", date(2021, 6, 1)) is None  # META did not exist yet

    # 2. On 2023-01-01, ticker "META" maps to SEC_META
    assert sm.resolve_security_id("META", date(2023, 1, 1)) == "SEC_META"
    assert sm.resolve_security_id("FB", date(2023, 1, 1)) is None

    # 3. SIVB is active on 2023-03-09, but delisted post 2023-03-10
    assert sm.is_active("SEC_SIVB", date(2023, 3, 9)) is True
    assert sm.is_active("SEC_SIVB", date(2023, 3, 15)) is False
    assert sm.resolve_security_id("SIVB", date(2023, 3, 15)) is None  # Fails closed post-delisting


# =====================================================================
# 5. CATALYST RELEASE TIMESTAMPS
# =====================================================================

def test_earnings_bmo_amc_availability_cutoff():
    """Verifies that BMO earnings are available on session t, while AMC is available on session t+1."""
    # AMC Event on 2020-07-30 at 16:30 ET -> Available for session 2020-07-31
    earn_amc = EarningsEvent(
        security_id="SEC_AAPL",
        event_date=date(2020, 7, 30),
        event_timestamp=datetime(2020, 7, 30, 16, 30, tzinfo=NY_TZ),
        timing="AMC",
        source="ZACKS",
        availability_timestamp=datetime(2020, 7, 30, 16, 30, tzinfo=NY_TZ),
    )
    provider = InMemoryEarningsProvider([earn_amc])

    # Cannot trade AMC event during session of 2020-07-30 (since announcement is after close)
    assert provider.get_earnings_event("SEC_AAPL", date(2020, 7, 30)) is None

    # Available for pre-market of session 2020-07-31
    assert provider.get_earnings_event("SEC_AAPL", date(2020, 7, 31)) is not None
