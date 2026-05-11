"""Local SQLite cache for ThetaData option/stock EOD pulls.

Lets repeat backtests on overlapping ranges hit local storage instead of the
API, and lets the user keep a private archive after canceling the subscription.
"""

from __future__ import annotations

import sqlite3
from datetime import date, timedelta
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

CREATE TABLE IF NOT EXISTS known_expirations (
    symbol TEXT NOT NULL,       -- API root used to fetch (e.g. SPX or SPXW)
    expiration TEXT NOT NULL,   -- YYYY-MM-DD
    PRIMARY KEY (symbol, expiration)
);

-- Records every successful fetch (or attempted fetch returning zero rows).
-- Lets us distinguish "no data exists" from "haven't asked yet" — without it,
-- holidays/weekends with no rows look identical to genuinely missing ranges
-- and we refetch forever.
CREATE TABLE IF NOT EXISTS option_eod_coverage (
    symbol TEXT NOT NULL,
    expiration TEXT NOT NULL,
    fetch_start TEXT NOT NULL,
    fetch_end TEXT NOT NULL,
    PRIMARY KEY (symbol, expiration, fetch_start, fetch_end)
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


def fetch_option_eod_for_range(
    symbol: str, start: date, end: date,
) -> dict[date, list[dict]]:
    """Return all cached option EOD rows for a symbol in [start, end],
    grouped by quote_date. One SQL query instead of one per day."""
    conn = _connect()
    try:
        cur = conn.execute(
            """SELECT symbol, expiration, strike, right, quote_date,
                      bid, ask, open, high, low, close, volume, open_interest,
                      delta, gamma, theta, vega, implied_vol, underlying_price
               FROM option_eod
               WHERE symbol = ? AND quote_date BETWEEN ? AND ?""",
            (symbol, start.isoformat(), end.isoformat()),
        )
        cols = [d[0] for d in cur.description]
        out: dict[date, list[dict]] = {}
        for row in cur.fetchall():
            r = dict(zip(cols, row))
            qd = date.fromisoformat(r["quote_date"])
            out.setdefault(qd, []).append(r)
        return out
    finally:
        conn.close()


def store_expirations(symbol: str, expirations: Iterable[date]) -> None:
    """Persist the set of expirations returned by option_list_expirations for
    a given API root symbol (e.g. SPX or SPXW). INSERT OR IGNORE so repeated
    calls are no-ops."""
    conn = _connect()
    try:
        conn.executemany(
            "INSERT OR IGNORE INTO known_expirations (symbol, expiration) VALUES (?, ?)",
            [(symbol, e.isoformat()) for e in expirations],
        )
        conn.commit()
    finally:
        conn.close()


def fetch_expirations(symbol: str) -> list[date]:
    """Return all cached expirations for a given API root symbol, sorted."""
    conn = _connect()
    try:
        cur = conn.execute(
            "SELECT expiration FROM known_expirations WHERE symbol = ? ORDER BY expiration",
            (symbol,),
        )
        return [date.fromisoformat(row[0]) for row in cur.fetchall()]
    finally:
        conn.close()


def max_known_expiration(symbol: str) -> date | None:
    """Return the latest cached expiration for a symbol, or None if no entries."""
    conn = _connect()
    try:
        cur = conn.execute(
            "SELECT MAX(expiration) FROM known_expirations WHERE symbol = ?",
            (symbol,),
        )
        row = cur.fetchone()
        return date.fromisoformat(row[0]) if row and row[0] else None
    finally:
        conn.close()


def record_coverage(symbol: str, expiration: date, start: date, end: date) -> None:
    """Record that we asked ThetaData for rows over [start, end] for this
    (symbol, expiration) — regardless of whether any rows came back. This is
    what distinguishes 'no data exists for this date' from 'never fetched'."""
    if start > end:
        return
    conn = _connect()
    try:
        conn.execute(
            "INSERT OR IGNORE INTO option_eod_coverage "
            "(symbol, expiration, fetch_start, fetch_end) VALUES (?, ?, ?, ?)",
            (symbol, expiration.isoformat(), start.isoformat(), end.isoformat()),
        )
        conn.commit()
    finally:
        conn.close()


def _merged_coverage(symbol: str, expiration: date) -> list[tuple[date, date]]:
    """All recorded fetches for this (symbol, expiration), merged into the
    minimum number of contiguous intervals."""
    conn = _connect()
    try:
        cur = conn.execute(
            "SELECT fetch_start, fetch_end FROM option_eod_coverage "
            "WHERE symbol = ? AND expiration = ? ORDER BY fetch_start",
            (symbol, expiration.isoformat()),
        )
        rows = [(date.fromisoformat(s), date.fromisoformat(e)) for s, e in cur.fetchall()]
    finally:
        conn.close()
    if not rows:
        return []
    merged: list[tuple[date, date]] = [rows[0]]
    for s, e in rows[1:]:
        last_s, last_e = merged[-1]
        # Adjacent (one day apart) or overlapping → merge
        if s <= last_e + timedelta(days=1):
            merged[-1] = (last_s, max(last_e, e))
        else:
            merged.append((s, e))
    return merged


def coverage_gaps(
    symbol: str, expiration: date, needed_start: date, needed_end: date,
) -> list[tuple[date, date]]:
    """Return the date sub-ranges of [needed_start, needed_end] that have
    NEVER been fetched. Empty list means 'fully covered, don't refetch'."""
    if needed_start > needed_end:
        return []
    merged = _merged_coverage(symbol, expiration)
    gaps: list[tuple[date, date]] = []
    cursor = needed_start
    for cov_s, cov_e in merged:
        if cov_e < cursor:
            continue
        if cov_s > needed_end:
            break
        if cov_s > cursor:
            gaps.append((cursor, min(cov_s - timedelta(days=1), needed_end)))
        if cov_e >= cursor:
            cursor = cov_e + timedelta(days=1)
        if cursor > needed_end:
            break
    if cursor <= needed_end:
        gaps.append((cursor, needed_end))
    return gaps


def backfill_coverage_from_existing_rows() -> int:
    """One-time migration: for every (symbol, expiration) that has cached
    option rows but no coverage record, insert a coverage row spanning the
    min..max quote_date of its rows. Returns the number of inserts.

    This avoids invalidating the existing cache on the day we introduce
    the coverage table — existing rows count as 'fetched what we have'."""
    conn = _connect()
    try:
        cur = conn.execute("""
            INSERT OR IGNORE INTO option_eod_coverage
                (symbol, expiration, fetch_start, fetch_end)
            SELECT symbol, expiration, MIN(quote_date), MAX(quote_date)
            FROM option_eod
            GROUP BY symbol, expiration
        """)
        inserted = cur.rowcount or 0
        conn.commit()
        return inserted
    finally:
        conn.close()
