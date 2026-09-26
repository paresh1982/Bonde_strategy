# Stage 4 — Frozen-Strategy Historical Backtest Architecture & Design Specification

**Repository:** `C:\work\projects\bonde-strategy`  
**Market:** United States Equities (NYSE / NASDAQ / AMEX)  
**Document:** `docs/stage4_backtest_design.md`  
**Status:** ARCHITECTURAL SPECIFICATION — FROZEN RULES  
**Date:** September 2026  

---

## 1. Objective & Non-Negotiable Constraints

This document defines the frozen architectural design of the multi-year US historical research and backtesting engine for Stage 4.

### Absolute Constraints
1. **Documents 01–06 Unchanged**: No entry rules, exit rules, sizing rules, stop logic, ORB rules, catalyst definitions, or risk limits may be altered.
2. **Zero Parameter Optimization**: No thresholds, moving average lengths, or multipliers may be calibrated to fit historical curves.
3. **No Lookahead Bias**: For any decision on session $t$, all screening and sizing must strictly rely on information timestamped on or before session $t-1$ EOD.
4. **Survivorship-Bias-Free Universe**: Delisted securities must be evaluated with identical priority to surviving securities during their active trading lifespans.

---

## 2. Chronological Pipeline & Event Flow

```
                      PRE-MARKET (t-1 EOD -> 09:29 ET)
┌────────────────────────────────────────────────────────────────────────┐
│ 1. Point-in-Time Security Universe Resolution (active on session t)    │
│ 2. Compute Indicators on completed bars [t-65, t-1] (ADV50, 65D, 10EMA)│
│ 3. Evaluate Market Regime from Breadth (GREEN, YELLOW, RED)            │
│ 4. Catalyst Ingestion: Earnings (BMO/AMC) & SEC 8-K (acceptanceDateTime)│
│ 5. Universal Screening Gates: Price >= $5, ADV50 >= 100k, Float < 50M  │
│ 6. Candidate Generation: Track A (Earnings), Track B (PR), Base-Hit    │
│ 7. Portfolio Allocation Waterfall: Priority, Seniority, Risk Budgets   │
└───────────────────────────────────┬────────────────────────────────────┘
                                    │
                                    ▼
                      OPENING & INTRADAY (09:30 - 15:54 ET)
┌────────────────────────────────────────────────────────────────────────┐
│ 8. ORB Bar Collection (09:30 - 09:34 1m bars): Establish ORH & ORL     │
│ 9. Order Staging (09:35 ET): BUY STOP-LIMIT at ORH + $0.01             │
│    - Limit Collar: Trigger + $0.05 (or 0.25%)                          │
│    - Structural Stop: ORL - $0.01                                      │
│ 10. Execution Simulation (09:35 - 15:54 ET):                            │
│     - Intrabay fill evaluation against high/low                        │
│     - STOP-FIRST Invariant: If stop & target breached on same bar,     │
│       stop takes mandatory precedence                                  │
│     - +2R Partial Exit: Liquidate 50%, ratchet remaining stop to BE+0.01│
│     - Stale Order Purge: Cancel untriggered entry orders at 10:15 ET   │
└───────────────────────────────────┬────────────────────────────────────┘
                                    │
                                    ▼
                      END-OF-DAY AUDIT (15:55 - 16:00 ET)
┌────────────────────────────────────────────────────────────────────────┐
│ 11. Mandatory EOD Audit (15:55 ET):                                     │
│     - T1 Liquidation: If close <= entry, liquidate immediately         │
│     - T2 Stall Liquidation: If held 1 day & close <= entry, liquidate  │
│ 12. Session Reconciliation & Checkpointing (16:00 ET):                  │
│     - Reconcile broker fills against portfolio state                   │
│     - Record trade records, telemetry, equity curve                    │
└────────────────────────────────────────────────────────────────────────┘
```

---

## 3. Strict Point-in-Time & Anti-Leakage Contracts

### A. Dual-Price Separation Architecture
- **Analytical Indicators**: Computed exclusively on split-adjusted historical series.
  - $\text{ADV}_{50} = \frac{1}{50}\sum_{i=1}^{50}\text{AdjustedVolume}_{t-i}$
  - $\text{65D High} = \max_{i=1}^{65}(\text{AdjustedHigh}_{t-i})$
  - $\text{10 EMA} = \text{EMA}_{10}(\text{AdjustedClose}_{t-1})$
- **Execution & Sizing**: Evaluated exclusively in raw unadjusted trade prints.
  - $\text{Trigger Price} = \text{Unadjusted ORH} + \$0.01$
  - $\text{Collar Limit} = \text{Trigger Price} + \$0.05$
  - $\text{Structural Stop} = \text{Unadjusted ORL} - \$0.01$
  - $\text{Dollar Risk per Share} = \text{Trigger} - \text{Stop}$
  - $\text{Position Shares} = \lfloor \frac{1\text{R Dollar Budget}}{\text{Dollar Risk per Share}} \rfloor$

### B. Security Identity Resolution
- Canonical surrogate ID format: `SEC_{SYMBOL}_{ID}`.
- Handled via `SecurityMasterProvider.resolve_security_id(ticker, as_of_date)`.
- Eliminates ticker reuse distortion (e.g. `RECY`) and corporate renaming distortion (e.g. `FB` $\rightarrow$ `META` on 2022-06-09).
- Prevents post-delisting leakage (e.g. `SIVB` cannot generate candidate signals after 2023-03-10).

---

## 4. Execution Invariants & Risk Governors

1. **STOP-FIRST Precedence Rule**:
   - If an intrabar 1-minute candle breaches both the stop price and the target/partial-target price, the engine **must execute the stop loss first**. Target realization on the same candle is strictly prohibited.
2. **Stop-Limit Collar Enforcement**:
   - If market gaps through the collar limit, order status becomes `COLLAR_MISS`. Fills outside the collar are rejected.
3. **Composite Risk Governors**:
   - **Regime Governor**: GREEN ($3.0\text{R}$ daily limit), YELLOW ($1.0\text{R}$ Catalyst only), RED ($0\text{R}$ trading halted).
   - **Heat Governor**: Maximum aggregate portfolio open uncushioned risk capped at $6.0\text{R}$.
   - **Sector Governor**: Maximum concurrent allocation per sector capped at $2.0\text{R}$ (maximum 2 positions).
   - **Single Ticker Cap**: Maximum $1.0\text{R}$ per ticker per day.
   - **Internal Loss Governor**: 3 consecutive losses $\rightarrow$ step-down sizing or trading halt.
   - **ADV Participation Limit**: Order shares cannot exceed $1.5\%$ of $\text{ADV}_{50}$.
   - **Minimum Allocation Gate**: If sizing yields $< 0.60\text{R}$ due to liquidity caps, candidate is rejected fail-closed.

---

## 5. Reproducibility & Cryptographic Manifest Specification

Every backtest run must produce a cryptographic `run_manifest.json` containing:
- **Dataset Manifest Hash**: SHA-256 Merkle root across all ingested raw and processed Parquet files.
- **Strategy Specification Version**: Git commit hash of frozen codebase.
- **Configuration Hash**: SHA-256 hash of `StrategyConfig` parameters.
- **Execution Environment**: Python version, OS platform, package dependency manifest.
- **Random Seed**: Deterministic seed (default `42`).

Given the identical dataset manifest hash and configuration hash, the backtest engine must produce bit-for-bit identical trade logs, execution fills, and P&L.

---

## 6. Descriptive Historical Telemetry Outputs

When commercial data is ingested, the engine generates:
1. **Trade-Level Journal**: Entry/exit timestamps, prices, slippage, commissions, holding period, setup type, regime, MAE, MFE, R-multiple.
2. **Daily Equity Curve**: Total portfolio equity, cash, unrealized P&L, daily turnover, cash percentage.
3. **Distribution Metrics**: Win rate, average winner R, average loser R, payoff ratio, profit factor, expectancy, max drawdown ($ and %), longest losing streak.
4. **Attribution Analysis**:
   - Catalyst Engine vs. Base-Hit Engine performance breakdown.
   - Rejections by governor (regime veto, sector cap, heat cap, min allocation, ADV cap).
   - EOD exit statistics (T1 exits vs. T2 stall liquidations).
