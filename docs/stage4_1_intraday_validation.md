# STAGE 4.1 — INTRADAY 1-MINUTE DATA VALIDATION REPORT

## 1. Intraday Validation Constraints
- Session Window: Strictly 09:30:00 to 16:00:00 America/New_York (RTH).
- Expected Regular Session Bar Count: Exactly 390 1-minute bars.
- Expected Early Close Bar Count (13:00 ET): Exactly 210 1-minute bars.
- Zero interpolation or artificial bar fabrication permitted.

## 2. Missing Bar Categorization Matrix
| Severity | Condition | Action |
|---|---|---|
| `PASS` | 390 bars (or 210 on early close), 0 duplicate/monotonic errors | Full simulation permitted |
| `WARN` | 1-5 missing bars outside ORB window without candidate/order | Logged, non-critical simulation permitted |
| `BLOCKER` | Missing bar in ORB window (09:30–09:35) or active order window | Fail closed; simulation strictly prohibited |

## 3. Commercial Universe Scale Gap
- Local verification fixtures contain exactly **7 isolated sessions** (2,730 total bars across 7 stocks).
- Commercial institutional requirement: Multi-year 1-minute historical tick/bar archive across ~10,000 equities.
- Status: **BLOCKER**.
