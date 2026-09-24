# Pradeep Bonde (Stockbee): Market Breadth, Scans, and Trading Routines

## 1. The Stockbee Market Breadth System

Pradeep Bonde pioneered the use of granular, momentum-specific market breadth indicators to determine whether the market environment is conducive to swing trading. Traditional index moving averages (e.g., SPY > 200 SMA) are lagging; Bonde's breadth indicators provide **leading, real-time feedback** on institutional risk appetite.

### The Core Breadth Metric: 4% Gainers vs. 4% Losers
- **Definition**: The daily count of stocks in the entire US equity universe (above $5 and 100k daily volume) making a price gain of **>= +4%** compared to those making a loss of **>= -4%**.
- **Market Signal Logic**:
  - **Green Light (Aggressive Offensive Mode)**:
    - 4% Gainers consistently exceed **100 to 200+** per day.
    - 4% Losers remain subdued (below 30 to 50).
    - *Action*: Trade aggressively, take full position sizes (1% risk), deploy margin if appropriate, hold runners for multi-week moves.
  - **Yellow Light (Prudence / Defensive Rotation)**:
    - 4% Gainers drop below 50; 4% Losers start expanding (50 to 100).
    - *Action*: Tighten trailing stops, scale out into strength faster (take profits at 2R or 3 days), reduce position count to 2-3 pilots, lower risk to 0.5%.
  - **Red Light (Hostile Market / Capital Preservation)**:
    - 4% Losers dominate (150 to 300+); 4% Gainers dry up (<25).
    - *Action*: **100% Cash**. Do not buy breakouts; breakouts fail with high probability. Preserve capital and mental energy.

### Secondary Breadth Indicators
1. **Worden T2108 / Stocks Above 40-Day Moving Average**:
   - **Oversold Reversal Signal**: When T2108 drops below **15% to 20%** and turns upward, Bonde looks for explosive market bounce plays and first-wave Episodic Pivots.
   - **Overbought Warning**: When T2108 stays above **70% to 80%** for extended periods, momentum becomes vulnerable to sharp pullbacks.
2. **25% in 1 Month / 50% in 1 Quarter**:
   - Measures speculative appetite and the presence of true market leaders.
   - If the count of stocks up 25% in a month is expanding, momentum strategies yield extraordinary returns.
   - If this count contracts to single digits, the market is devoid of sustained leadership.

---

## 2. TeleChart / TC2000 Scans & PCF Formulas

Stockbee relies on TeleChart (TC2000) for high-speed technical scanning. The primary scan filters are designed to capture range expansion and volume velocity:

### A. The 4% Breakout Scan (Daily Gainers)
- **PCF Formula**:
  - `(C - C1) / C1 * 100 >= 4.0`
  - `V > 100000`
  - `C >= 5.0`
  - `C * V >= 2500000` (Minimum $2.5M dollar volume)

### B. The 65-Day New High Breakout Scan
- **PCF Formula**:
  - `C >= MAXH65.1`
  - `(C - C1) / C1 * 100 >= 4.0`
  - `V >= 1.5 * AVGV50`

### C. The Volume Buzz / Volume Surge Scan
- Captures intraday volume pacing significantly higher than historical average:
  - `V > AVGV50 AND (V / AVGV50) >= 2.0`

### D. The Anticipation / Flat Top Scan
- Looks for stocks within 3% of their 20-day high that have formed narrow trading ranges (NR7 / inside days):
  - `C >= 0.97 * MAXH20`
  - `(H - L) < (H1 - L1) AND (H - L) < (H2 - L2)`

---

## 3. Daily and Weekly Routines

Pradeep Bonde attributes his longevity and success to an unyielding, mechanical daily routine:

```
┌────────────────────────────────────────────────────────┐
│               THE STOCKBEE DAILY CYCLE                 │
├────────────────────────────────────────────────────────┤
│ 1. POST-MARKET (Evening, 60-90 min):                   │
│    - Run 4% Gainers, 65-day Highs, Volume Surges       │
│    - Speed-chart 300 to 500 candidate stocks (1-2s/ch) │
│    - Select 5 to 8 Pristine Focus Setups               │
│    - Write down precise Entry, Stop-Loss, and Sizing   │
├────────────────────────────────────────────────────────┤
│ 2. PRE-MARKET (Morning, 30-45 min):                    │
│    - Review overnight news, earnings releases & PRs    │
│    - Scan pre-market gainers for potential EPs         │
│    - Read catalyst details to identify "negligence"    │
├────────────────────────────────────────────────────────┤
│ 3. MARKET OPEN (9:30 - 10:30 AM EST):                  │
│    - Execute Opening Range Breakouts (ORB 1-min/5-min) │
│    - Enter focus list setups immediately on trigger    │
│    - Place hard stop-loss orders in broker terminal    │
├────────────────────────────────────────────────────────┤
│ 4. MIDDAY & CLOSING (10:30 AM - 4:00 PM EST):          │
│    - Monitor trailing stops (8/10 EMA, previous low)   │
│    - Take 1/3 to 1/2 profits on 3-5 day runners        │
│    - Maintain trading log & update equity curve        │
└────────────────────────────────────────────────────────┘
```

### The Speed-Charting Method
- Bonde views **hundreds of charts in under 30 minutes**.
- By looking at thousands of charts over decades, pattern recognition becomes intuitive and subconscious.
- If a setup does not jump off the screen in 2 seconds, move to the next chart. Never force a trade.

### Weekend Routine
1. **Breadth Aggregation**: Review weekly 4% gainers vs losers trends and sector performance.
2. **Trade Audit / Post-Mortem**: Review every executed trade from the previous week. Categorize mistakes:
   - Was the loss execution error or natural statistical cost of doing business?
   - Did I violate stops? Did I overtrade in a hostile market?
3. **Deep Thematic Research**: Identify emerging industry groups (e.g., AI infrastructure, biotech subsectors, clean tech, defense) that could produce the next wave of Episodic Pivots.
