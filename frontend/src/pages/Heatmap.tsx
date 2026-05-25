import { useEffect, useMemo, useState } from 'react';

// ─── Live-data response shape (mirrors server /api/heatmap) ─────────────────
type LiveLeg = { bid: number | null; ask: number | null; delta: number | null; theta: number | null; vega: number | null } | null;
type LiveCell = { strike: number; call: LiveLeg; put: LiveLeg } | null;
type LiveRow = { dte_target: number; dte_actual: number; expiration: string; cells: LiveCell[] };
interface LiveResponse {
  ticker: string;
  spot: number;
  as_of: string;
  strike_offsets_pct: number[];
  rows: LiveRow[];
}

// ─── Black-Scholes (synthetic-only v1) ──────────────────────────────────────
// Abramowitz & Stegun approximation of the standard normal CDF. Good to ~1e-7,
// plenty accurate for displayed option premiums.
function ncdf(x: number): number {
  const a1 =  0.254829592, a2 = -0.284496736, a3 = 1.421413741;
  const a4 = -1.453152027, a5 =  1.061405429, p  = 0.3275911;
  const sign = x < 0 ? -1 : 1;
  const ax = Math.abs(x) / Math.SQRT2;
  const t = 1.0 / (1.0 + p * ax);
  const y = 1.0 - ((((a5 * t + a4) * t + a3) * t + a2) * t + a1) * t * Math.exp(-ax * ax);
  return 0.5 * (1.0 + sign * y);
}
function npdf(x: number): number { return Math.exp(-0.5 * x * x) / Math.sqrt(2 * Math.PI); }

interface BSOutput {
  premium: number;
  delta: number;
  gamma: number;
  theta: number;  // per day (premium decay per calendar day)
  vega: number;   // per 1 vol point (i.e., 0.01)
}
function blackScholes(
  S: number, K: number, T: number, r: number, sigma: number, isCall: boolean,
): BSOutput {
  if (T <= 0 || sigma <= 0 || K <= 0 || S <= 0) {
    const intrinsic = isCall ? Math.max(0, S - K) : Math.max(0, K - S);
    return { premium: intrinsic, delta: isCall ? (S > K ? 1 : 0) : (S < K ? -1 : 0), gamma: 0, theta: 0, vega: 0 };
  }
  const sqrtT = Math.sqrt(T);
  const d1 = (Math.log(S / K) + (r + 0.5 * sigma * sigma) * T) / (sigma * sqrtT);
  const d2 = d1 - sigma * sqrtT;
  const Nd1 = ncdf(d1);
  const Nd2 = ncdf(d2);
  const nd1 = npdf(d1);

  const premium = isCall
    ? S * Nd1 - K * Math.exp(-r * T) * Nd2
    : K * Math.exp(-r * T) * (1 - Nd2) - S * (1 - Nd1);
  const delta = isCall ? Nd1 : Nd1 - 1;
  const gamma = nd1 / (S * sigma * sqrtT);
  // BS theta is per year; convert to per-day for display
  const thetaYr = isCall
    ? (-(S * nd1 * sigma) / (2 * sqrtT)) - r * K * Math.exp(-r * T) * Nd2
    : (-(S * nd1 * sigma) / (2 * sqrtT)) + r * K * Math.exp(-r * T) * (1 - Nd2);
  const theta = thetaYr / 365;
  // Vega per 1.00 vol-point; divide by 100 for "per 1 IV point"
  const vega = (S * nd1 * sqrtT) / 100;
  return { premium, delta, gamma, theta, vega };
}

// ─── Grid generation ────────────────────────────────────────────────────────
// 0DTE = same-day expiry (4 hours of remaining trading time assumed),
// 4DTE = weekly (Mon open → Fri close).
const ALL_DTES = [0, 4, 7, 14, 21, 30, 45, 60];
const ZERO_DTE_T = 4 / (365 * 24); // ~4 hours expressed as fraction of a year

// Only a handful of underlyings list same-day-expiry (0DTE) contracts —
// indices and the most liquid index ETFs. Everyone else: hide the 0DTE row
// so we don't show premium for a contract that wouldn't exist.
const DAILY_EXPIRY_TICKERS = new Set([
  'SPX', 'SPY', 'QQQ', 'IWM', 'NDX', 'RUT', 'XSP', 'DIA',
]);

function dtesFor(ticker: string): number[] {
  const hasDaily = DAILY_EXPIRY_TICKERS.has(ticker.toUpperCase());
  return hasDaily ? ALL_DTES : ALL_DTES.filter((d) => d !== 0);
}
const STRIKE_OFFSETS_PCT = [-7.5, -5, -3, -2, -1, 0, 1, 2, 3, 5, 7.5];

function roundStrike(price: number, k: number): number {
  // Pick a strike grid increment that scales with price.
  const inc = price >= 1000 ? 5 : price >= 200 ? 2.5 : price >= 50 ? 1 : 0.5;
  return Math.round(k / inc) * inc;
}

function tierFor(delta: number): 'aggressive' | 'moderate' | 'conservative' {
  const d = Math.abs(delta);
  if (d > 0.6) return 'aggressive';
  if (d >= 0.3) return 'moderate';
  return 'conservative';
}

const TIER_BG: Record<string, string> = {
  aggressive:   'rgba(248,113,113,0.10)',  // red-ish (deep ITM-leaning)
  moderate:     'rgba(250,204,21,0.10)',   // yellow
  conservative: 'rgba(16,185,129,0.10)',   // green
};
const TIER_BORDER: Record<string, string> = {
  aggressive:   'rgba(248,113,113,0.25)',
  moderate:     'rgba(250,204,21,0.25)',
  conservative: 'rgba(16,185,129,0.25)',
};

function formatMoney(v: number): string {
  if (v >= 1000) return `$${(v / 1000).toFixed(2)}K`;
  return `$${v.toFixed(2)}`;
}

// ─── Component ──────────────────────────────────────────────────────────────
type CellData = {
  strike: number;
  premium: number;     // $ per contract (× 100)
  yieldPct: number;    // premium / collateral (strike × 100 for cash-secured / spread)
  perDay: number;      // premium / DTE
  delta: number;
  gamma: number;
  theta: number;       // per-day, $ per contract
  vega: number;        // per 1 vol-point, $ per contract
  extrinsic: number;
  moneyness: 'ITM' | 'ATM' | 'OTM';
};

export default function Heatmap() {
  const [ticker, setTicker] = useState('SPY');
  const [spot, setSpot] = useState(500);
  const [iv, setIV] = useState(0.20);
  // Risk-free rate is intentionally not exposed — for short-dated options
  // its effect on premium is sub-cent and we don't want to add a knob people
  // will worry about. Fixed at a reasonable T-bill-ish default.
  const rate = 0.05;
  const [isCall, setIsCall] = useState(false); // default to puts (more common income strategy)
  const [mode, setMode] = useState<'synthetic' | 'live'>('synthetic');
  const [live, setLive] = useState<LiveResponse | null>(null);
  const [liveLoading, setLiveLoading] = useState(false);
  const [liveError, setLiveError] = useState<string | null>(null);
  const [hover, setHover] = useState<{ row: number; col: number } | null>(null);
  const [pointer, setPointer] = useState<{ x: number; y: number } | null>(null);

  // Fetch live data when (mode == live) and the user finalizes a ticker.
  // Debounced via 400ms so typing doesn't fire a fetch per keystroke.
  useEffect(() => {
    if (mode !== 'live') return;
    const sym = ticker.trim().toUpperCase();
    if (!sym) return;
    const ctrl = new AbortController();
    const timer = setTimeout(async () => {
      setLiveLoading(true); setLiveError(null);
      try {
        const r = await fetch(`/api/heatmap?ticker=${encodeURIComponent(sym)}`, { signal: ctrl.signal });
        if (!r.ok) {
          const detail = (await r.json().catch(() => null))?.detail ?? `HTTP ${r.status}`;
          throw new Error(detail);
        }
        const data = await r.json() as LiveResponse;
        setLive(data);
        setSpot(data.spot);
      } catch (e: unknown) {
        if ((e as { name?: string }).name !== 'AbortError') {
          setLiveError((e as Error).message || 'Failed to fetch live data');
        }
      } finally {
        setLiveLoading(false);
      }
    }, 400);
    return () => { clearTimeout(timer); ctrl.abort(); };
  }, [ticker, mode]);

  const dteRows = useMemo(() => {
    if (mode === 'live' && live) return live.rows.map((r) => r.dte_actual);
    return dtesFor(ticker);
  }, [ticker, mode, live]);

  const grid = useMemo<CellData[][]>(() => {
    if (mode === 'live' && live) {
      // Build from server response — premium = mid × 100
      return live.rows.map((row) => {
        return row.cells.map((c) => {
          const leg = c ? (isCall ? c.call : c.put) : null;
          if (!c || !leg || leg.bid == null || leg.ask == null) {
            return { strike: c?.strike ?? 0, premium: 0, yieldPct: 0, perDay: 0,
              delta: 0, gamma: 0, theta: 0, vega: 0, extrinsic: 0, moneyness: 'OTM' as const };
          }
          const mid = (leg.bid + leg.ask) / 2;
          const premium = mid * 100;
          const collateral = c.strike * 100;
          const yieldPct = collateral > 0 ? (premium / collateral) * 100 : 0;
          const perDay = row.dte_actual > 0 ? premium / row.dte_actual : 0;
          const intrinsic = isCall ? Math.max(0, live.spot - c.strike) * 100 : Math.max(0, c.strike - live.spot) * 100;
          const extrinsic = Math.max(0, premium - intrinsic);
          const moneyness: CellData['moneyness'] =
            Math.abs(c.strike - live.spot) < live.spot * 0.005 ? 'ATM'
            : (isCall ? (c.strike < live.spot ? 'ITM' : 'OTM') : (c.strike > live.spot ? 'ITM' : 'OTM'));
          return {
            strike: c.strike, premium, yieldPct, perDay,
            delta: leg.delta ?? 0, gamma: 0,
            theta: (leg.theta ?? 0) * 100, vega: (leg.vega ?? 0) * 100,
            extrinsic, moneyness,
          };
        });
      });
    }
    // Synthetic path
    return dteRows.map((dte) => {
      const T = dte === 0 ? ZERO_DTE_T : dte / 365;
      return STRIKE_OFFSETS_PCT.map((off) => {
        const raw = spot * (1 + off / 100);
        const strike = roundStrike(spot, raw);
        const bs = blackScholes(spot, strike, T, rate, iv, isCall);
        const premium = bs.premium * 100;
        const collateral = strike * 100;
        const yieldPct = collateral > 0 ? (premium / collateral) * 100 : 0;
        const perDay = dte > 0 ? premium / dte : 0;
        const intrinsic = isCall ? Math.max(0, spot - strike) * 100 : Math.max(0, strike - spot) * 100;
        const extrinsic = Math.max(0, premium - intrinsic);
        const moneyness: CellData['moneyness'] =
          Math.abs(strike - spot) < spot * 0.005 ? 'ATM'
          : (isCall ? (strike < spot ? 'ITM' : 'OTM') : (strike > spot ? 'ITM' : 'OTM'));
        return {
          strike, premium, yieldPct, perDay,
          delta: bs.delta, gamma: bs.gamma, theta: bs.theta * 100, vega: bs.vega * 100,
          extrinsic, moneyness,
        };
      });
    });
  }, [spot, iv, rate, isCall, dteRows, mode, live]);

  // ATM column index for header highlight
  const atmCol = STRIKE_OFFSETS_PCT.indexOf(0);

  return (
    <div className="min-h-screen" style={{ backgroundColor: 'hsl(220 15% 8%)' }}>
      {/* Brand header */}
      <header className="px-6 py-4 flex items-center gap-3" style={{ background: 'linear-gradient(to right, #12E5CD, #12BAE6)' }}>
        <img src="/XL logo transparent.png" alt="ThesisLab" className="w-8 h-8" />
        <h1 className="text-xl font-bold text-white tracking-tight">Options Heatmap</h1>
      </header>

      <main style={{ padding: '1.5rem' }}>
        {/* Mode banner */}
        {mode === 'synthetic' ? (
          <div style={{ marginBottom: '1rem', padding: '8px 12px', background: 'rgba(245,158,11,0.08)', border: '1px solid rgba(245,158,11,0.25)', borderRadius: 6, fontSize: 12, color: '#fbbf24' }}>
            Synthetic mode — premiums computed from Black-Scholes using the spot price and IV below.
          </div>
        ) : liveError ? (
          <div style={{ marginBottom: '1rem', padding: '8px 12px', background: 'rgba(248,113,113,0.08)', border: '1px solid rgba(248,113,113,0.25)', borderRadius: 6, fontSize: 12, color: '#f87171' }}>
            Live data error: {liveError}
          </div>
        ) : (
          <div style={{ marginBottom: '1rem', padding: '8px 12px', background: 'rgba(16,185,129,0.08)', border: '1px solid rgba(16,185,129,0.25)', borderRadius: 6, fontSize: 12, color: '#34d399' }}>
            Live mode — ThetaData snapshot
            {live && <> · spot ${live.spot.toFixed(2)} · as of {new Date(live.as_of).toLocaleString()}</>}
            {liveLoading && <> · loading…</>}
          </div>
        )}

        {/* Controls */}
        <div style={{ display: 'flex', gap: 16, alignItems: 'flex-end', marginBottom: '1.5rem', flexWrap: 'wrap' }}>
          <div style={{ width: 110 }}>
            <label className="label">Ticker</label>
            <input className="input-field !text-lg !font-bold !tracking-widest !text-center" value={ticker}
              onChange={(e) => setTicker(e.target.value.toUpperCase())} />
          </div>
          <div style={{ width: 110 }}>
            <label className="label">Spot Price</label>
            <div className="relative">
              <span className="absolute left-3 top-1/2 -translate-y-1/2 text-gray-500 text-sm">$</span>
              <input type="number" className="input-field !pl-7" step="0.5" min="1" value={spot}
                onChange={(e) => setSpot(Math.max(1, Number(e.target.value)))}
                disabled={mode === 'live'} title={mode === 'live' ? 'Spot is auto-populated in live mode' : undefined} />
            </div>
          </div>
          {mode === 'synthetic' && (
            <div style={{ width: 110 }}>
              <label className="label">IV (annual)</label>
              <input type="number" className="input-field" step="0.01" min="0.01" max="3" value={iv}
                onChange={(e) => setIV(Math.max(0.01, Number(e.target.value)))} />
            </div>
          )}
          <div>
            <label className="label">Option Type</label>
            <div style={{ display: 'inline-flex', borderRadius: 8, backgroundColor: 'rgba(255,255,255,0.04)', padding: 3, border: '1px solid rgba(255,255,255,0.08)' }}>
              {(['call', 'put'] as const).map((t) => (
                <button key={t} type="button" onClick={() => setIsCall(t === 'call')}
                  style={{
                    padding: '6px 14px', fontSize: 13, fontWeight: 600, borderRadius: 5, border: 'none', cursor: 'pointer',
                    background: (isCall ? 'call' : 'put') === t ? 'hsl(var(--accent))' : 'transparent',
                    color: (isCall ? 'call' : 'put') === t ? 'hsl(var(--primary-foreground))' : '#9ca3af',
                    textTransform: 'capitalize',
                  }}>
                  {t}
                </button>
              ))}
            </div>
          </div>
          <div>
            <label className="label">Data Source</label>
            <div style={{ display: 'inline-flex', borderRadius: 8, backgroundColor: 'rgba(255,255,255,0.04)', padding: 3, border: '1px solid rgba(255,255,255,0.08)' }}>
              {(['synthetic', 'live'] as const).map((m) => (
                <button key={m} type="button" onClick={() => setMode(m)}
                  style={{
                    padding: '6px 14px', fontSize: 13, fontWeight: 600, borderRadius: 5, border: 'none', cursor: 'pointer',
                    background: mode === m ? 'hsl(var(--accent))' : 'transparent',
                    color: mode === m ? 'hsl(var(--primary-foreground))' : '#9ca3af',
                    textTransform: 'capitalize',
                  }}>
                  {m}
                </button>
              ))}
            </div>
          </div>
        </div>

        {/* Heatmap grid */}
        <div className="card" style={{ padding: '1rem', overflowX: 'auto', position: 'relative' }}>
          <div style={{ fontSize: 11, color: '#9ca3af', textTransform: 'uppercase', letterSpacing: '0.05em', textAlign: 'center', marginBottom: 8 }}>
            Strike Price
          </div>
          <table style={{ width: '100%', borderCollapse: 'separate', borderSpacing: '4px', minWidth: '900px' }}>
            <thead>
              <tr>
                <th style={{ fontSize: 11, color: '#9ca3af', textTransform: 'uppercase', letterSpacing: '0.05em', padding: '6px 8px', textAlign: 'center', minWidth: 80 }}>
                  Expiry
                </th>
                {STRIKE_OFFSETS_PCT.map((off, j) => {
                  const sampleStrike = roundStrike(spot, spot * (1 + off / 100));
                  const moneyness = sampleStrike === roundStrike(spot, spot)
                    ? 'ATM' : (isCall ? (sampleStrike < spot ? 'ITM' : 'OTM') : (sampleStrike > spot ? 'ITM' : 'OTM'));
                  const isAtm = j === atmCol;
                  return (
                    <th key={j} style={{
                      fontSize: 11, color: isAtm ? 'white' : '#9ca3af',
                      padding: '6px 8px', textAlign: 'center', fontWeight: 600,
                      background: isAtm ? 'rgba(59,130,246,0.15)' : undefined,
                      borderRadius: 4,
                    }}>
                      <div style={{ fontFamily: 'ui-monospace, monospace' }}>${sampleStrike}</div>
                      <div style={{ fontSize: 9, color: isAtm ? '#dbeafe' : '#6b7280' }}>{moneyness}</div>
                    </th>
                  );
                })}
              </tr>
            </thead>
            <tbody>
              {grid.map((row, i) => {
                const dte = dteRows[i];
                return (
                  <tr key={i}>
                    <td style={{ fontSize: 11, color: '#d1d5db', padding: '6px 8px', textAlign: 'center', fontFamily: 'ui-monospace, monospace' }}>
                      <div style={{ fontWeight: 600 }}>{dte}d</div>
                    </td>
                    {row.map((cell, j) => {
                      const tier = tierFor(cell.delta);
                      const liquidityWarn = false; // synthetic — always "liquid"
                      const isHover = hover?.row === i && hover?.col === j;
                      return (
                        <td key={j}
                          onMouseEnter={(e) => { setHover({ row: i, col: j }); setPointer({ x: e.clientX, y: e.clientY }); }}
                          onMouseMove={(e) => setPointer({ x: e.clientX, y: e.clientY })}
                          onMouseLeave={() => { setHover((h) => (h && h.row === i && h.col === j ? null : h)); setPointer(null); }}
                          style={{
                            background: TIER_BG[tier],
                            border: `1px solid ${isHover ? 'hsl(var(--accent))' : TIER_BORDER[tier]}`,
                            borderRadius: 4, padding: '6px 8px', textAlign: 'center', cursor: 'default',
                            transition: 'border-color 0.1s',
                          }}>
                          <div style={{ fontSize: 12, fontWeight: 700, fontFamily: 'ui-monospace, monospace', color: 'white' }}>
                            {cell.yieldPct.toFixed(2)}%
                          </div>
                          <div style={{ fontSize: 10, fontFamily: 'ui-monospace, monospace', color: '#d1d5db' }}>
                            {formatMoney(cell.premium)}
                          </div>
                          {dte > 0 && (
                            <div style={{ fontSize: 9, fontFamily: 'ui-monospace, monospace', color: '#9ca3af' }}>
                              ${cell.perDay.toFixed(2)}/day
                            </div>
                          )}
                          {liquidityWarn && <div style={{ fontSize: 9, color: '#fbbf24' }}>⚠</div>}
                        </td>
                      );
                    })}
                  </tr>
                );
              })}
            </tbody>
          </table>

          {/* Hover popover — anchored to the cursor, flips to the left/up
              edge if it would overflow the viewport. */}
          {hover && pointer && (() => {
            const cell = grid[hover.row][hover.col];
            const dte = dteRows[hover.row];
            const W = 280, H = 240, GAP = 14;
            const flipX = pointer.x + GAP + W > window.innerWidth;
            const flipY = pointer.y + GAP + H > window.innerHeight;
            const left = flipX ? Math.max(8, pointer.x - GAP - W) : pointer.x + GAP;
            const top  = flipY ? Math.max(8, pointer.y - GAP - H) : pointer.y + GAP;
            return (
              <div style={{
                position: 'fixed', left, top, width: W,
                background: 'rgba(15,20,30,0.97)', border: '1px solid rgba(255,255,255,0.12)', borderRadius: 8,
                padding: '12px 14px', boxShadow: '0 10px 30px rgba(0,0,0,0.4)', zIndex: 60, pointerEvents: 'none',
              }}>
                <div style={{ fontSize: 13, fontWeight: 700, color: 'white', marginBottom: 8 }}>
                  ${cell.strike} {isCall ? 'Call' : 'Put'} · {dte}d
                </div>
                <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: '6px 12px', fontSize: 11 }}>
                  <span style={{ color: '#9ca3af' }}>Yield</span>
                  <span style={{ color: 'white', fontFamily: 'ui-monospace, monospace', textAlign: 'right' }}>{cell.yieldPct.toFixed(2)}%</span>
                  <span style={{ color: '#9ca3af' }}>Premium</span>
                  <span style={{ color: 'white', fontFamily: 'ui-monospace, monospace', textAlign: 'right' }}>{formatMoney(cell.premium)}</span>
                  {dte > 0 && <>
                    <span style={{ color: '#9ca3af' }}>Premium/Day</span>
                    <span style={{ color: 'white', fontFamily: 'ui-monospace, monospace', textAlign: 'right' }}>${cell.perDay.toFixed(2)}</span>
                  </>}
                  <span style={{ color: '#9ca3af' }}>Extrinsic</span>
                  <span style={{ color: 'white', fontFamily: 'ui-monospace, monospace', textAlign: 'right' }}>{formatMoney(cell.extrinsic)}</span>
                  <span style={{ color: '#9ca3af' }}>Moneyness</span>
                  <span style={{ color: 'white', fontFamily: 'ui-monospace, monospace', textAlign: 'right' }}>{cell.moneyness}</span>
                </div>
                <div style={{ height: 1, background: 'rgba(255,255,255,0.08)', margin: '10px 0' }} />
                <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: '6px 12px', fontSize: 11 }}>
                  <span style={{ color: '#9ca3af' }}>Delta</span>
                  <span style={{ color: 'white', fontFamily: 'ui-monospace, monospace', textAlign: 'right' }}>{cell.delta.toFixed(3)}</span>
                  <span style={{ color: '#9ca3af' }}>Gamma</span>
                  <span style={{ color: 'white', fontFamily: 'ui-monospace, monospace', textAlign: 'right' }}>{cell.gamma.toFixed(4)}</span>
                  <span style={{ color: '#9ca3af' }}>Theta</span>
                  <span style={{ color: 'white', fontFamily: 'ui-monospace, monospace', textAlign: 'right' }}>{cell.theta.toFixed(2)}</span>
                  <span style={{ color: '#9ca3af' }}>Vega</span>
                  <span style={{ color: 'white', fontFamily: 'ui-monospace, monospace', textAlign: 'right' }}>{cell.vega.toFixed(2)}</span>
                </div>
              </div>
            );
          })()}
        </div>

        {/* Legend */}
        <div style={{ display: 'flex', gap: 16, marginTop: 16, fontSize: 11, color: '#9ca3af', flexWrap: 'wrap' }}>
          <span style={{ display: 'inline-flex', alignItems: 'center', gap: 6 }}>
            <span style={{ width: 14, height: 14, background: TIER_BG.aggressive, border: `1px solid ${TIER_BORDER.aggressive}`, borderRadius: 3 }} />
            Aggressive (&gt;0.60Δ)
          </span>
          <span style={{ display: 'inline-flex', alignItems: 'center', gap: 6 }}>
            <span style={{ width: 14, height: 14, background: TIER_BG.moderate, border: `1px solid ${TIER_BORDER.moderate}`, borderRadius: 3 }} />
            Moderate (0.30–0.60Δ)
          </span>
          <span style={{ display: 'inline-flex', alignItems: 'center', gap: 6 }}>
            <span style={{ width: 14, height: 14, background: TIER_BG.conservative, border: `1px solid ${TIER_BORDER.conservative}`, borderRadius: 3 }} />
            Conservative (&lt;0.30Δ)
          </span>
        </div>
      </main>
    </div>
  );
}
