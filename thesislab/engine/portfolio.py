"""Portfolio management - position tracking, cash, and P&L accounting."""

from datetime import date

from thesislab.domain import ClosedPosition, ExitReason, Leg, OptionsChain, Position, Trade


MULTIPLIER = 100  # standard options multiplier


class Portfolio:
    """Tracks open positions, closed positions, cash, and daily equity."""

    def __init__(self, starting_cash: float, commission_per_contract: float = 0.65) -> None:
        self.cash: float = starting_cash
        self.starting_cash: float = starting_cash
        self.commission_per_contract: float = commission_per_contract
        self.open_positions: list[Position] = []
        self.closed_positions: list[ClosedPosition] = []
        self.equity_curve: dict[date, float] = {}

    def open(self, trade: Trade, strategy_name: str, underlying_price: float = 0.0) -> Position:
        """Record a new position. Adjust cash by net premium minus commission."""
        commission = self._calc_commission(trade)
        self.cash += trade.net_premium - commission

        position = Position(
            entry_trade=Trade(
                legs=trade.legs,
                trade_date=trade.trade_date,
                net_premium=trade.net_premium,
                commission=commission,
            ),
            strategy_name=strategy_name,
            entry_underlying_price=underlying_price,
        )
        self.open_positions.append(position)
        return position

    def close(
        self,
        position: Position,
        closing_trade: Trade,
        exit_reason: ExitReason = ExitReason.EXPIRATION,
        entry_underlying_price: float = 0.0,
        exit_underlying_price: float = 0.0,
    ) -> ClosedPosition:
        """Close a position. Adjust cash. Move to closed_positions."""
        commission = self._calc_commission(closing_trade)
        self.cash += closing_trade.net_premium - commission

        entry_premium = position.entry_trade.net_premium
        exit_premium = closing_trade.net_premium
        total_commission = position.entry_trade.commission + commission
        realized_pnl = entry_premium + exit_premium - total_commission

        holding_days = (closing_trade.trade_date - position.entry_trade.trade_date).days

        # Position size in "strategy units" — for a vertical spread of 10
        # contracts, each leg's |qty| is 10, so we want 10 (not 20). Using
        # min(|qty|) extracts the per-strategy quantity correctly across
        # all leg ratios (1:1 spreads, 1:2:1 butterflies, etc.).
        contracts = min(abs(leg.quantity) for leg in position.entry_trade.legs) \
            if position.entry_trade.legs else 0
        notional = abs(position.entry_trade.net_premium)

        # Compute net greeks at entry
        entry_delta: float | None = None
        entry_theta: float | None = None
        entry_vega: float | None = None
        has_greeks = any(leg.contract.delta is not None for leg in position.entry_trade.legs)
        if has_greeks:
            entry_delta = sum(
                leg.quantity * (leg.contract.delta or 0.0)
                for leg in position.entry_trade.legs
            )
            entry_theta = sum(
                leg.quantity * (leg.contract.theta or 0.0)
                for leg in position.entry_trade.legs
            )
            entry_vega = sum(
                leg.quantity * (leg.contract.vega or 0.0)
                for leg in position.entry_trade.legs
            )

        closed = ClosedPosition(
            entry_trade=position.entry_trade,
            exit_trade=Trade(
                legs=closing_trade.legs,
                trade_date=closing_trade.trade_date,
                net_premium=closing_trade.net_premium,
                commission=commission,
            ),
            strategy_name=position.strategy_name,
            realized_pnl=realized_pnl,
            holding_days=holding_days,
            exit_reason=exit_reason,
            entry_underlying_price=entry_underlying_price,
            exit_underlying_price=exit_underlying_price,
            contracts=contracts,
            notional_value=notional,
            entry_delta=entry_delta,
            entry_theta=entry_theta,
            entry_vega=entry_vega,
        )
        self.open_positions.remove(position)
        self.closed_positions.append(closed)
        return closed

    def mark_to_market(self, on_date: date, chain: OptionsChain) -> float:
        """Estimate current portfolio value using mid prices from the chain.

        Returns total equity (cash + unrealized value of open positions).
        """
        unrealized = 0.0
        for position in self.open_positions:
            unrealized += self._estimate_position_value(position, chain)

        total_equity = self.cash + unrealized
        self.equity_curve[on_date] = total_equity
        return total_equity

    def _estimate_position_value(self, position: Position, chain: OptionsChain) -> float:
        """Estimate the current market value of an open position."""
        value = 0.0
        for leg in position.entry_trade.legs:
            current_contract = self._find_matching_contract(leg, chain)
            if current_contract:
                # Value = quantity * current_mid * multiplier
                # For short positions (negative quantity), this gives negative value
                # which represents the cost to close
                value += leg.quantity * current_contract.mid * MULTIPLIER
            else:
                # Contract not found in current chain - use intrinsic value
                value += self._intrinsic_value(leg, chain.underlying_price)
        return value

    def _find_matching_contract(self, leg: Leg, chain: OptionsChain) -> object | None:
        """Find the same contract in the current chain by strike/expiry/type."""
        for c in chain.contracts:
            if (
                c.strike == leg.contract.strike
                and c.expiration == leg.contract.expiration
                and c.option_type == leg.contract.option_type
            ):
                return c
        return None

    def _intrinsic_value(self, leg: Leg, underlying_price: float) -> float:
        """Calculate intrinsic value when contract isn't in the chain."""
        from thesislab.domain import OptionType

        contract = leg.contract
        if contract.option_type == OptionType.CALL:
            intrinsic = max(0.0, underlying_price - contract.strike)
        else:
            intrinsic = max(0.0, contract.strike - underlying_price)
        return leg.quantity * intrinsic * MULTIPLIER

    def _calc_commission(self, trade: Trade) -> float:
        total_contracts = sum(abs(leg.quantity) for leg in trade.legs)
        return total_contracts * self.commission_per_contract
