"""One-shot cache repair for SPX 2021-style "all bids are zero" data.

When `option_history_greeks_eod` returns rows but every bid is 0 (a known
issue for SPX in 2021), this script refetches the same expiration via
`option_history_trade_quote` (intraday) and downsamples to the last quote
of each day per contract, then patches the bad rows in place.

Usage:
    python -m scripts.repair_zero_bids SPX 2021-01-01 2021-12-31

It only updates rows where bid is currently null or zero — won't clobber
existing good data.
"""

from __future__ import annotations

import sqlite3
import sys
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import date, timedelta

import pandas as pd

from thesislab.data import cache
from thesislab.data.thetadata_provider import _DEFAULT_CREDS, _f, _read_creds, _root_for

# trade_quote is bulk-history-rate-limited to one calendar month per call.
# Chunk wider windows into 28-day pieces with a safety margin.
_CHUNK_DAYS = 28
# Decompression errors are transient — retry the same chunk once.
_RETRIES = 1


def _affected_expirations(
    symbol: str, start: date, end: date, zero_pct_threshold: float = 0.5,
) -> list[tuple[date, date, date]]:
    """Find (expiration, qd_start, qd_end) for expirations where >threshold
    of cached rows have bid=0 in the given quote-date window AND we haven't
    already attempted a trade_quote repair (deep-OTM contracts never trade,
    so the zero-bid rate alone stays high even after a successful repair)."""
    conn = sqlite3.connect(cache.CACHE_PATH)
    # Track which expirations we've attempted to repair already, by reusing
    # the option_eod_coverage table under a synthetic symbol suffix.
    conn.execute(
        "CREATE TABLE IF NOT EXISTS zero_bid_repair_done ("
        "symbol TEXT, expiration TEXT, PRIMARY KEY(symbol, expiration))"
    )
    cur = conn.execute(
        """
        SELECT expiration, MIN(quote_date), MAX(quote_date),
               SUM(CASE WHEN bid IS NULL OR bid = 0 THEN 1 ELSE 0 END) AS zb,
               COUNT(*) AS total
        FROM option_eod
        WHERE symbol = ? AND quote_date BETWEEN ? AND ?
          AND expiration NOT IN (
            SELECT expiration FROM zero_bid_repair_done WHERE symbol = ?
          )
        GROUP BY expiration
        HAVING (CAST(zb AS REAL) / total) > ?
        ORDER BY expiration
        """,
        (symbol, start.isoformat(), end.isoformat(), symbol, zero_pct_threshold),
    )
    rows = [
        (date.fromisoformat(r[0]), date.fromisoformat(r[1]), date.fromisoformat(r[2]))
        for r in cur.fetchall()
    ]
    conn.close()
    return rows


def _mark_repaired(symbol: str, expiration: date) -> None:
    """Record that we've attempted a trade_quote repair for this expiration,
    so future runs skip it even if many deep-OTM rows remain bid=0."""
    conn = sqlite3.connect(cache.CACHE_PATH)
    try:
        conn.execute(
            "INSERT OR IGNORE INTO zero_bid_repair_done (symbol, expiration) VALUES (?, ?)",
            (symbol, expiration.isoformat()),
        )
        conn.commit()
    finally:
        conn.close()


def _fetch_one_chunk(
    client, symbol: str, expiration: date, qd_start: date, qd_end: date,
) -> tuple[pd.DataFrame | None, str | None]:
    """Single trade_quote call. Retries `_RETRIES` times on transient errors
    (decompression / corruption). Returns (df, error_message)."""
    root = _root_for(symbol, expiration)
    last_err: str | None = None
    for attempt in range(_RETRIES + 1):
        try:
            df = client.option_history_trade_quote(
                symbol=root, expiration=expiration,
                start_date=qd_start, end_date=qd_end,
            )
            return df, None
        except Exception as e:
            last_err = str(e)
            # Only retry transient decompression errors — argument/permission
            # errors won't get better.
            if "decompression" not in last_err.lower():
                break
    return None, last_err


def _fetch_trade_quote_eod(
    client, symbol: str, expiration: date, qd_start: date, qd_end: date,
) -> list[dict]:
    """Pull intraday trade_quote rows for the expiration in <=28-day chunks
    (API limits bulk history to one month), downsample each to last quote of
    the day per (strike, right). Returns rows suitable for patching
    option_eod's bid/ask columns."""
    frames: list[pd.DataFrame] = []
    errors: list[str] = []
    chunk_start = qd_start
    while chunk_start <= qd_end:
        chunk_end = min(chunk_start + timedelta(days=_CHUNK_DAYS - 1), qd_end)
        df, err = _fetch_one_chunk(client, symbol, expiration, chunk_start, chunk_end)
        if err:
            errors.append(f"{chunk_start}..{chunk_end}: {err}")
        elif df is not None and len(df) > 0:
            frames.append(df)
        chunk_start = chunk_end + timedelta(days=1)

    if not frames:
        if errors:
            return [{"_error": "; ".join(errors[:2])}]
        return []

    df = pd.concat(frames, ignore_index=True)
    df = df.dropna(subset=["trade_timestamp", "strike", "right"])
    if len(df) == 0:
        return []
    ts = pd.to_datetime(df["trade_timestamp"])
    df = df.assign(_qd=ts.dt.date.astype(str), _ts=ts)

    # Last tick per (strike, right, date)
    last_idx = df.groupby(["strike", "right", "_qd"])["_ts"].idxmax()
    sub = df.loc[last_idx]

    out: list[dict] = []
    for _, r in sub.iterrows():
        right_val = str(r["right"]).upper()
        right = "C" if right_val.startswith("C") else "P"
        out.append({
            "symbol": symbol,
            "expiration": expiration.isoformat(),
            "strike": float(r["strike"]),
            "right": right,
            "quote_date": r["_qd"],
            "bid": _f(r["bid"]),
            "ask": _f(r["ask"]),
        })
    return out


def _patch_rows(rows: list[dict]) -> int:
    """UPDATE option_eod for each row, only overwriting bid/ask when our
    new value is non-null and the existing value is null/zero."""
    if not rows:
        return 0
    conn = sqlite3.connect(cache.CACHE_PATH)
    try:
        n = 0
        for r in rows:
            cur = conn.execute(
                """
                UPDATE option_eod
                SET bid = CASE WHEN ? IS NOT NULL AND (bid IS NULL OR bid = 0) THEN ? ELSE bid END,
                    ask = CASE WHEN ? IS NOT NULL AND (ask IS NULL OR ask = 0) THEN ? ELSE ask END
                WHERE symbol = ? AND expiration = ? AND strike = ? AND right = ? AND quote_date = ?
                """,
                (r["bid"], r["bid"], r["ask"], r["ask"],
                 r["symbol"], r["expiration"], r["strike"], r["right"], r["quote_date"]),
            )
            n += cur.rowcount or 0
        conn.commit()
        return n
    finally:
        conn.close()


def main() -> int:
    if len(sys.argv) < 4:
        print("Usage: python -m scripts.repair_zero_bids SYMBOL START END")
        return 2
    symbol = sys.argv[1].upper()
    start = date.fromisoformat(sys.argv[2])
    end = date.fromisoformat(sys.argv[3])

    affected = _affected_expirations(symbol, start, end)
    print(f"{symbol} {start}..{end}: {len(affected)} expirations need repair")
    if not affected:
        return 0

    creds = _read_creds()
    if not creds:
        print(f"ThetaData creds not found (env vars or {_DEFAULT_CREDS})")
        return 1
    from thetadata import ThetaClient
    client = ThetaClient(email=creds[0], password=creds[1], dataframe_type="pandas")

    t0 = time.perf_counter()
    done = 0
    total_patched = 0
    errors = 0
    with ThreadPoolExecutor(max_workers=4) as ex:
        futures = {
            ex.submit(_fetch_trade_quote_eod, client, symbol, exp, qs, qe): (exp, qs, qe)
            for exp, qs, qe in affected
        }
        for f in as_completed(futures):
            exp, qs, qe = futures[f]
            done += 1
            try:
                rows = f.result()
            except Exception as e:
                errors += 1
                print(f"  EXCEPTION exp={exp}: {type(e).__name__}: {e}", flush=True)
                # Still mark as attempted — re-running won't help if the
                # response shape itself is the problem.
                try:
                    _mark_repaired(symbol, exp)
                except Exception:
                    pass
                continue
            if rows and rows[0].get("_error"):
                errors += 1
                print(f"  ERROR exp={exp}: {rows[0]['_error']}", flush=True)
                try:
                    _mark_repaired(symbol, exp)
                except Exception:
                    pass
                continue
            try:
                patched = _patch_rows(rows)
                total_patched += patched
                _mark_repaired(symbol, exp)
            except Exception as e:
                errors += 1
                print(f"  PATCH_FAILED exp={exp}: {type(e).__name__}: {e}", flush=True)
            if done % 5 == 0 or done == len(affected):
                wall = time.perf_counter() - t0
                print(f"  {done}/{len(affected)} done — patched {total_patched:,} rows, "
                      f"{errors} errors ({wall:.0f}s, avg {wall/done:.1f}s/exp)", flush=True)

    print(f"\nFinished. Patched {total_patched:,} rows across {done} expirations. "
          f"{errors} errors. Wall: {time.perf_counter()-t0:.0f}s")
    return 0


if __name__ == "__main__":
    sys.exit(main())
