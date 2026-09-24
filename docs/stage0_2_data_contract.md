# Stage 0.2 Data Contracts Specification: USA Strategy Architecture

**Repository:** `C:\work\projects\bonde-strategy`  
**Topic:** Formal Data Interfaces for Historical Daily Indicators and Volume Averages  
**Date:** September 2026  
**Status Standard:** FROZEN CONTRACT FOR STAGE 1 HISTORICAL INGESTION  

---

## 1. Context & Purpose

In Stage 0, baseline tests operated on synthetic 1-minute bar series where $\text{ADV}_{50}$ and indicators were supplied via static test mappings. To prepare for multi-year survivorship-free historical datasets in Stage 1 without lookahead leakage, this document establishes formal data contracts for:
1. **Daily Technical Indicators (`DailyIndicatorProvider`)**, focusing on the 10-day Exponential Moving Average (10 EMA) runner exit.
2. **50-Day Average Daily Volume (`ADVProvider`)**, governing position sizing, the 1.5% ADV liquidity ceiling, and the 0.60R allocation cutoff.

---

## 2. Daily Indicator Provider Contract (`DailyIndicatorProvider`)

### 2.1 Interface Definition
```python
from abc import ABC, abstractmethod
from datetime import date
from typing import Optional

class DailyIndicatorProvider(ABC):
    """Abstract interface for point-in-time daily indicators (e.g., 10 EMA)."""
    @abstractmethod
    def get_ema(self, symbol: str, as_of_date: date, period: int = 10) -> Optional[float]:
        """
        Returns the EMA for the symbol computed strictly over completed daily sessions
        prior to or ending on as_of_date.
        Must NOT include uncompleted current-day sessions or future dates.
        Returns None if data is missing or history < period.
        """
        pass
```

### 2.2 Mathematical Definition
For session date $t$, the 10-day Exponential Moving Average is calculated strictly over completed daily closes $C_{t-k}$:
$$\text{Multiplier} = \frac{2}{\text{Period} + 1} = \frac{2}{10 + 1} \approx 0.1818$$
$$\text{EMA}_{10, t} = \left(\text{Close}_t - \text{EMA}_{10, t-1}\right) \times \text{Multiplier} + \text{EMA}_{10, t-1}$$

### 2.3 Strict Invariants & Anti-Leakage Constraints
1. **Completed Sessions Only:** Daily indicators consume completed session bars. Intraday price spikes from incomplete sessions cannot distort the daily EMA.
2. **Explicit Unavailable State:** If a ticker has fewer than `period` completed daily sessions (e.g., a recent IPO with 5 trading days), `get_ema()` returns `None`. It will **never** perform a silent fallback or estimate an EMA from fractional data.
3. **Runner Management at 03:55 PM:** When evaluating a Cushioned Runner at the 03:55 PM EOD audit:
   - If `daily_indicator_provider` is present and returns a valid float `ema_10`, the runner is liquidated if `bar.close < ema_10`.
   - If `daily_indicator_provider` is absent (Stage 0 baseline mode), runner liquidation via 10 EMA is bypassed, allowing synthetic tests to run without requiring a mock indicator engine.

---

## 3. ADV50 Data Contract (`ADVProvider`)

### 3.1 Interface Definition
```python
class ADVProvider(ABC):
    """Abstract interface for point-in-time Average Daily Volume (ADV)."""
    @abstractmethod
    def get_adv_50(self, symbol: str, as_of_date: date) -> Optional[float]:
        """
        Returns ADV50(t) = average daily volume over completed sessions [t-50, t-1].
        Requirements:
          - Strictly prior to as_of_date (never includes session t).
          - Requires at least 50 completed prior sessions.
          - Returns None if fewer than 50 completed prior sessions exist.
        """
        pass
```

### 3.2 Mathematical Definition
For any trade decision occurring on date $t$, $\text{ADV}_{50}(t)$ is defined strictly across the preceding 50 completed sessions:
$$\text{ADV}_{50}(t) = \frac{1}{50}\sum_{i=1}^{50} \text{Volume}_{t-i}$$
$$\text{Session } t \text{ is strictly excluded: } \text{SessionDate} < t$$

### 3.3 Strict Invariants & Sizing Integration
1. **Strict Exclusion of Day $t$:** Because position sizing occurs at 09:35:00 AM EST, Day $t$'s full-day volume does not exist yet. Including Day $t$'s volume would constitute a fatal lookahead violation.
2. **Sample Completeness Constraint:** If fewer than 50 completed sessions are available in the historical database prior to date $t$, `get_adv_50()` returns `None`.
3. **Execution Gate:** When `adv_provider` is attached to `Stage0BacktestEngine`:
   - If `get_adv_50()` returns `None`, the candidate is immediately rejected with:
     `rejection_reason = "MISSING_ADV50_DATA"`.
4. **Liquidity Ceiling & Allocation Floor:**
   $$\text{LiquidCap} = \lfloor \text{ADV}_{50}(t) \times 0.015 \rfloor$$
   $$\text{AllocatedShares} = \min\left(\text{PlannedShares}, \; \text{LiquidCap}\right)$$
   $$\text{If } \frac{\text{AllocatedShares}}{\text{PlannedShares}} < 0.60 \implies \textbf{REJECT TRADE}$$

---

## 4. Verification & Test Evidence

The data contracts are implemented in [`models.py`](file:///C:/work/projects/bonde-strategy/src/bonde/data/models.py#L108-L177) and verified by dedicated automated tests in [`test_stage0_2_hardening.py`](file:///C:/work/projects/bonde-strategy/tests/test_stage0_2_hardening.py#L295-L425):
- `test_daily_ema_uses_completed_sessions_only` (PASSED)
- `test_daily_ema_excludes_current_day_future_session` (PASSED)
- `test_daily_ema_missing_data_returns_none` (PASSED)
- `test_cushioned_runner_liquidated_below_10_ema` (PASSED)
- `test_adv50_exactly_50_sessions` (PASSED)
- `test_adv50_49_sessions_returns_none` (PASSED)
- `test_adv50_strictly_excludes_session_t` (PASSED)
- `test_adv50_rolling_update` (PASSED)
