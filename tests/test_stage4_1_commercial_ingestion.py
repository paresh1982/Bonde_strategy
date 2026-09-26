"""
Stage 4.1 Adversarial Test Suite: Commercial Historical Data Ingestion & Quality Validation.
Covers 15 rigorous adversarial scenarios specified in Stage 4.1 Part K:
1. Ticker recycling resolution (disjoint entities)
2. Delisted security resolution (fail-closed zero survivorship bias)
3. Corporate action ticker change (FB -> META)
4. Split adjustment and dual-price separation
5. Future-data contamination adversarial proof
6. Missing 1-minute bars classification (PASS, WARN, BLOCKER)
7. Duplicate intraday bars detection
8. Daylight Saving Time (DST) transition session alignment
9. Early-close session validation (13:00 ET close, 210 bars)
10. Catalyst timestamp leakage adversarial gate
11. Point-in-time float effective date enforcement
12. Point-in-time sector reclassification & fail-closed behavior
13. Breadth availability & ETF proxy rejection
14. Dataset checksum reproducibility
15. Formal gate DATA_BLOCKED_FOR_BASELINE_BACKTEST determination
"""

from datetime import date, datetime, time, timedelta, timezone
from pathlib import Path
import pytest
import zoneinfo

from bonde.data.catalysts import EarningsEvent, SECFilingEvent
from bonde.data.dual_price import DailyBar, InMemoryDailyBarProvider
from bonde.data.ingestion.breadth import BreadthValidationStatus, MarketBreadthValidator
from bonde.data.ingestion.catalysts import CommercialCatalystIngester
from bonde.data.ingestion.firstrate import FirstRateIntradayIngester, MissingBarSeverity
from bonde.data.ingestion.float_shares import FloatRecord, PointInTimeFloatProvider
from bonde.data.ingestion.inventory import VendorInventoryScanner
from bonde.data.ingestion.norgate import NorgateDailyIngester, NorgateSecurityMaster
from bonde.data.ingestion.quality_gate import BacktestGateStatus, Stage41DataQualityGate
from bonde.data.ingestion.sectors import CommercialSectorIngester
from bonde.data.intraday import IntradayBarRecord
from bonde.data.models import NY_TZ
from bonde.data.security_master import Security, SecurityHistoryRecord


# =====================================================================
# 1. TICKER RECYCLING RESOLUTION
# =====================================================================

def test_ticker_recycling_resolution():
    """Verifies that the same ticker symbol resolving to different companies in disjoint eras resolves correctly."""
    sec_old = Security(
        security_id="SEC_RECY_OLD",
        ticker="RECY",
        exchange="NYSE",
        name="Old Recycling Corp",
        first_trade_date=date(2010, 1, 1),
        last_trade_date=date(2019, 12, 31),
        delisting_date=date(2019, 12, 31),
        active_flag=False,
    )
    sec_new = Security(
        security_id="SEC_RECY_NEW",
        ticker="RECY",
        exchange="NASDAQ",
        name="New Renewable Energy Inc",
        first_trade_date=date(2020, 6, 1),
        last_trade_date=date(2026, 12, 31),
        active_flag=True,
    )
    hist_old = SecurityHistoryRecord(
        security_id="SEC_RECY_OLD",
        ticker="RECY",
        effective_from=date(2010, 1, 1),
        effective_to=date(2019, 12, 31),
    )
    hist_new = SecurityHistoryRecord(
        security_id="SEC_RECY_NEW",
        ticker="RECY",
        effective_from=date(2020, 6, 1),
        effective_to=None,
    )

    sm = NorgateSecurityMaster(securities=[sec_old, sec_new], history=[hist_old, hist_new])

    # Era 1: Old company
    assert sm.resolve_security_id("RECY", date(2015, 6, 1)) == "SEC_RECY_OLD"
    # Era 2: Gap between listings -> must fail closed (None)
    assert sm.resolve_security_id("RECY", date(2020, 2, 1)) is None
    # Era 3: New company
    assert sm.resolve_security_id("RECY", date(2021, 6, 1)) == "SEC_RECY_NEW"


# =====================================================================
# 2. DELISTED SECURITY RESOLUTION (SURVIVORSHIP-BIAS-FREE)
# =====================================================================

def test_delisted_security_fails_closed():
    """Verifies that queries for a security after its delisting date fail closed to prevent survivorship bias."""
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
    hist_sivb = SecurityHistoryRecord(
        security_id="SEC_SIVB",
        ticker="SIVB",
        effective_from=date(1987, 10, 1),
        effective_to=date(2023, 3, 10),
    )

    sm = NorgateSecurityMaster(securities=[sec_sivb], history=[hist_sivb])

    # Active date: resolves
    assert sm.resolve_security_id("SIVB", date(2023, 3, 10)) == "SEC_SIVB"
    # Delisted date: fails closed (zero survivorship bias)
    assert sm.resolve_security_id("SIVB", date(2023, 3, 11)) is None
    assert sm.resolve_security_id("SIVB", date(2023, 6, 1)) is None


# =====================================================================
# 3. CORPORATE ACTION TICKER CHANGE (FB -> META)
# =====================================================================

def test_corporate_action_ticker_change():
    """Verifies that point-in-time ticker resolution maps corporate symbol renames accurately without lookahead."""
    sec_meta = Security(
        security_id="SEC_META",
        ticker="META",
        exchange="NASDAQ",
        name="Meta Platforms Inc.",
        first_trade_date=date(2012, 5, 18),
        last_trade_date=date(2026, 12, 31),
        active_flag=True,
    )
    hist_fb = SecurityHistoryRecord(
        security_id="SEC_META",
        ticker="FB",
        effective_from=date(2012, 5, 18),
        effective_to=date(2022, 6, 8),
    )
    hist_meta = SecurityHistoryRecord(
        security_id="SEC_META",
        ticker="META",
        effective_from=date(2022, 6, 9),
        effective_to=None,
    )

    sm = NorgateSecurityMaster(securities=[sec_meta], history=[hist_fb, hist_meta])

    # Under old ticker FB
    assert sm.resolve_security_id("FB", date(2021, 1, 15)) == "SEC_META"
    assert sm.resolve_security_id("META", date(2021, 1, 15)) is None  # META did not exist yet!

    # Under new ticker META
    assert sm.resolve_security_id("META", date(2023, 1, 15)) == "SEC_META"
    assert sm.resolve_security_id("FB", date(2023, 1, 15)) is None  # FB is no longer active


# =====================================================================
# 4. SPLIT ADJUSTMENT & DUAL-PRICE SEPARATION
# =====================================================================

def test_split_adjustment_and_dual_price_separation():
    """Verifies that unadjusted prices reflect real execution dollars and adjusted prices reflect split factors."""
    # Simulating a 4:1 stock split
    bar_pre_split = DailyBar(
        security_id="SEC_AAPL",
        session_date=date(2020, 8, 28),
        open=500.0,
        high=505.0,
        low=495.0,
        close=500.0,
        volume=10_000_000.0,
        adjusted_open=125.0,
        adjusted_high=126.25,
        adjusted_low=123.75,
        adjusted_close=125.0,
        adjusted_volume=40_000_000.0,
        source="NORGATE",
        strict_validation=True,
    )

    assert bar_pre_split.execution_close == 500.0
    assert bar_pre_split.analytical_close == 125.0

    # Validation summary check
    summary = NorgateDailyIngester.validate_bars([bar_pre_split])
    assert summary.is_valid is True
    assert summary.ohlc_violations == 0
    assert summary.negative_prices == 0


# =====================================================================
# 5. FUTURE-DATA CONTAMINATION ADVERSARIAL PROOF
# =====================================================================

def test_future_data_contamination_adversarial_proof():
    """Adversarial proof: Mutating session t or injecting future data produces 0.000000 indicator change."""
    bars = []
    base_d = date(2023, 1, 1)
    for i in range(70):
        d = date.fromordinal(base_d.toordinal() + i)
        bars.append(
            DailyBar(
                security_id="SEC_PROOF",
                session_date=d,
                open=100.0,
                high=105.0,
                low=95.0,
                close=100.0,
                volume=1_000_000.0,
                adjusted_open=100.0,
                adjusted_high=105.0,
                adjusted_low=95.0,
                adjusted_close=100.0,
                adjusted_volume=1_000_000.0,
            )
        )
    provider = InMemoryDailyBarProvider(bars)
    eval_date = bars[-1].session_date

    # Corrupt bar to inject at session t (eval_date)
    corrupted_bar = DailyBar(
        security_id="SEC_PROOF",
        session_date=eval_date,
        open=9999.0,
        high=99999.0,
        low=1.0,
        close=88888.0,
        volume=999_999_999.0,
        adjusted_open=9999.0,
        adjusted_high=99999.0,
        adjusted_low=1.0,
        adjusted_close=88888.0,
        adjusted_volume=999_999_999.0,
    )

    is_uncontaminated = NorgateDailyIngester.verify_indicator_anti_leakage(
        provider=provider,
        security_id="SEC_PROOF",
        evaluation_date=eval_date,
        corrupted_session_bar=corrupted_bar,
    )
    assert is_uncontaminated is True


# =====================================================================
# 6. MISSING 1-MINUTE BARS CLASSIFICATION (PASS, WARN, BLOCKER)
# =====================================================================

def test_missing_1minute_bars_classification():
    """Verifies that missing 1m bars are classified strictly into PASS, WARN, and BLOCKER."""
    session_d = date(2023, 5, 10)
    base_dt = datetime.combine(session_d, time(9, 30, 0), tzinfo=NY_TZ)

    # 1. Full 390 bars -> PASS
    full_bars = []
    for m in range(390):
        t = base_dt + timedelta(minutes=m)
        full_bars.append(
            IntradayBarRecord(
                security_id="SEC_TEST",
                symbol="TEST",
                timestamp_utc=t.astimezone(timezone.utc),
                open=100.0,
                high=101.0,
                low=99.0,
                close=100.5,
                volume=1000.0,
            )
        )

    res_pass = FirstRateIntradayIngester.validate_session_bars(full_bars, session_d)
    assert res_pass.severity == MissingBarSeverity.PASS
    assert res_pass.can_simulate_execution is True

    # 2. 2 non-critical bars missing at 14:15 -> WARN
    warn_bars = [b for b in full_bars if b.timestamp_utc.astimezone(NY_TZ).time() not in (time(14, 15), time(14, 16))]
    res_warn = FirstRateIntradayIngester.validate_session_bars(warn_bars, session_d, has_active_order_or_candidate=False)
    assert res_warn.severity == MissingBarSeverity.WARN
    assert res_warn.can_simulate_execution is True

    # 3. Missing bar in ORB window (09:32) with candidate -> BLOCKER
    blocker_orb_bars = [b for b in full_bars if b.timestamp_utc.astimezone(NY_TZ).time() != time(9, 32)]
    res_blocker = FirstRateIntradayIngester.validate_session_bars(blocker_orb_bars, session_d, has_active_order_or_candidate=True)
    assert res_blocker.severity == MissingBarSeverity.BLOCKER
    assert res_blocker.can_simulate_execution is False

    # 4. Zero bars -> BLOCKER
    res_empty = FirstRateIntradayIngester.validate_session_bars([], session_d)
    assert res_empty.severity == MissingBarSeverity.BLOCKER
    assert res_empty.can_simulate_execution is False


# =====================================================================
# 7. DUPLICATE INTRADAY BARS DETECTION
# =====================================================================

def test_duplicate_intraday_bars_detection():
    """Verifies that duplicate 1m timestamps trigger a BLOCKER severity and halt execution."""
    session_d = date(2023, 5, 10)
    base_dt = datetime.combine(session_d, time(9, 30, 0), tzinfo=NY_TZ)

    bars = [
        IntradayBarRecord(
            security_id="SEC_TEST",
            symbol="TEST",
            timestamp_utc=base_dt.astimezone(timezone.utc),
            open=100.0,
            high=101.0,
            low=99.0,
            close=100.0,
            volume=500.0,
        ),
        # Duplicate timestamp
        IntradayBarRecord(
            security_id="SEC_TEST",
            symbol="TEST",
            timestamp_utc=base_dt.astimezone(timezone.utc),
            open=100.5,
            high=102.0,
            low=99.5,
            close=101.0,
            volume=600.0,
        ),
    ]

    res = FirstRateIntradayIngester.validate_session_bars(bars, session_d)
    assert res.duplicate_timestamps == 1
    assert res.severity == MissingBarSeverity.BLOCKER
    assert res.can_simulate_execution is False


# =====================================================================
# 8. DAYLIGHT SAVING TIME (DST) TRANSITION SESSION ALIGNMENT
# =====================================================================

def test_dst_transition_session_alignment():
    """Verifies that EDT and EST transitions preserve exact 09:30:00 America/New_York market open."""
    # Summer (EDT, UTC-4): 2023-06-15
    summer_open_ny = datetime(2023, 6, 15, 9, 30, 0, tzinfo=NY_TZ)
    summer_open_utc = summer_open_ny.astimezone(timezone.utc)
    assert summer_open_utc.hour == 13
    assert summer_open_utc.minute == 30

    # Winter (EST, UTC-5): 2023-01-15
    winter_open_ny = datetime(2023, 1, 15, 9, 30, 0, tzinfo=NY_TZ)
    winter_open_utc = winter_open_ny.astimezone(timezone.utc)
    assert winter_open_utc.hour == 14
    assert winter_open_utc.minute == 30


# =====================================================================
# 9. EARLY-CLOSE SESSION VALIDATION (13:00 ET CLOSE, 210 BARS)
# =====================================================================

def test_early_close_session_validation():
    """Verifies that an early close day (e.g. Day after Thanksgiving) expects 210 bars and passes validation."""
    early_d = date(2023, 11, 24)  # Day after Thanksgiving
    assert FirstRateIntradayIngester.is_early_close_session(early_d) is True
    assert FirstRateIntradayIngester.get_expected_bar_count(early_d) == 210

    base_dt = datetime.combine(early_d, time(9, 30, 0), tzinfo=NY_TZ)
    bars = []
    for m in range(210):
        t = base_dt + timedelta(minutes=m)
        bars.append(
            IntradayBarRecord(
                security_id="SEC_TEST",
                symbol="TEST",
                timestamp_utc=t.astimezone(timezone.utc),
                open=100.0,
                high=101.0,
                low=99.0,
                close=100.0,
                volume=100.0,
            )
        )

    res = FirstRateIntradayIngester.validate_session_bars(bars, early_d)
    assert res.is_early_close is True
    assert res.total_bars == 210
    assert res.missing_bars == 0
    assert res.severity == MissingBarSeverity.PASS
    assert res.can_simulate_execution is True


# =====================================================================
# 10. CATALYST TIMESTAMP LEAKAGE ADVERSARIAL GATE
# =====================================================================

def test_catalyst_timestamp_leakage_adversarial_gate():
    """Adversarial check: Catalyst releases occurring at or after 09:30:00 ET are rejected from session t pre-market."""
    session_d = date(2023, 6, 15)

    # Valid BMO earnings (07:00 ET)
    valid_earn = EarningsEvent(
        security_id="SEC_VALID",
        event_timestamp=datetime(2023, 6, 15, 7, 0, 0, tzinfo=NY_TZ),
        event_date=session_d,
        timing="BMO",
        source="ZACKS",
        availability_timestamp=datetime(2023, 6, 15, 7, 0, 0, tzinfo=NY_TZ),
    )

    # Leaked earnings (released at 09:31 ET on session date)
    leaked_earn = EarningsEvent(
        security_id="SEC_LEAKED",
        event_timestamp=datetime(2023, 6, 15, 9, 31, 0, tzinfo=NY_TZ),
        event_date=session_d,
        timing="BMO",
        source="ZACKS",
        availability_timestamp=datetime(2023, 6, 15, 9, 31, 0, tzinfo=NY_TZ),
    )

    # Leaked SEC 8-K (accepted at 09:30:15 ET)
    leaked_8k = SECFilingEvent(
        security_id="SEC_LEAKED",
        cik="0001234567",
        accession_number="0001234567-23-000001",
        filing_type="8-K",
        filing_timestamp=datetime(2023, 6, 15, 9, 30, 15, tzinfo=NY_TZ),
        acceptance_datetime=datetime(2023, 6, 15, 9, 30, 15, tzinfo=NY_TZ),
        form="8-K",
        items=["Item 1.01"],
        source_url="https://sec.gov",
        availability_timestamp=datetime(2023, 6, 15, 9, 30, 15, tzinfo=NY_TZ),
    )

    summary = CommercialCatalystIngester.validate_premarket_eligibility(
        earnings=[valid_earn, leaked_earn],
        sec_8ks=[leaked_8k],
        session_date=session_d,
    )

    assert summary.valid_earnings == 1
    assert summary.leaked_earnings == 1
    assert summary.leaked_sec_8k == 1
    assert summary.is_valid is False


# =====================================================================
# 11. POINT-IN-TIME FLOAT EFFECTIVE DATE ENFORCEMENT
# =====================================================================

def test_point_in_time_float_effective_date_enforcement():
    """Verifies that point-in-time float returns only records filed prior to as_of_date and fails closed if missing."""
    rec_q1 = FloatRecord(
        security_id="SEC_TEST",
        effective_date=date(2021, 5, 1),
        shares_outstanding=35_000_000,
        free_float_shares=30_000_000,
        filing_acceptance_datetime=datetime(2021, 5, 1, 16, 30, 0, tzinfo=NY_TZ),
    )
    rec_q2 = FloatRecord(
        security_id="SEC_TEST",
        effective_date=date(2021, 8, 5),
        shares_outstanding=70_000_000,
        free_float_shares=65_000_000,
        filing_acceptance_datetime=datetime(2021, 8, 5, 16, 30, 0, tzinfo=NY_TZ),
    )

    provider = PointInTimeFloatProvider(records=[rec_q1, rec_q2])

    # Before Q1 filing: fails closed (None)
    assert provider.get_free_float("SEC_TEST", date(2021, 4, 30)) is None

    # Between Q1 and Q2 filing: returns Q1 float (30M)
    assert provider.get_free_float("SEC_TEST", date(2021, 6, 1)) == 30_000_000

    # After Q2 filing: returns Q2 float (65M)
    assert provider.get_free_float("SEC_TEST", date(2021, 8, 10)) == 65_000_000


# =====================================================================
# 12. POINT-IN-TIME SECTOR RECLASSIFICATION & FAIL-CLOSED BEHAVIOR
# =====================================================================

def test_point_in_time_sector_reclassification_and_fail_closed():
    """Verifies that historical sector queries obey effective date windows and fail closed on unmapped names."""
    from bonde.data.sectors import HistoricalSectorRecord

    rec1 = HistoricalSectorRecord(
        security_id="SEC_RECLASS",
        sector="TECHNOLOGY",
        industry_group="Software",
        effective_from=date(2010, 1, 1),
        effective_to=date(2018, 9, 20),
    )
    rec2 = HistoricalSectorRecord(
        security_id="SEC_RECLASS",
        sector="COMMUNICATION",
        industry_group="Interactive Media",
        effective_from=date(2018, 9, 21),
        effective_to=None,
    )

    provider = CommercialSectorIngester.create_provider([rec1, rec2])

    # Old classification
    assert provider.get_sector("SEC_RECLASS", datetime(2015, 5, 1, 10, 0, tzinfo=NY_TZ)) == "TECHNOLOGY"
    # New classification
    assert provider.get_sector("SEC_RECLASS", datetime(2020, 5, 1, 10, 0, tzinfo=NY_TZ)) == "COMMUNICATION"
    # Unmapped security: fails closed (None)
    assert provider.get_sector("SEC_UNMAPPED", datetime(2020, 5, 1, 10, 0, tzinfo=NY_TZ)) is None


# =====================================================================
# 13. BREADTH AVAILABILITY & ETF PROXY REJECTION
# =====================================================================

def test_breadth_availability_and_proxy_rejection(tmp_path):
    """Verifies that single-ticker ETF proxies are strictly rejected in favor of cross-sectional breadth."""
    # 1. Test missing file
    res_missing = MarketBreadthValidator.validate_breadth_dataset(tmp_path / "non_existent.csv")
    assert res_missing.is_blocked is True
    assert res_missing.status == BreadthValidationStatus.MISSING_BREADTH_BLOCKED

    # 2. Test ETF proxy CSV
    proxy_csv = tmp_path / "spy_proxy.csv"
    proxy_csv.write_text("Date,symbol,close,volume\n2023-01-03,SPY,380.0,50000000\n", encoding="utf-8")
    res_proxy = MarketBreadthValidator.validate_breadth_dataset(proxy_csv)
    assert res_proxy.is_blocked is True
    assert res_proxy.status == BreadthValidationStatus.PROXY_SUBSTITUTE_BLOCKED

    # 3. Test genuine cross-sectional breadth CSV
    genuine_csv = tmp_path / "genuine_breadth.csv"
    genuine_csv.write_text("session_date,universe_size,gainers_4pct_count,losers_4pct_count,t2108_percent\n2023-01-03,6500,320,110,55.4\n", encoding="utf-8")
    res_genuine = MarketBreadthValidator.validate_breadth_dataset(genuine_csv)
    assert res_genuine.is_blocked is False
    assert res_genuine.status == BreadthValidationStatus.VALID_CROSS_SECTIONAL


# =====================================================================
# 14. DATASET CHECKSUM REPRODUCIBILITY
# =====================================================================

def test_dataset_checksum_reproducibility():
    """Verifies that SHA-256 calculation on raw datasets is deterministic and reproducible."""
    scanner = VendorInventoryScanner(data_roots=[Path("data/stage1d/raw")])
    entries = scanner.scan_all()
    assert len(entries) > 0

    # Pick first entry and recompute hash directly
    first = entries[0]
    recomputed_hash = VendorInventoryScanner.compute_sha256(Path(first.filepath))
    assert first.sha256 == recomputed_hash


# =====================================================================
# 15. FORMAL GATE DATA_BLOCKED_FOR_BASELINE_BACKTEST DETERMINATION
# =====================================================================

def test_formal_gate_reports_data_blocked_status():
    """Verifies that the Stage 4.1 Data Quality Gate formally returns DATA_BLOCKED_FOR_BASELINE_BACKTEST."""
    gate = Stage41DataQualityGate(data_root=Path("data"))
    report = gate.run_audit()

    assert report.gate_status == BacktestGateStatus.DATA_BLOCKED_FOR_BASELINE_BACKTEST
    assert report.blocker_count > 0
    assert any("Historical 1-Minute Intraday Coverage" in b for b in report.blockers)
    assert any("Security Master Commercial Universe Coverage" in b for b in report.blockers)
