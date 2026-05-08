"""Covered call strategy - sell OTM calls against underlying holdings."""

from dataclasses import dataclass

from thesislab.domain import CloseSignal, ExitReason, Leg, OptionType, OptionsChain, Position, Trade
from thesislab.strategies.utils import find_current_contract, intrinsic_value, check_non_pnl_exits


@dataclass
class CoveredCall:
    """Sell OTM calls targeting a specific delta, within a DTE window.

    Assumes the underlying shares are held externally (not tracked by the portfolio).
    P&L reflects only the options premium collected/returned.
    """

    name: str = "CoveredCall"
    delta_target: float = 0.30
    min_dte: int = 25
    max_dte: int = 45
    max_positions: int = 1
    contracts_per_trade: int = 1
    close_at_profit_pct: float = 0.50  # close when 50% of max profit captured
    close_at_dte: int = 7  # close when 7 DTE remaining
    close_at_profit_enabled: bool = False
    close_at_dte_enabled: bool = False
    close_on_short_breach: bool = False
    # Covered call has no close_at_loss; included for schema parity
    close_at_loss_pct: float = 0.0
    close_at_loss_enabled: bool = False

    def scan(self, chain: OptionsChain, current_positions: list[Position]) -> list[Trade]:
        active = [p for p in current_positions if p.strategy_name == self.name]
        if len(active) >= self.max_positions:
            return []

        # Find OTM calls in the DTE window
        candidates = chain.filter(
            option_type=OptionType.CALL,
            min_dte=self.min_dte,
            max_dte=self.max_dte,
            min_strike=chain.underlying_price,
        )
        if not candidates:
            return []

        # Pick the call closest to target delta
        best = min(candidates, key=lambda c: abs((c.delta or 0) - self.delta_target))
        if best.delta is None:
            return []

        n = self.contracts_per_trade
        leg = Leg(contract=best, quantity=-n)
        premium = best.mid * 100 * n  # credit received
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

        if self.close_at_profit_enabled and current is not None:
            entry_credit = position.entry_trade.net_premium
            n = abs(entry_leg.quantity) or 1
            cost_to_close = current.mid * 100 * n
            profit_captured = entry_credit - cost_to_close
            max_profit = entry_credit
            if max_profit > 0 and profit_captured / max_profit >= self.close_at_profit_pct:
                return CloseSignal(self._closing_trade(entry_leg, chain, current.mid), ExitReason.PROFIT_TARGET)

        return None

    def _closing_trade(self, entry_leg: Leg, chain: OptionsChain, price: float) -> Trade:
        """Create a trade to close the position (buy back the short call)."""
        close_leg = Leg(contract=entry_leg.contract, quantity=-entry_leg.quantity)
        n = abs(entry_leg.quantity) or 1
        return Trade(
            legs=(close_leg,),
            trade_date=chain.quote_date,
            net_premium=-price * 100 * n,  # debit to close
        )

