import { useState, useRef } from 'react';
import type { StrategyConfig } from '../types/api';
import { InfoTip } from './InfoTip';

interface Props {
  strategy: StrategyConfig;
  onChange: (s: StrategyConfig) => void;
  underlyingPrice: number;
}

/* ── Price-scaled width helpers ── */
// Returns a sensible strike-width step and snap points scaled to the underlying price.
// For a ~$450 stock (SPY) widths are $1-$50; for ~$5000 (SPX) widths are $5-$500.
function widthSnaps(price: number): { step: number; snaps: number[]; max: number } {
  if (price >= 1000) {
    return { step: 5, snaps: [5, 10, 25, 50, 75, 100, 200], max: 500 };
  }
  if (price >= 300) {
    return { step: 1, snaps: [1, 2, 5, 10, 15, 20, 50], max: 50 };
  }
  return { step: 0.5, snaps: [0.5, 1, 2, 3, 5, 10], max: 25 };
}


/* ── Editable value display ── */
function EditableValue({ value, onChange, format, min, max, step }: {
  value: number; onChange: (v: number) => void;
  format?: (v: number) => string; min: number; max: number; step: number;
}) {
  const [editing, setEditing] = useState(false);
  const [draft, setDraft] = useState('');

  const handleStart = () => {
    setDraft(String(value));
    setEditing(true);
  };

  const handleCommit = () => {
    const n = Number(draft);
    if (!isNaN(n)) {
      onChange(Math.min(max, Math.max(min, n)));
    }
    setEditing(false);
  };

  if (editing) {
    return (
      <input
        autoFocus
        type="number"
        className="w-16 bg-transparent border border-[hsl(var(--accent))] rounded px-1 py-0 text-sm font-mono text-white text-right outline-none"
        value={draft}
        min={min} max={max} step={step}
        onChange={(e) => setDraft(e.target.value)}
        onBlur={handleCommit}
        onKeyDown={(e) => { if (e.key === 'Enter') handleCommit(); if (e.key === 'Escape') setEditing(false); }}
      />
    );
  }

  return (
    <span
      onClick={handleStart}
      className="text-sm font-mono text-white cursor-pointer hover:text-[hsl(var(--accent))] transition-colors border-b border-dashed border-white/20 hover:border-[hsl(var(--accent))]"
      title="Click to edit"
    >
      {format ? format(value) : value}
    </span>
  );
}

/* ── Custom slider with snap points ── */
function SnapSlider({ value, min, max, step, snaps, snapLabels, onChange }: {
  value: number; min: number; max: number; step: number;
  snaps: number[]; snapLabels?: (v: number) => string;
  onChange: (v: number) => void;
}) {
  const trackRef = useRef<HTMLDivElement>(null);

  const pct = (v: number) => ((v - min) / (max - min)) * 100;
  const valuePct = pct(value);

  const handleTrackClick = (e: React.MouseEvent<HTMLDivElement>) => {
    if (!trackRef.current) return;
    const rect = trackRef.current.getBoundingClientRect();
    const x = (e.clientX - rect.left) / rect.width;
    const raw = min + x * (max - min);
    const snapped = Math.round(raw / step) * step;
    onChange(Math.min(max, Math.max(min, snapped)));
  };

  const handleDrag = (e: React.MouseEvent) => {
    e.preventDefault();
    const move = (ev: MouseEvent) => {
      if (!trackRef.current) return;
      const rect = trackRef.current.getBoundingClientRect();
      const x = Math.min(1, Math.max(0, (ev.clientX - rect.left) / rect.width));
      const raw = min + x * (max - min);
      const snapped = Math.round(raw / step) * step;
      onChange(Math.min(max, Math.max(min, snapped)));
    };
    const up = () => { window.removeEventListener('mousemove', move); window.removeEventListener('mouseup', up); };
    window.addEventListener('mousemove', move);
    window.addEventListener('mouseup', up);
  };

  return (
    <div className="relative" style={{ paddingTop: '20px', paddingBottom: '4px' }}>
      {/* Snap labels above track */}
      {snaps.map((s) => (
        <button
          key={s}
          onClick={() => onChange(s)}
          className={`absolute cursor-pointer transition-colors ${
            s === value ? 'font-semibold' : ''
          }`}
          style={{
            left: `${pct(s)}%`,
            transform: 'translateX(-50%)',
            top: 0,
            fontSize: '10px',
            color: s === value ? 'hsl(var(--accent))' : '#9ca3af',
            background: 'none',
            border: 'none',
            padding: 0,
          }}
        >
          {snapLabels ? snapLabels(s) : s}
        </button>
      ))}

      {/* Track background */}
      <div
        ref={trackRef}
        className="relative cursor-pointer"
        style={{ height: '4px', borderRadius: '2px', backgroundColor: 'rgba(255,255,255,0.08)' }}
        onClick={handleTrackClick}
      >
        {/* Filled portion */}
        <div
          className="absolute left-0 top-0"
          style={{ height: '100%', borderRadius: '2px', backgroundColor: 'hsl(var(--accent))', width: `${valuePct}%` }}
        />

        {/* Snap point dots */}
        {snaps.map((s) => {
          const active = s <= value;
          return (
            <button
              key={s}
              onClick={(e) => { e.stopPropagation(); onChange(s); }}
              style={{
                position: 'absolute',
                top: '50%',
                left: `${pct(s)}%`,
                transform: 'translate(-50%, -50%)',
                width: '6px',
                height: '6px',
                borderRadius: '50%',
                backgroundColor: active ? 'hsl(var(--accent))' : 'rgba(255,255,255,0.3)',
                border: 'none',
                padding: 0,
                cursor: 'pointer',
              }}
            />
          );
        })}

        {/* Draggable thumb */}
        <div
          className="cursor-grab active:cursor-grabbing"
          style={{
            position: 'absolute',
            top: '50%',
            left: `${valuePct}%`,
            transform: 'translate(-50%, -50%)',
            width: '14px',
            height: '14px',
            borderRadius: '50%',
            backgroundColor: 'hsl(var(--accent))',
            border: '2px solid white',
            boxShadow: '0 1px 3px rgba(0,0,0,0.3)',
          }}
          onMouseDown={handleDrag}
        />
      </div>
    </div>
  );
}

/* ── Slider with snap points and editable value ── */
function Slider({ label, value, min, max, step, help, tip, onChange, format, snaps, snapLabels }: {
  label: string; value: number; min: number; max: number; step: number;
  help?: string; tip?: string; onChange: (v: number) => void; format?: (v: number) => string;
  snaps?: number[]; snapLabels?: (v: number) => string;
}) {
  return (
    <div style={{ marginBottom: '1.75rem' }}>
      <div className="flex justify-between items-center mb-1">
        <label className="text-sm" style={{ color: '#d1d5db' }}>
          {label}{tip && <InfoTip text={tip} />}
        </label>
        <EditableValue value={value} onChange={onChange} format={format} min={min} max={max} step={step} />
      </div>
      {snaps ? (
        <SnapSlider value={value} min={min} max={max} step={step} snaps={snaps} snapLabels={snapLabels} onChange={onChange} />
      ) : (
        <input type="range" min={min} max={max} step={step} value={value}
          onChange={(e) => onChange(Number(e.target.value))}
          className="w-full accent-blue-500" />
      )}
      {help && <p className="text-xs text-[hsl(var(--muted-foreground))] mt-0.5">{help}</p>}
    </div>
  );
}

export function StrategyPanel({ strategy, onChange, underlyingPrice }: Props) {
  const set = (patch: Partial<StrategyConfig>) => onChange({ ...strategy, ...patch });
  const type = strategy.type;
  const w = widthSnaps(underlyingPrice);

  const isSpread = ['short_put_spread', 'short_call_spread', 'debit_call_spread', 'debit_put_spread', 'calendar_call_spread', 'calendar_put_spread'].includes(type);
  const isIronCondor = ['iron_condor', 'iron_butterfly', 'long_call_butterfly', 'long_put_butterfly'].includes(type);
  const isProtPut = type === 'protective_put';
  const isDebitStraddle = type === 'straddle';

  return (
    <div>
      <div className="grid grid-cols-1 md:grid-cols-3 gap-6">
        {/* Entry Criteria */}
        <div className="card">
          <h3 className="card-title">Entry Criteria<InfoTip text="Conditions that must be met before a new position is opened." /></h3>
          <Slider label="Min DTE" value={strategy.min_dte} min={1} max={90} step={1}
            snaps={[7, 14, 21, 30, 45, 60, 90]}
            snapLabels={(v) => `${v}d`}
            tip="Minimum days to expiration. Options expiring sooner than this are ignored."
            onChange={(v) => set({ min_dte: v })} />
          <Slider label="Max DTE" value={strategy.max_dte} min={1} max={120} step={1}
            snaps={[14, 30, 45, 60, 90, 120]}
            snapLabels={(v) => `${v}d`}
            tip="Maximum days to expiration. Options expiring later than this are ignored."
            onChange={(v) => set({ max_dte: v })} />
          {strategy.min_dte > strategy.max_dte && (
            <p className="text-yellow-400 text-xs">Min DTE should be less than Max DTE</p>
          )}
          <div style={{ marginTop: '0.75rem' }}>
            <div style={{ display: 'flex', alignItems: 'center', gap: '4px', marginBottom: '6px' }}>
              <label style={{ fontSize: '13px', color: '#d1d5db' }}>Entry Day</label>
              <InfoTip text="Restrict entries to a specific day of the week. 'Daily' opens whenever conditions allow." />
            </div>
            <select
              className="input-field"
              value={strategy.entry_dow}
              onChange={(e) => set({ entry_dow: e.target.value })}
              style={{ width: '100%', padding: '8px 10px', fontSize: '13px' }}
            >
              <option value="any">Daily</option>
              <option value="monday">Monday only</option>
              <option value="tuesday">Tuesday only</option>
              <option value="wednesday">Wednesday only</option>
              <option value="thursday">Thursday only</option>
              <option value="friday">Friday only</option>
              <option value="weekly">Weekly (Mon → Fri, holiday-aware)</option>
            </select>
            {strategy.entry_dow === 'weekly' && (
              <p className="text-xs text-gray-500" style={{ marginTop: '4px' }}>
                Opens on the first trading day of each week and targets the last trading day's expiration. Min/Max DTE are overridden automatically.
              </p>
            )}
          </div>
        </div>

        {/* Delta & Spread */}
        <div className="card">
          <h3 className="card-title">
            {isSpread || isIronCondor ? <>Delta & Spread<InfoTip text="Controls how far out-of-the-money the options are and the width between strike prices." /></> : <>Delta<InfoTip text="Controls how far out-of-the-money the selected options are." /></>}
          </h3>
          {isProtPut ? (
            <Slider label="Put Delta Target" value={strategy.put_delta}
              min={-0.5} max={-0.05} step={0.01}
              snaps={[-0.40, -0.30, -0.20, -0.10]}
              format={(v) => v.toFixed(2)}
              tip="Target delta for the protective put. More negative = closer to ATM (more expensive but more protection)."
              onChange={(v) => set({ put_delta: v })} />
          ) : (type !== 'straddle' && type !== 'short_straddle') ? (
            <Slider label="Short Delta" value={strategy.short_delta}
              min={0.05} max={0.5} step={0.01}
              snaps={[0.10, 0.16, 0.20, 0.25, 0.30, 0.40]}
              format={(v) => v.toFixed(2)}
              snapLabels={(v) => `.${(v * 100).toFixed(0).padStart(2, '0')}`}
              tip="Delta of the short option leg. Lower values are more OTM with higher probability of profit but smaller premium."
              onChange={(v) => set({ short_delta: v })} />
          ) : null}
          {(isSpread) && (
            <>
              <Slider label="Spread Width ($)" value={strategy.spread_width}
                min={w.step} max={w.max} step={w.step}
                snaps={w.snaps}
                format={(v) => `$${v}`}
                snapLabels={(v) => `$${v}`}
                tip="Dollar distance between short and long strikes. Wider spreads collect more premium but increase max loss."
                onChange={(v) => set({ spread_width: v })} />
              <Slider label="Quantity" value={strategy.contracts_per_trade}
                min={1} max={20} step={1}
                snaps={[1, 2, 3, 5, 10]}
                tip="Number of contracts per trade. P&L scales linearly with this — Quantity 5 buys/sells 5 contracts on each entry."
                onChange={(v) => set({ contracts_per_trade: v })} />
            </>
          )}
          {isIronCondor && (
            <Slider label="Wing Width ($)" value={strategy.wing_width}
              min={w.step} max={w.max} step={w.step}
              snaps={w.snaps}
              format={(v) => `$${v}`}
              snapLabels={(v) => `$${v}`}
              tip="Dollar distance between short and long wings on each side. Wider wings increase max loss but collect more premium."
              onChange={(v) => set({ wing_width: v })} />
          )}
        </div>

        {/* Exit Criteria — per-criterion opt-in */}
        <div className="card">
          <h3 className="card-title">Exit Criteria<InfoTip text="Optional rules that close a position before expiration. Enable any combination — none enabled means hold to expiration." /></h3>

          {/* Take Profit */}
          <div style={{ marginBottom: '0.5rem' }}>
            <label className="flex items-center gap-2 cursor-pointer" style={{ marginBottom: '4px' }}>
              <input type="checkbox" checked={strategy.close_at_profit_enabled}
                onChange={(e) => set({ close_at_profit_enabled: e.target.checked })}
                className="w-3.5 h-3.5 rounded accent-blue-500" />
              <span style={{ fontSize: '13px', color: strategy.close_at_profit_enabled ? 'white' : '#9ca3af' }}>Take Profit</span>
            </label>
            <div style={{ opacity: strategy.close_at_profit_enabled ? 1 : 0.4, pointerEvents: strategy.close_at_profit_enabled ? 'auto' : 'none' }}>
              <Slider label="" value={strategy.close_at_profit_pct}
                min={0.1} max={2.0} step={0.05}
                snaps={[0.25, 0.50, 0.75, 1.0]}
                format={(v) => `${(v * 100).toFixed(0)}%`}
                snapLabels={(v) => `${(v * 100).toFixed(0)}%`}
                tip="Close when this percentage of max profit is reached."
                onChange={(v) => set({ close_at_profit_pct: v })} />
            </div>
          </div>

          {/* Stop Loss */}
          <div style={{ marginBottom: '0.5rem' }}>
            <label className="flex items-center gap-2 cursor-pointer" style={{ marginBottom: '4px' }}>
              <input type="checkbox" checked={strategy.close_at_loss_enabled}
                onChange={(e) => set({ close_at_loss_enabled: e.target.checked })}
                className="w-3.5 h-3.5 rounded accent-blue-500" />
              <span style={{ fontSize: '13px', color: strategy.close_at_loss_enabled ? 'white' : '#9ca3af' }}>
                Stop Loss{!isDebitStraddle && !isProtPut ? ' (x credit)' : ''}
              </span>
            </label>
            <div style={{ opacity: strategy.close_at_loss_enabled ? 1 : 0.4, pointerEvents: strategy.close_at_loss_enabled ? 'auto' : 'none' }}>
              {!isDebitStraddle && !isProtPut ? (
                <Slider label="" value={strategy.close_at_loss_pct}
                  min={0.5} max={5.0} step={0.25}
                  snaps={[1.0, 1.5, 2.0, 3.0, 4.0]}
                  format={(v) => `${v.toFixed(2)}x`}
                  snapLabels={(v) => `${v}x`}
                  tip="Close when cost to close exceeds this multiple of the entry credit."
                  onChange={(v) => set({ close_at_loss_pct: v })} />
              ) : (
                <Slider label="" value={strategy.close_at_loss_pct}
                  min={0.1} max={1.0} step={0.05}
                  snaps={[0.25, 0.50, 0.75, 1.0]}
                  format={(v) => `${(v * 100).toFixed(0)}%`}
                  snapLabels={(v) => `${(v * 100).toFixed(0)}%`}
                  tip="Close when loss reaches this percentage of the entry debit."
                  onChange={(v) => set({ close_at_loss_pct: v })} />
              )}
            </div>
          </div>

          {/* Close at DTE */}
          <div style={{ marginBottom: '0.5rem' }}>
            <label className="flex items-center gap-2 cursor-pointer" style={{ marginBottom: '4px' }}>
              <input type="checkbox" checked={strategy.close_at_dte_enabled}
                onChange={(e) => set({ close_at_dte_enabled: e.target.checked })}
                className="w-3.5 h-3.5 rounded accent-blue-500" />
              <span style={{ fontSize: '13px', color: strategy.close_at_dte_enabled ? 'white' : '#9ca3af' }}>Close at DTE</span>
            </label>
            <div style={{ opacity: strategy.close_at_dte_enabled ? 1 : 0.4, pointerEvents: strategy.close_at_dte_enabled ? 'auto' : 'none' }}>
              <Slider label="" value={strategy.close_at_dte}
                min={0} max={30} step={1}
                snaps={[0, 3, 7, 14, 21]}
                snapLabels={(v) => `${v}d`}
                tip="Close when this many days remain until expiration, regardless of P&L."
                onChange={(v) => set({ close_at_dte: v })} />
            </div>
          </div>

          {/* Short Strike Breach */}
          <div>
            <label className="flex items-center gap-2 cursor-pointer">
              <input type="checkbox" checked={strategy.close_on_short_breach}
                onChange={(e) => set({ close_on_short_breach: e.target.checked })}
                className="w-3.5 h-3.5 rounded accent-blue-500" />
              <span style={{ fontSize: '13px', color: strategy.close_on_short_breach ? 'white' : '#9ca3af' }}>Short Strike Breach</span>
              <InfoTip text="Close as soon as the underlying crosses any short strike (price falls below a short put or rises above a short call). No effect on long-only strategies." />
            </label>
          </div>
        </div>
      </div>
    </div>
  );
}
