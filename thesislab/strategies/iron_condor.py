"""Iron condor strategy - sell OTM put spread + OTM call spread."""

from dataclasses import dataclass

from thesislab.domain import CloseSignal, ExitReason, Leg, OptionType, OptionsChain, Position, Trade
from thesislab.strategies.utils import find_current_contract, intrinsic_value, check_non_pnl_exits


@dataclass
class IronCondor:
    """Sell an iron condor: short OTM put + long further OTM put +
    short OTM call + long further OTM call.

    Profits from low volatility / range-bound price action.
    """

    name: str = "IronCondor"
    short_delta: float = 0.16  # ~1 std dev
    wing_width: float = 5.0  # strike distance between short and long legs
    min_dte: int = 30
    max_dte: int = 50
    max_positions: int = 1
    close_at_profit_pct: float = 0.50
    close_at_loss_pct: float = 2.00  # close at 2x credit received
    close_at_dte: int = 10
    close_at_profit_enabled: bool = False
    close_at_loss_enabled: bool = False
    close_at_dte_enabled: bool = False
    close_on_short_breach: bool = False

    def scan(self, chain: OptionsChain, current_positions: list[Position]) -> list[Trade]:
        active = [p for p in current_positions if p.strategy_name == self.name]
        if len(active) >= self.max_positions:
            return []

        # Find short put (OTM, negative delta near target)
        put_candidates = chain.filter(
            option_type=OptionType.PUT,
            min_dte=self.min_dte,
            max_dte=self.max_dte,
            max_strike=chain.underlying_price,
        )
        call_candidates = chain.filter(
            option_type=OptionType.CALL,
            min_dte=self.min_dte,
            max_dte=self.max_dte,
            min_strike=chain.underlying_price,
        )

        if not put_candidates or not call_candidates:
            return []

        # Short put: closest to -short_delta
        short_put = min(put_candidates, key=lambda c: abs(abs(c.delta or 0) - self.short_delta))
        # Short call: closest to +short_delta
        short_call = min(call_candidates, key=lambda c: abs((c.delta or 0) - self.short_delta))

        if short_put.delta is None or short_call.delta is None:
            return []

        # Long wings
        long_put = self._find_wing(chain, OptionType.PUT, short_put.strike - self.wing_width, short_put.expiration)
        long_call = self._find_wing(chain, OptionType.CALL, short_call.strike + self.wing_width, short_call.expiration)

        if long_put is None or long_call is None:
            return []

        legs = (
            Leg(contract=short_put, quantity=-1),
            Leg(contract=long_put, quantity=1),
            Leg(contract=short_call, quantity=-1),
            Leg(contract=long_call, quantity=1),
        )
        net_credit = (short_put.mid + short_call.mid - long_put.mid - long_call.mid) * 100
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
            total += abs(leg.quantity) * current.mid * 100
        return total

    def _find_wing(self, chain: OptionsChain, opt_type: OptionType, target_strike: float, expiration):
        candidates = [
            c for c in chain.contracts
            if c.option_type == opt_type and c.expiration == expiration
        ]
        if not candidates:
            return None
        return min(candidates, key=lambda c: abs(c.strike - target_strike))

