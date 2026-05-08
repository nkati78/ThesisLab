"""Protective put strategy - buy OTM puts to hedge downside risk."""

from dataclasses import dataclass

from thesislab.domain import CloseSignal, ExitReason, Leg, OptionType, OptionsChain, Position, Trade
from thesislab.strategies.utils import find_current_contract, intrinsic_value, check_non_pnl_exits


@dataclass
class ProtectivePut:
    """Buy OTM puts as portfolio insurance.

    Targets puts at a specific delta (e.g., -0.20) within a DTE window.
    Closes when profit target is hit, DTE threshold reached, or at expiration.
    """

    name: str = "ProtectivePut"
    delta_target: float = -0.20
    min_dte: int = 25
    max_dte: int = 45
    max_positions: int = 1
    contracts_per_trade: int = 1
    close_at_profit_pct: float = 1.00  # close at 100% profit (put doubled)
    close_at_dte: int = 7
    close_at_loss_pct: float = 0.50  # cut loss at 50%
    close_at_profit_enabled: bool = False
    close_at_loss_enabled: bool = False
    close_at_dte_enabled: bool = False
    close_on_short_breach: bool = False

    def scan(self, chain: OptionsChain, current_positions: list[Position]) -> list[Trade]:
        active = [p for p in current_positions if p.strategy_name == self.name]
        if len(active) >= self.max_positions:
            return []

        candidates = chain.filter(
            option_type=OptionType.PUT,
            min_dte=self.min_dte,
            max_dte=self.max_dte,
            max_strike=chain.underlying_price,
        )
        if not candidates:
            return []

        best = min(candidates, key=lambda c: abs((c.delta or 0) - self.delta_target))
        if best.delta is None:
            return []

        n = self.contracts_per_trade
        leg = Leg(contract=best, quantity=n)
        premium = -best.mid * 100 * n  # debit paid
        return [Trade(legs=(leg,), trade_date=chain.quote_date, net_premium=premium)]

    def should_close(self, position: Position, chain: OptionsChain) -> CloseSignal | None:
        entry_leg = position.entry_trade.legs[0]
        contract = entry_leg.contract
        current = find_current_contract(contract, chain)

        non_pnl = check_non_pnl_exits(
            position, chain,
            close_at_dte_enabled=self.close_at_dte_enabled, close_at_dte=self.close_at_dte,
            close_on_short_breach=self.close_on_short_breach,
        )
        if non_pnl == ExitReason.EXPIRATION:
            close_price = intrinsic_value(contract, chain.underlying_price) if current is None else current.mid
            return CloseSignal(self._closing_trade(entry_leg, chain, close_price), ExitReason.EXPIRATION)
        if non_pnl is not None and current is not None:
            return CloseSignal(self._closing_trade(entry_leg, chain, current.mid), non_pnl)

        if current is None:
            return None

        if not (self.close_at_profit_enabled or self.close_at_loss_enabled):
            return None

        n = abs(entry_leg.quantity) or 1
        entry_cost = abs(position.entry_trade.net_premium)
        current_value = current.mid * 100 * n

        if entry_cost > 0:
            profit_pct = (current_value - entry_cost) / entry_cost
            if self.close_at_profit_enabled and profit_pct >= self.close_at_profit_pct:
                return CloseSignal(self._closing_trade(entry_leg, chain, current.mid), ExitReason.PROFIT_TARGET)

            loss_pct = (entry_cost - current_value) / entry_cost
            if self.close_at_loss_enabled and loss_pct >= self.close_at_loss_pct:
                return CloseSignal(self._closing_trade(entry_leg, chain, current.mid), ExitReason.STOP_LOSS)

        return None

    def _closing_trade(self, entry_leg: Leg, chain: OptionsChain, price: float) -> Trade:
        close_leg = Leg(contract=entry_leg.contract, quantity=-entry_leg.quantity)
        n = abs(entry_leg.quantity) or 1
        return Trade(
            legs=(close_leg,),
            trade_date=chain.quote_date,
            net_premium=price * 100 * n,  # credit from selling
        )

