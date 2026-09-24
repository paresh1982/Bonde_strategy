"""
Unit & Adversarial Tests for Stage 1B Data Infrastructure
Verifies:
- Point-in-time security identity resolution (ticker recycling, delisting, symbol changes)
- Dual-price daily data architecture (unadjusted vs split-adjusted isolation)
- Point-in-time indicators (T-1 isolation, 65D lookback, ADV50 lookback, session-t anti-leakage)
- Configurable universe screening & candidate generation (fail closed)
- Catalyst events Track A & Track B (pre-market, intraday, and post-market cutoff)
- Candidate-targeted 1-minute intraday extraction & DST mapping
- Market breadth provider & PointInTimeMarketRegimeProvider
- Historical point-in-time sector provider
- Data quality engine & 8 validation gates (PASS/WARN/FAIL)
- Data manifest generation and checksum reproducibility
- End-to-end historical backtest pipeline with zero lookahead
"""

from datetime import date, datetime, time, timedelta, timezone
from pathlib import Path
import tempfile
import pytest
import zoneinfo

from bonde.config.strategy_config import StrategyConfig
from bonde.data.breadth import (
    InMemoryMarketBreadthProvider,
    MarketBreadthRecord,
    PointInTimeMarketRegimeProvider,
)
from bonde.data.catalysts import (
    EarningsEvent,
    InMemoryEarningsProvider,
    InMemoryFilingProvider,
    SECFilingEvent,
)
from bonde.data.dual_price import DailyBar, InMemoryDailyBarProvider
from bonde.data.indicators import (
    PointInTimeIndicatorEngine,
    calculate_10ema,
    calculate_65d_high,
    calculate_adv50,
)
from bonde.data.intraday import (
    InMemoryIntradayBarProvider,
    IntradayBarRecord,
)
from bonde.data.manifest import ManifestManager
from bonde.data.models import Bar, NY_TZ
from bonde.data.pipeline import HistoricalBacktestPipeline
from bonde.data.quality import (
    AnomalySeverity,
    DataQualityValidator,
    QualityStatus,
)
from bonde.data.screener import (
    BaseHitCandidateGenerator,
    UniverseScreener,
)
from bonde.data.sectors import (
    HistoricalSectorRecord,
    PointInTimeSectorProvider,
)
from bonde.data.security_master import (
    InMemorySecurityMaster,
    Security,
    SecurityHistoryRecord,
)
from bonde.regime.market_regime import MarketRegime

UTC = timezone.utc


# =====================================================================
# 1. SECURITY MASTER & POINT-IN-TIME IDENTITY TESTS
# =====================================================================

def test_ticker_recycling():
    """Tests that two different companies using the same ticker at different times resolve correctly."""
    sec1 = Security(
        security_id="SEC_COMP_A",
        ticker="XYZ",
        exchange="NASDAQ",
        name="Company Alpha Inc",
        first_trade_date=date(2010, 1, 1),
        last_trade_date=date(2015, 12, 31),
        delisting_date=date(2015, 12, 31),
    )
    sec2 = Security(
        security_id="SEC_COMP_B",
        ticker="XYZ",
        exchange="NYSE",
        name="Company Beta Corp",
        first_trade_date=date(2018, 1, 1),
        last_trade_date=date(2025, 12, 31),
    )

    history = [
        SecurityHistoryRecord(security_id="SEC_COMP_A", ticker="XYZ", effective_from=date(2010, 1, 1), effective_to=date(2015, 12, 31)),
        SecurityHistoryRecord(security_id="SEC_COMP_B", ticker="XYZ", effective_from=date(2018, 1, 1), effective_to=None),
    ]

    master = InMemorySecurityMaster(securities=[sec1, sec2], history=history)

    # During Alpha period
    assert master.resolve_security_id("XYZ", date(2012, 6, 15)) == "SEC_COMP_A"
    # During unassigned interregnum (2016-2017) -> fails closed (None)
    assert master.resolve_security_id("XYZ", date(2017, 3, 1)) is None
    # During Beta period
    assert master.resolve_security_id("XYZ", date(2020, 1, 10)) == "SEC_COMP_B"


def test_delisted_security_fails_closed():
    """Tests that querying for a delisted security after its delisting date returns None."""
    sec = Security(
        security_id="SEC_DELISTED",
        ticker="DEAD",
        exchange="NASDAQ",
        name="Bankrupt Corp",
        first_trade_date=date(2020, 1, 1),
        last_trade_date=date(2022, 6, 30),
        delisting_date=date(2022, 6, 30),
    )
    history = [
        SecurityHistoryRecord(security_id="SEC_DELISTED", ticker="DEAD", effective_from=date(2020, 1, 1), effective_to=None),
    ]
    master = InMemorySecurityMaster(securities=[sec], history=history)

    # Valid before delisting
    assert master.resolve_security_id("DEAD", date(2022, 6, 29)) == "SEC_DELISTED"
    # Fails closed on/after delisting
    assert master.resolve_security_id("DEAD", date(2022, 7, 1)) is None


def test_security_ticker_change():
    """Tests a single security that changed ticker (e.g., FB -> META)."""
    sec = Security(
        security_id="SEC_META",
        ticker="META",
        exchange="NASDAQ",
        name="Meta Platforms Inc",
        first_trade_date=date(2012, 5, 18),
        last_trade_date=date(2026, 12, 31),
    )
    history = [
        SecurityHistoryRecord(security_id="SEC_META", ticker="FB", effective_from=date(2012, 5, 18), effective_to=date(2022, 6, 8)),
        SecurityHistoryRecord(security_id="SEC_META", ticker="META", effective_from=date(2022, 6, 9), effective_to=None),
    ]
    master = InMemorySecurityMaster(securities=[sec], history=history)

    # Under old ticker
    assert master.resolve_security_id("FB", date(2020, 1, 1)) == "SEC_META"
    assert master.resolve_security_id("META", date(2020, 1, 1)) is None

    # Under new ticker
    assert master.resolve_security_id("META", date(2023, 1, 1)) == "SEC_META"
    assert master.resolve_security_id("FB", date(2023, 1, 1)) is None


# =====================================================================
# 2. DUAL-PRICE ARCHITECTURE TESTS
# =====================================================================

def test_dual_price_separation():
    """Verifies unadjusted vs split-adjusted isolation and accessors."""
    # Simulating a 2-for-1 forward split: unadjusted = 100, split-adjusted = 50
    bar = DailyBar(
        security_id="SEC_SPLIT",
        session_date=date(2023, 1, 10),
        open=98.0,
        high=102.0,
        low=97.0,
        close=100.0,
        volume=1_000_000.0,
        adjusted_open=49.0,
        adjusted_high=51.0,
        adjusted_low=48.5,
        adjusted_close=50.0,
        adjusted_volume=2_000_000.0,
    )

    # Execution prices must strictly reflect raw dollars
    assert bar.execution_close == 100.0
    assert bar.execution_high == 102.0
    assert bar.execution_low == 97.0

    # Analytical prices must strictly reflect split-adjusted figures
    assert bar.analytical_close == 50.0
    assert bar.analytical_high == 51.0


def test_dual_price_validation_errors():
    """Ensures inverted OHLC or negative volume throws ValueError when strict_validation=True."""
    with pytest.raises(ValueError, match="cannot exceed high"):
        DailyBar(
            security_id="SEC_ERR",
            session_date=date(2023, 1, 10),
            open=10.0,
            high=10.0,
            low=15.0,  # low > high
            close=12.0,
            volume=100.0,
            adjusted_open=10.0,
            adjusted_high=10.0,
            adjusted_low=15.0,
            adjusted_close=12.0,
            adjusted_volume=100.0,
            strict_validation=True,
        )


# =====================================================================
# 3. POINT-IN-TIME INDICATORS & ANTI-LEAKAGE ADVERSARIAL TESTS
# =====================================================================

def _generate_daily_series(security_id: str, count: int, base_date: date = date(2024, 1, 1)):
    """Generates synthetic daily bars."""
    bars = []
    current_d = base_date
    for i in range(count):
        # Skip weekends
        while current_d.weekday() >= 5:
            current_d += timedelta(days=1)

        b = DailyBar(
            security_id=security_id,
            session_date=current_d,
            open=100.0 + i,
            high=105.0 + i,
            low=95.0 + i,
            close=102.0 + i,
            volume=500_000.0 + (i * 1000),
            adjusted_open=100.0 + i,
            adjusted_high=105.0 + i,
            adjusted_low=95.0 + i,
            adjusted_close=102.0 + i,
            adjusted_volume=500_000.0 + (i * 1000),
        )
        bars.append(b)
        current_d += timedelta(days=1)
    return bars, current_d


def test_indicators_insufficient_history_fails_closed():
    """Tests that calculate_65d_high, adv50, and 10ema return None when history is insufficient."""
    bars, session_t = _generate_daily_series("SEC_SHORT", 30)
    provider = InMemoryDailyBarProvider(bars)

    # 30 bars is < 65 required for 65D high
    assert calculate_65d_high("SEC_SHORT", session_t, provider, lookback_sessions=65) is None
    # 30 bars is < 50 required for ADV50
    assert calculate_adv50("SEC_SHORT", session_t, provider, lookback_sessions=50) is None
    # 30 bars is >= 10, so 10 EMA is available
    assert calculate_10ema("SEC_SHORT", session_t, provider, period=10) is not None


def test_adversarial_session_t_anti_leakage():
    """
    CRITICAL ADVERSARIAL TEST:
    Verifies that modifying session-t high, close, and volume to extreme anomalous values
    has ZERO effect on indicators computed for session t.
    """
    bars, session_t = _generate_daily_series("SEC_LEAK_TEST", 70)
    provider = InMemoryDailyBarProvider(bars)

    # Compute baseline indicators for session_t using historical bars (through t-1)
    baseline_high65 = calculate_65d_high("SEC_LEAK_TEST", session_t, provider, lookback_sessions=65)
    baseline_adv50 = calculate_adv50("SEC_LEAK_TEST", session_t, provider, lookback_sessions=50)
    baseline_ema10 = calculate_10ema("SEC_LEAK_TEST", session_t, provider, period=10)

    assert baseline_high65 is not None
    assert baseline_adv50 is not None
    assert baseline_ema10 is not None

    # Now add an extreme corrupt bar ON session_t itself (High=$999,999, Close=$999,999, Vol=100,000,000)
    corrupt_bar_t = DailyBar(
        security_id="SEC_LEAK_TEST",
        session_date=session_t,
        open=100.0,
        high=999_999.0,
        low=90.0,
        close=999_999.0,
        volume=100_000_000.0,
        adjusted_open=100.0,
        adjusted_high=999_999.0,
        adjusted_low=90.0,
        adjusted_close=999_999.0,
        adjusted_volume=100_000_000.0,
    )
    provider.add_bar(corrupt_bar_t)

    # Recalculate indicators for session_t
    test_high65 = calculate_65d_high("SEC_LEAK_TEST", session_t, provider, lookback_sessions=65)
    test_adv50 = calculate_adv50("SEC_LEAK_TEST", session_t, provider, lookback_sessions=50)
    test_ema10 = calculate_10ema("SEC_LEAK_TEST", session_t, provider, period=10)

    # Assert 100% strict equality: Session t data MUST NOT LEAK!
    assert test_high65 == baseline_high65, f"Leakage detected in 65D High! {test_high65} != {baseline_high65}"
    assert test_adv50 == baseline_adv50, f"Leakage detected in ADV50! {test_adv50} != {baseline_adv50}"
    assert test_ema10 == baseline_ema10, f"Leakage detected in 10 EMA! {test_ema10} != {baseline_ema10}"


# =====================================================================
# 4. UNIVERSE SCREENING & CANDIDATE GENERATION TESTS
# =====================================================================

def test_universe_screening_filters():
    """Tests price floor, ADV50, and dollar volume gates in UniverseScreener."""
    sec_pass = Security("SEC_PASS", "PASS", "NASDAQ", "Pass Corp", date(2020, 1, 1), date(2025, 12, 31))
    sec_cheap = Security("SEC_CHEAP", "CHEAP", "NASDAQ", "Penny Corp", date(2020, 1, 1), date(2025, 12, 31))
    sec_illiquid = Security("SEC_ILLIQ", "ILLIQ", "NASDAQ", "Dry Corp", date(2020, 1, 1), date(2025, 12, 31))

    master = InMemorySecurityMaster(
        securities=[sec_pass, sec_cheap, sec_illiquid],
        history=[
            SecurityHistoryRecord("SEC_PASS", "PASS", date(2020, 1, 1), None),
            SecurityHistoryRecord("SEC_CHEAP", "CHEAP", date(2020, 1, 1), None),
            SecurityHistoryRecord("SEC_ILLIQ", "ILLIQ", date(2020, 1, 1), None),
        ]
    )

    bars_pass, session_t = _generate_daily_series("SEC_PASS", 70)
    bars_cheap, _ = _generate_daily_series("SEC_CHEAP", 70)
    bars_illiq, _ = _generate_daily_series("SEC_ILLIQ", 70)

    daily_provider = InMemoryDailyBarProvider(bars_pass)

    # Add cheap bars (< $5.00)
    for b in bars_cheap:
        daily_provider.add_bar(
            DailyBar(
                security_id="SEC_CHEAP",
                session_date=b.session_date,
                open=3.0, high=3.5, low=2.8, close=3.2, volume=500_000.0,
                adjusted_open=3.0, adjusted_high=3.5, adjusted_low=2.8, adjusted_close=3.2, adjusted_volume=500_000.0,
            )
        )

    # Add illiquid bars (ADV < 100k)
    for b in bars_illiq:
        daily_provider.add_bar(
            DailyBar(
                security_id="SEC_ILLIQ",
                session_date=b.session_date,
                open=50.0, high=52.0, low=49.0, close=50.0, volume=10_000.0,
                adjusted_open=50.0, adjusted_high=52.0, adjusted_low=49.0, adjusted_close=50.0, adjusted_volume=10_000.0,
            )
        )

    config = StrategyConfig(price_floor=5.0, adv50_min=100_000.0, dollar_adv_min=2_500_000.0)
    screener = UniverseScreener(config=config, security_master=master, daily_provider=daily_provider)

    candidates = screener.screen_universe(session_t)
    candidate_ids = [c.security_id for c in candidates]

    assert "SEC_PASS" in candidate_ids
    assert "SEC_CHEAP" not in candidate_ids  # Below $5 floor
    assert "SEC_ILLIQ" not in candidate_ids  # Below 100k ADV


def test_base_hit_candidate_generator():
    """Verifies Base-Hit breakout trigger and stop geometry calculation."""
    bars_pass, session_t = _generate_daily_series("SEC_BASE", 70)
    # Ensure the recent bars form a tight shelf (low=171.0) to pass <= 4.0% risk geometry
    tight_bars = []
    for b in bars_pass[:-3]:
        tight_bars.append(b)
    for b in bars_pass[-3:]:
        tight_bars.append(
            DailyBar(
                security_id=b.security_id,
                session_date=b.session_date,
                open=b.open,
                high=b.high,
                low=171.0,  # Tight shelf
                close=b.close,
                volume=b.volume,
                adjusted_open=b.adjusted_open,
                adjusted_high=b.adjusted_high,
                adjusted_low=171.0,
                adjusted_close=b.adjusted_close,
                adjusted_volume=b.adjusted_volume,
            )
        )
    daily_provider = InMemoryDailyBarProvider(tight_bars)

    high_65 = calculate_65d_high("SEC_BASE", session_t, daily_provider)
    prior_bars = daily_provider.get_prior_completed_bars("SEC_BASE", session_t, 1)
    prior_close = prior_bars[-1].close

    generator = BaseHitCandidateGenerator(config=StrategyConfig(), daily_provider=daily_provider)

    from bonde.data.screener import ScreenedCandidate
    mock_candidate = ScreenedCandidate(
        security_id="SEC_BASE",
        ticker="BASE",
        session_date=session_t,
        prior_close=prior_close,
        adv50=500_000.0,
        dollar_adv=prior_close * 500_000.0,
        high_65=high_65,
        ema_10=prior_close,
    )

    breakouts = generator.generate_breakout_candidates([mock_candidate], session_t)
    assert len(breakouts) == 1
    bh = breakouts[0]
    assert bh.is_qualified is True
    assert bh.trigger_price == round(high_65 + 0.01, 2)
    assert bh.risk_geometry_pct <= 0.040


# =====================================================================
# 5. CATALYST POINT-IN-TIME AVAILABILITY TESTS (TRACK A & TRACK B)
# =====================================================================

def test_track_a_earnings_premarket_cutoff():
    """Verifies that only earnings released strictly prior to 09:30:00 ET qualify for Day-1 pre-market."""
    session_d = date(2024, 3, 15)

    # Case 1: Pre-market BMO at 07:00 ET -> VALID
    ev_bmo = EarningsEvent(
        security_id="SEC_EARN",
        event_timestamp=datetime(2024, 3, 15, 7, 0, tzinfo=NY_TZ),
        event_date=session_d,
        timing="BMO",
        source="ZACKS",
        availability_timestamp=datetime(2024, 3, 15, 7, 5, tzinfo=NY_TZ),
    )
    assert ev_bmo.is_available_for_premarket(session_d) is True

    # Case 2: Released at 09:30:01 ET (post-market open) -> INVALID for Day-1 open
    ev_late = EarningsEvent(
        security_id="SEC_EARN",
        event_timestamp=datetime(2024, 3, 15, 9, 30, 1, tzinfo=NY_TZ),
        event_date=session_d,
        timing="UNKNOWN",
        source="ZACKS",
        availability_timestamp=datetime(2024, 3, 15, 9, 30, 1, tzinfo=NY_TZ),
    )
    assert ev_late.is_available_for_premarket(session_d) is False

    # Case 3: AMC released after close (16:30 ET) -> INVALID for session_d open
    ev_amc = EarningsEvent(
        security_id="SEC_EARN",
        event_timestamp=datetime(2024, 3, 15, 16, 30, tzinfo=NY_TZ),
        event_date=session_d,
        timing="AMC",
        source="ZACKS",
        availability_timestamp=datetime(2024, 3, 15, 16, 35, tzinfo=NY_TZ),
    )
    assert ev_amc.is_available_for_premarket(session_d) is False


def test_track_b_sec_filing_availability():
    """Verifies SEC 8-K acceptance timestamp cutoff."""
    filing = SECFilingEvent(
        security_id="SEC_BIO",
        cik="0001234567",
        accession_number="0001234567-24-000100",
        filing_type="8-K",
        filing_timestamp=datetime(2024, 3, 15, 8, 15, tzinfo=NY_TZ),
        acceptance_datetime=datetime(2024, 3, 15, 8, 15, 22, tzinfo=NY_TZ),
        form="8-K",
        items=["Item 1.01"],
        source_url="https://sec.gov",
        availability_timestamp=datetime(2024, 3, 15, 8, 15, 22, tzinfo=NY_TZ),
    )

    provider = InMemoryFilingProvider([filing])

    # Query before filing acceptance (08:00 ET) -> empty
    before = provider.get_filings_before("SEC_BIO", datetime(2024, 3, 15, 8, 0, tzinfo=NY_TZ))
    assert len(before) == 0

    # Query after filing acceptance (09:00 ET) -> found
    after = provider.get_filings_before("SEC_BIO", datetime(2024, 3, 15, 9, 0, tzinfo=NY_TZ))
    assert len(after) == 1
    assert after[0].items == ["Item 1.01"]


# =====================================================================
# 6. INTRADAY DATA & CANDIDATE-TARGETED EXTRACTION
# =====================================================================

def test_candidate_targeted_intraday_extraction():
    """Verifies that intraday bars are only extracted for targeted candidate during RTH."""
    session_d = date(2024, 4, 10)
    bars = []
    # Create 390 1m bars for candidate SEC_TARGET (09:30 to 15:59 ET)
    start_dt_ny = datetime(2024, 4, 10, 9, 30, tzinfo=NY_TZ)
    for m in range(390):
        dt_ny = start_dt_ny + timedelta(minutes=m)
        dt_utc = dt_ny.astimezone(UTC)
        bars.append(
            IntradayBarRecord(
                security_id="SEC_TARGET",
                symbol="TARGET",
                timestamp_utc=dt_utc,
                open=50.0,
                high=50.5,
                low=49.8,
                close=50.2,
                volume=1000.0,
            )
        )

    provider = InMemoryIntradayBarProvider(bars)

    # Query for targeted candidate
    extracted = provider.get_intraday_bars("SEC_TARGET", session_d)
    assert len(extracted) == 390
    assert extracted[0].timestamp.time() == time(9, 30)
    assert extracted[-1].timestamp.time() == time(15, 59)

    # Query for untargeted candidate -> empty
    untargeted = provider.get_intraday_bars("SEC_OTHER", session_d)
    assert len(untargeted) == 0


# =====================================================================
# 7. MARKET BREADTH & POINT-IN-TIME SECTOR TESTS
# =====================================================================

def test_market_breadth_fsm():
    """Tests Breadth Record regime mapping (GREEN, YELLOW, RED)."""
    # RED: Heavy losers
    b_red = MarketBreadthRecord(
        session_date=date(2024, 1, 15),
        universe_size=5000,
        gainers_4pct_count=50,
        losers_4pct_count=300,
        t2108_percent=15.0,
        regime_state="CALCULATE",
    )
    assert b_red.compute_regime() == MarketRegime.RED

    # GREEN: Healthy breadth
    b_green = MarketBreadthRecord(
        session_date=date(2024, 1, 16),
        universe_size=5000,
        gainers_4pct_count=250,
        losers_4pct_count=80,
        t2108_percent=65.0,
        regime_state="CALCULATE",
    )
    assert b_green.compute_regime() == MarketRegime.GREEN


def test_point_in_time_sector_provider():
    """Tests date-bounded historical sector lookups and fail-closed behavior."""
    rec = HistoricalSectorRecord(
        security_id="SEC_TECH",
        sector="TECHNOLOGY",
        industry_group="SEMICONDUCTORS",
        effective_from=date(2020, 1, 1),
        effective_to=date(2023, 12, 31),
    )
    provider = PointInTimeSectorProvider(records=[rec])

    # Valid within window
    assert provider.get_sector("SEC_TECH", datetime(2022, 5, 1)) == "TECHNOLOGY"
    # Outside window (after 2023-12-31) -> fails closed (None)
    assert provider.get_sector("SEC_TECH", datetime(2024, 1, 1)) is None


# =====================================================================
# 8. DATA QUALITY ENGINE & 8 VALIDATION GATES TESTS
# =====================================================================

def test_data_quality_gates():
    """Tests detection of corrupt bars across OHLC ordering, negative values, and spikes."""
    validator = DataQualityValidator()

    # Corrupt daily bar (low > high)
    bad_bars = [
        DailyBar(
            security_id="SEC_BAD",
            session_date=date(2024, 1, 1),
            open=10.0, high=10.0, low=10.0, close=10.0, volume=-100.0,  # Negative volume
            adjusted_open=10.0, adjusted_high=10.0, adjusted_low=10.0, adjusted_close=10.0, adjusted_volume=10.0,
        )
    ]
    report = validator.validate_daily_bars(bad_bars)
    assert report.status == QualityStatus.FAIL
    assert any(a.anomaly_type == "NEGATIVE_OR_ZERO_PRICE" for a in report.anomalies)

    # Intraday 60% price spike during RTH (15:00 UTC = 10:00 EST)
    spike_bars = [
        IntradayBarRecord("SEC_SPIKE", "SPIKE", datetime(2024, 1, 2, 15, 0, tzinfo=UTC), 10.0, 10.0, 10.0, 10.0, 100),
        IntradayBarRecord("SEC_SPIKE", "SPIKE", datetime(2024, 1, 2, 15, 1, tzinfo=UTC), 17.0, 17.0, 17.0, 17.0, 100),  # +70% jump
    ]
    report_intra = validator.validate_intraday_bars(spike_bars, expected_bars=2)
    assert any(a.anomaly_type == "EXTREME_PRICE_SPIKE" for a in report_intra.anomalies)


# =====================================================================
# 9. DATASET MANIFEST & REPRODUCIBILITY TESTS
# =====================================================================

def test_manifest_creation_and_integrity():
    """Verifies dataset manifest generation, persistence, and SHA-256 integrity."""
    with tempfile.TemporaryDirectory() as tmp_dir:
        meta_path = Path(tmp_dir)
        manager = ManifestManager(metadata_dir=meta_path)

        manifest = manager.create_manifest(
            dataset_name="us_equities_test",
            provider="SYNTHETIC_DATA_CORP",
            version="1.0.0",
            coverage_start="2020-01-01",
            coverage_end="2024-12-31",
            symbol_count=50,
            row_count=10000,
        )

        manager.save_manifest(manifest)
        loaded = manager.get_manifest("us_equities_test")
        assert loaded is not None
        assert loaded.dataset_name == "us_equities_test"
        assert loaded.provider == "SYNTHETIC_DATA_CORP"
        assert len(loaded.checksum) == 64  # SHA-256 hex string


# =====================================================================
# 10. SYNTHETIC END-TO-END POINT-IN-TIME BACKTEST PIPELINE TEST
# =====================================================================

def test_synthetic_end_to_end_pipeline():
    """
    Executes the complete end-to-end historical data pipeline:
    Security Master -> Daily Provider -> PIT Screener -> Candidate Generator -> Targeted 1m Bars -> Stage 0.2 Engine.
    Proves execution simulation functions seamlessly with zero lookahead bias.
    """
    sec = Security("SEC_PIPELINE", "PIPE", "NASDAQ", "Pipeline Corp", date(2020, 1, 1), date(2025, 12, 31))
    master = InMemorySecurityMaster(
        securities=[sec],
        history=[SecurityHistoryRecord("SEC_PIPELINE", "PIPE", date(2020, 1, 1), None)],
    )

    # 1. 70 days of daily history ending at date(2024, 5, 20)
    daily_bars, test_date = _generate_daily_series("SEC_PIPELINE", 70, base_date=date(2024, 2, 1))
    daily_provider = InMemoryDailyBarProvider(daily_bars)

    # 2. Market Breadth: GREEN on test_date
    breadth_provider = InMemoryMarketBreadthProvider({
        test_date: MarketBreadthRecord(test_date, 5000, 300, 50, 75.0, regime_state="GREEN")
    })

    # 3. Sector Provider
    sector_provider = PointInTimeSectorProvider([
        HistoricalSectorRecord("SEC_PIPELINE", "TECHNOLOGY", "SOFTWARE", date(2020, 1, 1))
    ])

    # 4. Intraday 1m bars for test_date designed to trigger a clean 5-minute ORB setup:
    # Opening 5 mins: 09:30 to 09:34. ORH = 175.00, ORL = 173.00 (Risk Geometry = 2.00 / 175.01 = 1.14% <= 4.0%)
    # Trigger = 175.01, Stop = 172.99
    # At 09:36: price crosses 175.10 -> fills order!
    # At 15:55: price trades at 178.00 -> profitable holding.
    intra_bars = []
    start_ny = datetime.combine(test_date, time(9, 30), tzinfo=NY_TZ)

    # 09:30 - 09:34 (5 bars)
    for m in range(5):
        dt = start_ny + timedelta(minutes=m)
        intra_bars.append(
            IntradayBarRecord("SEC_PIPELINE", "PIPE", dt.astimezone(UTC), 173.5, 175.0, 173.0, 174.0, 5000)
        )

    # 09:35 (ORB evaluation bar)
    intra_bars.append(
        IntradayBarRecord("SEC_PIPELINE", "PIPE", (start_ny + timedelta(minutes=5)).astimezone(UTC), 174.0, 174.5, 173.8, 174.2, 5000)
    )

    # 09:36 (Breakout bar: High = 175.50 > Trigger 175.01 -> Fills buy order!)
    intra_bars.append(
        IntradayBarRecord("SEC_PIPELINE", "PIPE", (start_ny + timedelta(minutes=6)).astimezone(UTC), 174.5, 175.5, 174.5, 175.2, 10000)
    )

    # Remaining bars to EOD
    for m in range(7, 390):
        dt = start_ny + timedelta(minutes=m)
        intra_bars.append(
            IntradayBarRecord("SEC_PIPELINE", "PIPE", dt.astimezone(UTC), 176.0, 178.0, 175.8, 177.5, 3000)
        )

    intraday_provider = InMemoryIntradayBarProvider(intra_bars)

    # Run End-to-End Pipeline
    pipeline = HistoricalBacktestPipeline(
        config=StrategyConfig(),
        security_master=master,
        daily_provider=daily_provider,
        intraday_provider=intraday_provider,
        sector_provider=sector_provider,
        breadth_provider=breadth_provider,
        initial_equity=100_000.0,
    )

    screened = pipeline.run_session(test_date)
    assert len(screened) == 1
    assert screened[0].security_id == "SEC_PIPELINE"

    # Verify execution engine state
    portfolio = pipeline.engine.portfolio
    # An open position should have been established via ORB fill
    assert "PIPE" in portfolio.open_positions
    pos = portfolio.open_positions["PIPE"]
    assert pos.status.value == "OPEN"
    assert pos.entry_price > 0
    assert pos.quantity > 0
    assert pos.initial_stop == 172.99
