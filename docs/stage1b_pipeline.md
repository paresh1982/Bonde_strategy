# Stage 1B End-to-End Historical Data & Backtest Pipeline

**Repository:** `C:\work\projects\bonde-strategy`  
**Market:** United States Equities (NYSE / NASDAQ / AMEX)  
**Document:** `docs/stage1b_pipeline.md`  
**Status:** IMPLEMENTED PIPELINE ARCHITECTURE  

---

## 1. Architectural Overview

The Stage 1B data infrastructure decouples historical data storage, point-in-time querying, universe screening, setup discovery, and execution simulation into discrete, testable layers:

```
                    ┌──────────────────────────────┐
                    │ RAW HISTORICAL DATA PROVIDERS│
                    │ Norgate / FirstRate / SEC    │
                    └──────────────┬───────────────┘
                                   │
                                   ▼
                    ┌──────────────────────────────┐
                    │  LOCAL STORAGE ENGINE        │
                    │  DuckDB + Partitioned Parquet│
                    └──────────────┬───────────────┘
                                   │
                                   ▼
                    ┌──────────────────────────────┐
                    │  POINT-IN-TIME DATA LAYER    │
                    │  • Security Master (No leak) │
                    │  • Indicators (t-1 strictly) │
                    │  • Dual-Price Isolation      │
                    └──────────────┬───────────────┘
                                   │
                                   ▼
                    ┌──────────────────────────────┐
                    │  DAILY UNIVERSE SCREENER     │
                    │  Price >= $5, ADV50 >= 100k, │
                    │  $ADV >= $2.5M, Float <= 50M │
                    └──────────────┬───────────────┘
                                   │
                                   ▼
                    ┌──────────────────────────────┐
                    │  CANDIDATE SETUP GENERATOR   │
                    │  • 65-Day Breakout Geometry  │
                    │  • Catalyst Pre-Market Check │
                    └──────────────┬───────────────┘
                                   │
                                   ▼
                    ┌──────────────────────────────┐
                    │  TARGETED INTRADAY EXTRACTOR │
                    │  Extracts 1m bars ONLY for   │
                    │  qualifying candidates + open│
                    └──────────────┬───────────────┘
                                   │
                                   ▼
                    ┌──────────────────────────────┐
                    │  STAGE 0.2 EXECUTION ENGINE  │
                    │  09:30–09:35 ORB, Collars,   │
                    │  Stops, EOD Audits, Journal  │
                    └──────────────────────────────┘
```

---

## 2. Chronological Pipeline Sequence (Session $t$)

Every trading day $t$ executes through the following strict timeline without future data leakage:

### Phase 1: Pre-Market Initialization (08:00–09:29 ET)
1. **Market Regime Determination (08:00 ET):**
   - Query `market_breadth` for session $t-1$.
   - Calculate net 4% gainers/losers and % stocks above 40 SMA.
   - Set regime: `GREEN` (1.0% risk), `YELLOW` (0.5% risk), or `RED` (0% risk / new entries blocked).
2. **Point-in-Time Universe Screening (08:30 ET):**
   - `UniverseScreener.screen_universe(session_date=t)` queries active securities.
   - Computes $t-1$ metrics:
     - `prior_close` = Close of session $t-1$ ($\ge \$5.00$).
     - $\text{ADV}_{50}$ = Average volume over completed sessions $[t-50, t-1]$ ($\ge 100,000$ shares).
     - Dollar ADV = $\text{prior\_close} \times \text{ADV}_{50}$ ($\ge \$2.5\text{M}$).
     - Shares Float = Point-in-time float history ($\le 50\text{M}$ shares).
3. **Catalyst Pre-Market Audit (09:00 ET):**
   - Track A: Verify earnings release timestamp $\le 09:29:59$ ET.
   - Track B: Verify SEC 8-K `acceptanceDateTime` $\le 09:29:59$ ET.
4. **Candidate-Targeted 1-Minute Bar Extraction (09:25 ET):**
   - Instead of scanning multi-terabyte datasets, `IntradayBarProvider.get_intraday_bars()` extracts regular-session 1-minute bars *strictly* for:
     1. Qualifying candidates passing daily screen.
     2. Securities with open positions in `Portfolio` requiring trailing stops.

---

### Phase 2: Opening Range & Execution Simulation (09:30–10:15 ET)
1. **09:30:00–09:34:59 ET (Opening Range Construction):**
   - Engine buffers the five 1-minute continuous bars.
   - Derives $\text{ORH} = \max(\text{High})$ and $\text{ORL} = \min(\text{Low})$.
2. **09:35:00 ET (ORB Evaluation & Staging):**
   - Enforces the hard Universal Risk-Geometry Gate:
     $$\text{Planned Risk} = \frac{\text{Trigger} - \text{Stop}}{\text{Trigger}} \le 4.0\%$$
   - Calculates position sizing with liquidity participation cap:
     $$\text{Max Shares} \le 1.5\% \times \text{ADV}_{50}$$
     $$\text{Deployment} \ge 0.60R \quad (\text{otherwise cancel})$$
   - Stages stop-limit buy order: $\text{Trigger} = \text{ORH} + \$0.01$, $\text{Limit} = \text{Trigger} + \$0.10$, $\text{Stop} = \text{ORL} - \$0.01$.
3. **09:35:01–10:15:00 ET (Order Matching & Post-Fill Stop):**
   - Simulator processes incoming 1-minute bars.
   - If $\text{Bar High} \ge \text{Trigger}$ and $\text{Open} \le \text{Limit}$, order fills.
   - Immediate conservative post-fill evaluation: if the fill bar touches the stop price on the same bar, the position is stopped out immediately (`SAME_BAR_STOP_FIRST`).
4. **10:15:00 ET (Stale Order Purge):**
   - Any staged ORB entry order not filled by 10:15:00 ET is unconditionally purged.

---

### Phase 3: Intraday Management & EOD Audit (10:15–16:00 ET)
1. **10:15:00–15:54:59 ET (Position Trailing):**
   - Checks partial target ($+2.0R$): exits 50% tranche and ratchets stop to breakeven ($+\$0.01$).
   - Structural stop-loss enforcement: closes position if bar low breaches active stop.
2. **15:55:00 ET (Mandatory EOD Audit):**
   - **T1 Liquidation:** Closes uncushioned Day-1 position if $\text{Close} \le \text{Entry}$.
   - **T2 Stall Liquidation:** Closes uncushioned Day-2 position if $\text{Close} \le \text{Entry}$.
   - **Base-Hit Time Stop:** Closes Base-Hit position after Day 5.
   - **Cushioned Runner Check:** Closes cushioned runner if $\text{Close} < \text{10 EMA}(t-1)$.
3. **16:00:00 ET (Session Close):**
   - Marks open positions to continuous session close. Records trade journal logs.

---

## 3. Storage Layout & Pathing

```
data/
  raw/
    security_master/     <- Ingested vendor listing files (CSV/JSON)
    daily/               <- Ingested daily raw OHLCV
    intraday/            <- Raw 1-minute CSVs
    earnings/            <- Zacks / FMP historical earnings calendars
    sec_filings/         <- SEC EDGAR 8-K submission metadata
    sectors/             <- Historical GICS/SIC mappings
    breadth/             <- Historical advance/decline breadth feeds
  processed/
    daily/               <- Partitioned dual-price Parquet
    intraday/            <- Candidate-partitioned 1-minute Parquet
    indicators/          <- Pre-calculated 10 EMA / 65D High caches
    candidates/          <- Daily screened candidate logs
  metadata/
    market_metadata.duckdb <- DuckDB relational database (security master, history)
    dataset_manifest.json  <- Cryptographic version manifests
  quality/
    *.json               <- Automated data quality audit reports
```
