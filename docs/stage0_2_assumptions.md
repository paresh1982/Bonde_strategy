# Stage 0.2 Architectural & Structural Assumptions Matrix

**Repository:** `C:\work\projects\bonde-strategy`  
**Topic:** Unresolved Data Constraints, Structural Modeling Assumptions, and Scope Boundaries  
**Date:** September 2026  
**Status Standard:** EXPLICIT ARCHITECTURAL LOG (NO SILENT RESOLUTIONS)  

---

## 1. Purpose & Principles

This document explicitly catalogs every operational assumption and unresolved ambiguity in the Stage 0/0.2 codebase. Per the system's foundational directives, **no assumption may be silently converted into an established fact** without empirical verification against institutional historical market data.

---

## 2. Structural & Data Assumptions Matrix

| ID | Domain | Documented Assumption | Rationale & Impact | Stage 1 Resolution Path |
| :---: | :--- | :--- | :--- | :--- |
| **A1** | **Intrabar Multi-Event Precedence** | When both target and stop are reachable in the same 1-minute bar, STOP is assumed to execute first (Rule D2). Post-fill on entry bar evaluates stop breach immediately. | With 1-minute OHLC bars, sub-minute tick sequencing is physically unknowable. Assuming Stop-First enforces maximum conservatism and prevents optimistic fill bias. | Retain D2 STOP-FIRST as invariant; run ablation tests on 1-second or tick datasets if needed. |
| **A2** | **Continuous Intrabar Auction** | When a bar's open is within the allowable collar (`open <= limit`) but `high > limit`, the simulator assumes continuous trade through the trigger and fills at `trigger_price` (plus slippage). | In continuous liquid markets (ADV50 >= 100k), a Buy Stop triggers at the first ask touch. Without tick data, instantaneous jump gaps cannot be differentiated from rapid continuous trends. | In Stage 1, apply variable spread models and volume sweep penalties to collar fills. |
| **A3** | **Execution Friction Baseline** | Stage 0 assumes zero commissions and zero slippage by default (`ZeroCommissionModel`, `ZeroSlippageModel`). | Isolates strategy logic from broker fee structures during software verification. | In Stage 1, plug in institutional execution models (e.g., $0.005/share commission, 2-cent spread slippage, half-spread cross cost). |
| **A4** | **External Market Monitor Breadth** | The Market Monitor (GREEN / YELLOW / RED) is ingested as a pre-computed daily feed rather than computed cross-sectionally from 6,000+ tickers inside the bar loop. | Computing daily Worden T2108 / 4% gainers vs losers across all US stocks requires a full survivorship-free daily database. | Build dedicated Stage 1 offline breadth pre-processor computing daily regime states historically (2010–2024). |
| **A5** | **Point-in-Time Sector Taxonomy** | Sector and industry group metadata are interfaced via `SectorProvider` rather than hardcoded static GICS codes. | US tickers undergo structural reclassifications, mergers, and theme rotations. Static ticker mapping creates point-in-time lookahead bias. | Ingest historical point-in-time sector mapping tables (e.g., historical GICS or SIC). |
| **A6** | **Catalyst Track B Text Parsing** | Automated Natural Language Processing (NLP) of SEC Form 8-K filings and PR Newswire headlines is deferred; catalyst events are ingested as structured event tuples (`CatalystEvent`). | Automated financial NLP introduces non-deterministic model variance. The trading engine's mathematical edge must be validated on structured events first. | Ingest structured historical corporate action feeds (earnings calendars, FDA approvals, buyout announcements). |
| **A7** | **Price Floor Specification Discrepancy** | The baseline price floor is frozen at **$5.00** (`02` L17, `06` L78), despite `01` L91 mentioning $3.00 for Episodic Pivots. | Sub-$5 stocks exhibit severe micro-structure distortions, reverse split risks, and wider percentage bid-ask spreads that impair 1R execution. | Conduct explicit parameter ablation testing in Stage 1 comparing $3.00 vs. $5.00 universe performance. |
| **A8** | **Daily 10 EMA Indicator Feed** | The 10 EMA runner exit is abstracted via `DailyIndicatorProvider` consuming completed daily sessions, operating in non-blocking mode when unavailable. | Intraday 1-minute bars cannot synthesize historical multi-day daily closes without risk of premature current-day bar inclusion. | Connect survivorship-free daily close historical series to `SeriesDailyIndicatorProvider` in Stage 1. |
| **A9** | **Historical ADV50 Lookback** | Position sizing requires $\text{ADV}_{50}(t)$ computed strictly across completed sessions $[t-50, t-1]$. | Stage 0 synthetic tests accept external static ADV maps; real historical data must strictly exclude Day $t$ volume. | Enforce `HistoricalADV50Provider` in Stage 1 backtest runner with strict 50-session minimum lookback. |

---

## 3. Retained Boundary Conditions

1. **No Discretionary Overrides:** All assumptions above are codified into deterministic interfaces. No hidden heuristics or arbitrary overrides exist in the simulation loop.
2. **Conservative Default Posture:** Where empirical uncertainty exists (e.g., intrabar collision, missing ADV, missing EMA), the engine either enforces the most conservative outcome (Stop-First) or rejects the trade explicitly (`MISSING_ADV50_DATA`).
