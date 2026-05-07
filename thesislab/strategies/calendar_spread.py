"""Calendar spread strategy - sell near-term, buy longer-term at same strike."""

from dataclasses import dataclass
from enum import Enum

from thesislab.domain import CloseSignal, ExitReason, Leg, OptionType, OptionsChain, Position, Trade
from thesislab.strategies.utils import find_current_contract, intrinsic_value, check_non_pnl_exits


class CalendarType(Enum):
    CALL = "call"
    PUT = "put"


@dataclass
class CalendarSpread:
    """Calendar (time) spread.

    Sell a near-term option, buy a longer-term option at the same strike.
    Profits from time decay differential and stable underlying price.
    """

    name: str = "CalendarSpread"
    calendar_type: CalendarType = CalendarType.CALL
    min_dte: int = 25
    max_dte: int = 45
    back_month_offset: int = 30  # additional DTE for the long leg
    max_positions: int = 1
    close_at_profit_pct: float = 0.50
    close_at_loss_pct: float = 1.00
    close_at_dte: int = 5  # close when front month is near expiry
    close_at_profit_enabled: bool = False
    close_at_loss_enabled: bool = False
    close_at_dte_enabled: bool = False
    close_on_short_breach: bool = False

    def scan(self, chain: OptionsChain, current_positions: list[Position]) -> list[Trade]:
        active = [p for p in current_positions if p.strategy_name == self.name]
        if len(active) >= self.max_positions:
            return []

        opt_type = OptionType.CALL if self.calendar_type == CalendarType.CALL else OptionType.PUT

        # Front month: near-term ATM
        front_candidates = chain.filter(
            option_type=opt_type,
            min_dte=self.min_dte,
            max_dte=self.max_dte,
        )
        if not front_candidates:
            return []

        # ATM option for the front month
        front = min(front_candidates, key=lambda c: abs(c.strike - chain.underlying_price))

        # Back month: same strike, longer expiry
        back_min_dte = front.dte(chain.quote_date) + 15
        back_candidates = chain.filter(
            option_type=opt_type,
            min_dte=back_min_dte,
        )
        if not back_candidates:
            return []

        # Same strike, furthest expiry within range
        same_strike = [c for c in back_candidates if c.strike == front.strike and c.expiration != front.expiration]
        if not same_strike:
            # Try closest strike
            same_strike = [c for c in back_candidates if c.expiration != front.expiration]
            if not same_strike:
                return []
            same_strike.sort(key=lambda c: (abs(c.strike - front.strike), -c.dte(chain.quote_date)))

        back = same_strike[0]

        legs = (
            Leg(contract=front, quantity=-1),  # sell front month
            Leg(contract=back, quantity=1),     # buy back month
        )
        net_debit = (back.mid - front.mid) * 100
        if net_debit <= 0:
            return []

        return [Trade(legs=legs, trade_date=chain.quote_date, net_premium=-net_debit)]

    def should_close(self, position: Position, chain: OptionsChain) -> CloseSignal | None:
        non_pnl = check_non_pnl_exits(
            position, chain,
            close_at_dte_enabled=self.close_at_dte_enabled, close_at_dte=self.close_at_dte,
            close_on_short_breach=self.close_on_short_breach,
        )
        if non_pnl is not None:
            return CloseSignal(self._close_position(position, chain), non_pnl)

        if not (self.close_at_profit_enabled or self.close_at_loss_enabled):
            return None

        current_value = self._current_value(position, chain)
        if current_value is None:
            return None

        entry_cost = abs(position.entry_trade.net_premium)
        if entry_cost == 0:
            return None

        pnl_pct = (current_value - entry_cost) / entry_cost

        if self.close_at_profit_enabled and pnl_pct >= self.close_at_profit_pct:
            return CloseSignal(self._close_position(position, chain), ExitReason.PROFIT_TARGET)

        if self.close_at_loss_enabled and pnl_pct <= -self.close_at_loss_pct:
            return CloseSignal(self._close_position(position, chain), ExitReason.STOP_LOSS)

        return None

    def _close_position(self, position: Position, chain: OptionsChain) -> Trade:
        close_legs = tuple(
            Leg(contract=leg.contract, quantity=-leg.quantity)
            for leg in position.entry_trade.legs
        )
        value = self._current_value(position, chain) or 0.0
        return Trade(legs=close_legs, trade_date=chain.quote_date, net_premium=value)

    def _current_value(self, position: Position, chain: OptionsChain) -> float | None:
        total = 0.0
        for leg in position.entry_trade.legs:
            current = find_current_contract(leg.contract, chain)
            if current is None:
                return None
            total += leg.quantity * current.mid * 100
        return total
