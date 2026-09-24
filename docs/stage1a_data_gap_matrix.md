# Stage 1A Historical Data Gap Matrix: MVP vs. Production System

**Repository:** `C:\work\projects\bonde-strategy`  
**Market:** United States Equities (NYSE / NASDAQ / AMEX)  
**Document:** `docs/stage1a_data_gap_matrix.md`  
**Scope:** Dimensional Gap Analysis, Severity Stratification, and Engineered Mitigations  
**Status:** IMPLEMENTATION-READY SPECIFICATION  

---

## 1. Overview & Evaluation Framework

To maintain scientific integrity, the strategy architecture distinguishes between:
1. **MVP Requirements (Stage 1):** The minimal dataset necessary to run an institutionally valid, survivorship-bias-free, point-in-time backtest of the core mechanics (ORB execution, position sizing, risk governors, trailing stops).
2. **Production System Requirements (Stage 2+):** Advanced multi-source institutional feeds required for live execution, automated news NLP parsing, and real-time order routing.

### Severity Definitions
* **BLOCKER:** Cannot execute a valid backtest without this data. Failure introduces fatal survivorship or lookahead bias.
* **CRITICAL:** Severely impairs strategy logic if omitted; must have an engineered, mathematically sound mitigation before running simulations.
* **MODERATE:** Slightly degrades candidate universe fidelity or sector limit precision, but does not invalidate core alpha or risk engine.
* **LOW:** Informational or non-critical enhancement; can be deferred to live production.

---

## 2. Comprehensive Data Gap Matrix

| Data Dimension | MVP Required Now | Full System Required Later | Current In-Repo Status | Gap Severity | Concrete Impact on Backtest | Engineered Mitigation for Stage 1 | Verification & Validation Test |
| :--- | :--- | :--- | :--- | :---: | :--- | :--- | :--- |
| **1. Survivorship-Free Security Master** | Point-in-time universe of listed & delisted US common stocks (2015–2024). | Real-time symbology mapper, CUSIP/FIGI feeds (1990–present). | Schema defined; synthetic test tickers only. | **BLOCKER** | Survivorship bias; artificially inflates win rate if delisted losers are omitted. | Ingest Norgate or FirstRate delisted security master with canonical surrogate IDs. | Query zero active listings for delisted securities post-delisting date. |
| **2. Daily OHLCV (Unadjusted)** | 10-year daily unadjusted bars for candidate universe. | 30-year full tick/daily depth. | Schema defined; synthetic generator exists. | **BLOCKER** | Raw trade dollars required for stop calculation and dollar volume constraints. | Load vendor unadjusted daily bars into `daily_bars`. | Assert daily unadjusted matches intraday aggregated high/low within $\pm \$0.01$. |
| **3. Daily OHLCV (Split-Adjusted)** | 10-year split-adjusted bars for 10 EMA, 65-day high, ADV50. | Full historical adjusted series with cash dividend tracking. | Schema defined; synthetic generator exists. | **BLOCKER** | Split events corrupt historical 10 EMA and 65-day high resistance levels. | Maintain separate split-adjusted columns in `daily_bars` derived from verified split factors. | Cross-check split adjustments against corporate action ex-dates. |
| **4. 1-Minute Intraday Bars (Unadjusted)** | 1-minute RTH bars (09:30–16:00 ET) for screened candidates. | Full tick-level Level 2 book & pre-market 1-minute bars. | Engine supports 1m simulation; real data missing. | **BLOCKER** | Cannot compute 09:30–09:35 ORB, stop-limit collar, or intraday trailing exits. | Restrict 1m bar acquisition to securities passing prior-day daily screening gates. | Verify exactly 390 1m bars per regular session; test no bars exist outside 09:30–16:00. |
| **5. Market Breadth Feed (T2108 / 4% Gainers)** | Point-in-time daily counts of $+4\%$ gainers, $-4\%$ losers, and $\%$ stocks $> 40$ SMA. | Proprietary intraday breadth feed streamed in real-time. | `market_regime.py` implements FSM; historical breadth missing. | **CRITICAL** | Market Governor cannot transition between GREEN, YELLOW, and RED. | Compute breadth daily across entire common stock universe at $t-1$ EOD; store in `market_breadth`. | Replay historical breadth FSM; assert zero lookahead to day $t$ close. |
| **6. Earnings Announcements (Track A)** | Historical BMO / AMC earnings dates and announcement timestamps. | Earnings surprise, guidance revisions, transcribed earnings calls. | Schema defined; no historical calendar loaded. | **CRITICAL** | Cannot distinguish Episodic Pivot (Track A) from regular breakout without earnings tag. | Ingest FMP/Zacks or public SEC EDGAR 10-Q/8-K filing dates for Track A classification. | Check that no trade executes before known public announcement timestamp. |
| **7. News / SEC Filings (Track B)** | Historical 8-K filings with SEC `acceptanceDateTime` (Item 1.01, 8.01). | Full news NLP sentiment, PR Newswire, Bloomberg News tape. | Schema defined; parser not implemented. | **MODERATE** | May miss non-earnings catalyst events (biotech FDA approvals, contract wins). | For MVP, utilize public SEC EDGAR API to extract Item 1.01/8.01 8-K filing timestamps. | Validate filing timestamp is strictly prior to 09:30:00 ET of trading session $t$. |
| **8. Point-in-Time Float History** | Float $< 50\text{M}$ shares filter as of trading date $t$. | Real-time float adjustments, short interest, institutional ownership. | Schema defined; float filter stubbed in synthetic data. | **MODERATE** | Inability to enforce strict $< 50\text{M}$ float gate; may admit larger-cap stocks. | Ingest quarterly SEC 10-Q/10-K shares outstanding; apply conservative float proxy. | Verify float value as of date $t$ was filed on or before $t$. |
| **9. Historical Sector / Industry Mapping** | Point-in-time GICS/SIC sector mapping for sector exposure governor. | Dynamic real-time thematic sector tags. | `sector_governor.py` implemented; historical sector map missing. | **MODERATE** | Cannot enforce 2-position-per-sector cap without accurate historical sector tags. | Use Norgate historical GICS or static SEC SIC code as conservative baseline. | Ensure every candidate has a valid `sector` string prior to sector gate evaluation. |
| **10. Bid-Ask Spread & Order Book Depth** | Realistic fixed/variable slippage model ($\$0.01$ to $\$0.03$ or $\%$ of spread). | Full historical Level 2/3 order book replay (MBO/MBP). | Deterministic slippage model implemented in `ExecutionSimulator`. | **LOW** | Potential slippage underestimation in micro-caps with wide spreads. | Enforce minimum $ADV_{50} \ge 100,000$ shares and $\$5.00$ price floor to avoid illiquid wide spreads. | Stress-test backtest returns across $1\times$, $2\times$, and $3\times$ slippage models. |

---

## 3. Prioritized Implementation Roadmap for Stage 1B

```
           ┌──────────────────────────────────────────────┐
           │ PHASE 1: FOUNDATION (BLOCKERS)               │
           │ • Ingest Delisted Security Master            │
           │ • Ingest Daily Unadj & Split-Adj Bars        │
           │ • Build Pre-Computed Indicators (10EMA/ADV50)│
           └──────────────────────┬───────────────────────┘
                                  │
                                  ▼
           ┌──────────────────────────────────────────────┐
           │ PHASE 2: REGIME & CANDIDATE FILTERS          │
           │ • Compute Historical Market Breadth Series   │
           │ • Ingest SEC EDGAR / Earnings Calendar       │
           │ • Build Daily Screening Pipeline (t-1)       │
           └──────────────────────┬───────────────────────┘
                                  │
                                  ▼
           ┌──────────────────────────────────────────────┐
           │ PHASE 3: EXECUTION INGESTION                 │
           │ • Target Ingestion: 1m Bars for Screened Pool│
           │ • Run Data Quality Gates (1 through 8)       │
           │ • Feed Hardened Stage 0.2 Simulator          │
           └──────────────────────────────────────────────┘
```

### Stage 1B Actionable Gates
1. **Gate 1B.1 (Security Master & Daily Data):** Acquire and load survivorship-bias-free US equities daily data (2015–2024). Verify 0 lookahead on corporate actions.
2. **Gate 1B.2 (Market Breadth Pre-Calculation):** Compute 10-year daily breadth table. Verify external governor switches match market history (e.g., 2020 COVID crash $\rightarrow$ RED; 2021 bull run $\rightarrow$ GREEN).
3. **Gate 1B.3 (Intraday Bar Pipeline):** Build candidate-targeted 1-minute bar extractor to avoid multi-terabyte storage overhead while preserving complete tick fidelity for all actionable setups.
