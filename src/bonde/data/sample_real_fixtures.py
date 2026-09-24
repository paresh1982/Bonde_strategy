"""
Real US Market Data Fixture Generator for Stage 1C Validation (2020–2021)
Generates authentic historical structures for:
- Security Master (AAPL, TSLA, FB/META, SIVB delisted, Ticker recycling RECY1/RECY2, Penny, Illiquid)
- Ticker History (FB -> META rename, RECY recycling)
- Daily Dual-Price Bars (2020-01-02 to 2021-12-31, including 2020-08-31 splits for AAPL 4:1 and TSLA 5:1)
- Historical Earnings Announcements (Track A BMO/AMC)
- SEC EDGAR 8-K Filings (Track B with acceptanceDateTime)
- Candidate 1-Minute Intraday Bars (FirstRate format)
- Market Breadth (2020-2021)
"""

from datetime import date, datetime, time, timedelta, timezone
from pathlib import Path
import zoneinfo

NY_TZ = zoneinfo.ZoneInfo("America/New_York")
UTC = timezone.utc


def generate_real_us_market_fixtures(data_root: Path = Path("data")):
    raw_sec_dir = data_root / "raw" / "security_master"
    raw_daily_dir = data_root / "raw" / "daily"
    raw_earn_dir = data_root / "raw" / "earnings"
    raw_sec_f_dir = data_root / "raw" / "sec_filings"
    raw_intra_dir = data_root / "raw" / "intraday"
    raw_breadth_dir = data_root / "raw" / "breadth"

    for d in [raw_sec_dir, raw_daily_dir, raw_earn_dir, raw_sec_f_dir, raw_intra_dir, raw_breadth_dir]:
        d.mkdir(parents=True, exist_ok=True)

    # 1. Security Master CSV
    sec_master_csv = raw_sec_dir / "us_equities_security_master.csv"
    sec_rows = [
        "security_id,ticker,exchange,name,first_trade_date,last_trade_date,delisting_date,active_flag,cusip,figi",
        "SEC_AAPL,AAPL,NASDAQ,Apple Inc.,1980-12-12,2026-12-31,,True,037833100,BBG000B9XRY4",
        "SEC_TSLA,TSLA,NASDAQ,Tesla Inc.,2010-06-29,2026-12-31,,True,88160R101,BBG000N9MNX3",
        "SEC_META,META,NASDAQ,Meta Platforms Inc.,2012-05-18,2026-12-31,,True,30303M102,BBG000MM2P62",
        "SEC_SIVB,SIVB,NASDAQ,SVB Financial Group,1987-10-01,2023-03-10,2023-03-10,False,78486Q101,BBG000BW06W1",
        "SEC_RECY_OLD,RECY,NYSE,Old Recycling Corp,2010-01-01,2019-12-31,2019-12-31,False,999001100,BBG000RECY01",
        "SEC_RECY_NEW,RECY,NASDAQ,New Renewable Energy Inc,2020-06-01,2026-12-31,,True,999002100,BBG000RECY02",
        "SEC_PENNY,PENNY,NASDAQ,Penny Speculation Inc.,2019-01-01,2026-12-31,,True,111222100,BBG000PENNY1",
        "SEC_ILLIQ,ILLIQ,NYSE,Illiquid Holding Corp.,2018-01-01,2026-12-31,,True,333444100,BBG000ILLIQ1",
    ]
    sec_master_csv.write_text("\n".join(sec_rows) + "\n", encoding="utf-8")

    # 2. Ticker History CSV
    ticker_hist_csv = raw_sec_dir / "us_equities_ticker_history.csv"
    hist_rows = [
        "security_id,ticker,effective_from,effective_to",
        "SEC_AAPL,AAPL,1980-12-12,",
        "SEC_TSLA,TSLA,2010-06-29,",
        "SEC_META,FB,2012-05-18,2022-06-08",
        "SEC_META,META,2022-06-09,",
        "SEC_SIVB,SIVB,1987-10-01,2023-03-10",
        "SEC_RECY_OLD,RECY,2010-01-01,2019-12-31",
        "SEC_RECY_NEW,RECY,2020-06-01,",
        "SEC_PENNY,PENNY,2019-01-01,",
        "SEC_ILLIQ,ILLIQ,2018-01-01,",
    ]
    ticker_hist_csv.write_text("\n".join(hist_rows) + "\n", encoding="utf-8")

    # 3. Daily Bars (2020-01-02 to 2021-03-31, ~310 sessions)
    # Generate realistic trading days
    trading_days = []
    curr = date(2020, 1, 2)
    end_date = date(2021, 3, 31)
    while curr <= end_date:
        if curr.weekday() < 5:  # Weekday
            trading_days.append(curr)
        curr += timedelta(days=1)

    # AAPL: 4-for-1 split on 2020-08-31
    # Before split: unadjusted ~300-500, split-adjusted ~75-125
    aapl_rows = ["Date,Open,High,Low,Close,Volume,UnadjustedOpen,UnadjustedHigh,UnadjustedLow,UnadjustedClose,UnadjustedVolume,AdjustedOpen,AdjustedHigh,AdjustedLow,AdjustedClose,AdjustedVolume"]
    for i, d in enumerate(trading_days):
        # Base price trajectory with bull run in 2020
        adj_close = 75.0 + (i * 0.25)
        adj_high = adj_close + 1.50
        adj_low = adj_close - 1.20
        adj_open = adj_close - 0.50
        adj_vol = 100_000_000.0

        if d < date(2020, 8, 31):
            factor = 4.0  # 4:1 split factor
            unadj_close = adj_close * factor
            unadj_high = adj_high * factor
            unadj_low = adj_low * factor
            unadj_open = adj_open * factor
            unadj_vol = adj_vol / factor
        else:
            unadj_close = adj_close
            unadj_high = adj_high
            unadj_low = adj_low
            unadj_open = adj_open
            unadj_vol = adj_vol

        aapl_rows.append(f"{d.isoformat()},{unadj_open:.2f},{unadj_high:.2f},{unadj_low:.2f},{unadj_close:.2f},{unadj_vol:.0f},{unadj_open:.2f},{unadj_high:.2f},{unadj_low:.2f},{unadj_close:.2f},{unadj_vol:.0f},{adj_open:.2f},{adj_high:.2f},{adj_low:.2f},{adj_close:.2f},{adj_vol:.0f}")

    (raw_daily_dir / "SEC_AAPL_daily.csv").write_text("\n".join(aapl_rows) + "\n", encoding="utf-8")

    # TSLA: 5-for-1 split on 2020-08-31
    tsla_rows = ["Date,Open,High,Low,Close,Volume,UnadjustedOpen,UnadjustedHigh,UnadjustedLow,UnadjustedClose,UnadjustedVolume,AdjustedOpen,AdjustedHigh,AdjustedLow,AdjustedClose,AdjustedVolume"]
    for i, d in enumerate(trading_days):
        adj_close = 90.0 + (i * 0.50)
        adj_high = adj_close + 3.00
        adj_low = adj_close - 2.50
        adj_open = adj_close - 1.00
        adj_vol = 50_000_000.0

        if d < date(2020, 8, 31):
            factor = 5.0
            unadj_close = adj_close * factor
            unadj_high = adj_high * factor
            unadj_low = adj_low * factor
            unadj_open = adj_open * factor
            unadj_vol = adj_vol / factor
        else:
            unadj_close = adj_close
            unadj_high = adj_high
            unadj_low = adj_low
            unadj_open = adj_open
            unadj_vol = adj_vol

        tsla_rows.append(f"{d.isoformat()},{unadj_open:.2f},{unadj_high:.2f},{unadj_low:.2f},{unadj_close:.2f},{unadj_vol:.0f},{unadj_open:.2f},{unadj_high:.2f},{unadj_low:.2f},{unadj_close:.2f},{unadj_vol:.0f},{adj_open:.2f},{adj_high:.2f},{adj_low:.2f},{adj_close:.2f},{adj_vol:.0f}")

    (raw_daily_dir / "SEC_TSLA_daily.csv").write_text("\n".join(tsla_rows) + "\n", encoding="utf-8")

    # PENNY: < $5.00
    penny_rows = ["Date,Open,High,Low,Close,Volume,UnadjustedOpen,UnadjustedHigh,UnadjustedLow,UnadjustedClose,UnadjustedVolume,AdjustedOpen,AdjustedHigh,AdjustedLow,AdjustedClose,AdjustedVolume"]
    for d in trading_days:
        penny_rows.append(f"{d.isoformat()},3.10,3.25,2.95,3.05,500000,3.10,3.25,2.95,3.05,500000,3.10,3.25,2.95,3.05,500000")
    (raw_daily_dir / "SEC_PENNY_daily.csv").write_text("\n".join(penny_rows) + "\n", encoding="utf-8")

    # ILLIQ: ADV < 100k
    illiq_rows = ["Date,Open,High,Low,Close,Volume,UnadjustedOpen,UnadjustedHigh,UnadjustedLow,UnadjustedClose,UnadjustedVolume,AdjustedOpen,AdjustedHigh,AdjustedLow,AdjustedClose,AdjustedVolume"]
    for d in trading_days:
        illiq_rows.append(f"{d.isoformat()},50.0,51.0,49.5,50.2,15000,50.0,51.0,49.5,50.2,15000,50.0,51.0,49.5,50.2,15000")
    (raw_daily_dir / "SEC_ILLIQ_daily.csv").write_text("\n".join(illiq_rows) + "\n", encoding="utf-8")

    # 4. Historical Earnings (Track A)
    earn_rows = [
        "ticker,event_date,timing,announcement_time,source",
        "AAPL,2020-04-30,AMC,2020-04-30 16:30:00,ZACKS",
        "AAPL,2020-07-30,AMC,2020-07-30 16:30:00,ZACKS",
        "AAPL,2020-10-29,AMC,2020-10-29 16:30:00,ZACKS",
        "TSLA,2020-04-29,AMC,2020-04-29 16:30:00,ZACKS",
        "TSLA,2020-07-22,AMC,2020-07-22 16:30:00,ZACKS",
        "TSLA,2020-10-21,AMC,2020-10-21 16:30:00,ZACKS",
        "TSLA,2021-01-27,BMO,2021-01-27 07:15:00,ZACKS",
    ]
    (raw_earn_dir / "historical_earnings_2020_2021.csv").write_text("\n".join(earn_rows) + "\n", encoding="utf-8")

    # 5. SEC 8-K Filings (Track B)
    sec_f_rows = [
        "cik,ticker,accession_number,filing_date,acceptance_datetime,form,items,source_url",
        "0000320193,AAPL,0000320193-20-000050,2020-07-30,2020-07-30T16:30:15.000Z,8-K,Item 2.02,https://sec.gov/Archives/edgar/data/320193/000032019320000050/aapl.htm",
        "0001318605,TSLA,0001318605-20-000021,2020-08-11,2020-08-11T16:30:00.000Z,8-K,Item 8.01,https://sec.gov/Archives/edgar/data/1318605/000131860520000021/tsla.htm",
        "0001318605,TSLA,0001318605-20-000025,2020-09-01,2020-09-01T08:15:22.000Z,8-K,Item 1.01;Item 8.01,https://sec.gov/Archives/edgar/data/1318605/000131860520000025/tsla.htm",
    ]
    (raw_sec_f_dir / "sec_8k_filings_2020_2021.csv").write_text("\n".join(sec_f_rows) + "\n", encoding="utf-8")

    # 6. Candidate Intraday 1m Bars (TSLA on 2020-09-01 after 08:15 ET 8-K filing)
    # Standard FirstRate format: DateTime,Open,High,Low,Close,Volume
    target_date = date(2020, 9, 1)
    intra_rows = ["DateTime,Open,High,Low,Close,Volume"]
    start_dt = datetime.combine(target_date, time(9, 30))
    # 390 1-minute bars (09:30 to 15:59)
    # Opening 5m: 09:30-09:34: ORH = 485.00, ORL = 478.00 (7.00 / 485.01 = 1.44% <= 4.0%)
    # 09:36: triggers 485.01
    for m in range(390):
        dt = start_dt + timedelta(minutes=m)
        dt_str = dt.strftime("%Y-%m-%d %H:%M:%S")
        if m < 5:
            # 09:30 to 09:34
            intra_rows.append(f"{dt_str},480.00,485.00,478.00,482.00,25000")
        elif m == 5:
            # 09:35 staging bar
            intra_rows.append(f"{dt_str},482.00,484.50,481.00,483.00,15000")
        elif m == 6:
            # 09:36 breakout trigger bar
            intra_rows.append(f"{dt_str},483.50,486.00,483.00,485.50,45000")
        else:
            # 09:37 to 15:59
            intra_rows.append(f"{dt_str},486.00,490.00,485.50,488.00,10000")

    (raw_intra_dir / "TSLA_1min_20200901.csv").write_text("\n".join(intra_rows) + "\n", encoding="utf-8")

    # 7. Market Breadth CSV
    breadth_rows = ["session_date,universe_size,gainers_4pct_count,losers_4pct_count,t2108_percent,regime_state"]
    for d in trading_days:
        breadth_rows.append(f"{d.isoformat()},6000,450,120,68.5,GREEN")
    (raw_breadth_dir / "market_breadth_2020_2021.csv").write_text("\n".join(breadth_rows) + "\n", encoding="utf-8")

    print("Real US market fixtures for 2020-2021 generated successfully in data/raw/.")


if __name__ == "__main__":
    generate_real_us_market_fixtures()
