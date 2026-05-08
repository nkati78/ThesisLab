"""Debit vertical spread strategy - bull call spread or bear put spread."""

from dataclasses import dataclass
from enum import Enum

from thesislab.domain import CloseSignal, ExitReason, Leg, OptionType, OptionsChain, Position, Trade
from thesislab.strategies.utils import find_current_contract, intrinsic_value, check_non_pnl_exits


class DebitDirection(Enum):
    BULL = "bull"   # bull call spread: buy lower call, sell higher call
    BEAR = "bear"   # bear put spread: buy higher put, sell lower put


@dataclass
class DebitSpread:
    """Debit vertical spread.

    BULL: Buy ATM/near-ATM call, sell further OTM call (bull call spread).
    BEAR: Buy ATM/near-ATM put, sell further OTM put (bear put spread).
    """

    name: str = "DebitSpread"
    direction: DebitDirection = DebitDirection.BULL
    short_delta: float = 0.25
    spread_width: float = 5.0
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

        if self.direction == DebitDirection.BULL:
            return self._scan_bull_call(chain)
        else:
            return self._scan_bear_put(chain)

    def _scan_bull_call(self, chain: OptionsChain) -> list[Trade]:
        """Buy lower strike call, sell higher strike call."""
        candidates = chain.filter(
            option_type=OptionType.CALL,
            min_dte=self.min_dte,
            max_dte=self.max_dte,
            min_strike=chain.underlying_price * 0.95,
        )
        if not candidates:
            return []

        # Long call: near the money, closest to target delta
        long_call = min(candidates, key=lambda c: abs(abs(c.delta or 0) - (1 - self.short_delta)))
        if long_call.delta is None:
            return []

        short_strike = long_call.strike + self.spread_width
        short_call = self._find_closest(chain, OptionType.CALL, short_strike, long_call.expiration)
        if short_call is None:
            return []

        n = self.contracts_per_trade
        legs = (
            Leg(contract=long_call, quantity=n),
            Leg(contract=short_call, quantity=-n),
        )
        net_debit = (long_call.mid - short_call.mid) * 100 * n
        if net_debit <= 0:
            return []
        return [Trade(legs=legs, trade_date=chain.quote_date, net_premium=-net_debit)]

    def _scan_bear_put(self, chain: OptionsChain) -> list[Trade]:
        """Buy higher strike put, sell lower strike put."""
        candidates = chain.filter(
            option_type=OptionType.PUT,
            min_dte=self.min_dte,
            max_dte=self.max_dte,
            max_strike=chain.underlying_price * 1.05,
        )
        if not candidates:
            return []

        long_put = min(candidates, key=lambda c: abs(abs(c.delta or 0) - (1 - self.short_delta)))
        if long_put.delta is None:
            return []

        short_strike = long_put.strike - self.spread_width
        short_put = self._find_closest(chain, OptionType.PUT, short_strike, long_put.expiration)
        if short_put is None:
            return []

        n = self.contracts_per_trade
        legs = (
            Leg(contract=long_put, quantity=n),
            Leg(contract=short_put, quantity=-n),
        )
        net_debit = (long_put.mid - short_put.mid) * 100 * n
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
