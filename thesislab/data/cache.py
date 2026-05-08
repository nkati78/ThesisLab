"""Local SQLite cache for ThetaData option/stock EOD pulls.

Lets repeat backtests on overlapping ranges hit local storage instead of the
API, and lets the user keep a private archive after canceling the subscription.
"""

from __future__ import annotations

import sqlite3
from datetime import date
from pathlib import Path
from typing import Iterable

CACHE_PATH = Path.home() / ".thesislab" / "thetadata_cache.sqlite"

_SCHEMA = """
CREATE TABLE IF NOT EXISTS option_eod (
    symbol TEXT NOT NULL,
    expiration TEXT NOT NULL,   -- YYYY-MM-DD
    strike REAL NOT NULL,
    right TEXT NOT NULL,        -- 'C' or 'P'
    quote_date TEXT NOT NULL,   -- YYYY-MM-DD
    bid REAL, ask REAL,
    open REAL, high REAL, low REAL, close REAL,
    volume INTEGER, open_interest INTEGER,
    delta REAL, gamma REAL, theta REAL, vega REAL,
    implied_vol REAL,
    underlying_price REAL,
    PRIMARY KEY (symbol, expiration, strike, right, quote_date)
);

CREATE INDEX IF NOT EXISTS idx_option_eod_lookup
    ON option_eod (symbol, quote_date);

CREATE TABLE IF NOT EXISTS stock_eod (
    symbol TEXT NOT NULL,
    quote_date TEXT NOT NULL,
    open REAL, high REAL, low REAL, close REAL,
    volume INTEGER,
    PRIMARY KEY (symbol, quote_date)
);

CREATE TABLE IF NOT EXISTS contract_universe (
    symbol TEXT NOT NULL,
    quote_date TEXT NOT NULL,   -- the date we cached the chain on
    expiration TEXT NOT NULL,
    strike REAL NOT NULL,
    right TEXT NOT NULL,
    PRIMARY KEY (symbol, quote_date, expiration, strike, right)
);
"""


def _connect() -> sqlite3.Connection:
    CACHE_PATH.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(CACHE_PATH)
    conn.executescript(_SCHEMA)
    return conn


def store_option_eod(rows: Iterable[dict]) -> None:
    """Bulk insert option EOD rows. Each row is a dict with the table's columns."""
    conn = _connect()
    try:
        conn.executemany(
            """INSERT OR REPLACE INTO option_eod
               (symbol, expiration, strike, right, quote_date,
                bid, ask, open, high, low, close, volume, open_interest,
                delta, gamma, theta, vega, implied_vol, underlying_price)
               VALUES (:symbol, :expiration, :strike, :right, :quote_date,
                       :bid, :ask, :open, :high, :low, :close, :volume, :open_interest,
                       :delta, :gamma, :theta, :vega, :implied_vol, :underlying_price)""",
            rows,
        )
        conn.commit()
    finally:
        conn.close()


def fetch_option_eod_for_date(symbol: str, on_date: date) -> list[dict]:
    """Return all cached option EOD rows for a symbol on a given date."""
    conn = _connect()
    try:
        cur = conn.execute(
            """SELECT symbol, expiration, strike, right, quote_date,
                      bid, ask, open, high, low, close, volume, open_interest,
                      delta, gamma, theta, vega, implied_vol, underlying_price
               FROM option_eod
               WHERE symbol = ? AND quote_date = ?""",
            (symbol, on_date.isoformat()),
        )
        cols = [d[0] for d in cur.description]
        return [dict(zip(cols, row)) for row in cur.fetchall()]
    finally:
        conn.close()


def has_option_data_for_range(symbol: str, start: date, end: date) -> bool:
    """Quick check: do we have any option data for this symbol in the range?
    Used to short-circuit API fetches when the cache is already populated.
    """
    conn = _connect()
    try:
        cur = conn.execute(
            """SELECT COUNT(*) FROM option_eod
               WHERE symbol = ? AND quote_date BETWEEN ? AND ?""",
            (symbol, start.isoformat(), end.isoformat()),
        )
        return (cur.fetchone()[0] or 0) > 0
    finally:
        conn.close()


def store_stock_eod(rows: Iterable[dict]) -> None:
    conn = _connect()
    try:
        conn.executemany(
            """INSERT OR REPLACE INTO stock_eod
               (symbol, quote_date, open, high, low, close, volume)
               VALUES (:symbol, :quote_date, :open, :high, :low, :close, :volume)""",
            rows,
        )
        conn.commit()
    finally:
        conn.close()


def fetch_stock_close(symbol: str, on_date: date) -> float | None:
    conn = _connect()
    try:
        cur = conn.execute(
            "SELECT close FROM stock_eod WHERE symbol = ? AND quote_date = ?",
            (symbol, on_date.isoformat()),
        )
        row = cur.fetchone()
        return row[0] if row else None
    finally:
        conn.close()


def has_expiration_data(symbol: str, expiration: date) -> bool:
    """True if we have any cached EOD rows for this (symbol, expiration)."""
    conn = _connect()
    try:
        cur = conn.execute(
            "SELECT 1 FROM option_eod WHERE symbol = ? AND expiration = ? LIMIT 1",
            (symbol, expiration.isoformat()),
        )
        return cur.fetchone() is not None
    finally:
        conn.close()


def expiration_quote_date_range(symbol: str, expiration: date) -> tuple[date, date] | None:
    """Return (min_quote_date, max_quote_date) cached for this (symbol, expiration),
    or None if no rows exist. Used to detect when an earlier run partially
    populated an expiration but didn't fetch all the days we need now."""
    conn = _connect()
    try:
        cur = conn.execute(
            "SELECT MIN(quote_date), MAX(quote_date) FROM option_eod WHERE symbol = ? AND expiration = ?",
            (symbol, expiration.isoformat()),
        )
        row = cur.fetchone()
        if not row or row[0] is None:
            return None
        return date.fromisoformat(row[0]), date.fromisoformat(row[1])
    finally:
        conn.close()


def cached_dates_with_options(symbol: str, start: date, end: date) -> list[date]:
    """Return the distinct dates within [start, end] that have any cached option data."""
    conn = _connect()
    try:
        cur = conn.execute(
            """SELECT DISTINCT quote_date FROM option_eod
               WHERE symbol = ? AND quote_date BETWEEN ? AND ?
               ORDER BY quote_date""",
            (symbol, start.isoformat(), end.isoformat()),
        )
        return [date.fromisoformat(row[0]) for row in cur.fetchall()]
    finally:
        conn.close()
