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
    ):
        self.ticker = ticker.upper()
        self.start_date = start_date
        self.end_date = end_date
        self.strike_pct = strike_pct
        self.max_dte = max_dte
        self.max_workers = max_workers
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

        # Step 1: ensure stock EOD is cached for the full range
        self._ensure_stock_eod()

        # Step 2: ensure we have option data covering the full range.
        # We consider it covered if both endpoints have data — partial coverage
        # forces a re-fetch (cheap due to ThetaData's bulk-by-expiration calls).
        cached_dates = cache.cached_dates_with_options(
            self.ticker, self.start_date, self.end_date,
        )
        needs_fetch = (
            not cached_dates
            or cached_dates[0] > self.start_date + timedelta(days=4)
            or cached_dates[-1] < self.end_date - timedelta(days=4)
        )
        if needs_fetch:
            self._fetch_chain_universe()

        # Step 3: hydrate in-memory dict[date] -> OptionsChain
        self._build_chains_from_cache()

    def _ensure_stock_eod(self) -> None:
        # Try cache first
        if cache.fetch_stock_close(self.ticker, self.start_date) is not None and \
           cache.fetch_stock_close(self.ticker, self.end_date) is not None:
            return
        df = self._client.stock_history_eod(
            symbol=self.ticker, start_date=self.start_date, end_date=self.end_date,
        )
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
        # Underlying range — used to filter strikes after the pull
        prices = []
        cur = self.start_date
        while cur <= self.end_date:
            p = cache.fetch_stock_close(self.ticker, cur)
            if p is not None:
                prices.append(p)
            cur += timedelta(days=1)
        if not prices:
            raise RuntimeError(
                f"No stock EOD data cached for {self.ticker} in range — "
                "ThetaData may not cover this symbol/range on your tier."
            )
        lo_strike = min(prices) * (1 - self.strike_pct)
        hi_strike = max(prices) * (1 + self.strike_pct)

        # Expirations: anything expiring up to max_dte days past end_date
        exp_horizon = self.end_date + timedelta(days=self.max_dte)
        exp_df = self._client.option_list_expirations(symbol=self.ticker)
        expirations: list[date] = []
        for _, r in exp_df.iterrows():
            d = _to_date(r.get("expiration"))
            if d and self.start_date <= d <= exp_horizon:
                expirations.append(d)

        # One API call per expiration (all strikes, both rights, full date range)
        with ThreadPoolExecutor(max_workers=self.max_workers) as ex:
            futures = [
                ex.submit(self._fetch_expiration, exp, lo_strike, hi_strike)
                for exp in expirations
            ]
            for f in as_completed(futures):
                rows = f.result()
                if rows:
                    cache.store_option_eod(rows)

    def _fetch_expiration(
        self, expiration: date, lo_strike: float, hi_strike: float,
    ) -> list[dict]:
        """Fetch greeks/eod for ALL strikes (both calls and puts) at this
        expiration over the backtest date range. Filter strikes locally."""
        try:
            df = self._client.option_history_greeks_eod(
                symbol=self.ticker,
                expiration=expiration,
                start_date=self.start_date,
                end_date=self.end_date,
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
        """Read all cached rows for our window into in-memory chains."""
        cur = self.start_date
        while cur <= self.end_date:
            rows = cache.fetch_option_eod_for_date(self.ticker, cur)
            if rows:
                contracts: list[OptionContract] = []
                underlying = None
                for r in rows:
                    if underlying is None and r.get("underlying_price"):
                        underlying = r["underlying_price"]
                    contracts.append(_row_to_contract(r))
                if underlying is None:
                    underlying = cache.fetch_stock_close(self.ticker, cur) or 0.0
                self._chain_by_date[cur] = OptionsChain(
                    underlying=self.ticker,
                    quote_date=cur,
                    underlying_price=underlying,
                    contracts=tuple(contracts),
                )
            cur += timedelta(days=1)

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
