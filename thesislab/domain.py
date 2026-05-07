"""Core domain types for the options backtesting system."""

from dataclasses import dataclass, field
from datetime import date
from enum import Enum


class OptionType(Enum):
    CALL = "call"
    PUT = "put"


class ExitReason(Enum):
    PROFIT_TARGET = "profit_target"
    STOP_LOSS = "stop_loss"
    DTE_LIMIT = "dte_limit"
    EXPIRATION = "expiration"
    SHORT_BREACH = "short_breach"


@dataclass(frozen=True)
class OptionContract:
    """A single options contract at a point in time."""

    underlying: str
    expiration: date
    strike: float
    option_type: OptionType
    bid: float
    ask: float
    last: float
    volume: int
    open_interest: int
    implied_volatility: float
    delta: float | None = None
    gamma: float | None = None
    theta: float | None = None
    vega: float | None = None

    @property
    def mid(self) -> float:
        return (self.bid + self.ask) / 2

    def dte(self, as_of: date) -> int:
        return (self.expiration - as_of).days


@dataclass(frozen=True)
class OptionsChain:
    """All available contracts for one underlying on one date."""

    underlying: str
    quote_date: date
    underlying_price: float
    contracts: tuple[OptionContract, ...]

    def calls(self) -> list[OptionContract]:
        return [c for c in self.contracts if c.option_type == OptionType.CALL]

    def puts(self) -> list[OptionContract]:
        return [c for c in self.contracts if c.option_type == OptionType.PUT]

    def filter(
        self,
        *,
        option_type: OptionType | None = None,
        min_dte: int | None = None,
        max_dte: int | None = None,
        min_strike: float | None = None,
        max_strike: float | None = None,
        min_delta: float | None = None,
        max_delta: float | None = None,
    ) -> list[OptionContract]:
        results = list(self.contracts)
        if option_type is not None:
            results = [c for c in results if c.option_type == option_type]
        if min_dte is not None:
            results = [c for c in results if c.dte(self.quote_date) >= min_dte]
        if max_dte is not None:
            results = [c for c in results if c.dte(self.quote_date) <= max_dte]
        if min_strike is not None:
            results = [c for c in results if c.strike >= min_strike]
        if max_strike is not None:
            results = [c for c in results if c.strike <= max_strike]
        if min_delta is not None:
            results = [c for c in results if c.delta is not None and c.delta >= min_delta]
        if max_delta is not None:
            results = [c for c in results if c.delta is not None and c.delta <= max_delta]
        return results


@dataclass(frozen=True)
class Leg:
    """One leg of a multi-leg position. Quantity is signed: +1 = long, -1 = short."""

    contract: OptionContract
    quantity: int

    @property
    def is_long(self) -> bool:
        return self.quantity > 0

    @property
    def is_short(self) -> bool:
        return self.quantity < 0


@dataclass(frozen=True)
class Trade:
    """A complete trade event (open or close)."""

    legs: tuple[Leg, ...]
    trade_date: date
    net_premium: float  # positive = credit received, negative = debit paid
    commission: float = 0.0


@dataclass(frozen=True)
class CloseSignal:
    """Bundles a closing trade with the reason for exit."""

    trade: Trade
    reason: ExitReason


@dataclass
class Position:
    """An open position being tracked by the portfolio."""

    entry_trade: Trade
    strategy_name: str
    tag: str = ""
    entry_underlying_price: float = 0.0


@dataclass
class ClosedPosition:
    """A position that has been fully closed."""

    entry_trade: Trade
    exit_trade: Trade
    strategy_name: str
    realized_pnl: float
    holding_days: int
    # Enriched fields
    exit_reason: ExitReason = ExitReason.EXPIRATION
    entry_underlying_price: float = 0.0
    exit_underlying_price: float = 0.0
    contracts: int = 1
    notional_value: float = 0.0
    entry_delta: float | None = None
    entry_theta: float | None = None
    entry_vega: float | None = None
