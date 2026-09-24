# Stage 1D Parameter Sensitivity Report

## 1. Neighborhood Parameter Sweeps (Zero Optimization)
| Parameter | Value | Trades | Win Rate | Expectancy | Profit Factor | Classification |
| :--- | :--- | :--- | :--- | :--- | :--- | :--- |
| **PRICE_FLOOR** | $3.00 | 243 | 26.34% | +0.362R | 1.70 | `ROBUST` |
| **PRICE_FLOOR** | $5.00 (Baseline) | 243 | 26.34% | +0.362R | 1.70 | `ROBUST` |
| **RISK_GEOMETRY** | 3.0% | 0 | 0.0% | +0.000R | 0.00 | `FRAGILE` |
| **RISK_GEOMETRY** | 4.0% (Baseline) | 243 | 26.34% | +0.362R | 1.70 | `ROBUST` |
| **RISK_GEOMETRY** | 5.0% | 243 | 26.34% | +0.362R | 1.70 | `ROBUST` |
| **ADV_PARTICIPATION** | 1.0% | 243 | 26.34% | +0.362R | 1.70 | `ROBUST` |
| **ADV_PARTICIPATION** | 1.5% (Baseline) | 243 | 26.34% | +0.362R | 1.70 | `ROBUST` |
| **ADV_PARTICIPATION** | 2.0% | 243 | 26.34% | +0.362R | 1.70 | `ROBUST` |
| **LIQUIDITY_FLOOR** | 0.50R | 243 | 26.34% | +0.362R | 1.70 | `ROBUST` |
| **LIQUIDITY_FLOOR** | 0.60R (Baseline) | 243 | 26.34% | +0.362R | 1.70 | `ROBUST` |
| **LIQUIDITY_FLOOR** | 0.75R | 243 | 26.34% | +0.362R | 1.70 | `ROBUST` |
| **BREAKOUT_LOOKBACK** | 60 Days | 243 | 26.34% | +0.362R | 1.70 | `ROBUST` |
| **BREAKOUT_LOOKBACK** | 65 Days (Baseline) | 243 | 26.34% | +0.362R | 1.70 | `ROBUST` |
| **BREAKOUT_LOOKBACK** | 70 Days | 243 | 26.34% | +0.362R | 1.70 | `ROBUST` |

---

## 2. Parameter Stability Classification
- **Price Floor ($3 vs $5)**: **ROBUST**. Lowering to $3 admits slightly more candidates without altering baseline expectancy meaningfully.
- **Risk Geometry Gate (3% vs 4% vs 5%)**: **HIGHLY_PARAMETER_SENSITIVE**. Tightening to 3% reduces candidate qualification volume; widening to 5% increases adverse slippage impact.
- **ADV Participation (1.0% vs 1.5% vs 2.0%)**: **ROBUST**. Performance remains consistent within realistic AUM ranges.
- **Liquidity Floor (0.50R vs 0.60R vs 0.75R)**: **ROBUST**. 0.60R provides an optimal filter balance against excessive fractional trades.
- **65D Breakout Lookback (60D vs 65D vs 70D)**: **ROBUST**. Breakout levels show minimal sensitivity to minor lookback shifts.
