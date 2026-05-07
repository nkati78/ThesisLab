"""Butterfly strategies - iron butterfly and long butterfly spreads."""

from dataclasses import dataclass
from enum import Enum

from thesislab.domain import CloseSignal, ExitReason, Leg, OptionType, OptionsChain, Position, Trade
from thesislab.strategies.utils import find_current_contract, intrinsic_value, check_non_pnl_exits


class ButterflyType(Enum):
    IRON = "iron"        # sell ATM straddle + buy OTM wings (credit)
    LONG_CALL = "call"   # buy 1 lower call, sell 2 middle calls, buy 1 upper call (debit)
    LONG_PUT = "put"     # buy 1 lower put, sell 2 middle puts, buy 1 upper put (debit)


@dataclass
class Butterfly:
    """Butterfly spread strategy.

    IRON: Sell ATM call + ATM put, buy OTM call wing + OTM put wing.
    LONG_CALL: Buy 1 lower call, sell 2 ATM calls, buy 1 upper call.
    LONG_PUT: Buy 1 lower put, sell 2 ATM puts, buy 1 upper put.
    """

    name: str = "Butterfly"
    butterfly_type: ButterflyType = ButterflyType.IRON
    wing_width: float = 5.0
    min_dte: int = 25
    max_dte: int = 45
    max_positions: int = 1
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

        if self.butterfly_type == ButterflyType.IRON:
            return self._scan_iron(chain)
        elif self.butterfly_type == ButterflyType.LONG_CALL:
            return self._scan_long_call(chain)
        else:
            return self._scan_long_put(chain)

    def _scan_iron(self, chain: OptionsChain) -> list[Trade]:
        """Sell ATM straddle, buy OTM wings."""
        calls = chain.filter(option_type=OptionType.CALL, min_dte=self.min_dte, max_dte=self.max_dte)
        puts = chain.filter(option_type=OptionType.PUT, min_dte=self.min_dte, max_dte=self.max_dte)

        if not calls or not puts:
            return []

        # ATM call and put
        atm_call = min(calls, key=lambda c: abs(c.strike - chain.underlying_price))
        matching_puts = [p for p in puts if p.strike == atm_call.strike and p.expiration == atm_call.expiration]
        if not matching_puts:
            return []
        atm_put = matching_puts[0]

        # OTM wings
        long_call = self._find_closest(chain, OptionType.CALL, atm_call.strike + self.wing_width, atm_call.expiration)
        long_put = self._find_closest(chain, OptionType.PUT, atm_put.strike - self.wing_width, atm_put.expiration)

        if long_call is None or long_put is None:
            return []

        legs = (
            Leg(contract=atm_call, quantity=-1),
            Leg(contract=atm_put, quantity=-1),
            Leg(contract=long_call, quantity=1),
            Leg(contract=long_put, quantity=1),
        )
        net_credit = (atm_call.mid + atm_put.mid - long_call.mid - long_put.mid) * 100
        if net_credit <= 0:
            return []

        return [Trade(legs=legs, trade_date=chain.quote_date, net_premium=net_credit)]

    def _scan_long_call(self, chain: OptionsChain) -> list[Trade]:
        """Buy 1 lower call, sell 2 middle calls, buy 1 upper call."""
        calls = chain.filter(option_type=OptionType.CALL, min_dte=self.min_dte, max_dte=self.max_dte)
        if not calls:
            return []

        # Middle strike: ATM
        mid_call = min(calls, key=lambda c: abs(c.strike - chain.underlying_price))
        lower_call = self._find_closest(chain, OptionType.CALL, mid_call.strike - self.wing_width, mid_call.expiration)
        upper_call = self._find_closest(chain, OptionType.CALL, mid_call.strike + self.wing_width, mid_call.expiration)

        if lower_call is None or upper_call is None:
            return []

        legs = (
            Leg(contract=lower_call, quantity=1),
            Leg(contract=mid_call, quantity=-2),
            Leg(contract=upper_call, quantity=1),
        )
        net_debit = (lower_call.mid - 2 * mid_call.mid + upper_call.mid) * 100
        if net_debit <= 0:
            return []

        return [Trade(legs=legs, trade_date=chain.quote_date, net_premium=-net_debit)]

    def _scan_long_put(self, chain: OptionsChain) -> list[Trade]:
        """Buy 1 lower put, sell 2 middle puts, buy 1 upper put."""
        puts = chain.filter(option_type=OptionType.PUT, min_dte=self.min_dte, max_dte=self.max_dte)
        if not puts:
            return []

        mid_put = min(puts, key=lambda c: abs(c.strike - chain.underlying_price))
        lower_put = self._find_closest(chain, OptionType.PUT, mid_put.strike - self.wing_width, mid_put.expiration)
        upper_put = self._find_closest(chain, OptionType.PUT, mid_put.strike + self.wing_width, mid_put.expiration)

        if lower_put is None or upper_put is None:
            return []

        legs = (
            Leg(contract=lower_put, quantity=1),
            Leg(contract=mid_put, quantity=-2),
            Leg(contract=upper_put, quantity=1),
        )
        net_debit = (lower_put.mid - 2 * mid_put.mid + upper_put.mid) * 100
        if net_debit <= 0:
            return []

        return [Trade(legs=legs, trade_date=chain.quote_date, net_premium=-net_debit)]

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

        entry_premium = position.entry_trade.net_premium
        is_credit = entry_premium > 0

        if is_credit:
            profit = entry_premium - cost_to_close
            if self.close_at_profit_enabled and profit / entry_premium >= self.close_at_profit_pct:
                return CloseSignal(self._close_position(position, chain), ExitReason.PROFIT_TARGET)
            if self.close_at_loss_enabled and cost_to_close / entry_premium >= (1 + self.close_at_loss_pct):
                return CloseSignal(self._close_position(position, chain), ExitReason.STOP_LOSS)
        else:
            entry_cost = abs(entry_premium)
            if entry_cost == 0:
                return None
            current_val = self._current_spread_value(position, chain)
            if current_val is None:
                return None
            pnl_pct = (current_val - entry_cost) / entry_cost
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

    def _current_spread_value(self, position: Position, chain: OptionsChain) -> float | None:
        total = 0.0
        for leg in position.entry_trade.legs:
            current = find_current_contract(leg.contract, chain)
            if current is None:
                return None
            total += leg.quantity * current.mid * 100
        return total

    def _find_closest(self, chain, opt_type, target_strike, expiration):
        candidates = [
            c for c in chain.contracts
            if c.option_type == opt_type and c.expiration == expiration
        ]
        if not candidates:
            return None
        return min(candidates, key=lambda c: abs(c.strike - target_strike))
