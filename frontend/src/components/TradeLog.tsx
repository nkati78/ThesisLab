import { useState, useMemo } from 'react';
import type { TradeResult } from '../types/api';
import { formatCurrency } from '../lib/utils';

interface Props {
  trades: TradeResult[];
}

type SortKey = keyof TradeResult;
type SortDir = 'asc' | 'desc';

const COLUMNS: { key: SortKey; label: string; align: 'left' | 'center' | 'right' }[] = [
  { key: 'number', label: '#', align: 'center' },
  { key: 'strategy', label: 'Strategy', align: 'center' },
  { key: 'entry_date', label: 'Entry', align: 'center' },
  { key: 'exit_date', label: 'Exit', align: 'center' },
  { key: 'strikes', label: 'Strikes', align: 'center' },
  { key: 'contracts', label: 'Qty', align: 'center' },
  { key: 'entry_premium', label: 'Entry Prem.', align: 'center' },
  { key: 'exit_premium', label: 'Exit Prem.', align: 'center' },
  { key: 'pnl', label: 'P&L', align: 'center' },
  { key: 'days_held', label: 'Days', align: 'center' },
  { key: 'result', label: 'Result', align: 'center' },
];

const perShare = (t: TradeResult): number => {
  // contracts is per-strategy-unit count; standard options multiplier is 100.
  const denom = (t.contracts || 1) * 100;
  return t.entry_premium / denom;
};

const PAGE_SIZE = 20;

function downloadCSV(trades: TradeResult[]) {
  const headers = ['#', 'Strategy', 'Entry Date', 'Exit Date', 'Strikes', 'Qty', 'Entry Premium', 'Entry $/share', 'Exit Premium', 'P&L', 'Days Held', 'Result'];
  const rows = trades.map((t) => [
    t.number, t.strategy, t.entry_date, t.exit_date,
    `"${t.strikes}"`, t.contracts ?? 1, t.entry_premium.toFixed(2),
    perShare(t).toFixed(2), t.exit_premium.toFixed(2),
    t.pnl.toFixed(2), t.days_held, t.result,
  ]);
  const csv = [headers.join(','), ...rows.map((r) => r.join(','))].join('\n');
  const blob = new Blob([csv], { type: 'text/csv' });
  const url = URL.createObjectURL(blob);
  const a = document.createElement('a');
  a.href = url;
  a.download = 'trade_log.csv';
  a.click();
  URL.revokeObjectURL(url);
}

const EXIT_REASON_LABELS: Record<string, { label: string; color: string }> = {
  profit_target: { label: 'Profit Target', color: 'text-emerald-400' },
  stop_loss: { label: 'Stop Loss', color: 'text-red-400' },
  dte_limit: { label: 'DTE Limit', color: 'text-amber-400' },
  expiration: { label: 'Expiration', color: 'text-gray-400' },
};

export function TradeLog({ trades }: Props) {
  const [sortKey, setSortKey] = useState<SortKey>('number');
  const [sortDir, setSortDir] = useState<SortDir>('asc');
  const [filter, setFilter] = useState<'all' | 'WIN' | 'LOSS'>('all');
  const [search, setSearch] = useState('');
  const [page, setPage] = useState(0);
  const [expandedRow, setExpandedRow] = useState<number | null>(null);

  // Filter
  const filtered = useMemo(() => {
    let result = trades;
    if (filter !== 'all') result = result.filter((t) => t.result === filter);
    if (search.trim()) {
      const q = search.toLowerCase();
      result = result.filter((t) =>
        t.strategy.toLowerCase().includes(q) ||
        t.strikes.toLowerCase().includes(q) ||
        t.entry_date.includes(q) ||
        t.exit_date.includes(q)
      );
    }
    return result;
  }, [trades, filter, search]);

  // Sort
  const sorted = useMemo(() => {
    const arr = [...filtered];
    arr.sort((a, b) => {
      const aVal = a[sortKey];
      const bVal = b[sortKey];
      if (typeof aVal === 'number' && typeof bVal === 'number') {
        return sortDir === 'asc' ? aVal - bVal : bVal - aVal;
      }
      const aStr = String(aVal);
      const bStr = String(bVal);
      return sortDir === 'asc' ? aStr.localeCompare(bStr) : bStr.localeCompare(aStr);
    });
    return arr;
  }, [filtered, sortKey, sortDir]);

  // Running P&L (computed on sorted list)
  const runningPnl = useMemo(() => {
    let cumulative = 0;
    return sorted.map((t) => {
      cumulative += t.pnl;
      return cumulative;
    });
  }, [sorted]);

  // Max absolute P&L for bar scaling
  const maxAbsPnl = useMemo(() => {
    const max = Math.max(...trades.map((t) => Math.abs(t.pnl)), 1);
    return max;
  }, [trades]);

  // Pagination
  const totalPages = Math.max(1, Math.ceil(sorted.length / PAGE_SIZE));
  const paginated = sorted.slice(page * PAGE_SIZE, (page + 1) * PAGE_SIZE);
  const paginatedRunning = runningPnl.slice(page * PAGE_SIZE, (page + 1) * PAGE_SIZE);

  // Summary stats
  const summary = useMemo(() => {
    const wins = filtered.filter((t) => t.result === 'WIN').length;
    const losses = filtered.length - wins;
    const totalPnl = filtered.reduce((s, t) => s + t.pnl, 0);
    const avgPnl = filtered.length > 0 ? totalPnl / filtered.length : 0;
    const avgDays = filtered.length > 0 ? filtered.reduce((s, t) => s + t.days_held, 0) / filtered.length : 0;
    return { wins, losses, totalPnl, avgPnl, avgDays, count: filtered.length };
  }, [filtered]);

  const handleSort = (key: SortKey) => {
    if (sortKey === key) {
      setSortDir((d) => (d === 'asc' ? 'desc' : 'asc'));
    } else {
      setSortKey(key);
      setSortDir('asc');
    }
    setPage(0);
  };

  const handleFilter = (f: 'all' | 'WIN' | 'LOSS') => {
    setFilter(f);
    setPage(0);
  };

  if (trades.length === 0) {
    return <p className="text-[hsl(var(--muted-foreground))] text-sm">No closed trades.</p>;
  }

  return (
    <div>
      {/* Toolbar: filter + search + export */}
      <div className="flex flex-wrap items-center gap-2 mb-3">
        {/* WIN/LOSS filter */}
        {(['all', 'WIN', 'LOSS'] as const).map((f) => (
          <button
            key={f}
            onClick={() => handleFilter(f)}
            className={`px-2.5 py-1 rounded text-xs font-medium transition-colors ${
              filter === f
                ? f === 'WIN' ? 'bg-emerald-500/15 text-emerald-400'
                : f === 'LOSS' ? 'bg-red-500/15 text-red-400'
                : 'bg-white/10 text-white'
                : 'bg-white/[0.03] text-gray-500 hover:bg-white/[0.06] hover:text-gray-400'
            }`}
          >
            {f === 'all' ? `All (${trades.length})` : f === 'WIN' ? `Wins (${trades.filter((t) => t.result === 'WIN').length})` : `Losses (${trades.filter((t) => t.result === 'LOSS').length})`}
          </button>
        ))}
        <span className="w-px h-4 bg-white/10" />
        {/* Search */}
        <input
          type="text"
          placeholder="Search strategy, strikes, date..."
          value={search}
          onChange={(e) => { setSearch(e.target.value); setPage(0); }}
          className="input-field !py-1 !text-xs"
          style={{ width: '220px' }}
        />
        {/* Spacer */}
        <div style={{ flex: 1 }} />
        {/* Export CSV */}
        <button
          onClick={() => downloadCSV(filtered)}
          className="flex items-center gap-1.5 px-2.5 py-1 rounded text-xs font-medium bg-white/[0.03] text-gray-400 hover:bg-white/[0.06] hover:text-white transition-colors"
        >
          <svg width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
            <path d="M21 15v4a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2v-4" />
            <polyline points="7 10 12 15 17 10" />
            <line x1="12" y1="15" x2="12" y2="3" />
          </svg>
          Export CSV
        </button>
      </div>

      {/* Table */}
      <div className="overflow-x-auto">
        <table className="w-full text-sm">
          <thead>
            <tr className="border-b border-[hsl(var(--border))]">
              {COLUMNS.map((col) => (
                <th
                  key={col.key}
                  onClick={() => handleSort(col.key)}
                  className={`th cursor-pointer select-none hover:text-white transition-colors text-${col.align}`}
                >
                  <span className="inline-flex items-center gap-1" style={{ justifyContent: col.align === 'center' ? 'center' : col.align === 'right' ? 'flex-end' : 'flex-start', width: '100%' }}>
                    {col.label}
                    {sortKey === col.key && (
                      <span style={{ fontSize: '10px', opacity: 0.7 }}>{sortDir === 'asc' ? '▲' : '▼'}</span>
                    )}
                  </span>
                </th>
              ))}
              <th className="th text-center">Cumulative</th>
            </tr>
          </thead>
          <tbody>
            {paginated.map((t, i) => {
              const pnlBarWidth = (Math.abs(t.pnl) / maxAbsPnl) * 100;
              const isExpanded = expandedRow === t.number;
              const reasonInfo = EXIT_REASON_LABELS[t.exit_reason] || EXIT_REASON_LABELS.expiration;
              return (
                <>
                <tr
                  key={t.number}
                  onClick={() => setExpandedRow(isExpanded ? null : t.number)}
                  className="border-b border-[hsl(var(--border))] hover:bg-white/[0.03] cursor-pointer"
                  style={{ backgroundColor: i % 2 === 1 ? 'rgba(255,255,255,0.015)' : undefined }}
                >
                  <td className="td text-center font-mono">
                    <span className="inline-flex items-center gap-1.5 justify-center">
                      <span style={{ fontSize: '9px', opacity: 0.4, transition: 'transform 0.15s', transform: isExpanded ? 'rotate(90deg)' : 'rotate(0deg)' }}>▶</span>
                      {t.number}
                    </span>
                  </td>
                  <td className="td text-center">{t.strategy}</td>
                  <td className="td text-center font-mono">{t.entry_date}</td>
                  <td className="td text-center font-mono">{t.exit_date}</td>
                  <td className="td text-center font-mono text-xs">{t.strikes}</td>
                  <td className="td text-center font-mono">{t.contracts ?? 1}</td>
                  <td className="td text-center font-mono">
                    <div>{formatCurrency(t.entry_premium)}</div>
                    <div className="text-[10px] text-gray-500">${perShare(t).toFixed(2)}/sh</div>
                  </td>
                  <td className="td text-center font-mono">{formatCurrency(t.exit_premium)}</td>
                  <td className="td text-center font-mono" style={{ position: 'relative' }}>
                    {/* P&L bar background */}
                    <div style={{
                      position: 'absolute',
                      top: '2px',
                      bottom: '2px',
                      left: 0,
                      right: 0,
                      width: `${Math.min(pnlBarWidth, 100)}%`,
                      margin: '0 auto',
                      backgroundColor: t.pnl >= 0 ? 'rgba(16,185,129,0.08)' : 'rgba(248,113,113,0.08)',
                      borderRadius: '2px',
                    }} />
                    <span className={`relative font-semibold ${t.pnl >= 0 ? 'text-[hsl(var(--accent))]' : 'text-[hsl(var(--danger))]'}`}>
                      {formatCurrency(t.pnl)}
                    </span>
                  </td>
                  <td className="td text-center font-mono">{t.days_held}</td>
                  <td className="td text-center">
                    <span className={`inline-flex items-center justify-center rounded-full text-xs font-semibold border ${
                      t.result === 'WIN'
                        ? 'border-[hsl(var(--accent))] text-[hsl(var(--accent))] bg-[hsl(var(--accent)/0.1)]'
                        : 'border-[hsl(var(--danger))] text-[hsl(var(--danger))] bg-[hsl(var(--danger)/0.1)]'
                    }`} style={{ width: '52px', height: '24px' }}>
                      {t.result}
                    </span>
                  </td>
                  <td className={`td text-center font-mono font-semibold ${paginatedRunning[i] >= 0 ? 'text-[hsl(var(--accent))]' : 'text-[hsl(var(--danger))]'}`}>
                    {formatCurrency(paginatedRunning[i])}
                  </td>
                </tr>
                {isExpanded && (
                  <tr key={`${t.number}-detail`} className="border-b border-[hsl(var(--border))]" style={{ backgroundColor: 'rgba(255,255,255,0.02)' }}>
                    <td colSpan={COLUMNS.length + 1} className="px-4 py-3">
                      <div className="grid grid-cols-3 gap-x-8 gap-y-2 text-xs">
                        {/* Exit Reason */}
                        <div>
                          <span className="text-gray-500">Exit Reason</span>
                          <div className={`font-semibold mt-0.5 ${reasonInfo.color}`}>{reasonInfo.label}</div>
                        </div>
                        {/* Position Sizing */}
                        <div>
                          <span className="text-gray-500">Contracts</span>
                          <div className="font-mono text-gray-300 mt-0.5">{t.contracts}</div>
                        </div>
                        <div>
                          <span className="text-gray-500">Notional</span>
                          <div className="font-mono text-gray-300 mt-0.5">{formatCurrency(t.notional_value)}</div>
                        </div>
                        {/* Underlying Prices */}
                        <div>
                          <span className="text-gray-500">Entry Price</span>
                          <div className="font-mono text-gray-300 mt-0.5">{t.entry_underlying_price > 0 ? `$${t.entry_underlying_price.toFixed(2)}` : '—'}</div>
                        </div>
                        <div>
                          <span className="text-gray-500">Exit Price</span>
                          <div className="font-mono text-gray-300 mt-0.5">{t.exit_underlying_price > 0 ? `$${t.exit_underlying_price.toFixed(2)}` : '—'}</div>
                        </div>
                        <div>
                          <span className="text-gray-500">Price Move</span>
                          {t.entry_underlying_price > 0 && t.exit_underlying_price > 0 ? (() => {
                            const move = ((t.exit_underlying_price - t.entry_underlying_price) / t.entry_underlying_price) * 100;
                            return <div className={`font-mono font-semibold mt-0.5 ${move >= 0 ? 'text-emerald-400' : 'text-red-400'}`}>{move >= 0 ? '+' : ''}{move.toFixed(2)}%</div>;
                          })() : <div className="text-gray-500 mt-0.5">—</div>}
                        </div>
                        {/* Greeks at Entry */}
                        <div>
                          <span className="text-gray-500">Entry Delta</span>
                          <div className="font-mono text-gray-300 mt-0.5">{t.entry_delta != null ? t.entry_delta.toFixed(3) : '—'}</div>
                        </div>
                        <div>
                          <span className="text-gray-500">Entry Theta</span>
                          <div className="font-mono text-gray-300 mt-0.5">{t.entry_theta != null ? t.entry_theta.toFixed(3) : '—'}</div>
                        </div>
                        <div>
                          <span className="text-gray-500">Entry Vega</span>
                          <div className="font-mono text-gray-300 mt-0.5">{t.entry_vega != null ? t.entry_vega.toFixed(3) : '—'}</div>
                        </div>
                      </div>
                    </td>
                  </tr>
                )}
                </>
              );
            })}
          </tbody>
          {/* Summary footer */}
          <tfoot>
            <tr className="border-t-2 border-[hsl(var(--border))]" style={{ backgroundColor: 'rgba(255,255,255,0.02)' }}>
              <td className="td font-mono font-semibold text-gray-300" colSpan={2}>
                {summary.count} trade{summary.count !== 1 ? 's' : ''}
              </td>
              <td className="td" colSpan={3}>
                <span className="text-xs text-gray-500">
                  <span className="text-emerald-400 font-semibold">{summary.wins}W</span>
                  {' / '}
                  <span className="text-red-400 font-semibold">{summary.losses}L</span>
                </span>
              </td>
              <td className="td" colSpan={3} />
              <td className={`td text-right font-mono font-bold ${summary.totalPnl >= 0 ? 'text-[hsl(var(--accent))]' : 'text-[hsl(var(--danger))]'}`}>
                {formatCurrency(summary.totalPnl)}
              </td>
              <td className="td text-right font-mono text-gray-400">
                ~{summary.avgDays.toFixed(0)}d
              </td>
              <td className="td text-right text-xs text-gray-500">
                avg {formatCurrency(summary.avgPnl)}
              </td>
              <td className="td" />
            </tr>
          </tfoot>
        </table>
      </div>

      {/* Pagination */}
      {totalPages > 1 && (
        <div className="flex items-center justify-between mt-3">
          <span className="text-xs text-gray-500">
            Showing {page * PAGE_SIZE + 1}–{Math.min((page + 1) * PAGE_SIZE, sorted.length)} of {sorted.length}
          </span>
          <div className="flex items-center gap-1">
            <button
              onClick={() => setPage(0)}
              disabled={page === 0}
              className="px-2 py-1 rounded text-xs font-medium bg-white/[0.03] text-gray-400 hover:bg-white/[0.06] hover:text-white disabled:opacity-30 disabled:cursor-default transition-colors"
            >
              ««
            </button>
            <button
              onClick={() => setPage((p) => Math.max(0, p - 1))}
              disabled={page === 0}
              className="px-2 py-1 rounded text-xs font-medium bg-white/[0.03] text-gray-400 hover:bg-white/[0.06] hover:text-white disabled:opacity-30 disabled:cursor-default transition-colors"
            >
              ‹
            </button>
            <span className="text-xs text-gray-400 px-2">
              {page + 1} / {totalPages}
            </span>
            <button
              onClick={() => setPage((p) => Math.min(totalPages - 1, p + 1))}
              disabled={page >= totalPages - 1}
              className="px-2 py-1 rounded text-xs font-medium bg-white/[0.03] text-gray-400 hover:bg-white/[0.06] hover:text-white disabled:opacity-30 disabled:cursor-default transition-colors"
            >
              ›
            </button>
            <button
              onClick={() => setPage(totalPages - 1)}
              disabled={page >= totalPages - 1}
              className="px-2 py-1 rounded text-xs font-medium bg-white/[0.03] text-gray-400 hover:bg-white/[0.06] hover:text-white disabled:opacity-30 disabled:cursor-default transition-colors"
            >
              »»
            </button>
          </div>
        </div>
      )}
    </div>
  );
}
