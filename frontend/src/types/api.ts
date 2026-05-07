export interface TimeOfDayFilterConfig {
  enabled: boolean;
  entry_start: string;
  entry_end: string;
  exit_start: string;
  exit_end: string;
}

export interface RSIFilterConfig {
  enabled: boolean;
  rsi_min: number;
  rsi_max: number;
  rsi_zone: string;
}

export interface BollingerFilterConfig {
  enabled: boolean;
  position: string;
  use_pct_b: boolean;
  pct_b_min: number;
  pct_b_max: number;
}

export interface MAFilterConfig {
  enabled: boolean;
  sma_20: string;
  sma_50: string;
  sma_200: string;
  ema_9: string;
  ema_21: string;
  sma_cross: string;
}

export interface VWAPFilterConfig {
  enabled: boolean;
  direction: string;
}

export interface AdvancedFilters {
  time_of_day: TimeOfDayFilterConfig;
  rsi: RSIFilterConfig;
  bollinger: BollingerFilterConfig;
  moving_average: MAFilterConfig;
  vwap: VWAPFilterConfig;
}

export interface StrategyConfig {
  type: string;
  min_dte: number;
  max_dte: number;
  short_delta: number;
  spread_width: number;
  max_positions: number;
  close_at_profit_pct: number;
  close_at_loss_pct: number;
  close_at_dte: number;
  close_at_profit_enabled: boolean;
  close_at_loss_enabled: boolean;
  close_at_dte_enabled: boolean;
  close_on_short_breach: boolean;
  entry_dow: string;
  put_delta: number;
  wing_width: number;
}

export interface SyntheticDataConfig {
  start_price: number;
  daily_drift: number;
  base_iv: number;
  seed: number;
}

export interface BacktestRequest {
  ticker: string;
  start_date: string;
  end_date: string;
  starting_cash: number;
  commission: number;
  strategy: StrategyConfig;
  advanced_filters: AdvancedFilters;
  data_source: string;
  synthetic_config: SyntheticDataConfig;
}

export interface TradeResult {
  number: number;
  strategy: string;
  entry_date: string;
  exit_date: string;
  strikes: string;
  entry_premium: number;
  exit_premium: number;
  pnl: number;
  days_held: number;
  result: string;
  // Enriched fields
  exit_reason: string;
  entry_underlying_price: number;
  exit_underlying_price: number;
  contracts: number;
  notional_value: number;
  entry_delta: number | null;
  entry_theta: number | null;
  entry_vega: number | null;
}

export interface IndicatorSnapshot {
  date: string;
  price: number;
  sma_20: number | null;
  sma_50: number | null;
  sma_200: number | null;
  ema_9: number | null;
  ema_21: number | null;
  rsi_14: number | null;
  bb_upper: number | null;
  bb_middle: number | null;
  bb_lower: number | null;
  vwap: number | null;
}

export interface BacktestResponse {
  total_return_pct: number;
  total_pnl: number;
  win_rate: number;
  total_trades: number;
  max_drawdown_pct: number;
  sharpe_ratio: number;
  annualized_return: number;
  avg_pnl_per_trade: number;
  avg_holding_days: number;
  profit_factor: number;
  equity_curve: { date: string; equity: number }[];
  trades: TradeResult[];
  indicators: IndicatorSnapshot[];
  open_positions_count: number;
  sp500_benchmark: { date: string; value: number }[];
  buy_hold_benchmark: { date: string; value: number }[];
}

export const DEFAULT_STRATEGY: StrategyConfig = {
  type: "short_put_spread",
  min_dte: 25,
  max_dte: 45,
  short_delta: 0.25,
  spread_width: 5,
  max_positions: 1,
  close_at_profit_pct: 0.5,
  close_at_loss_pct: 2.0,
  close_at_dte: 7,
  close_at_profit_enabled: false,
  close_at_loss_enabled: false,
  close_at_dte_enabled: false,
  close_on_short_breach: false,
  entry_dow: "any",
  put_delta: -0.2,
  wing_width: 5,
};

export const DEFAULT_ADVANCED: AdvancedFilters = {
  time_of_day: { enabled: false, entry_start: "09:30", entry_end: "16:00", exit_start: "09:30", exit_end: "16:00" },
  rsi: { enabled: false, rsi_min: 20, rsi_max: 80, rsi_zone: "any" },
  bollinger: { enabled: false, position: "any", use_pct_b: false, pct_b_min: 0, pct_b_max: 0.2 },
  moving_average: { enabled: false, sma_20: "ignore", sma_50: "ignore", sma_200: "ignore", ema_9: "ignore", ema_21: "ignore", sma_cross: "ignore" },
  vwap: { enabled: false, direction: "above" },
};

export const DEFAULT_SYNTHETIC: SyntheticDataConfig = {
  start_price: 450,
  daily_drift: 0.0003,
  base_iv: 0.25,
  seed: 42,
};
