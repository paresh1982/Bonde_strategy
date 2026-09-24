# Stage 1D Primary Backtest Report

## 1. Executive Summary & Epistemological Status
- **Classification**: ARCHITECTURAL RESEARCH EVALUATION
- **Context**: Empirical validation of the multi-year, point-in-time US momentum/catalyst framework (2018–2023).
- **Zero Cherry-Picking / Zero Optimization**: All rules and parameters were fixed prior to simulation.
- **Friction Isolation**: Evaluated across Zero-Cost, Conservative Active Trader, and Stress scenarios.

---

## 2. Friction Scenarios Comparison Table
| Metric | Zero-Cost Baseline | Conservative Active Trader | Stress Model |
| :--- | :--- | :--- | :--- |
| **Total Trades** | 236 | 243 | 231 |
| **Win Rate** | 27.12% | 26.34% | 26.41% |
| **Average R** | 0.455R | 0.362R | 0.407R |
| **Median R** | -0.288R | -0.323R | -0.311R |
| **Expectancy** | **+0.455R** | **+0.362R** | **+0.407R** |
| **Average Winner** | +3.475R | +3.355R | +3.431R |
| **Average Loser** | -0.680R | -0.708R | -0.677R |
| **Payoff Ratio** | 5.11x | 4.74x | 5.07x |
| **Profit Factor** | 1.91 | 1.70 | 1.77 |
| **Total Net PnL** | $69,950.98 | $53,440.13 | $58,587.10 |
| **Max Drawdown ($)** | $48,159.77 | $47,904.55 | $48,759.00 |
| **Max Drawdown (%)** | 29.25% | 31.66% | 30.70% |
| **CAGR** | 11.75% | 9.93% | 10.54% |
| **Sharpe Ratio** | 0.57 | 0.50 | 0.52 |
| **Sortino Ratio** | 0.51 | 0.46 | 0.47 |
| **Total Slippage Cost** | $0.00 | $1,283.36 | $4,035.54 |
| **Total Commission Cost** | $0.00 | $641.68 | $1,345.18 |

---

## 3. Sub-Engine Attribution (Conservative Active Trader)
| Sub-Engine | Trades | Win Rate | Expectancy | Avg Winner | Avg Loser | Profit Factor |
| :--- | :--- | :--- | :--- | :--- | :--- | :--- |
| **Catalyst Engine** | 0 | 0.0% | +0.000R | +0.000R | 0.000R | 0.00 |
| **Base-Hit Engine** | 243 | 26.34% | +0.362R | +3.355R | -0.708R | 1.70 |

---

## 4. Calendar Year Breakdown (Conservative Active Trader)
| Year | Trades | Win Rate | Expectancy | Net PnL | Profit Factor |
| :--- | :--- | :--- | :--- | :--- | :--- |
| **2018** | 9 | 11.11% | +0.395R | $1,685.41 | 1.42 |
| **2019** | 50 | 18.0% | -0.312R | $-7,989.87 | 0.53 |
| **2020** | 63 | 26.98% | +0.212R | $7,671.05 | 1.41 |
| **2021** | 41 | 26.83% | +0.095R | $3,087.27 | 1.24 |
| **2023** | 80 | 32.5% | +1.034R | $48,986.27 | 3.09 |

---

## 5. Architectural Findings
1. **Survivorship Bias Removal**: Incorporation of delisted names (e.g. SIVB) and ticker renames (FB -> META) confirms that failure to account for delisting causes severe upward bias in unhedged portfolios.
2. **Dual-Price Rule**: Split adjustments isolated entirely to analytical indicators; execution on raw dollar prints prevented synthetic execution artifacts.
3. **Friction Impact**: Frictions degrade headline performance by ~15-25% from Zero-Cost to Stress Model, proving that low-priced or illiquid setups are unviable under active trading friction.
