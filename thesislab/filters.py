"""Entry and exit filters based on indicators and time-of-day rules.

Filters are evaluated before a strategy's scan() or should_close() to gate
whether trading is allowed on a given bar.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date, time

from thesislab.indicators import IndicatorValues


@dataclass
class TimeOfDayFilter:
    """Restrict entries/exits to specific times of day.

    For daily data, this is informational (logged but not enforced).
    For intraday data, entries/exits only trigger within the window.
    """

    entry_start: time = time(9, 30)   # earliest entry
    entry_end: time = time(16, 0)     # latest entry
    exit_start: time = time(9, 30)    # earliest exit
    exit_end: time = time(16, 0)      # latest exit
    label: str = ""

    def can_enter(self, current_time: time | None = None) -> bool:
        if current_time is None:
            return True  # daily data, no time filter
        return self.entry_start <= current_time <= self.entry_end

    def can_exit(self, current_time: time | None = None) -> bool:
        if current_time is None:
            return True
        return self.exit_start <= current_time <= self.exit_end


@dataclass
class IndicatorFilter:
    """Filter entries based on technical indicator conditions.

    Each condition is optional. When set, ALL active conditions must pass
    for the filter to allow entry (AND logic).
    """

    # RSI
    rsi_min: float | None = None       # e.g., 30 = only enter when RSI > 30
    rsi_max: float | None = None       # e.g., 70 = only enter when RSI < 70
    rsi_zone: str | None = None        # "oversold", "neutral", "overbought"

    # Bollinger Bands
    bb_position: str | None = None     # "below_lower", "lower_half", "upper_half", "above_upper"
    bb_pct_b_min: float | None = None  # e.g., 0.0
    bb_pct_b_max: float | None = None  # e.g., 0.2 = price near lower band

    # Moving averages - price relationship
    price_above_sma_20: bool | None = None
    price_above_sma_50: bool | None = None
    price_above_sma_200: bool | None = None
    price_above_ema_9: bool | None = None
    price_above_ema_21: bool | None = None

    # SMA crossover
    sma_20_above_50: bool | None = None  # golden/death cross signal

    # VWAP
    price_above_vwap: bool | None = None

    def check(self, ind: IndicatorValues | None) -> bool:
        """Return True if all active conditions pass."""
        if ind is None:
            return True  # no indicator data, allow by default

        # RSI checks
        if self.rsi_min is not None and ind.rsi_14 is not None:
            if ind.rsi_14 < self.rsi_min:
                return False
        if self.rsi_max is not None and ind.rsi_14 is not None:
            if ind.rsi_14 > self.rsi_max:
                return False
        if self.rsi_zone is not None and ind.rsi_zone is not None:
            if ind.rsi_zone != self.rsi_zone:
                return False

        # Bollinger Band checks
        if self.bb_position is not None and ind.bb_position is not None:
            if ind.bb_position != self.bb_position:
                return False
        if self.bb_pct_b_min is not None and ind.bb_pct_b is not None:
            if ind.bb_pct_b < self.bb_pct_b_min:
                return False
        if self.bb_pct_b_max is not None and ind.bb_pct_b is not None:
            if ind.bb_pct_b > self.bb_pct_b_max:
                return False

        # SMA/EMA price relationship
        if self.price_above_sma_20 is not None and ind.sma_20 is not None:
            above = ind.price > ind.sma_20
            if above != self.price_above_sma_20:
                return False
        if self.price_above_sma_50 is not None and ind.sma_50 is not None:
            above = ind.price > ind.sma_50
            if above != self.price_above_sma_50:
                return False
        if self.price_above_sma_200 is not None and ind.sma_200 is not None:
            above = ind.price > ind.sma_200
            if above != self.price_above_sma_200:
                return False
        if self.price_above_ema_9 is not None and ind.ema_9 is not None:
            above = ind.price > ind.ema_9
            if above != self.price_above_ema_9:
                return False
        if self.price_above_ema_21 is not None and ind.ema_21 is not None:
            above = ind.price > ind.ema_21
            if above != self.price_above_ema_21:
                return False

        # SMA crossover
        if self.sma_20_above_50 is not None and ind.sma_20 is not None and ind.sma_50 is not None:
            above = ind.sma_20 > ind.sma_50
            if above != self.sma_20_above_50:
                return False

        # VWAP
        if self.price_above_vwap is not None and ind.vwap is not None:
            above = ind.price > ind.vwap
            if above != self.price_above_vwap:
                return False

        return True


@dataclass
class WeekdayFilter:
    """Restrict entries to specific days of the week.

    entry_days uses Python's weekday convention: 0=Monday ... 4=Friday.
    Default = all weekdays (no restriction).
    """

    entry_days: tuple[int, ...] = (0, 1, 2, 3, 4)

    def can_enter(self, current_date: date | None) -> bool:
        if current_date is None:
            return True
        return current_date.weekday() in self.entry_days


@dataclass
class EntryExitFilters:
    """Combined filters for controlling when trades can be opened or closed."""

    time_filter: TimeOfDayFilter = field(default_factory=TimeOfDayFilter)
    entry_indicator_filter: IndicatorFilter = field(default_factory=IndicatorFilter)
    exit_indicator_filter: IndicatorFilter = field(default_factory=IndicatorFilter)
    weekday_filter: WeekdayFilter = field(default_factory=WeekdayFilter)

    def can_enter(
        self,
        ind: IndicatorValues | None = None,
        current_time: time | None = None,
        current_date: date | None = None,
    ) -> bool:
        return (
            self.time_filter.can_enter(current_time)
            and self.weekday_filter.can_enter(current_date)
            and self.entry_indicator_filter.check(ind)
        )

    def can_exit(self, ind: IndicatorValues | None = None, current_time: time | None = None) -> bool:
        return self.time_filter.can_exit(current_time) and self.exit_indicator_filter.check(ind)
