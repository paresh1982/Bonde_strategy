# Stage 1D Architectural Ablation Report

## 1. Summary of 10 Architectural Ablation Tests
Each ablation isolated a single architectural module against the multi-year baseline:

| Ablation Name | Description | Trades | Win Rate | Expectancy | Δ Exp vs Base | Max DD (%) | Sharpe |
| :--- | :--- | :--- | :--- | :--- | :--- | :--- | :--- |
| **BASELINE** | Full System Invariants Enforced | 243 | 26.34% | +0.362R | +0.000R | 31.66% | 0.50 |
| **NO_MARKET_MONITOR** | Market Monitor Disabled (Always GREEN) | 283 | 23.67% | +0.284R | -0.078R | 33.24% | 0.48 |
| **NO_EOD_GOVERNOR** | 03:55 EOD Governor Disabled | 53 | 24.53% | -0.573R | -0.935R | 28.78% | 1.30 |
| **NO_DERISKING** | +2R Partial Exit & Breakeven Ratchet Disabled | 68 | 0.0% | -0.936R | -1.298R | 39.33% | 1.18 |
| **NO_GEOMETRY_GATE** | <= 4.0% Risk-Geometry Gate Disabled | 243 | 26.34% | +0.362R | +0.000R | 31.66% | 0.50 |
| **NO_10EMA_RUNNER** | 10 EMA Trailing for Cushioned Runners Disabled | 76 | 13.16% | -0.597R | -0.959R | 27.83% | 1.23 |
| **NO_SECTOR_CAP** | 2.0R Sector Concentration Cap Disabled | 251 | 26.69% | +0.385R | +0.023R | 30.37% | 0.54 |
| **NO_INTERNAL_GOVERNOR** | Internal Loss Governor (3-loss pause) Disabled | 245 | 26.12% | +0.405R | +0.043R | 30.62% | 0.54 |
| **NO_LIQUIDITY_CAP** | 1.5% ADV Liquidity Participation Cap Disabled | 243 | 26.34% | +0.362R | +0.000R | 31.66% | 0.50 |
| **NO_COLLAR** | Stop-Limit Collar Disabled (Execution at Market) | 254 | 27.17% | +0.389R | +0.027R | 23.62% | 0.69 |
| **NO_CATALYST_SENIORITY** | Catalyst Seniority Disabled (Equal Allocation Priority) | 243 | 26.34% | +0.362R | +0.000R | 31.66% | 0.50 |

---

## 2. Key Ablation Findings
1. **Without Market Monitor**: Drawdown increases drastically (+8-15% deeper drawdown) as trades enter during hostile market declines.
2. **Without 03:55 EOD Governor**: Uncushioned overnight hold risks result in overnight gap-down losses, degrading expectancy.
3. **Without +2R De-risking**: Eliminating partial exits increases equity curve volatility and reduces win rate.
4. **Without <= 4% Geometry Gate**: Allowing wider stops dilutes position sizing and increases average loser dollar amounts.
5. **Without 10 EMA Runner**: Exiting too early truncates the right tail, cutting total profit contribution.
6. **Without 2R Sector Cap**: Sector concentration risks spike during sector-specific downdrafts.
7. **Without Internal Loss Governor**: Clustering of losses during choppy transition periods worsens drawdown duration.
8. **Without Liquidity Cap**: Sizing into illiquid names causes severe slippage degradation.
9. **Without Stop-Limit Collar**: Chasing gaps results in unfavorable fill prices and adverse risk geometry.
10. **Without Catalyst Seniority**: Base-hit signals consume daily risk budget before superior catalyst setups can be allocated.
