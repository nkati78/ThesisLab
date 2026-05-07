"""Pydantic models for API request/response."""

from __future__ import annotations

from pydantic import BaseModel


class TimeOfDayFilterConfig(BaseModel):
    enabled: bool = False
    entry_start: str = "09:30"
    entry_end: str = "16:00"
    exit_start: str = "09:30"
    exit_end: str = "16:00"


class RSIFilterConfig(BaseModel):
    enabled: bool = False
    rsi_min: int = 20
    rsi_max: int = 80
    rsi_zone: str = "any"  # "any", "oversold", "neutral", "overbought"


class BollingerFilterConfig(BaseModel):
    enabled: bool = False
    position: str = "any"  # "any", "below_lower", "lower_half", "upper_half", "above_upper"
    use_pct_b: bool = False
    pct_b_min: float = 0.0
    pct_b_max: float = 0.2


class MAFilterConfig(BaseModel):
    enabled: bool = False
    sma_20: str = "ignore"  # "ignore", "above", "below"
    sma_50: str = "ignore"
    sma_200: str = "ignore"
    ema_9: str = "ignore"
    ema_21: str = "ignore"
    sma_cross: str = "ignore"  # "ignore", "bullish", "bearish"


class VWAPFilterConfig(BaseModel):
    enabled: bool = False
    direction: str = "above"  # "above", "below"


class AdvancedFilters(BaseModel):
    time_of_day: TimeOfDayFilterConfig = TimeOfDayFilterConfig()
    rsi: RSIFilterConfig = RSIFilterConfig()
    bollinger: BollingerFilterConfig = BollingerFilterConfig()
    moving_average: MAFilterConfig = MAFilterConfig()
    vwap: VWAPFilterConfig = VWAPFilterConfig()


class StrategyConfig(BaseModel):
    type: str  # "short_put_spread", "short_call_spread", "covered_call", etc.
    min_dte: int = 25
    max_dte: int = 45
    short_delta: float = 0.25
    spread_width: float = 5.0
    max_positions: int = 1
    close_at_profit_pct: float = 0.50
    close_at_loss_pct: float = 2.0
    close_at_dte: int = 7
    # Per-criterion enable flags — defaults OFF so positions hold to expiration
    # unless the user explicitly opts into one or more exit rules.
    close_at_profit_enabled: bool = False
    close_at_loss_enabled: bool = False
    close_at_dte_enabled: bool = False
    close_on_short_breach: bool = False
    entry_dow: str = "any"  # "any", "monday", "tuesday", "wednesday", "thursday", "friday"
    # Protective put specific
    put_delta: float = -0.20
    # Iron condor specific
    wing_width: float = 5.0


class SyntheticDataConfig(BaseModel):
    start_price: float = 450.0
    daily_drift: float = 0.0003
    base_iv: float = 0.25
    seed: int = 42


class BacktestRequest(BaseModel):
    ticker: str = "AAPL"
    start_date: str = "2023-01-03"
    end_date: str = "2024-01-03"
    starting_cash: float = 100_000.0
    commission: float = 0
    strategy: StrategyConfig
    advanced_filters: AdvancedFilters = AdvancedFilters()
    data_source: str = "synthetic"  # "synthetic" or "csv"
    synthetic_config: SyntheticDataConfig = SyntheticDataConfig()


class TradeResult(BaseModel):
    number: int
    strategy: str
    entry_date: str
    exit_date: str
    strikes: str
    entry_premium: float
    exit_premium: float
    pnl: float
    days_held: int
    result: str
    # Enriched fields
    exit_reason: str = "expiration"
    entry_underlying_price: float = 0.0
    exit_underlying_price: float = 0.0
    contracts: int = 1
    notional_value: float = 0.0
    entry_delta: float | None = None
    entry_theta: float | None = None
    entry_vega: float | None = None


class IndicatorSnapshot(BaseModel):
    date: str
    price: float
    sma_20: float | None = None
    sma_50: float | None = None
    sma_200: float | None = None
    ema_9: float | None = None
    ema_21: float | None = None
    rsi_14: float | None = None
    bb_upper: float | None = None
    bb_middle: float | None = None
    bb_lower: float | None = None
    vwap: float | None = None


class BacktestResponse(BaseModel):
    total_return_pct: float
    total_pnl: float
    win_rate: float
    total_trades: int
    max_drawdown_pct: float
    sharpe_ratio: float
    annualized_return: float
    avg_pnl_per_trade: float
    avg_holding_days: float
    profit_factor: float
    equity_curve: list[dict[str, object]]  # [{date, equity}]
    trades: list[TradeResult]
    indicators: list[IndicatorSnapshot]
    open_positions_count: int
    sp500_benchmark: list[dict[str, object]]  # [{date, value}]
    buy_hold_benchmark: list[dict[str, object]]  # [{date, value}]
