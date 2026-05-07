"""Short straddle strategy - sell ATM call + ATM put."""

from dataclasses import dataclass

from thesislab.domain import CloseSignal, ExitReason, Leg, OptionType, OptionsChain, Position, Trade
from thesislab.strategies.utils import find_current_contract, intrinsic_value, check_non_pnl_exits


@dataclass
class ShortStraddle:
    """Sell ATM call + ATM put on the same strike and expiration.

    Profits from low volatility / range-bound price action (short volatility).
    """

    name: str = "ShortStraddle"
    min_dte: int = 25
    max_dte: int = 45
    max_positions: int = 1
    close_at_profit_pct: float = 0.50
    close_at_loss_pct: float = 2.00
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

        atm_call = min(calls, key=lambda c: abs(c.strike - chain.underlying_price))
        matching_puts = [
            p for p in puts
            if p.strike == atm_call.strike and p.expiration == atm_call.expiration
        ]
        if not matching_puts:
            return []

        atm_put = matching_puts[0]
        legs = (
            Leg(contract=atm_call, quantity=-1),
            Leg(contract=atm_put, quantity=-1),
        )
        total_credit = (atm_call.mid + atm_put.mid) * 100
        return [Trade(legs=legs, trade_date=chain.quote_date, net_premium=total_credit)]

    def should_close(self, position: Position, chain: OptionsChain) -> CloseSignal | None:
        non_pnl = check_non_pnl_exits(
            position, chain,
            close_at_dte_enabled=self.close_at_dte_enabled, close_at_dte=self.close_at_dte,
            close_on_short_breach=self.close_on_short_breach,
        )
        if non_pnl == ExitReason.EXPIRATION:
            return CloseSignal(self._close_at_expiration(position, chain), ExitReason.EXPIRATION)
        if non_pnl is not None:
            return CloseSignal(self._close_position(position, chain), non_pnl)

        if not (self.close_at_profit_enabled or self.close_at_loss_enabled):
            return None

        cost_to_close = self._cost_to_close(position, chain)
        if cost_to_close is None:
            return None

        entry_credit = position.entry_trade.net_premium
        if entry_credit <= 0:
            return None

        profit = entry_credit - cost_to_close
        if self.close_at_profit_enabled and profit / entry_credit >= self.close_at_profit_pct:
            return CloseSignal(self._close_position(position, chain), ExitReason.PROFIT_TARGET)

        if self.close_at_loss_enabled and cost_to_close / entry_credit >= (1 + self.close_at_loss_pct):
            return CloseSignal(self._close_position(position, chain), ExitReason.STOP_LOSS)

        return None

    def _close_position(self, position: Position, chain: OptionsChain) -> Trade:
        close_legs = tuple(
            Leg(contract=leg.contract, quantity=-leg.quantity)
            for leg in position.entry_trade.legs
        )
        cost = self._cost_to_close(position, chain) or 0.0
        return Trade(legs=close_legs, trade_date=chain.quote_date, net_premium=-cost)

    def _close_at_expiration(self, position: Position, chain: OptionsChain) -> Trade:
        close_legs = tuple(
            Leg(contract=leg.contract, quantity=-leg.quantity)
            for leg in position.entry_trade.legs
        )
        value = sum(
            leg.quantity * intrinsic_value(leg.contract, chain.underlying_price) * 100
            for leg in position.entry_trade.legs
        )
        return Trade(legs=close_legs, trade_date=chain.quote_date, net_premium=value)

    def _cost_to_close(self, position: Position, chain: OptionsChain) -> float | None:
        total = 0.0
        for leg in position.entry_trade.legs:
            current = find_current_contract(leg.contract, chain)
            if current is None:
                return None
            total += abs(leg.quantity) * current.mid * 100
        return total
