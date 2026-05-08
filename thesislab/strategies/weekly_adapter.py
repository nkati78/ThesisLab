"""Weekly entry adapter — wraps any strategy to behave like a weekly cadence.

On entry, opens on the FIRST trading day of each calendar week.
For the expiration target, picks the LAST trading day of that same week.
This is holiday-aware: if Monday is a holiday, the trade opens Tuesday;
if Friday is a holiday, the trade targets Thursday's expiration.

The wrapper temporarily overrides the base strategy's min_dte/max_dte to
match the actual calendar-week target, so existing strategy code (which
uses chain.filter(min_dte=, max_dte=)) finds the right contracts without
modification.
"""

from __future__ import annotations

from datetime import date

from thesislab.domain import CloseSignal, OptionsChain, Position, Trade


def _iso_week(d: date) -> tuple[int, int]:
    iso = d.isocalendar()
    return iso[0], iso[1]


class WeeklyAdapter:
    """Strategy wrapper for weekly Mon→Fri (holiday-aware) cadence."""

    def __init__(self, base, trading_dates):
        self.base = base
        self.name = base.name
        # Precompute first/last trading day per ISO calendar week.
        self._first_by_week: dict[tuple[int, int], date] = {}
        self._last_by_week: dict[tuple[int, int], date] = {}
        for d in trading_dates:
            wk = _iso_week(d)
            cur_first = self._first_by_week.get(wk)
            if cur_first is None or d < cur_first:
                self._first_by_week[wk] = d
            cur_last = self._last_by_week.get(wk)
            if cur_last is None or d > cur_last:
                self._last_by_week[wk] = d

    def scan(self, chain: OptionsChain, current_positions: list[Position]) -> list[Trade]:
        wk = _iso_week(chain.quote_date)
        first = self._first_by_week.get(wk)
        last = self._last_by_week.get(wk)
        if first is None or last is None:
            return []
        # Only enter on the week's first trading day.
        if chain.quote_date != first:
            return []
        # Need at least one later trading day in the week to target as expiration.
        if last <= chain.quote_date:
            return []
        target_dte = (last - chain.quote_date).days

        # Temporarily override DTE filter so the base strategy targets the
        # week's last trading day instead of its configured DTE.
        old_min = getattr(self.base, "min_dte", None)
        old_max = getattr(self.base, "max_dte", None)
        try:
            if old_min is not None:
                self.base.min_dte = target_dte
            if old_max is not None:
                self.base.max_dte = target_dte
            return self.base.scan(chain, current_positions)
        finally:
            if old_min is not None:
                self.base.min_dte = old_min
            if old_max is not None:
                self.base.max_dte = old_max

    def should_close(self, position: Position, chain: OptionsChain) -> CloseSignal | None:
        return self.base.should_close(position, chain)
