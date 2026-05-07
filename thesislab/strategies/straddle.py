"""Long straddle strategy - buy ATM call + ATM put."""

from dataclasses import dataclass

from thesislab.domain import CloseSignal, ExitReason, Leg, OptionType, OptionsChain, Position, Trade
from thesislab.strategies.utils import find_current_contract, intrinsic_value, check_non_pnl_exits


@dataclass
class Straddle:
    """Buy ATM call + ATM put on the same strike and expiration.

    Profits from large moves in either direction (long volatility).
    """

    name: str = "Straddle"
    min_dte: int = 25
    max_dte: int = 45
    max_positions: int = 1
    close_at_profit_pct: float = 0.50  # close at 50% profit
    close_at_loss_pct: float = 0.30  # cut loss at 30%
    close_at_dte: int = 7
    close_at_profit_enabled: bool = False
    close_at_loss_enabled: bool = False
    close_at_dte_enabled: bool = False
    close_on_short_breach: bool = False

    def scan(self, chain: OptionsChain, current_positions: list[Position]) -> list[Trade]:
        active = [p for p in current_positions if p.strategy_name == self.name]
        if len(active) >= self.max_positions:
            return []

        calls = chain.filter(option_type=OptionType.CALL, min_dte=self.min_dte, max_dte=self.max_dte)
        puts = chain.filter(option_type=OptionType.PUT, min_dte=self.min_dte, max_dte=self.max_dte)

        if not calls or not puts:
            return []

        # Find ATM call (strike closest to underlying price)
        atm_call = min(calls, key=lambda c: abs(c.strike - chain.underlying_price))
        # Find matching put at same strike and expiration
        matching_puts = [
            p for p in puts
            if p.strike == atm_call.strike and p.expiration == atm_call.expiration
        ]
        if not matching_puts:
            return []

        atm_put = matching_puts[0]
        legs = (
            Leg(contract=atm_call, quantity=1),
            Leg(contract=atm_put, quantity=1),
        )
        total_debit = (atm_call.mid + atm_put.mid) * 100
        return [Trade(legs=legs, trade_date=chain.quote_date, net_premium=-total_debit)]

    def should_close(self, position: Position, chain: OptionsChain) -> CloseSignal | None:
        non_pnl = check_non_pnl_exits(
            position, chain,
            close_at_dte_enabled=self.close_at_dte_enabled, close_at_dte=self.close_at_dte,
            close_on_short_breach=self.close_on_short_breach,
        )
        if non_pnl == ExitReason.EXPIRATION:
            return CloseSignal(self._close_at_intrinsic(position, chain), ExitReason.EXPIRATION)
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

    def _close_at_intrinsic(self, position: Position, chain: OptionsChain) -> Trade:
        close_legs = tuple(
            Leg(contract=leg.contract, quantity=-leg.quantity)
            for leg in position.entry_trade.legs
        )
        value = sum(
            intrinsic_value(leg.contract, chain.underlying_price) * abs(leg.quantity) * 100
            for leg in position.entry_trade.legs
        )
        return Trade(legs=close_legs, trade_date=chain.quote_date, net_premium=value)

    def _current_value(self, position: Position, chain: OptionsChain) -> float | None:
        total = 0.0
        for leg in position.entry_trade.legs:
            current = find_current_contract(leg.contract, chain)
            if current is None:
                return None
            total += abs(leg.quantity) * current.mid * 100
        return total

