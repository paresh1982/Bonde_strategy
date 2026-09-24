# USA Systematic Momentum & Catalyst Strategy Engine

Stage 0 Deterministic MVP Foundation for US Equities.

---

## What This Project Is
A deterministic research and backtesting foundation for the USA version of the systematic momentum and catalyst swing-trading strategy.

## Current Stage
**Stage 0 — Deterministic Architecture & Execution Foundation.**  
Stage 0 is **NOT** a live trading system. It translates documented strategy rules into deterministic software without discretionary decisions, lookahead bias, or hidden assumptions.

---

## What Works (Implemented in Stage 0)
1. **Canonical Data Models (`bonde.data.models`):**
   - 1-minute OHLCV Bar model enforcing `America/New_York` timezone awareness.
   - Abstract `SectorProvider` (D5) to prevent hardcoding static sector data into historical trades.
   - Abstract `CommissionModel` and `SlippageModel` (D8) with zero-cost defaults.
   - Structured `CatalystEvent` point-in-time container.
2. **Market Regime FSM (`bonde.regime.market_regime`):**
   - External regime provider (GREEN, YELLOW, RED) consuming market state (D6).
   - Dynamic equity risk fractions: Green = 1.0% (D3), Yellow = 0.5% (D4), Red = 0.0% (new trades disabled).
3. **Risk Sizing & Liquidity Engine (`bonde.risk.sizing`):**
   - Deterministic 1R position sizing: `floor(risk_dollars / abs(entry - stop))`.
   - 1.5% ADV50 liquidity participation ceiling.
   - 0.60R minimum allocation threshold (rejects trades below 60% of planned 1R).
4. **Portfolio Governors (`bonde.risk.governors`):**
   - Master veto hierarchy: `Account RED > Internal RED > External RED > YELLOW > GREEN`.
   - Sector Governor enforcing max 2.0R uncushioned risk in the same industry group.
   - Single-Ticker Governor enforcing max 1.0R per symbol (deduplicating multiple signals).
   - Portfolio Heat Governor enforcing max 6.0R uncushioned open risk.
5. **Execution Simulator (`bonde.execution.simulator`):**
   - Stop-Limit collar matching (`Trigger + $0.10`); rejects price chasing (`COLLAR_MISS`).
   - 10:15:00 AM stale order purge (`STALE_ORDER_PURGE`).
   - **MANDATORY SAME-BAR RULE (D2):** When both target and stop are reached in the same bar, **STOP IS ASSUMED TO OCCUR FIRST**.
6. **Setup Engines (`bonde.setups`):**
   - Catalyst 5-minute ORB (09:30–09:35 EST) with hard $\le 4.0\%$ geometry gate (`ORB_GEOMETRY_FAIL`).
   - Base-Hit 65-day high intraday breakout detection (D1) and structural stop establishment.
   - Inside-Day compression squeeze evaluator.
7. **Position Lifecycle & EOD Audit (`bonde.portfolio.portfolio`):**
   - Partial profit-taking at $+2.0\text{R}$ (50% tranche) with immediate Breakeven stop ratchet (`Entry + $0.01`).
   - 03:55 PM EOD audit: liquidates fresh T1 positions closing at or below entry price; enforces Day 5 time stop on Base Hits.
8. **Telemetry & Audit Journal (`bonde.telemetry.trade_log`):**
   - Master trade schema tracking planned vs actual R, realized PnL, exit reasons.
   - Explicit rejection event logger.
9. **Event-Driven Backtest Engine (`bonde.engine.backtest`):**
   - Strictly chronological, point-in-time event simulator over intraday bars.

---

## What Does NOT Work Yet (Post-Stage 0)
* **Live Market Feeds & Broker Integration:** Zero live execution or broker API connectivity.
* **Production Historical Equities Database:** Survivorship-free historical delisting universe (e.g. Norgate/CRSP) is required for Stage 1.
* **Automated News / SEC EDGAR NLP:** Text parsing of news wires or 8-K filings is deferred; Stage 0 uses structured earnings calendar flags.
* **Automated Cross-Sectional Breadth Engine:** Daily batch calculation of 4% gainers vs. losers across 6,000+ stocks is deferred; regime is consumed as an external input.
* **Realistic Slippage & Microstructure Fees:** Zero slippage/commission baseline used for Stage 0 testing.

---

## How to Run

### 1. Run Unit Tests (Pytest)
```bash
pytest -v
```

### 2. Run Deterministic Stage 0 Execution Script
```bash
python scripts/run_stage0.py
```
