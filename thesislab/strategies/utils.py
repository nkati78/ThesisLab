"""Shared utility functions for strategy implementations."""

from thesislab.domain import OptionType, OptionsChain, OptionContract, Leg, Position


def find_current_contract(contract: OptionContract, chain: OptionsChain) -> OptionContract | None:
    """Find the same contract in the current chain by strike/expiry/type."""
    for c in chain.contracts:
        if (
            c.strike == contract.strike
            and c.expiration == contract.expiration
            and c.option_type == contract.option_type
        ):
            return c
    return None


def intrinsic_value(contract: OptionContract, underlying_price: float) -> float:
    """Calculate intrinsic value of a contract."""
    if contract.option_type == OptionType.CALL:
        return max(0.0, underlying_price - contract.strike)
    return max(0.0, contract.strike - underlying_price)


def check_non_pnl_exits(
    position: Position,
    chain: OptionsChain,
    *,
    close_at_dte_enabled: bool,
    close_at_dte: int,
    close_on_short_breach: bool,
):
    """Check the exits that don't depend on P&L: expiration, DTE limit, breach.
    Returns the ExitReason if one fires, else None. Always checks expiration
    (DTE <= 0) regardless of enables — that's a hard stop."""
    from thesislab.domain import ExitReason
    dte = min(leg.contract.dte(chain.quote_date) for leg in position.entry_trade.legs)
    if dte <= 0:
        return ExitReason.EXPIRATION
    if close_on_short_breach and is_short_strike_breached(position, chain.underlying_price):
        return ExitReason.SHORT_BREACH
    if close_at_dte_enabled and dte <= close_at_dte:
        return ExitReason.DTE_LIMIT
    return None


def is_short_strike_breached(position: Position, underlying_price: float) -> bool:
    """True if the underlying has crossed any short strike's threshold.

    For a short put leg: breach when underlying < strike (price below the put).
    For a short call leg: breach when underlying > strike (price above the call).
    Long-only positions (e.g., long call, debit spread) have no shorts and so
    can never be breached — returns False.
    """
    for leg in position.entry_trade.legs:
        if leg.quantity >= 0:
            continue
        if leg.contract.option_type == OptionType.PUT and underlying_price < leg.contract.strike:
            return True
        if leg.contract.option_type == OptionType.CALL and underlying_price > leg.contract.strike:
            return True
    return False
