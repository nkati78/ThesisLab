"""Main backtesting loop."""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass, field
from datetime import date

from thesislab.analytics.metrics import BacktestResult
from thesislab.data.provider import DataProvider
from thesislab.engine.portfolio import Portfolio
from thesislab.filters import EntryExitFilters
from thesislab.indicators import IndicatorEngine, IndicatorValues
from thesislab.strategies.base import Strategy


@dataclass
class BacktestConfig:
    """Configuration for a backtest run."""

    ticker: str
    start_date: date
    end_date: date
    starting_cash: float = 100_000.0
    commission_per_contract: float = 0.65


class Backtester:
    """Runs a backtest over historical data with one or more strategies."""

    def __init__(
        self,
        config: BacktestConfig,
        provider: DataProvider,
        strategies: Sequence[Strategy],
        filters: EntryExitFilters | None = None,
    ) -> None:
        self.config = config
        self.provider = provider
        self.strategies = strategies
        self.filters = filters or EntryExitFilters()
        self.portfolio = Portfolio(config.starting_cash, config.commission_per_contract)
        self.indicator_engine = IndicatorEngine()
        self.indicator_history: dict[date, IndicatorValues] = {}

    def run(self) -> BacktestResult:
        """Execute the backtest and return results."""
        dates = self.provider.get_trading_dates(
            self.config.ticker, self.config.start_date, self.config.end_date
        )

        for current_date in dates:
            chain = self.provider.get_chain(self.config.ticker, current_date)
            if chain is None:
                continue

            # Update indicators
            indicators = self.indicator_engine.update(current_date, chain.underlying_price)
            self.indicator_history[current_date] = indicators

            # Phase 1: Check exits on all open positions
            for position in list(self.portfolio.open_positions):
                strategy = self._strategy_by_name(position.strategy_name)
                if strategy is None:
                    continue
                if not self.filters.can_exit(indicators):
                    continue
                close_signal = strategy.should_close(position, chain)
                if close_signal is not None:
                    self.portfolio.close(
                        position,
                        close_signal.trade,
                        exit_reason=close_signal.reason,
                        entry_underlying_price=position.entry_underlying_price,
                        exit_underlying_price=chain.underlying_price,
                    )

            # Phase 2: Check entries (only if filters allow)
            if self.filters.can_enter(indicators, current_date=current_date):
                for strategy in self.strategies:
                    new_trades = strategy.scan(chain, self.portfolio.open_positions)
                    for trade in new_trades:
                        self.portfolio.open(trade, strategy.name, underlying_price=chain.underlying_price)

            # Phase 3: Mark to market
            self.portfolio.mark_to_market(current_date, chain)

        return BacktestResult(
            equity_curve=dict(self.portfolio.equity_curve),
            closed_positions=list(self.portfolio.closed_positions),
            open_positions=list(self.portfolio.open_positions),
            starting_cash=self.config.starting_cash,
            indicator_history=dict(self.indicator_history),
        )

    def _strategy_by_name(self, name: str) -> Strategy | None:
        for s in self.strategies:
            if s.name == name:
                return s
        return None
