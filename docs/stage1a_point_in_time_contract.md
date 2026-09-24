# Stage 1A Point-in-Time Integrity Contract

**Repository:** `C:\work\projects\bonde-strategy`  
**Topic:** Exact Mathematical & Relational Rules for Lookahead Prevention in Backtesting  
**Date:** September 2026  
**Status Standard:** INVIOLABLE MATHEMATICAL INTEGRITY SPECIFICATION  

---

## 1. Principles of Point-in-Time Backtesting

A backtest is valid if and only if every decision state $S(T)$ at simulation time $T$ satisfies:
$$S(T) \subseteq \mathcal{F}_T$$
where $\mathcal{F}_T$ is the sigma-algebra representing all public market information generated strictly at or before timestamp $T$.

If any variable in $S(T)$ depends on information generated at $T' > T$, the backtest contains **lookahead bias** and is disqualified.

---

## 2. Inviolable Point-in-Time Rules by Domain

### Rule 1: Prior-Day Lookback Data (Daily Closes, ADV50, 65D High)
* **Rule:** A trading decision at timestamp $T$ on session date $t$ may only consume daily closing metrics from completed sessions $t-1, t-2, \dots$:
  $$\text{Indicator}(T) = g\big(\text{DailyBars}_{k} \mid k \le t-1\big)$$
* **Forbidden:** Never include Day $t$'s own close, volume, high, or low in prior-day metrics.

### Rule 2: Intraday Bar Time Boundaries
* **Rule:** An intraday bar stamped $T_{\text{bar}}$ covers the interval $[T_{\text{bar}}, \; T_{\text{bar}} + \Delta t)$.
* **Availability:** A 1-minute bar stamped `09:34:00` closes at `09:34:59.999`. Its summary values (`high`, `low`, `close`, `volume`) only become physically available at `09:35:00.000`.
* **ORB Window:** The 5-minute Opening Range (09:30–09:35) is formed strictly by bars stamped `09:30`, `09:31`, `09:32`, `09:33`, `09:34`. The bar stamped `09:35:00` cannot enter the range calculation.

### Rule 3: Corporate Catalyst Availability
* **Rule:** A catalyst event (earnings or 8-K) is eligible for session $t$'s morning ORB if and only if:
  $$\text{PublicAvailabilityTimestamp} \le t \text{ at } 09\text{:}30\text{:}00\text{ EST}$$
* **Timing Conventions:**
  - **BMO (Before Market Open):** Announced on date $t$ before 09:30:00 EST $\implies$ tradable on date $t$.
  - **AMC (After Market Close):** Announced on date $t$ after 16:00:00 EST $\implies$ tradable on date $t+1$.
  - **Intraday Announcement:** Announced at 11:30:00 EST $\implies$ disqualified from morning 5-minute ORB on date $t$.

### Rule 4: Point-in-Time Sector Taxonomy
* **Rule:** Sector and industry group mapping for ticker $S$ on date $t$ must query the record satisfying:
  $$\text{effective\_from} \le t \le \text{effective\_to}$$
* **Forbidden:** Joining against contemporary 2026 sector tables when simulating 2012 trading sessions.

### Rule 5: Shares Outstanding & Free Float
* **Rule:** Float turnover calculations on date $t$ must consume the most recent SEC Form 10-Q/10-K accepted before date $t$:
  $$\text{FilingAcceptanceDate} < t$$
* **Forbidden:** Using the fiscal quarter end date (e.g. consuming a 10-Q dated March 31 on April 1st before the document was actually filed on May 10th).

### Rule 6: Survivorship-Bias-Free Security Universe
* **Rule:** The universe of investable candidates on date $t$ consists of all securities actively trading on date $t$:
  $$\text{first\_traded\_date} \le t \le \text{last\_traded\_date}$$
* **Forbidden:** Filtering the 2015 historical universe using a static list of companies currently active in the S&P 500 or NASDAQ today.

---

## 3. Concrete SQL Join Examples: Valid vs. Invalid

### Example 1: Rolling ADV50 & Technical Indicators Join

#### ❌ INVALID JOIN (Lookahead Leakage):
```sql
-- FATAL ERROR: Includes today's (date t) volume in ADV50!
SELECT 
    d.security_id,
    d.trading_date,
    AVG(d_prev.volume_adj) AS adv_50
FROM daily_bars d
JOIN daily_bars d_prev 
  ON d.security_id = d_prev.security_id 
 AND d_prev.trading_date BETWEEN d.trading_date - INTERVAL '50 days' AND d.trading_date -- LEAK: Includes today!
WHERE d.trading_date = '2026-01-05'
GROUP BY d.security_id, d.trading_date;
```

#### ✅ VALID POINT-IN-TIME JOIN:
```sql
-- VALID: Strictly joins completed sessions prior to date t (t-50 to t-1)
WITH prior_50_sessions AS (
    SELECT 
        d_prev.security_id,
        d_prev.volume_adj,
        ROW_NUMBER() OVER (PARTITION BY d_prev.security_id ORDER BY d_prev.trading_date DESC) AS rn
    FROM daily_bars d_prev
    WHERE d_prev.trading_date < '2026-01-05' -- Invariant: Strictly prior sessions!
)
SELECT 
    security_id,
    '2026-01-05'::DATE AS as_of_date,
    ROUND(AVG(volume_adj), 2) AS adv_50
FROM prior_50_sessions
WHERE rn <= 50
GROUP BY security_id
HAVING COUNT(*) = 50; -- Invariant: Exactly 50 completed sessions required!
```

---

### Example 2: Point-in-Time Sector Classification Join

#### ❌ INVALID JOIN (Survivorship & Retrofitting Bias):
```sql
-- FATAL ERROR: Uses current ticker and contemporary sector table!
SELECT 
    b.timestamp,
    s.primary_ticker,
    c.sector -- LEAK: Current 2026 sector applied to historical 2012 trades!
FROM intraday_bars_1m b
JOIN security_master s ON b.security_id = s.security_id
JOIN contemporary_sectors c ON s.primary_ticker = c.ticker
WHERE b.timestamp BETWEEN '2012-05-18 09:30:00-04' AND '2012-05-18 16:00:00-04';
```

#### ✅ VALID POINT-IN-TIME JOIN:
```sql
-- VALID: Joins sector classification effective on the exact trade date
SELECT 
    b.timestamp,
    h.ticker AS historical_ticker,
    sec.sector,
    sec.industry_group
FROM intraday_bars_1m b
-- Point-in-time ticker resolution
JOIN security_history h 
  ON b.security_id = h.security_id 
 AND b.timestamp::DATE BETWEEN h.effective_from AND h.effective_to
-- Point-in-time sector classification resolution
JOIN sector_history sec 
  ON b.security_id = sec.security_id 
 AND b.timestamp::DATE BETWEEN sec.effective_from AND sec.effective_to
WHERE b.timestamp BETWEEN '2012-05-18 09:30:00-04' AND '2012-05-18 16:00:00-04';
```

---

### Example 3: Earnings Catalyst Verification Join

#### ❌ INVALID JOIN (Lookahead on Earnings Time):
```sql
-- FATAL ERROR: Consumes earnings announced AMC as if tradable morning ORB!
SELECT 
    c.symbol,
    e.eps_surprise_pct
FROM candidate_screen c
JOIN earnings_events e 
  ON c.security_id = e.security_id 
 AND e.announcement_date = '2026-01-05' -- LEAK: AMC earnings announced at 16:05 tradable at 09:30 AM!
```

#### ✅ VALID POINT-IN-TIME JOIN:
```sql
-- VALID: Only qualifies earnings publicly released prior to 09:30:00 EST
SELECT 
    c.security_id,
    e.timing_convention,
    e.announcement_time,
    e.eps_reported,
    e.eps_estimate
FROM candidate_screen c
JOIN earnings_events e 
  ON c.security_id = e.security_id
WHERE (
    -- Case A: Released BMO on Trade Date
    (e.announcement_date = '2026-01-05' AND e.timing_convention = 'BMO' 
     AND e.announcement_time <= '2026-01-05 09:30:00-05')
    OR
    -- Case B: Released AMC on Prior Trading Date (e.g. Friday afternoon for Monday trade)
    (e.announcement_date = '2026-01-02' AND e.timing_convention = 'AMC' 
     AND e.announcement_time >= '2026-01-02 16:00:00-05')
);
```

---

## 4. Summary Integrity Checklist

Before any historical backtest run is certified, the data pipeline must pass automated assertions verifying:
1. `max(daily_bars.trading_date) < session_date` for all prior-day indicators.
2. `max(opening_range_bars.timestamp) <= session_date 09:34:59.999`.
3. `corporate_actions.ex_date <= session_date` for split-adjusted multipliers.
4. `catalyst_events.public_timestamp < session_date 09:30:00` for morning ORB candidates.
5. All timestamps are explicitly zoned in `America/New_York` with correct DST transitions.
