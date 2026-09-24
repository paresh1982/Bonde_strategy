"""
US Market Calendar & Session Provider (Stage 2)
Implements NYSE/NASDAQ trading calendar with holidays, early closes,
DST awareness, and regular trading hour (RTH) boundary enforcement.
"""

from datetime import date, datetime, time, timedelta
from typing import List, Optional, Set, Tuple
import zoneinfo

NY_TZ = zoneinfo.ZoneInfo("America/New_York")


def calculate_easter_sunday(year: int) -> date:
    """
    Computes Easter Sunday using the Anonymous Gregorian algorithm (Meeus/Jones/Butcher).
    """
    a = year % 19
    b = year // 100
    c = year % 100
    d = b // 4
    e = b % 4
    f = (b + 8) // 25
    g = (b - f + 1) // 3
    h = (19 * a + b - d - g + 15) % 30
    i = c // 4
    k = c % 4
    l = (32 + 2 * e + 2 * i - h - k) % 7
    m = (a + 11 * h + 22 * l) // 451
    month = (h + l - 7 * m + 114) // 31
    day = ((h + l - 7 * m + 114) % 31) + 1
    return date(year, month, day)


def _observed_date(d: date) -> date:
    """If holiday falls on Saturday, observed on Friday; if Sunday, observed on Monday."""
    if d.weekday() == 5:  # Saturday
        return d - timedelta(days=1)
    elif d.weekday() == 6:  # Sunday
        return d + timedelta(days=1)
    return d


class USMarketCalendar:
    """
    Authoritative US Equities Market Calendar enforcing NYSE/NASDAQ trading schedules.
    """

    def __init__(self):
        self._holiday_cache: dict[int, Set[date]] = {}
        self._early_close_cache: dict[int, Set[date]] = {}

    def _get_holidays(self, year: int) -> Set[date]:
        if year in self._holiday_cache:
            return self._holiday_cache[year]

        holidays = set()

        # 1. New Year's Day (Jan 1)
        ny = _observed_date(date(year, 1, 1))
        # If observed in prior year (Dec 31), don't add to this year
        if ny.year == year:
            holidays.add(ny)

        # 2. Martin Luther King Jr. Day (3rd Monday in January)
        # Find first Monday of January
        jan1_weekday = date(year, 1, 1).weekday()
        first_mon = 1 + ((0 - jan1_weekday) % 7)
        mlk = date(year, 1, first_mon + 14)
        holidays.add(mlk)

        # 3. Presidents' Day (Washington's Birthday: 3rd Monday in February)
        feb1_weekday = date(year, 2, 1).weekday()
        first_mon_feb = 1 + ((0 - feb1_weekday) % 7)
        pres = date(year, 2, first_mon_feb + 14)
        holidays.add(pres)

        # 4. Good Friday (Friday before Easter)
        easter = calculate_easter_sunday(year)
        good_friday = easter - timedelta(days=2)
        holidays.add(good_friday)

        # 5. Memorial Day (Last Monday in May)
        # May has 31 days
        may31_weekday = date(year, 5, 31).weekday()
        mem_day = date(year, 5, 31 - may31_weekday)
        holidays.add(mem_day)

        # 6. Juneteenth (June 19, federal holiday starting 2021)
        if year >= 2021:
            june19 = _observed_date(date(year, 6, 19))
            holidays.add(june19)

        # 7. Independence Day (July 4)
        july4 = _observed_date(date(year, 7, 4))
        holidays.add(july4)

        # 8. Labor Day (1st Monday in September)
        sep1_weekday = date(year, 9, 1).weekday()
        first_mon_sep = 1 + ((0 - sep1_weekday) % 7)
        labor_day = date(year, 9, first_mon_sep)
        holidays.add(labor_day)

        # 9. Thanksgiving Day (4th Thursday in November)
        nov1_weekday = date(year, 11, 1).weekday()
        first_thu_nov = 1 + ((3 - nov1_weekday) % 7)
        thanksgiving = date(year, 11, first_thu_nov + 21)
        holidays.add(thanksgiving)

        # 10. Christmas Day (Dec 25)
        xmas = _observed_date(date(year, 12, 25))
        holidays.add(xmas)

        self._holiday_cache[year] = holidays
        return holidays

    def _get_early_closes(self, year: int) -> Set[date]:
        if year in self._early_close_cache:
            return self._early_close_cache[year]

        early_closes = set()

        # 1. Day before Independence Day (July 3 if weekday)
        july3 = date(year, 7, 3)
        if july3.weekday() < 5:
            early_closes.add(july3)

        # 2. Black Friday (Day after Thanksgiving: 4th Friday in Nov)
        nov1_weekday = date(year, 11, 1).weekday()
        first_thu_nov = 1 + ((3 - nov1_weekday) % 7)
        black_friday = date(year, 11, first_thu_nov + 21 + 1)
        early_closes.add(black_friday)

        # 3. Christmas Eve (Dec 24 if weekday and Christmas observed Dec 25)
        dec24 = date(year, 12, 24)
        if dec24.weekday() < 5 and not self.is_holiday(dec24):
            early_closes.add(dec24)

        self._early_close_cache[year] = early_closes
        return early_closes

    def is_weekend(self, d: date) -> bool:
        return d.weekday() >= 5

    def is_holiday(self, d: date) -> bool:
        return d in self._get_holidays(d.year)

    def is_trading_day(self, d: date) -> bool:
        if self.is_weekend(d):
            return False
        if self.is_holiday(d):
            return False
        return True

    def is_early_close(self, d: date) -> bool:
        if not self.is_trading_day(d):
            return False
        return d in self._get_early_closes(d.year)

    def get_session_hours(self, d: date) -> Tuple[datetime, datetime]:
        """
        Returns (open_dt, close_dt) in America/New_York timezone.
        Raises ValueError if d is not a valid trading day.
        """
        if not self.is_trading_day(d):
            raise ValueError(f"Date {d.isoformat()} is not a US trading day (holiday/weekend).")

        open_dt = datetime.combine(d, time(9, 30, 0), tzinfo=NY_TZ)
        close_time = time(13, 0, 0) if self.is_early_close(d) else time(16, 0, 0)
        close_dt = datetime.combine(d, close_time, tzinfo=NY_TZ)
        return open_dt, close_dt

    def is_regular_trading_hours(self, dt: datetime) -> bool:
        """Determines if datetime falls strictly within RTH for its session date."""
        dt_ny = dt.astimezone(NY_TZ) if dt.tzinfo else dt.replace(tzinfo=NY_TZ)
        session_d = dt_ny.date()
        if not self.is_trading_day(session_d):
            return False

        open_dt, close_dt = self.get_session_hours(session_d)
        return open_dt <= dt_ny <= close_dt

    def get_next_trading_day(self, d: date) -> date:
        current = d + timedelta(days=1)
        while not self.is_trading_day(current):
            current += timedelta(days=1)
        return current

    def get_prior_trading_day(self, d: date) -> date:
        current = d - timedelta(days=1)
        while not self.is_trading_day(current):
            current -= timedelta(days=1)
        return current

    def get_trading_days_between(self, start_d: date, end_d: date) -> List[date]:
        res = []
        cur = start_d
        while cur <= end_d:
            if self.is_trading_day(cur):
                res.append(cur)
            cur += timedelta(days=1)
        return res
