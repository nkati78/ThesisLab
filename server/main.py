"""FastAPI backend for the ThesisLab backtesting engine."""

from __future__ import annotations

import math
import random
from datetime import datetime, time

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from server.schemas import (
    BacktestRequest, BacktestResponse, TradeResult, IndicatorSnapshot,
)
from thesislab.data.fake_provider import FakeDataProvider
from thesislab.data.provider import DataProvider
from thesislab.engine.backtester import Backtester, BacktestConfig
from thesislab.filters import EntryExitFilters, IndicatorFilter, TimeOfDayFilter
from thesislab.strategies.butterfly import Butterfly, ButterflyType
from thesislab.strategies.calendar_spread import CalendarSpread, CalendarType
from thesislab.strategies.covered_call import CoveredCall
from thesislab.strategies.debit_spread import DebitSpread, DebitDirection
from thesislab.strategies.iron_condor import IronCondor
from thesislab.strategies.protective_put import ProtectivePut
from thesislab.strategies.short_straddle import ShortStraddle
from thesislab.strategies.single_leg import SingleLeg, LegDirection
from thesislab.strategies.straddle import Straddle
from thesislab.strategies.strangle import Strangle
from thesislab.strategies.vertical_spread import VerticalSpread, SpreadDirection

app = FastAPI(title="ThesisLab Backtester API")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:5173", "http://localhost:3000"],
    allow_methods=["*"],
    allow_headers=["*"],
)


def _build_strategy(cfg):
    t = cfg.type
    common_kw = {"contracts_per_trade": cfg.contracts_per_trade}
    exit_kw = {
        "close_at_profit_pct": cfg.close_at_profit_pct,
        "close_at_loss_pct": cfg.close_at_loss_pct,
        "close_at_dte": cfg.close_at_dte,
        "close_at_profit_enabled": cfg.close_at_profit_enabled,
        "close_at_loss_enabled": cfg.close_at_loss_enabled,
        "close_at_dte_enabled": cfg.close_at_dte_enabled,
        "close_on_short_breach": cfg.close_on_short_breach,
    }

    # ── Single-leg strategies ──
    _leg_map = {
        "long_call": LegDirection.LONG_CALL,
        "long_put": LegDirection.LONG_PUT,
        "short_call": LegDirection.SHORT_CALL,
        "short_put": LegDirection.SHORT_PUT,
    }
    if t in _leg_map:
        return SingleLeg(
            name=t, leg_direction=_leg_map[t],
            short_delta=cfg.short_delta,
            min_dte=cfg.min_dte, max_dte=cfg.max_dte,
            max_positions=cfg.max_positions,
            **common_kw, **exit_kw,
        )

    # ── Credit vertical spreads ──
    if t == "short_put_spread":
        return VerticalSpread(
            name="ShortPutSpread", direction=SpreadDirection.BULL,
            short_delta=cfg.short_delta, spread_width=cfg.spread_width,
            min_dte=cfg.min_dte, max_dte=cfg.max_dte,
            max_positions=cfg.max_positions,
            **common_kw, **exit_kw,
        )
    elif t == "short_call_spread":
        return VerticalSpread(
            name="ShortCallSpread", direction=SpreadDirection.BEAR,
            short_delta=cfg.short_delta, spread_width=cfg.spread_width,
            min_dte=cfg.min_dte, max_dte=cfg.max_dte,
            max_positions=cfg.max_positions,
            **common_kw, **exit_kw,
        )

    # ── Debit vertical spreads ──
    elif t == "debit_call_spread":
        return DebitSpread(
            name="DebitCallSpread", direction=DebitDirection.BULL,
            short_delta=cfg.short_delta, spread_width=cfg.spread_width,
            min_dte=cfg.min_dte, max_dte=cfg.max_dte,
            max_positions=cfg.max_positions,
            **common_kw, **exit_kw,
        )
    elif t == "debit_put_spread":
        return DebitSpread(
            name="DebitPutSpread", direction=DebitDirection.BEAR,
            short_delta=cfg.short_delta, spread_width=cfg.spread_width,
            min_dte=cfg.min_dte, max_dte=cfg.max_dte,
            max_positions=cfg.max_positions,
            **common_kw, **exit_kw,
        )

    # ── Calendar spreads ──
    elif t == "calendar_call_spread":
        return CalendarSpread(
            name="CalendarCallSpread", calendar_type=CalendarType.CALL,
            min_dte=cfg.min_dte, max_dte=cfg.max_dte,
            **common_kw, **exit_kw,
        )
    elif t == "calendar_put_spread":
        return CalendarSpread(
            name="CalendarPutSpread", calendar_type=CalendarType.PUT,
            min_dte=cfg.min_dte, max_dte=cfg.max_dte,
            **common_kw, **exit_kw,
        )

    # ── Iron condor ──
    elif t == "iron_condor":
        return IronCondor(
            short_delta=cfg.short_delta, wing_width=cfg.wing_width,
            min_dte=cfg.min_dte, max_dte=cfg.max_dte,
            **common_kw, **exit_kw,
        )

    # ── Straddles ──
    elif t == "straddle":
        return Straddle(
            min_dte=cfg.min_dte, max_dte=cfg.max_dte,
            **common_kw, **exit_kw,
        )
    elif t == "short_straddle":
        return ShortStraddle(
            min_dte=cfg.min_dte, max_dte=cfg.max_dte,
            **common_kw, **exit_kw,
        )

    # ── Strangles ──
    elif t == "long_strangle":
        return Strangle(
            name="LongStrangle", is_short=False,
            short_delta=cfg.short_delta,
            min_dte=cfg.min_dte, max_dte=cfg.max_dte,
            **common_kw, **exit_kw,
        )
    elif t == "short_strangle":
        return Strangle(
            name="ShortStrangle", is_short=True,
            short_delta=cfg.short_delta,
            min_dte=cfg.min_dte, max_dte=cfg.max_dte,
            **common_kw, **exit_kw,
        )

    # ── Butterflies ──
    elif t == "iron_butterfly":
        return Butterfly(
            name="IronButterfly", butterfly_type=ButterflyType.IRON,
            wing_width=cfg.wing_width,
            min_dte=cfg.min_dte, max_dte=cfg.max_dte,
            **common_kw, **exit_kw,
        )
    elif t == "long_call_butterfly":
        return Butterfly(
            name="LongCallButterfly", butterfly_type=ButterflyType.LONG_CALL,
            wing_width=cfg.wing_width,
            min_dte=cfg.min_dte, max_dte=cfg.max_dte,
            **common_kw, **exit_kw,
        )
    elif t == "long_put_butterfly":
        return Butterfly(
            name="LongPutButterfly", butterfly_type=ButterflyType.LONG_PUT,
            wing_width=cfg.wing_width,
            min_dte=cfg.min_dte, max_dte=cfg.max_dte,
            **common_kw, **exit_kw,
        )

    # ── Legacy strategies ──
    elif t == "covered_call":
        return CoveredCall(
            delta_target=cfg.short_delta, min_dte=cfg.min_dte, max_dte=cfg.max_dte,
            **common_kw, **exit_kw,
        )
    elif t == "protective_put":
        return ProtectivePut(
            delta_target=cfg.put_delta, min_dte=cfg.min_dte, max_dte=cfg.max_dte,
            **common_kw, **exit_kw,
        )

    raise ValueError(f"Unknown strategy: {t}")


def _parse_time(s: str) -> time:
    parts = s.split(":")
    return time(int(parts[0]), int(parts[1]))


_DOW_MAP = {
    "any": (0, 1, 2, 3, 4),
    "monday": (0,),
    "tuesday": (1,),
    "wednesday": (2,),
    "thursday": (3,),
    "friday": (4,),
}


def _build_filters(adv, entry_dow: str = "any") -> EntryExitFilters:
    time_f = TimeOfDayFilter()
    entry_ind = IndicatorFilter()

    if adv.time_of_day.enabled:
        time_f = TimeOfDayFilter(
            entry_start=_parse_time(adv.time_of_day.entry_start),
            entry_end=_parse_time(adv.time_of_day.entry_end),
            exit_start=_parse_time(adv.time_of_day.exit_start),
            exit_end=_parse_time(adv.time_of_day.exit_end),
        )

    if adv.rsi.enabled:
        entry_ind.rsi_min = float(adv.rsi.rsi_min)
        entry_ind.rsi_max = float(adv.rsi.rsi_max)
        zone_map = {"oversold": "oversold", "neutral": "neutral", "overbought": "overbought"}
        if adv.rsi.rsi_zone in zone_map:
            entry_ind.rsi_zone = zone_map[adv.rsi.rsi_zone]

    if adv.bollinger.enabled:
        pos_map = {
            "below_lower": "below_lower", "lower_half": "lower_half",
            "upper_half": "upper_half", "above_upper": "above_upper",
        }
        if adv.bollinger.position in pos_map:
            entry_ind.bb_position = pos_map[adv.bollinger.position]
        if adv.bollinger.use_pct_b:
            entry_ind.bb_pct_b_min = adv.bollinger.pct_b_min
            entry_ind.bb_pct_b_max = adv.bollinger.pct_b_max

    if adv.moving_average.enabled:
        def _parse_ma(val: str) -> bool | None:
            return {"above": True, "below": False}.get(val)

        entry_ind.price_above_sma_20 = _parse_ma(adv.moving_average.sma_20)
        entry_ind.price_above_sma_50 = _parse_ma(adv.moving_average.sma_50)
        entry_ind.price_above_sma_200 = _parse_ma(adv.moving_average.sma_200)
        entry_ind.price_above_ema_9 = _parse_ma(adv.moving_average.ema_9)
        entry_ind.price_above_ema_21 = _parse_ma(adv.moving_average.ema_21)
        if adv.moving_average.sma_cross == "bullish":
            entry_ind.sma_20_above_50 = True
        elif adv.moving_average.sma_cross == "bearish":
            entry_ind.sma_20_above_50 = False

    if adv.vwap.enabled:
        entry_ind.price_above_vwap = (adv.vwap.direction == "above")

    from thesislab.filters import WeekdayFilter
    weekday_f = WeekdayFilter(entry_days=_DOW_MAP.get(entry_dow, _DOW_MAP["any"]))
    return EntryExitFilters(
        time_filter=time_f,
        entry_indicator_filter=entry_ind,
        exit_indicator_filter=IndicatorFilter(),
        weekday_filter=weekday_f,
    )


@app.post("/api/backtest", response_model=BacktestResponse)
def run_backtest(req: BacktestRequest):
    import time
    _t_total = time.perf_counter()
    start = datetime.strptime(req.start_date, "%Y-%m-%d").date()
    end = datetime.strptime(req.end_date, "%Y-%m-%d").date()

    provider: DataProvider
    if req.data_source == "thetadata":
        # Lazy-import so synthetic-only setups don't pay the import cost
        from thesislab.data.thetadata_provider import ThetaDataProvider
        try:
            provider = ThetaDataProvider(
                ticker=req.ticker.upper(),
                start_date=start, end_date=end,
                # Pass the strategy's DTE window so we only pull each
                # expiration's history during the days it could actually
                # be entered — keeps SPX year-long backtests tractable.
                dte_window=(req.strategy.min_dte, req.strategy.max_dte),
            )
        except RuntimeError as e:
            from fastapi import HTTPException
            raise HTTPException(status_code=400, detail=str(e))
    else:
        provider = FakeDataProvider(
            ticker=req.ticker.upper(),
            start_price=req.synthetic_config.start_price,
            daily_drift=req.synthetic_config.daily_drift,
            base_iv=req.synthetic_config.base_iv,
            seed=req.synthetic_config.seed,
        )

    strategy = _build_strategy(req.strategy)
    # Weekly mode: wrap the strategy so it enters on the first trading day of
    # each calendar week and targets the last trading day's expiration. The
    # WeekdayFilter is set to "any" since the wrapper handles entry gating.
    if req.strategy.entry_dow == "weekly":
        from thesislab.strategies.weekly_adapter import WeeklyAdapter
        trading_dates = provider.get_trading_dates(req.ticker.upper(), start, end)
        strategy = WeeklyAdapter(strategy, trading_dates)
        filters = _build_filters(req.advanced_filters, entry_dow="any")
    else:
        filters = _build_filters(req.advanced_filters, entry_dow=req.strategy.entry_dow)
    config = BacktestConfig(
        ticker=req.ticker.upper(),
        start_date=start, end_date=end,
        starting_cash=req.starting_cash,
        commission_per_contract=req.commission,
    )

    backtester = Backtester(config=config, provider=provider,
                            strategies=[strategy], filters=filters)
    _t_provider = time.perf_counter()
    result = backtester.run()
    _t_loop = time.perf_counter()
    print(f"[backtest] provider_build={_t_provider-_t_total:.2f}s "
          f"loop={_t_loop-_t_provider:.2f}s "
          f"trades={len(result.closed_positions)}", flush=True)

    # Format response
    equity_curve = [
        {"date": d.isoformat(), "equity": v}
        for d, v in sorted(result.equity_curve.items())
    ]

    trades = []
    for i, pos in enumerate(result.closed_positions, 1):
        strikes = ", ".join(
            f"{'S' if leg.quantity < 0 else 'L'} {leg.contract.strike}"
            for leg in pos.entry_trade.legs
        )
        trades.append(TradeResult(
            number=i,
            strategy=pos.strategy_name,
            entry_date=pos.entry_trade.trade_date.isoformat(),
            exit_date=pos.exit_trade.trade_date.isoformat(),
            strikes=strikes,
            entry_premium=pos.entry_trade.net_premium,
            exit_premium=pos.exit_trade.net_premium,
            pnl=pos.realized_pnl,
            days_held=pos.holding_days,
            result="WIN" if pos.realized_pnl > 0 else "LOSS",
            exit_reason=pos.exit_reason.value,
            entry_underlying_price=pos.entry_underlying_price,
            exit_underlying_price=pos.exit_underlying_price,
            contracts=pos.contracts,
            notional_value=pos.notional_value,
            entry_delta=pos.entry_delta,
            entry_theta=pos.entry_theta,
            entry_vega=pos.entry_vega,
        ))

    indicators = []
    for d in sorted(result.indicator_history):
        ind = result.indicator_history[d]
        indicators.append(IndicatorSnapshot(
            date=d.isoformat(),
            price=ind.price,
            sma_20=ind.sma_20,
            sma_50=ind.sma_50,
            sma_200=ind.sma_200,
            ema_9=ind.ema_9,
            ema_21=ind.ema_21,
            rsi_14=ind.rsi_14,
            bb_upper=ind.bb_upper,
            bb_middle=ind.bb_middle,
            bb_lower=ind.bb_lower,
            vwap=ind.vwap,
        ))

    pf = result.profit_factor

    # S&P 500 benchmark — real SPX prices when using ThetaData (cache-backed,
    # so it keeps working offline once cached). Falls back to a synthetic
    # 10%-annual-drift series for synthetic-data backtests.
    sorted_dates = sorted(result.equity_curve.keys())
    sp500_benchmark: list[dict] = []
    if req.data_source == "thetadata" and sorted_dates:
        # S&P 500 benchmark — try SPX (cached as a side-effect of any SPX
        # option backtest), then SPY (Standard tier blocks older history),
        # then synthetic fallback.
        from thesislab.data.thetadata_provider import fetch_stock_eod_series
        sp_series = fetch_stock_eod_series("SPX", sorted_dates[0], sorted_dates[-1])
        if not sp_series or len(sp_series) < len(sorted_dates) // 2:
            sp_series = fetch_stock_eod_series("SPY", sorted_dates[0], sorted_dates[-1])
        if sp_series:
            sp_by_date = dict(sp_series)
            first_close = sp_series[0][1]
            last_known = first_close
            for d in sorted_dates:
                close = sp_by_date.get(d, last_known)
                last_known = close
                sp500_benchmark.append({
                    "date": d.isoformat(),
                    "value": round(req.starting_cash * (close / first_close), 2),
                })
    if not sp500_benchmark:
        # Synthetic fallback (also covers data_source == "synthetic")
        sp500_rng = random.Random(12345)
        daily_drift = math.log(1.10) / 252
        daily_vol = 0.16 / math.sqrt(252)
        sp500_value = req.starting_cash
        for d in sorted_dates:
            sp500_benchmark.append({"date": d.isoformat(), "value": round(sp500_value, 2)})
            z = sp500_rng.gauss(0, 1)
            sp500_value *= math.exp(daily_drift - 0.5 * daily_vol**2 + daily_vol * z)

    # Generate buy-and-hold benchmark for the underlying
    # If you invested starting_cash into the underlying at the first price and held
    buy_hold_benchmark = []
    if indicators:
        first_price = indicators[0].price
        for ind in indicators:
            buy_hold_value = req.starting_cash * (ind.price / first_price)
            buy_hold_benchmark.append({"date": ind.date, "value": round(buy_hold_value, 2)})

    return BacktestResponse(
        total_return_pct=result.total_return_pct,
        total_pnl=result.total_pnl,
        win_rate=result.win_rate,
        total_trades=result.total_trades,
        max_drawdown_pct=result.max_drawdown_pct,
        sharpe_ratio=result.sharpe_ratio,
        annualized_return=result.annualized_return,
        avg_pnl_per_trade=result.avg_pnl_per_trade,
        avg_holding_days=result.avg_holding_days,
        profit_factor=pf if pf != float("inf") else 9999.99,
        equity_curve=equity_curve,
        trades=trades,
        indicators=indicators,
        open_positions_count=len(result.open_positions),
        sp500_benchmark=sp500_benchmark,
        buy_hold_benchmark=buy_hold_benchmark,
    )


@app.get("/api/strategies")
def list_strategies():
    return [
        {"key": "long_call", "name": "Long Call"},
        {"key": "long_put", "name": "Long Put"},
        {"key": "short_call", "name": "Short Call"},
        {"key": "short_put", "name": "Short Put"},
        {"key": "short_put_spread", "name": "Put Credit Spread"},
        {"key": "short_call_spread", "name": "Call Credit Spread"},
        {"key": "debit_call_spread", "name": "Call Debit Spread"},
        {"key": "debit_put_spread", "name": "Put Debit Spread"},
        {"key": "calendar_call_spread", "name": "Calendar Call Spread"},
        {"key": "calendar_put_spread", "name": "Calendar Put Spread"},
        {"key": "iron_condor", "name": "Iron Condor"},
        {"key": "straddle", "name": "Long Straddle"},
        {"key": "short_straddle", "name": "Short Straddle"},
        {"key": "long_strangle", "name": "Long Strangle"},
        {"key": "short_strangle", "name": "Short Strangle"},
        {"key": "iron_butterfly", "name": "Iron Butterfly"},
        {"key": "long_call_butterfly", "name": "Long Call Butterfly"},
        {"key": "long_put_butterfly", "name": "Long Put Butterfly"},
    ]


@app.get("/api/health")
def health():
    return {"status": "ok"}


# ─── Heatmap (live ThetaData snapshot) ────────────────────────────────────────
# Standard tier offers per-expiration snapshot endpoints. We pick a handful of
# expirations close to the heatmap's target DTEs, fetch greeks for each, and
# return a grid the frontend can render directly.

_HEATMAP_DTE_TARGETS = [0, 4, 7, 14, 21, 30, 45, 60]
_HEATMAP_STRIKE_OFFSETS_PCT = [-7.5, -5, -3, -2, -1, 0, 1, 2, 3, 5, 7.5]
_DAILY_EXPIRY_TICKERS = {"SPX", "SPY", "QQQ", "IWM", "NDX", "RUT", "XSP", "DIA"}


def _pick_expirations(all_expirations: list, dte_targets: list[int], today) -> list[tuple[int, "date"]]:
    """For each target DTE, find the closest available expiration on/after today.
    De-duplicates if two targets land on the same expiration."""
    from datetime import date as _date
    future = sorted(e for e in all_expirations if isinstance(e, _date) and e >= today)
    if not future:
        return []
    picked: list[tuple[int, _date]] = []
    used: set = set()
    for target_dte in dte_targets:
        # closest expiration to (today + target_dte)
        target_d = today
        best = None
        best_diff = 10**9
        for e in future:
            diff = abs((e - today).days - target_dte)
            if diff < best_diff:
                best_diff = diff
                best = e
        if best is None or best in used:
            continue
        used.add(best)
        picked.append((target_dte, best))
        target_d = best  # silence unused
    return picked


def _derive_spot_from_chain(rows: list[dict], expiration) -> float | None:
    """Use put-call parity at the most ATM strike to estimate spot.
    S ≈ C - P + K  (ignoring r,q at this short maturity).
    Returns None if we can't find a matching call+put pair."""
    calls: dict[float, dict] = {}
    puts: dict[float, dict] = {}
    for r in rows:
        right = str(r.get("right") or "").upper()
        strike = r.get("strike")
        if strike is None:
            continue
        mid = ((r.get("bid") or 0) + (r.get("ask") or 0)) / 2
        if right.startswith("C"):
            calls[float(strike)] = {"mid": mid}
        elif right.startswith("P"):
            puts[float(strike)] = {"mid": mid}
    common = sorted(set(calls.keys()) & set(puts.keys()))
    if not common:
        return None
    # Pick the strike where |delta_call| is closest to 0.5 — not available here,
    # so fall back to the strike whose call mid ≈ put mid (synthetic forward).
    best = min(common, key=lambda k: abs(calls[k]["mid"] - puts[k]["mid"]))
    return best + calls[best]["mid"] - puts[best]["mid"]


@app.get("/api/heatmap")
def heatmap_snapshot(ticker: str):
    """Return a (DTE × strike-offset) grid of live option snapshots for the
    given ticker. Synthetic mode lives entirely in the frontend; this is the
    live-data path."""
    from datetime import date as _date
    from fastapi import HTTPException
    import time as _time

    sym = ticker.upper()
    try:
        from thesislab.data.thetadata_provider import _read_creds, _root_for, _to_date, _f
    except Exception:
        raise HTTPException(status_code=500, detail="ThetaData provider unavailable")
    creds = _read_creds()
    if not creds:
        raise HTTPException(status_code=400, detail="ThetaData credentials not configured")
    try:
        from thetadata import ThetaClient
    except Exception:
        raise HTTPException(status_code=500, detail="thetadata library not installed")

    client = ThetaClient(email=creds[0], password=creds[1], dataframe_type="pandas")
    today = _date.today()

    # Filter the DTE list: 0DTE only for tickers that list same-day expiries.
    dte_targets = list(_HEATMAP_DTE_TARGETS)
    if sym not in _DAILY_EXPIRY_TICKERS:
        dte_targets = [d for d in dte_targets if d != 0]

    # Get list of expirations (try both SPX and SPXW for indices)
    roots_to_try = [sym]
    if sym == "SPX":
        roots_to_try.append("SPXW")
    all_exps: set = set()
    for root in roots_to_try:
        try:
            df = client.option_list_expirations(symbol=root)
            for _, r in df.iterrows():
                d = _to_date(r.get("expiration"))
                if d:
                    all_exps.add(d)
        except Exception:
            continue
    if not all_exps:
        raise HTTPException(status_code=404, detail=f"No expirations found for {sym}")

    picks = _pick_expirations(sorted(all_exps), dte_targets, today)
    if not picks:
        raise HTTPException(status_code=404, detail=f"No future expirations for {sym}")

    # Fetch snapshot greeks for each picked expiration (parallel-safe but
    # sequential here for simplicity; per-expiration call is ~1-2s).
    t0 = _time.perf_counter()
    rows_by_exp: dict = {}
    for dte, exp in picks:
        root = _root_for(sym, exp)
        try:
            df = client.option_snapshot_greeks_first_order(symbol=root, expiration=exp)
        except Exception:
            continue
        if df is None or len(df) == 0:
            continue
        contracts = []
        for _, r in df.iterrows():
            strike = _f(r.get("strike"))
            if strike is None:
                continue
            right_val = str(r.get("right") or "").upper()
            right = "C" if right_val.startswith("C") else "P"
            contracts.append({
                "strike": strike,
                "right": right,
                "bid": _f(r.get("bid")),
                "ask": _f(r.get("ask")),
                "delta": _f(r.get("delta")),
                "theta": _f(r.get("theta")),
                "vega": _f(r.get("vega")),
            })
        rows_by_exp[(dte, exp)] = contracts
    print(f"[heatmap] {sym}: {len(rows_by_exp)} expirations in {_time.perf_counter()-t0:.1f}s", flush=True)

    # Derive spot from the nearest expiration's chain (best ATM data)
    spot = None
    for (dte, exp), rows in rows_by_exp.items():
        spot = _derive_spot_from_chain(rows, exp)
        if spot is not None:
            break
    if spot is None:
        raise HTTPException(status_code=500, detail=f"Could not derive spot price for {sym}")

    # Round strike grid increment based on price magnitude
    if spot >= 1000:
        inc = 5.0
    elif spot >= 200:
        inc = 2.5
    elif spot >= 50:
        inc = 1.0
    else:
        inc = 0.5

    # Build the response grid: rows = chosen expirations, cols = strike offsets
    rows_out = []
    for (dte, exp), contracts in rows_by_exp.items():
        # Index by (strike, right) for lookups
        by_key: dict = {}
        for c in contracts:
            by_key[(round(c["strike"], 2), c["right"])] = c
        cells = []
        for off in _HEATMAP_STRIKE_OFFSETS_PCT:
            raw = spot * (1 + off / 100.0)
            strike = round(raw / inc) * inc
            # Closest available strike in chain
            avail = [s for (s, _) in by_key.keys()]
            if not avail:
                cells.append(None)
                continue
            actual = min(set(avail), key=lambda s: abs(s - strike))
            call = by_key.get((round(actual, 2), "C"))
            put  = by_key.get((round(actual, 2), "P"))
            cells.append({
                "strike": actual,
                "call": {
                    "bid": call.get("bid") if call else None,
                    "ask": call.get("ask") if call else None,
                    "delta": call.get("delta") if call else None,
                    "theta": call.get("theta") if call else None,
                    "vega": call.get("vega") if call else None,
                } if call else None,
                "put": {
                    "bid": put.get("bid") if put else None,
                    "ask": put.get("ask") if put else None,
                    "delta": put.get("delta") if put else None,
                    "theta": put.get("theta") if put else None,
                    "vega": put.get("vega") if put else None,
                } if put else None,
            })
        rows_out.append({
            "dte_target": dte,
            "dte_actual": (exp - today).days,
            "expiration": exp.isoformat(),
            "cells": cells,
        })

    return {
        "ticker": sym,
        "spot": round(spot, 2),
        "as_of": datetime.now().isoformat(timespec="seconds"),
        "strike_offsets_pct": _HEATMAP_STRIKE_OFFSETS_PCT,
        "rows": rows_out,
    }
