"""Strangle strategy - buy/sell OTM call + OTM put."""

from dataclasses import dataclass

from thesislab.domain import CloseSignal, ExitReason, Leg, OptionType, OptionsChain, Position, Trade
from thesislab.strategies.utils import find_current_contract, intrinsic_value, check_non_pnl_exits


@dataclass
class Strangle:
    """OTM call + OTM put at different strikes, same expiration.

    Long strangle: buy both legs (profits from large moves).
    Short strangle: sell both legs (profits from low volatility).
    """

    name: str = "Strangle"
    is_short: bool = False
    short_delta: float = 0.16
    min_dte: int = 25
    max_dte: int = 45
    max_positions: int = 1
    contracts_per_trade: int = 1
    close_at_profit_pct: float = 0.50
    close_at_loss_pct: float = 1.00
    close_at_dte: int = 7
    close_at_profit_enabled: bool = False
    close_at_loss_enabled: bool = False
    close_at_dte_enabled: bool = False
    close_on_short_breach: bool = False

    def scan(self, chain: OptionsChain, current_positions: list[Position]) -> list[Trade]:
        active = [p for p in current_positions if p.strategy_name == self.name]
        if len(active) >= self.max_positions:
            return []

        calls = chain.filter(
            option_type=OptionType.CALL,
            min_dte=self.min_dte,
            max_dte=self.max_dte,
            min_strike=chain.underlying_price,
        )
        puts = chain.filter(
            option_type=OptionType.PUT,
            min_dte=self.min_dte,
            max_dte=self.max_dte,
            max_strike=chain.underlying_price,
        )

        if not calls or not puts:
            return []

        # Find OTM call closest to target delta
        otm_call = min(calls, key=lambda c: abs((c.delta or 0) - self.short_delta))
        # Find OTM put closest to target delta (puts have negative delta)
        otm_put = min(puts, key=lambda c: abs(abs(c.delta or 0) - self.short_delta))

        if otm_call.delta is None or otm_put.delta is None:
            return []

        # Match expirations
        matching_puts = [
            p for p in puts
            if p.expiration == otm_call.expiration
        ]
        if matching_puts:
            otm_put = min(matching_puts, key=lambda c: abs(abs(c.delta or 0) - self.short_delta))

        n = self.contracts_per_trade
        qty = -n if self.is_short else n
        legs = (
            Leg(contract=otm_call, quantity=qty),
            Leg(contract=otm_put, quantity=qty),
        )

        total_premium = (otm_call.mid + otm_put.mid) * 100 * n
        if self.is_short:
            net_premium = total_premium  # credit received
        else:
            net_premium = -total_premium  # debit paid

        return [Trade(legs=legs, trade_date=chain.quote_date, net_premium=net_premium)]

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

        current_value = self._current_value(position, chain)
        if current_value is None:
            return None

        if self.is_short:
            entry_credit = position.entry_trade.net_premium
            if entry_credit <= 0:
                return None
            profit = entry_credit - current_value
            if self.close_at_profit_enabled and profit / entry_credit >= self.close_at_profit_pct:
                return CloseSignal(self._close_position(position, chain), ExitReason.PROFIT_TARGET)
            if self.close_at_loss_enabled and current_value / entry_credit >= (1 + self.close_at_loss_pct):
                return CloseSignal(self._close_position(position, chain), ExitReason.STOP_LOSS)
        else:
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
        premium = value if not self.is_short else -value
        return Trade(legs=close_legs, trade_date=chain.quote_date, net_premium=premium)

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

    def _current_value(self, position: Position, chain: OptionsChain) -> float | None:
        total = 0.0
        for leg in position.entry_trade.legs:
            current = find_current_contract(leg.contract, chain)
            if current is None:
                return None
            total += abs(leg.quantity) * current.mid * 100
        return total
