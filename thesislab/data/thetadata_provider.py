"""Real options data provider backed by ThetaData (Python library + SQLite cache).

On construction we pull every (expiration, strike, right) contract relevant to
the backtest window once, store in a local SQLite cache, then serve per-day
chains from the cache. Repeat backtests on overlapping ranges hit the cache
instead of the API; once you've done your research you can cancel the
subscription and continue running offline.
"""

from __future__ import annotations

import os
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import date, timedelta
from pathlib import Path

from thesislab.data import cache
from thesislab.domain import OptionContract, OptionType, OptionsChain

# ─── ThetaData credentials ────────────────────────────────────────────────────
# The library reads from env vars or a creds file. We default to the same file
# the JAR uses so the user only manages one credential.
_DEFAULT_CREDS = Path("C:/Program Files/ThetaTerminal/creds.txt")


def fetch_stock_eod_series(
    symbol: str, start_date: date, end_date: date,
) -> list[tuple[date, float]]:
    """Return [(date, close), ...] for the symbol over the range.

    Cache-first: serves from local SQLite when present, else fetches via the
    Python library and writes through. After the first fetch, subsequent calls
    work offline — including after the user's subscription expires.
    """
    # Try cache first — only hit the API if any expected day is missing.
    cached: dict[date, float] = {}
    cur = start_date
    while cur <= end_date:
        c = cache.fetch_stock_close(symbol, cur)
        if c is not None:
            cached[cur] = c
        cur += timedelta(days=1)

    # Heuristic: if cache covers both endpoints (within a few days), trust it.
    # Otherwise fetch the missing range from ThetaData.
    cached_dates = sorted(cached.keys())
    needs_fetch = (
        not cached_dates
        or cached_dates[0] > start_date + timedelta(days=4)
        or cached_dates[-1] < end_date - timedelta(days=4)
    )
    if needs_fetch:
        creds = _read_creds()
        if creds:
            try:
                from thetadata import ThetaClient
                client = ThetaClient(
                    email=creds[0], password=creds[1], dataframe_type="pandas",
                )
                df = client.stock_history_eod(
                    symbol=symbol, start_date=start_date, end_date=end_date,
                )
                if df is not None and len(df) > 0:
                    rows = []
                    for _, r in df.iterrows():
                        qd = _to_date(r.get("created") or r.get("date") or r.get("quote_date"))
                        if qd is None:
                            continue
                        close = _f(r.get("close"))
                        rows.append({
                            "symbol": symbol,
                            "quote_date": qd.isoformat(),
                            "open": _f(r.get("open")), "high": _f(r.get("high")),
                            "low": _f(r.get("low")), "close": close,
                            "volume": _i(r.get("volume")),
                        })
                        if close is not None:
                            cached[qd] = close
                    cache.store_stock_eod(rows)
            except Exception:
                # Fall back to whatever we had cached — caller decides what to do
                # if the series is empty.
                pass

    return sorted(cached.items())


def _root_for(ticker: str, expiration: date) -> str:
    """For SPX-family options, monthly 3rd-Friday expirations live under
    root SPX, weeklies/dailies under SPXW. For other tickers we just use
    the ticker as-is."""
    if ticker == "SPX":
        # 3rd Friday of the month: weekday 4 (Fri), and 15 <= day <= 21
        if expiration.weekday() == 4 and 15 <= expiration.day <= 21:
            return "SPX"
        return "SPXW"
    return ticker


def _read_creds() -> tuple[str, str] | None:
    user = os.environ.get("THETADATA_USERNAME")
    pw = os.environ.get("THETADATA_PASSWORD")
    if user and pw:
        return user, pw
    if _DEFAULT_CREDS.exists():
        lines = [l.strip() for l in _DEFAULT_CREDS.read_text().splitlines() if l.strip()]
        if len(lines) >= 2:
            return lines[0], lines[1]
    return None


# ─── Provider ─────────────────────────────────────────────────────────────────
class ThetaDataProvider:
    """Standard-tier ThetaData provider with local SQLite caching."""

    def __init__(
        self,
        ticker: str,
        start_date: date,
        end_date: date,
        *,
        strike_pct: float = 0.30,
        max_dte: int = 90,
        max_workers: int = 4,
        dte_window: tuple[int, int] = (0, 60),
        close_buffer_days: int = 14,
    ):
        self.ticker = ticker.upper()
        self.start_date = start_date
        self.end_date = end_date
        self.strike_pct = strike_pct
        self.max_dte = max_dte
        self.max_workers = max_workers
        # Strategy DTE window — used to clamp how much of each expiration's
        # history we pull. For a 4-DTE strategy each expiration only needs
        # ~4 trading days, not the full backtest range.
        self.dte_window = dte_window
        # Extra days past max_dte to cover open positions through close_at_dte
        # / expiration. A position opened at max_dte and held to expiration
        # needs `max_dte` days of history; we add a small cushion.
        self.close_buffer_days = close_buffer_days
        self._chain_by_date: dict[date, OptionsChain] = {}

        creds = _read_creds()
        if not creds:
            raise RuntimeError(
                "ThetaData credentials not found. Set THETADATA_USERNAME / "
                "THETADATA_PASSWORD env vars, or place creds at "
                f"{_DEFAULT_CREDS} (line 1 = username, line 2 = password)."
            )
        # Lazy-import so the module loads even if thetadata isn't installed
        from thetadata import ThetaClient

        self._client = ThetaClient(
            email=creds[0], password=creds[1], dataframe_type="pandas"
        )
        self._populate()

    # ─── Bulk population ──────────────────────────────────────────────────────
    def _populate(self) -> None:
        """Ensure cache has all data for [start_date, end_date], then load
        chains into memory for fast per-day lookups."""
        import time
        t0 = time.perf_counter()
        self._ensure_stock_eod()
        t1 = time.perf_counter()
        print(f"[provider] stock_eod: {t1-t0:.2f}s", flush=True)

        self._fetch_chain_universe()
        t2 = time.perf_counter()
        print(f"[provider] chain_universe: {t2-t1:.2f}s", flush=True)

        self._build_chains_from_cache()
        t3 = time.perf_counter()
        print(f"[provider] build_chains: {t3-t2:.2f}s ({len(self._chain_by_date)} days)", flush=True)

    def _ensure_stock_eod(self) -> None:
        # Try cache first
        if cache.fetch_stock_close(self.ticker, self.start_date) is not None and \
           cache.fetch_stock_close(self.ticker, self.end_date) is not None:
            return
        try:
            df = self._client.stock_history_eod(
                symbol=self.ticker, start_date=self.start_date, end_date=self.end_date,
            )
        except Exception:
            # SPX and other indices have no stock EOD endpoint — that's fine.
            # _fetch_chain_universe will derive underlying prices from option rows.
            return
        if df is None or len(df) == 0:
            return
        rows = []
        for _, r in df.iterrows():
            qd = _to_date(r.get("created") or r.get("date") or r.get("quote_date"))
            if qd is None:
                continue
            rows.append({
                "symbol": self.ticker,
                "quote_date": qd.isoformat(),
                "open": _f(r.get("open")), "high": _f(r.get("high")),
                "low": _f(r.get("low")), "close": _f(r.get("close")),
                "volume": _i(r.get("volume")),
            })
        cache.store_stock_eod(rows)

    def _fetch_chain_universe(self) -> None:
        """Pull EOD greeks for every expiration within scope, all strikes both
        rights in one call per expiration."""
        # Underlying range — used to filter strikes after the pull. For indices
        # (SPX) stock EOD is unavailable; fall back to sampling the option
        # chain's underlying_price field.
        prices = []
        cur = self.start_date
        while cur <= self.end_date:
            p = cache.fetch_stock_close(self.ticker, cur)
            if p is not None:
                prices.append(p)
            cur += timedelta(days=1)

        if not prices:
            sample = self._sample_underlying_from_options()
            if sample is None:
                raise RuntimeError(
                    f"Could not determine underlying price for {self.ticker} — "
                    "neither stock EOD nor option data was retrievable. "
                    "ThetaData may not cover this symbol/range on your tier."
                )
            # Wide bound for indices since we only have one sample point
            prices = [sample]
            self.strike_pct = max(self.strike_pct, 0.40)

        lo_strike = min(prices) * (1 - self.strike_pct)
        hi_strike = max(prices) * (1 + self.strike_pct)

        # Expirations: only those that can actually be entered given the
        # strategy's DTE window. An expiration X is in scope iff some entry
        # day D in [start_date, end_date] satisfies min_dte <= (X-D) <= max_dte
        # — i.e., (start_date + min_dte) <= X <= (end_date + max_dte).
        # For SPX, weeklies live under root "SPXW" — query both and combine
        # so dailies/weeklies are included, not just 3rd-Friday monthlies.
        min_dte_window, max_dte_window = self.dte_window
        exp_lower = self.start_date + timedelta(days=min_dte_window)
        exp_upper = self.end_date + timedelta(days=max_dte_window + self.close_buffer_days)
        exp_symbols = [self.ticker]
        if self.ticker == "SPX":
            exp_symbols.append("SPXW")
        exp_set: set[date] = set()
        for sym in exp_symbols:
            # Use cached expirations if they extend past what we need. The
            # expiration list only grows over time, so a cache that already
            # contains expirations >= exp_upper is complete for this run.
            cached_max = cache.max_known_expiration(sym)
            cached_exps = cache.fetch_expirations(sym) if cached_max else []
            if cached_max and cached_max >= exp_upper:
                for d in cached_exps:
                    if exp_lower <= d <= exp_upper:
                        exp_set.add(d)
                continue
            # Cache miss or stale — hit the API and persist.
            try:
                exp_df = self._client.option_list_expirations(symbol=sym)
            except Exception:
                # Fall back to whatever we have cached
                for d in cached_exps:
                    if exp_lower <= d <= exp_upper:
                        exp_set.add(d)
                continue
            fresh: list[date] = []
            for _, r in exp_df.iterrows():
                d = _to_date(r.get("expiration"))
                if d:
                    fresh.append(d)
                    if exp_lower <= d <= exp_upper:
                        exp_set.add(d)
            if fresh:
                cache.store_expirations(sym, fresh)
        expirations = sorted(exp_set)

        # Determine which expirations need a (re-)fetch. An expiration counts
        # as missing if either (a) we have no cached rows at all, or (b) the
        # cached date range doesn't extend through what this backtest needs
        # — covers the case where an earlier run with a shorter end_date
        # cached only part of an expiration's history.
        min_dte_w, max_dte_w = self.dte_window
        missing: list[date] = []
        for exp in expirations:
            needed_end = min(self.end_date, exp)
            needed_start = max(
                self.start_date,
                exp - timedelta(days=max_dte_w + self.close_buffer_days),
            )
            cached_range = cache.expiration_quote_date_range(self.ticker, exp)
            if cached_range is None:
                missing.append(exp)
                continue
            cached_min, cached_max = cached_range
            if cached_min > needed_start or cached_max < needed_end:
                missing.append(exp)
        if not missing:
            return

        # One API call per missing expiration (all strikes, both rights, clamped DTE window)
        synthesized_stock: dict[str, float] = {}  # quote_date -> close (for indices)
        with ThreadPoolExecutor(max_workers=self.max_workers) as ex:
            futures = [
                ex.submit(self._fetch_expiration, exp, lo_strike, hi_strike)
                for exp in missing
            ]
            for f in as_completed(futures):
                rows = f.result()
                if rows:
                    cache.store_option_eod(rows)
                    # For indices: synthesize stock_eod from underlying_price
                    for r in rows:
                        if r.get("underlying_price") and r["quote_date"] not in synthesized_stock:
                            synthesized_stock[r["quote_date"]] = r["underlying_price"]
        # Persist synthesized stock prices for any dates not yet in stock_eod.
        # INSERT OR REPLACE keeps existing rows intact for dates already covered.
        if synthesized_stock:
            new_rows = []
            for qd, close in synthesized_stock.items():
                # Skip dates that already have a real stock close cached
                qd_date = date.fromisoformat(qd)
                if cache.fetch_stock_close(self.ticker, qd_date) is None:
                    new_rows.append({
                        "symbol": self.ticker, "quote_date": qd,
                        "open": None, "high": None, "low": None, "close": close,
                        "volume": None,
                    })
            if new_rows:
                cache.store_stock_eod(new_rows)

    def _sample_underlying_from_options(self) -> float | None:
        """For indices like SPX with no stock_history_eod, fetch one near-term
        expiration's chain at start_date and read the underlying_price field."""
        sym_for_list = "SPXW" if self.ticker == "SPX" else self.ticker
        try:
            exp_df = self._client.option_list_expirations(symbol=sym_for_list)
        except Exception:
            return None
        for _, r in exp_df.iterrows():
            d = _to_date(r.get("expiration"))
            if d and d >= self.start_date and d <= self.start_date + timedelta(days=60):
                root = _root_for(self.ticker, d)
                try:
                    df = self._client.option_history_greeks_eod(
                        symbol=root, expiration=d,
                        start_date=self.start_date, end_date=self.start_date,
                    )
                    if df is not None and len(df) > 0:
                        up = _f(df.iloc[0].get("underlying_price"))
                        if up:
                            return up
                except Exception:
                    continue
        return None

    def _fetch_expiration(
        self, expiration: date, lo_strike: float, hi_strike: float,
    ) -> list[dict]:
        """Fetch greeks/eod for ALL strikes (both calls and puts) at this
        expiration. Date range is clamped to when this expiration is
        actually in the strategy's DTE window — for a 4-DTE strategy
        on a Friday expiration we only need 4 trading days, not a full year."""
        min_dte, max_dte = self.dte_window
        # An expiration E is in scope for entry on day D when min_dte <= (E - D) <= max_dte,
        # i.e., D ∈ [E - max_dte - close_buffer, E - min_dte].
        # Buffer accounts for held positions closing at expiration / close_at_dte.
        fetch_start = max(self.start_date, expiration - timedelta(days=max_dte + self.close_buffer_days))
        fetch_end = min(self.end_date, expiration)
        if fetch_start > fetch_end:
            return []
        root = _root_for(self.ticker, expiration)
        try:
            df = self._client.option_history_greeks_eod(
                symbol=root,
                expiration=expiration,
                start_date=fetch_start,
                end_date=fetch_end,
                # strike defaults to "*" = all strikes
                # right defaults to "both" = calls + puts
            )
        except Exception:
            return []
        if df is None or len(df) == 0:
            return []
        out = []
        for _, r in df.iterrows():
            strike = _f(r.get("strike"))
            if strike is None or not (lo_strike <= strike <= hi_strike):
                continue
            qd = _to_date(r.get("timestamp") or r.get("date") or r.get("quote_date"))
            if qd is None:
                continue
            right_val = str(r.get("right") or "").upper()
            right = "C" if right_val.startswith("C") else "P"
            out.append({
                "symbol": self.ticker,
                "expiration": expiration.isoformat(),
                "strike": strike,
                "right": right,
                "quote_date": qd.isoformat(),
                "bid": _f(r.get("bid")), "ask": _f(r.get("ask")),
                "open": _f(r.get("open")), "high": _f(r.get("high")),
                "low": _f(r.get("low")), "close": _f(r.get("close")),
                "volume": _i(r.get("volume")),
                "open_interest": _i(r.get("open_interest")),
                "delta": _f(r.get("delta")), "gamma": _f(r.get("gamma")),
                "theta": _f(r.get("theta")), "vega": _f(r.get("vega")),
                "implied_vol": _f(r.get("implied_vol")),
                "underlying_price": _f(r.get("underlying_price")),
            })
        return out

    def _build_chains_from_cache(self) -> None:
        """Read all cached rows for our window into in-memory chains.
        One SQL query for the entire range, then group by date in Python."""
        by_date = cache.fetch_option_eod_for_range(
            self.ticker, self.start_date, self.end_date,
        )
        for qd, rows in by_date.items():
            contracts: list[OptionContract] = []
            underlying = None
            for r in rows:
                if underlying is None and r.get("underlying_price"):
                    underlying = r["underlying_price"]
                contracts.append(_row_to_contract(r))
            if underlying is None:
                underlying = cache.fetch_stock_close(self.ticker, qd) or 0.0
            self._chain_by_date[qd] = OptionsChain(
                underlying=self.ticker,
                quote_date=qd,
                underlying_price=underlying,
                contracts=tuple(contracts),
            )

    # ─── DataProvider Protocol methods ─────────────────────────────────────────
    def get_chain(self, ticker: str, on_date: date) -> OptionsChain | None:
        if ticker.upper() != self.ticker:
            return None
        return self._chain_by_date.get(on_date)

    def get_trading_dates(self, ticker: str, start: date, end: date) -> list[date]:
        if ticker.upper() != self.ticker:
            return []
        return sorted(d for d in self._chain_by_date if start <= d <= end)

    def get_underlying_price(self, ticker: str, on_date: date) -> float | None:
        if ticker.upper() != self.ticker:
            return None
        chain = self._chain_by_date.get(on_date)
        if chain is not None:
            return chain.underlying_price
        return cache.fetch_stock_close(ticker.upper(), on_date)


# ─── Helpers ──────────────────────────────────────────────────────────────────
def _row_to_contract(r: dict) -> OptionContract:
    bid = r.get("bid") or 0.0
    ask = r.get("ask") or 0.0
    last = r.get("close") or (bid + ask) / 2 if (bid or ask) else 0.0
    return OptionContract(
        underlying=r["symbol"],
        expiration=date.fromisoformat(r["expiration"]),
        strike=r["strike"],
        option_type=OptionType.CALL if r["right"] == "C" else OptionType.PUT,
        bid=bid, ask=ask, last=last,
        volume=r.get("volume") or 0,
        open_interest=r.get("open_interest") or 0,
        implied_volatility=r.get("implied_vol") or 0.0,
        delta=r.get("delta"),
        gamma=r.get("gamma"),
        theta=r.get("theta"),
        vega=r.get("vega"),
    )


def _to_date(v) -> date | None:
    if v is None:
        return None
    # Pandas Timestamp / datetime — pull just the date component
    if hasattr(v, "date") and callable(v.date):
        try:
            d = v.date()
            if isinstance(d, date):
                return d
        except Exception:
            pass
    if isinstance(v, date):
        return v
    s = str(v)
    # Accept "2024-01-02", "2024-01-02T17:17:51.877", "20240102", "2024-01-02 17:17:53..."
    if " " in s:
        s = s.split(" ", 1)[0]
    if "T" in s:
        s = s.split("T", 1)[0]
    if len(s) == 8 and s.isdigit():
        return date(int(s[:4]), int(s[4:6]), int(s[6:]))
    try:
        return date.fromisoformat(s)
    except ValueError:
        return None


def _f(v) -> float | None:
    if v is None:
        return None
    try:
        f = float(v)
        # pandas often surfaces NaN — treat as missing
        if f != f:  # NaN check
            return None
        return f
    except (TypeError, ValueError):
        return None


def _i(v) -> int | None:
    if v is None:
        return None
    try:
        return int(v)
    except (TypeError, ValueError):
        return None
