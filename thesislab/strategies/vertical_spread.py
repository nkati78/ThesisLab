"""Vertical spread strategy - bull put spread or bear call spread."""

from dataclasses import dataclass, field
from enum import Enum

from thesislab.domain import CloseSignal, ExitReason, Leg, OptionType, OptionsChain, Position, Trade
from thesislab.strategies.utils import find_current_contract, intrinsic_value, check_non_pnl_exits


class SpreadDirection(Enum):
    BULL = "bull"  # bull put spread (credit put spread)
    BEAR = "bear"  # bear call spread (credit call spread)


@dataclass
class VerticalSpread:
    """Credit vertical spread.

    BULL: Sell OTM put, buy further OTM put (bull put spread).
    BEAR: Sell OTM call, buy further OTM call (bear call spread).
    """

    name: str = "VerticalSpread"
    direction: SpreadDirection = SpreadDirection.BULL
    short_delta: float = 0.25
    spread_width: float = 5.0  # strike distance between legs
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
    entry_time: str = ""  # e.g. "10:00" - preferred entry time (for logging/filtering)

    def scan(self, chain: OptionsChain, current_positions: list[Position]) -> list[Trade]:
        active = [p for p in current_positions if p.strategy_name == self.name]
        if len(active) >= self.max_positions:
            return []

        if self.direction == SpreadDirection.BULL:
            return self._scan_bull_put(chain)
        else:
            return self._scan_bear_call(chain)

    def _scan_bull_put(self, chain: OptionsChain) -> list[Trade]:
        candidates = chain.filter(
            option_type=OptionType.PUT,
            min_dte=self.min_dte,
            max_dte=self.max_dte,
            max_strike=chain.underlying_price,
        )
        if not candidates:
            return []

        short_put = min(candidates, key=lambda c: abs(abs(c.delta or 0) - self.short_delta))
        if short_put.delta is None:
            return []

        long_strike = short_put.strike - self.spread_width
        long_put = self._find_closest(chain, OptionType.PUT, long_strike, short_put.expiration)
        if long_put is None:
            return []

        legs = (
            Leg(contract=short_put, quantity=-1),
            Leg(contract=long_put, quantity=1),
        )
        net_credit = (short_put.mid - long_put.mid) * 100
        if net_credit <= 0:
            return []
        return [Trade(legs=legs, trade_date=chain.quote_date, net_premium=net_credit)]

    def _scan_bear_call(self, chain: OptionsChain) -> list[Trade]:
        candidates = chain.filter(
            option_type=OptionType.CALL,
            min_dte=self.min_dte,
            max_dte=self.max_dte,
            min_strike=chain.underlying_price,
        )
        if not candidates:
            return []

        short_call = min(candidates, key=lambda c: abs((c.delta or 0) - self.short_delta))
        if short_call.delta is None:
            return []

        long_strike = short_call.strike + self.spread_width
        long_call = self._find_closest(chain, OptionType.CALL, long_strike, short_call.expiration)
        if long_call is None:
            return []

        legs = (
            Leg(contract=short_call, quantity=-1),
            Leg(contract=long_call, quantity=1),
        )
        net_credit = (short_call.mid - long_call.mid) * 100
        if net_credit <= 0:
            return []
        return [Trade(legs=legs, trade_date=chain.quote_date, net_premium=net_credit)]

    def should_close(self, position: Position, chain: OptionsChain) -> CloseSignal | None:
        non_pnl = check_non_pnl_exits(
            position, chain,
            close_at_dte_enabled=self.close_at_dte_enabled, close_at_dte=self.close_at_dte,
            close_on_short_breach=self.close_on_short_breach,
        )
        if non_pnl == ExitReason.EXPIRATION:
            return CloseSignal(self._close_at_expiration(position, chain), ExitReason.EXPIRATION)
        if non_pnl is not None:
            return CloseSignal(self._close_at_market(position, chain), non_pnl)

        if not (self.close_at_profit_enabled or self.close_at_loss_enabled):
            return None

        cost = self._cost_to_close(position, chain)
        if cost is None:
            return None

        entry_credit = position.entry_trade.net_premium
        if entry_credit <= 0:
            return None

        profit = entry_credit - cost
        if self.close_at_profit_enabled and profit / entry_credit >= self.close_at_profit_pct:
            return CloseSignal(self._close_at_market(position, chain), ExitReason.PROFIT_TARGET)

        if self.close_at_loss_enabled and cost / entry_credit >= (1 + self.close_at_loss_pct):
            return CloseSignal(self._close_at_market(position, chain), ExitReason.STOP_LOSS)

        return None

    def _close_at_market(self, position: Position, chain: OptionsChain) -> Trade:
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
        intrinsic = sum(
            leg.quantity * intrinsic_value(leg.contract, chain.underlying_price) * 100
            for leg in position.entry_trade.legs
        )
        return Trade(legs=close_legs, trade_date=chain.quote_date, net_premium=intrinsic)

    def _cost_to_close(self, position: Position, chain: OptionsChain) -> float | None:
        total = 0.0
        for leg in position.entry_trade.legs:
            current = find_current_contract(leg.contract, chain)
            if current is None:
                return None
            # For short legs we pay mid, for long legs we receive mid
            if leg.quantity < 0:
                total += current.mid * 100
            else:
                total -= current.mid * 100
        return max(total, 0.0)

    def _find_closest(self, chain, opt_type, target_strike, expiration):
        candidates = [
            c for c in chain.contracts
            if c.option_type == opt_type and c.expiration == expiration
        ]
        if not candidates:
            return None
        return min(candidates, key=lambda c: abs(c.strike - target_strike))

