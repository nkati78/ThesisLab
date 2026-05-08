import { useState, useRef, useCallback, useEffect } from 'react';
import { StrategyPanel } from './components/StrategyPanel';
import { AdvancedSettings } from './components/AdvancedSettings';
import { EquityChart } from './components/EquityChart';
import { PriceChart } from './components/PriceChart';
import { TradeLog } from './components/TradeLog';
import { runBacktest } from './lib/api';
import { formatCurrency, formatPct } from './lib/utils';
import { useAuth } from './lib/AuthContext';
import { useNavigate, useLocation } from 'react-router-dom';
import { saveBacktest } from './lib/storage';
import type {
  StrategyConfig, AdvancedFilters, SyntheticDataConfig, BacktestResponse,
} from './types/api';

const SINGLE_LEG = [
  { key: 'long_call', name: 'Long Call', tag: 'Bullish' },
  { key: 'long_put', name: 'Long Put', tag: 'Bearish' },
  { key: 'short_call', name: 'Short Call', tag: 'Bearish' },
  { key: 'short_put', name: 'Short Put', tag: 'Bullish' },
];

const STRATEGY_GROUPS = [
  {
    label: 'Vertical Spreads',
    items: [
      { key: 'debit_call_spread', name: 'Call Debit Spread', tag: 'Bullish' },
      { key: 'debit_put_spread', name: 'Put Debit Spread', tag: 'Bearish' },
      { key: 'short_put_spread', name: 'Put Credit Spread', tag: 'Bullish' },
      { key: 'short_call_spread', name: 'Call Credit Spread', tag: 'Bearish' },
    ],
  },
  {
    label: 'Calendar Spreads',
    items: [
      { key: 'calendar_call_spread', name: 'Calendar Call Spread', tag: 'Neutral' },
      { key: 'calendar_put_spread', name: 'Calendar Put Spread', tag: 'Neutral' },
    ],
  },
  {
    label: 'Iron Condor',
    items: [
      { key: 'iron_condor', name: 'Iron Condor', tag: 'Neutral' },
    ],
  },
  {
    label: 'Straddles',
    items: [
      { key: 'straddle', name: 'Long Straddle', tag: 'Directional' },
      { key: 'short_straddle', name: 'Short Straddle', tag: 'Neutral' },
    ],
  },
  {
    label: 'Strangles',
    items: [
      { key: 'long_strangle', name: 'Long Strangle', tag: 'Directional' },
      { key: 'short_strangle', name: 'Short Strangle', tag: 'Neutral' },
    ],
  },
  {
    label: 'Butterflies',
    items: [
      { key: 'iron_butterfly', name: 'Iron Butterfly', tag: 'Neutral' },
      { key: 'long_call_butterfly', name: 'Long Call Butterfly', tag: 'Neutral' },
      { key: 'long_put_butterfly', name: 'Long Put Butterfly', tag: 'Neutral' },
    ],
  },
];

/* Sensible defaults per strategy type — spread/wing widths scale with underlying price */
function defaultWidth(price: number): number {
  if (price >= 1000) return 50;
  if (price >= 300) return 5;
  return 3;
}

function getStrategyDefaults(key: string, price: number): Partial<StrategyConfig> {
  const w = defaultWidth(price);
  const base: Record<string, Partial<StrategyConfig>> = {
    long_call: { min_dte: 30, max_dte: 60, short_delta: 0.30, close_at_profit_pct: 0.5, close_at_loss_pct: 0.5, close_at_dte: 7 },
    long_put: { min_dte: 30, max_dte: 60, short_delta: 0.30, close_at_profit_pct: 0.5, close_at_loss_pct: 0.5, close_at_dte: 7 },
    short_call: { min_dte: 25, max_dte: 45, short_delta: 0.25, close_at_profit_pct: 0.5, close_at_loss_pct: 2.0, close_at_dte: 7 },
    short_put: { min_dte: 25, max_dte: 45, short_delta: 0.25, close_at_profit_pct: 0.5, close_at_loss_pct: 2.0, close_at_dte: 7 },
    short_put_spread: { min_dte: 25, max_dte: 45, short_delta: 0.25, spread_width: w, max_positions: 1, close_at_profit_pct: 0.5, close_at_loss_pct: 2.0, close_at_dte: 7 },
    short_call_spread: { min_dte: 25, max_dte: 45, short_delta: 0.25, spread_width: w, max_positions: 1, close_at_profit_pct: 0.5, close_at_loss_pct: 2.0, close_at_dte: 7 },
    debit_call_spread: { min_dte: 25, max_dte: 45, short_delta: 0.25, spread_width: w, max_positions: 1, close_at_profit_pct: 0.5, close_at_loss_pct: 0.5, close_at_dte: 7 },
    debit_put_spread: { min_dte: 25, max_dte: 45, short_delta: 0.25, spread_width: w, max_positions: 1, close_at_profit_pct: 0.5, close_at_loss_pct: 0.5, close_at_dte: 7 },
    iron_condor: { min_dte: 30, max_dte: 45, short_delta: 0.15, wing_width: w, close_at_profit_pct: 0.5, close_at_loss_pct: 2.0, close_at_dte: 7 },
    straddle: { min_dte: 20, max_dte: 45, close_at_profit_pct: 0.5, close_at_loss_pct: 0.5, close_at_dte: 7 },
    short_straddle: { min_dte: 20, max_dte: 45, close_at_profit_pct: 0.5, close_at_loss_pct: 2.0, close_at_dte: 7 },
    long_strangle: { min_dte: 25, max_dte: 45, close_at_profit_pct: 0.5, close_at_loss_pct: 0.5, close_at_dte: 7 },
    short_strangle: { min_dte: 25, max_dte: 45, short_delta: 0.15, close_at_profit_pct: 0.5, close_at_loss_pct: 2.0, close_at_dte: 7 },
    iron_butterfly: { min_dte: 30, max_dte: 45, short_delta: 0.50, wing_width: w, close_at_profit_pct: 0.5, close_at_loss_pct: 2.0, close_at_dte: 7 },
    long_call_butterfly: { min_dte: 30, max_dte: 60, short_delta: 0.50, wing_width: w, close_at_profit_pct: 0.5, close_at_loss_pct: 0.5, close_at_dte: 7 },
    long_put_butterfly: { min_dte: 30, max_dte: 60, short_delta: 0.50, wing_width: w, close_at_profit_pct: 0.5, close_at_loss_pct: 0.5, close_at_dte: 7 },
    calendar_call_spread: { min_dte: 25, max_dte: 45, short_delta: 0.30, close_at_profit_pct: 0.5, close_at_loss_pct: 0.5, close_at_dte: 7 },
    calendar_put_spread: { min_dte: 25, max_dte: 45, short_delta: 0.30, close_at_profit_pct: 0.5, close_at_loss_pct: 0.5, close_at_dte: 7 },
  };
  return base[key] ?? {};
}

const CREDIT_STRATEGIES = new Set([
  'short_put', 'short_call', 'short_put_spread', 'short_call_spread',
  'iron_condor', 'iron_butterfly', 'short_straddle', 'short_strangle',
  'calendar_call_spread', 'calendar_put_spread',
]);

interface TradeEstimate {
  creditOrDebit: number;   // positive = credit, negative = debit
  isCredit: boolean;
  marginRequired: number;
  maxGain: number;
  maxLoss: number;
}

function estimateTradeStats(
  type: string, price: number, delta: number,
  spreadW: number, wingW: number,
  minDte: number, maxDte: number, iv: number,
): TradeEstimate | null {
  if (!type) return null;
  const isCredit = CREDIT_STRATEGIES.has(type);
  const T = ((minDte + maxDte) / 2) / 365;
  const sqrtT = Math.sqrt(T);
  const df = delta / 0.50;
  const legPrem = price * 0.4 * iv * sqrtT * df;

  let cd: number, margin: number, gain: number, loss: number;

  if (type === 'short_put_spread' || type === 'short_call_spread') {
    const longDf = Math.max(0.05, delta - spreadW / price) / 0.50;
    const longPrem = price * 0.4 * iv * sqrtT * longDf;
    cd = (legPrem - longPrem) * 100;
    margin = spreadW * 100;
    gain = cd; loss = margin - cd;
  } else if (type === 'debit_call_spread' || type === 'debit_put_spread') {
    const shortDf = Math.max(0.05, delta - spreadW / price) / 0.50;
    const shortPrem = price * 0.4 * iv * sqrtT * shortDf;
    cd = -(legPrem - shortPrem) * 100;
    margin = Math.abs(cd);
    gain = spreadW * 100 - margin; loss = margin;
  } else if (type === 'short_put' || type === 'short_call') {
    cd = legPrem * 100;
    margin = price * 20; gain = cd; loss = Infinity;
  } else if (type === 'long_call' || type === 'long_put') {
    cd = -(legPrem * 100);
    margin = Math.abs(cd); gain = Infinity; loss = margin;
  } else if (type === 'iron_condor') {
    const wingDf = Math.max(0.05, delta - wingW / price) / 0.50;
    const wingPrem = price * 0.4 * iv * sqrtT * wingDf;
    cd = (2 * legPrem - 2 * wingPrem) * 100;
    margin = wingW * 100; gain = cd; loss = margin - cd;
  } else if (type === 'iron_butterfly') {
    const atmPrem = price * 0.4 * iv * sqrtT;
    const wingDf = Math.max(0.05, 0.50 - wingW / price) / 0.50;
    const wingPrem = price * 0.4 * iv * sqrtT * wingDf;
    cd = (2 * atmPrem - 2 * wingPrem) * 100;
    margin = wingW * 100; gain = cd; loss = margin - cd;
  } else if (type === 'short_straddle') {
    const atmPrem = price * 0.4 * iv * sqrtT;
    cd = 2 * atmPrem * 100;
    margin = price * 20; gain = cd; loss = Infinity;
  } else if (type === 'straddle') {
    const atmPrem = price * 0.4 * iv * sqrtT;
    cd = -(2 * atmPrem * 100);
    margin = Math.abs(cd); gain = Infinity; loss = margin;
  } else if (type === 'short_strangle') {
    cd = 2 * legPrem * 100;
    margin = price * 20; gain = cd; loss = Infinity;
  } else if (type === 'long_strangle') {
    cd = -(2 * legPrem * 100);
    margin = Math.abs(cd); gain = Infinity; loss = margin;
  } else if (type === 'long_call_butterfly' || type === 'long_put_butterfly') {
    const atmPrem = price * 0.4 * iv * sqrtT;
    const wingDf = Math.max(0.05, 0.50 - wingW / price) / 0.50;
    const wingPrem = price * 0.4 * iv * sqrtT * wingDf;
    cd = -(2 * wingPrem - 2 * (atmPrem * 0.5)) * 100;
    margin = Math.abs(cd); gain = wingW * 100 - margin; loss = margin;
  } else if (type === 'calendar_call_spread' || type === 'calendar_put_spread') {
    const frontPrem = legPrem * 0.7;
    const backPrem = legPrem * 1.3;
    cd = -(backPrem - frontPrem) * 100;
    margin = Math.abs(cd); gain = margin * 1.5; loss = margin;
  } else {
    return null;
  }
  return { creditOrDebit: cd, isCredit, marginRequired: Math.max(0, margin), maxGain: Math.max(0, gain), maxLoss: Math.max(0, loss) };
}

const ALL_STRATEGIES = [...SINGLE_LEG, ...STRATEGY_GROUPS.flatMap((g) => g.items)];
const STRATEGY_NAME_MAP: Record<string, string> = Object.fromEntries(ALL_STRATEGIES.map((s) => [s.key, s.name]));

const TAG_COLORS: Record<string, string> = {
  Bullish: 'text-emerald-400',
  Bearish: 'text-red-400',
  Neutral: 'text-amber-400',
  Directional: 'text-blue-400',
};

/* ── Strategy metadata for hover preview ── */
interface StrategyMeta {
  desc: string;
  legs: { action: 'Buy' | 'Sell'; label: string }[];
  type: 'credit' | 'debit';
  risk: 'defined' | 'undefined';
  points: [number, number][]; // [x, y] pairs — y=50 is breakeven, y<50 profit, y>50 loss
  strikes: { x: number; label: string }[];
}

const STRATEGY_META: Record<string, StrategyMeta> = {
  long_call:           { desc: 'Buy a call to profit from upside moves. Loss limited to premium paid.', legs: [{ action: 'Buy', label: 'call at strike A' }], type: 'debit', risk: 'defined', points: [[5,62],[45,62],[80,18]], strikes: [{x:45,label:'A'}] },
  long_put:            { desc: 'Buy a put to profit from downside moves. Loss limited to premium paid.', legs: [{ action: 'Buy', label: 'put at strike A' }], type: 'debit', risk: 'defined', points: [[5,18],[45,62],[80,62]], strikes: [{x:45,label:'A'}] },
  short_call:          { desc: 'Sell a call to collect premium. Profits if price stays below strike.', legs: [{ action: 'Sell', label: 'call at strike A' }], type: 'credit', risk: 'undefined', points: [[5,38],[45,38],[80,82]], strikes: [{x:45,label:'A'}] },
  short_put:           { desc: 'Sell a put to collect premium. Profits if price stays above strike.', legs: [{ action: 'Sell', label: 'put at strike A' }], type: 'credit', risk: 'undefined', points: [[5,82],[45,38],[80,38]], strikes: [{x:45,label:'A'}] },
  short_put_spread:    { desc: 'Sell a higher-strike put, buy a lower-strike put. Bullish credit strategy with defined risk.', legs: [{ action: 'Buy', label: 'put at strike A' }, { action: 'Sell', label: 'put at strike B' }], type: 'credit', risk: 'defined', points: [[5,62],[28,62],[55,32],[80,32]], strikes: [{x:28,label:'A'},{x:55,label:'B'}] },
  short_call_spread:   { desc: 'Sell a lower-strike call, buy a higher-strike call. Bearish credit strategy with defined risk.', legs: [{ action: 'Sell', label: 'call at strike A' }, { action: 'Buy', label: 'call at strike B' }], type: 'credit', risk: 'defined', points: [[5,32],[35,32],[62,62],[80,62]], strikes: [{x:35,label:'A'},{x:62,label:'B'}] },
  debit_call_spread:   { desc: 'Buy a lower-strike call, sell a higher-strike call. Bullish with capped profit and loss.', legs: [{ action: 'Buy', label: 'call at strike A' }, { action: 'Sell', label: 'call at strike B' }], type: 'debit', risk: 'defined', points: [[5,62],[28,62],[55,32],[80,32]], strikes: [{x:28,label:'A'},{x:55,label:'B'}] },
  debit_put_spread:    { desc: 'Buy a higher-strike put, sell a lower-strike put. Bearish with capped profit and loss.', legs: [{ action: 'Buy', label: 'put at strike B' }, { action: 'Sell', label: 'put at strike A' }], type: 'debit', risk: 'defined', points: [[5,32],[35,32],[62,62],[80,62]], strikes: [{x:35,label:'A'},{x:62,label:'B'}] },
  iron_condor:         { desc: 'Sell an OTM put spread and OTM call spread. Profits from low volatility in a range.', legs: [{ action: 'Buy', label: 'put at A' }, { action: 'Sell', label: 'put at B' }, { action: 'Sell', label: 'call at C' }, { action: 'Buy', label: 'call at D' }], type: 'credit', risk: 'defined', points: [[5,62],[18,62],[30,32],[58,32],[70,62],[80,62]], strikes: [{x:18,label:'A'},{x:30,label:'B'},{x:58,label:'C'},{x:70,label:'D'}] },
  straddle:            { desc: 'Buy ATM call + put at the same strike. Profits from large moves in either direction.', legs: [{ action: 'Buy', label: 'call at strike A' }, { action: 'Buy', label: 'put at strike A' }], type: 'debit', risk: 'defined', points: [[5,15],[42,62],[80,15]], strikes: [{x:42,label:'A'}] },
  short_straddle:      { desc: 'Sell ATM call + put at the same strike. Profits from low volatility near the strike.', legs: [{ action: 'Sell', label: 'call at strike A' }, { action: 'Sell', label: 'put at strike A' }], type: 'credit', risk: 'undefined', points: [[5,85],[42,28],[80,85]], strikes: [{x:42,label:'A'}] },
  long_strangle:       { desc: 'Buy OTM call + OTM put at different strikes. Cheaper than a straddle, needs bigger moves.', legs: [{ action: 'Buy', label: 'put at strike A' }, { action: 'Buy', label: 'call at strike B' }], type: 'debit', risk: 'defined', points: [[5,15],[30,62],[55,62],[80,15]], strikes: [{x:30,label:'A'},{x:55,label:'B'}] },
  short_strangle:      { desc: 'Sell OTM call + OTM put. Wider profit zone than a straddle but unlimited risk.', legs: [{ action: 'Sell', label: 'put at strike A' }, { action: 'Sell', label: 'call at strike B' }], type: 'credit', risk: 'undefined', points: [[5,85],[30,34],[55,34],[80,85]], strikes: [{x:30,label:'A'},{x:55,label:'B'}] },
  iron_butterfly:      { desc: 'Sell ATM straddle + buy OTM wings. Tighter profit zone than iron condor, higher credit.', legs: [{ action: 'Buy', label: 'put at A' }, { action: 'Sell', label: 'put+call at B' }, { action: 'Buy', label: 'call at C' }], type: 'credit', risk: 'defined', points: [[5,62],[20,62],[42,25],[64,62],[80,62]], strikes: [{x:20,label:'A'},{x:42,label:'B'},{x:64,label:'C'}] },
  long_call_butterfly: { desc: 'Buy 1 lower call, sell 2 middle calls, buy 1 upper call. Max profit at middle strike.', legs: [{ action: 'Buy', label: 'call at A' }, { action: 'Sell', label: '2 calls at B' }, { action: 'Buy', label: 'call at C' }], type: 'debit', risk: 'defined', points: [[5,62],[25,62],[42,20],[60,62],[80,62]], strikes: [{x:25,label:'A'},{x:42,label:'B'},{x:60,label:'C'}] },
  long_put_butterfly:  { desc: 'Buy 1 upper put, sell 2 middle puts, buy 1 lower put. Max profit at middle strike.', legs: [{ action: 'Buy', label: 'put at A' }, { action: 'Sell', label: '2 puts at B' }, { action: 'Buy', label: 'put at C' }], type: 'debit', risk: 'defined', points: [[5,62],[25,62],[42,20],[60,62],[80,62]], strikes: [{x:25,label:'A'},{x:42,label:'B'},{x:60,label:'C'}] },
  calendar_call_spread:{ desc: 'Sell near-term call, buy longer-term call at same strike. Profits from time decay.', legs: [{ action: 'Sell', label: 'front call at A' }, { action: 'Buy', label: 'back call at A' }], type: 'debit', risk: 'defined', points: [[5,62],[25,62],[42,22],[60,62],[80,62]], strikes: [{x:42,label:'A'}] },
  calendar_put_spread: { desc: 'Sell near-term put, buy longer-term put at same strike. Profits from time decay.', legs: [{ action: 'Sell', label: 'front put at A' }, { action: 'Buy', label: 'back put at A' }], type: 'debit', risk: 'defined', points: [[5,62],[25,62],[42,22],[60,62],[80,62]], strikes: [{x:42,label:'A'}] },
  covered_call:        { desc: 'Own shares + sell OTM call. Generates income, caps upside.', legs: [{ action: 'Buy', label: '100 shares' }, { action: 'Sell', label: 'call at strike A' }], type: 'credit', risk: 'defined', points: [[5,80],[50,32],[80,32]], strikes: [{x:50,label:'A'}] },
  protective_put:      { desc: 'Own shares + buy OTM put. Insures downside, keeps upside.', legs: [{ action: 'Buy', label: '100 shares' }, { action: 'Buy', label: 'put at strike A' }], type: 'debit', risk: 'defined', points: [[5,55],[30,55],[80,15]], strikes: [{x:30,label:'A'}] },
};

const BRK = 50; // breakeven y-coordinate

function PayoffDiagram({ points, strikes }: { points: [number, number][]; strikes: { x: number; label: string }[] }) {
  const pathD = points.map((p, i) => `${i === 0 ? 'M' : 'L'} ${p[0]} ${p[1]}`).join(' ');
  const firstX = points[0][0];
  const lastX = points[points.length - 1][0];
  // closed shape from payoff line back along the breakeven line
  const fillD = `${pathD} L ${lastX} ${BRK} L ${firstX} ${BRK} Z`;

  return (
    <svg viewBox="-12 -4 124 100" width="423" height="240" style={{ overflow: 'visible', flexShrink: 0 }}>
      <defs>
        <clipPath id="payoff-profit"><rect x="0" y="0" width="100" height={BRK} /></clipPath>
        <clipPath id="payoff-loss"><rect x="0" y={BRK} width="100" height={100 - BRK} /></clipPath>
      </defs>

      {/* Profit fill (green, above breakeven) */}
      <path d={fillD} fill="rgba(16,185,129,0.15)" clipPath="url(#payoff-profit)" />
      {/* Loss fill (red, below breakeven) */}
      <path d={fillD} fill="rgba(248,113,113,0.15)" clipPath="url(#payoff-loss)" />

      {/* Breakeven line */}
      <line x1={firstX} y1={BRK} x2={lastX} y2={BRK} stroke="rgba(255,255,255,0.35)" strokeWidth="0.35" strokeDasharray="3 2" />

      {/* Payoff line — green in profit zone */}
      <path d={pathD} fill="none" stroke="#10b981" strokeWidth="1.4" strokeLinecap="round" strokeLinejoin="round" clipPath="url(#payoff-profit)" />
      {/* Payoff line — red in loss zone */}
      <path d={pathD} fill="none" stroke="#f87171" strokeWidth="1.4" strokeLinecap="round" strokeLinejoin="round" clipPath="url(#payoff-loss)" />

      {/* Axis labels — positioned outside the chart area */}
      <text x={-5} y={20} textAnchor="end" fill="#10b981" fontSize="5.5" fontWeight="700">Profit</text>
      <text x={-5} y={BRK + 10} textAnchor="end" fill="#f87171" fontSize="5.5" fontWeight="700">Loss</text>

      {/* Strike markers — labels well below the chart */}
      {strikes.map((s) => (
        <g key={s.label}>
          <line x1={s.x} y1={8} x2={s.x} y2={BRK + 18} stroke="rgba(255,255,255,0.3)" strokeWidth="0.35" strokeDasharray="2 2" />
          <text x={s.x} y={BRK + 26} textAnchor="middle" fill="#ffffff" fontSize="5.2" fontWeight="600">{s.label}</text>
        </g>
      ))}

      {/* Stock Price label below chart area */}
      <text x={(firstX + lastX) / 2} y={BRK + 36} textAnchor="middle" fill="rgba(255,255,255,0.5)" fontSize="4.3">Stock Price →</text>
    </svg>
  );
}

function StrategyCard({ name, tag, selected, onClick, onHover }: {
  name: string; tag: string; selected: boolean; onClick: () => void; onHover: () => void;
}) {
  return (
    <button
      onClick={onClick}
      onMouseEnter={onHover}
      style={{ minWidth: '11rem', minHeight: '4.25rem' }}
      className={`relative flex flex-col items-center justify-center gap-0.5 px-7 py-4 rounded-md border transition-all text-center ${
        selected
          ? 'border-[hsl(var(--accent))] bg-[hsl(var(--accent)/0.08)] shadow-lg shadow-[hsl(var(--accent)/0.15)]'
          : 'border-white/[0.08] bg-white/[0.02] hover:border-white/[0.15] hover:bg-white/[0.04]'
      }`}
    >
      {selected && (
        <span className="absolute top-2 right-2 w-2 h-2 rounded-full bg-[hsl(var(--accent))]" />
      )}
      <span className={`text-sm font-semibold ${selected ? 'text-[hsl(var(--accent))]' : 'text-white'}`}>
        {name}
      </span>
      <span className={`text-xs font-medium ${TAG_COLORS[tag] ?? 'text-gray-500'}`}>
        {tag.toLowerCase()}
      </span>
    </button>
  );
}

function App() {
  const { user } = useAuth();
  const nav = useNavigate();
  const location = useLocation();
  const [strategy, setStrategy] = useState<StrategyConfig>({
    type: '', min_dte: 25, max_dte: 45, short_delta: 0.25,
    spread_width: 5, max_positions: 1, contracts_per_trade: 1, close_at_profit_pct: 0.5,
    close_at_loss_pct: 2.0, close_at_dte: 7,
    close_at_profit_enabled: false, close_at_loss_enabled: false,
    close_at_dte_enabled: false, close_on_short_breach: false,
    entry_dow: 'any',
    put_delta: -0.2, wing_width: 5,
  });
  const [filters, setFilters] = useState<AdvancedFilters>({
    time_of_day: { enabled: false, entry_start: '09:30', entry_end: '16:00', exit_start: '09:30', exit_end: '16:00' },
    rsi: { enabled: false, rsi_min: 20, rsi_max: 80, rsi_zone: 'any' },
    bollinger: { enabled: false, position: 'any', use_pct_b: false, pct_b_min: 0, pct_b_max: 0.2 },
    moving_average: { enabled: false, sma_20: 'ignore', sma_50: 'ignore', sma_200: 'ignore', ema_9: 'ignore', ema_21: 'ignore', sma_cross: 'ignore' },
    vwap: { enabled: false, direction: 'above' },
  });

  const [activeSection, setActiveSection] = useState<'setup' | 'results'>('setup');
  const [chartTab, setChartTab] = useState<'equity' | 'price'>('equity');
  const [showSaveModal, setShowSaveModal] = useState(false);
  const [saveName, setSaveName] = useState('');
  const [saveMsg, setSaveMsg] = useState('');
  const [hoveredStrategy, setHoveredStrategy] = useState<string | null>(null);

  const [syntheticConfig] = useState<SyntheticDataConfig>({
    start_price: 450, daily_drift: 0.0003, base_iv: 0.25, seed: 42,
  });
  const [ticker, setTicker] = useState('AAPL');
  const [startDate, setStartDate] = useState('2023-01-03');
  const [endDate, setEndDate] = useState('2024-01-03');
  const [startingCash, setStartingCash] = useState(100000);
  const [commission, setCommission] = useState(0);
  const [dataSource, setDataSource] = useState<'synthetic' | 'thetadata'>('synthetic');
  const [result, setResult] = useState<BacktestResponse | null>(null);
  const [isLoading, setIsLoading] = useState(false);
  const [loadingElapsed, setLoadingElapsed] = useState(0);
  const [error, setError] = useState<string | null>(null);
  const [hasSelectedStrategy, setHasSelectedStrategy] = useState(false);
  const [isStale, setIsStale] = useState(false);
  const progressRef = useRef<ReturnType<typeof setInterval> | null>(null);
  const abortRef = useRef<AbortController | null>(null);

  const markStale = useCallback(() => { if (result) setIsStale(true); }, [result]);

  // Hydrate from a saved backtest passed via navigation state
  useEffect(() => {
    const state = location.state as { loadBacktest?: import('./lib/storage').SavedBacktest } | null;
    if (state?.loadBacktest) {
      const bt = state.loadBacktest;
      setTicker(bt.ticker);
      setStartDate(bt.startDate);
      setEndDate(bt.endDate);
      setStartingCash(bt.startingCash);
      setCommission(bt.commission);
      setStrategy(bt.strategy);
      setFilters(bt.filters);
      setResult(bt.result);
      setHasSelectedStrategy(!!bt.strategy.type);
      setActiveSection('results');
      setIsStale(false);
      // Clear nav state so a refresh doesn't re-hydrate
      nav('/', { replace: true, state: null });
    }
  // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  const handleStrategyChange = (key: string) => {
    if (strategy.type === key) {
      setStrategy({ ...strategy, type: '' });
      setHasSelectedStrategy(false);
    } else {
      const defaults = getStrategyDefaults(key, syntheticConfig.start_price);
      setStrategy({ ...strategy, type: key, ...defaults });
      setHasSelectedStrategy(true);
    }
    markStale();
  };

  const handleSetStrategy = (s: StrategyConfig) => { setStrategy(s); markStale(); };
  const handleSetFilters = (f: AdvancedFilters) => { setFilters(f); markStale(); };
  const handleSetTicker = (v: string) => { setTicker(v); markStale(); };
  const handleSetStartDate = (v: string) => { setStartDate(v); markStale(); };
  const handleSetEndDate = (v: string) => { setEndDate(v); markStale(); };
  const handleSetStartingCash = (v: number) => { setStartingCash(v); markStale(); };
  const handleSetCommission = (v: number) => { setCommission(v); markStale(); };

  /* ── Trade estimate ── */
  const tradeEstimate = estimateTradeStats(
    strategy.type, syntheticConfig.start_price, strategy.short_delta,
    strategy.spread_width, strategy.wing_width,
    strategy.min_dte, strategy.max_dte, syntheticConfig.base_iv,
  );

  /* ── Summary chip helpers ── */
  type Chip = { label: string; value: string };

  const fmtShortDate = (iso: string) => {
    const [y, m, d] = iso.split('-');
    return `${parseInt(m)}/${parseInt(d)}/${y.slice(2)}`;
  };

  const strategySummary = (): Chip[] => {
    const chips: Chip[] = [];
    chips.push({ label: 'Strategy', value: STRATEGY_NAME_MAP[strategy.type] ?? strategy.type });
    chips.push({ label: 'Range', value: `${fmtShortDate(startDate)} → ${fmtShortDate(endDate)}` });
    chips.push({ label: 'Expiry', value: `${strategy.min_dte}–${strategy.max_dte} days` });
    if (strategy.type !== 'straddle' && strategy.type !== 'short_straddle' && strategy.type !== 'protective_put') {
      chips.push({ label: 'Delta', value: strategy.short_delta.toFixed(2) });
    }
    if (strategy.type === 'protective_put') {
      chips.push({ label: 'Put Delta', value: strategy.put_delta.toFixed(2) });
    }
    const exitChips: string[] = [];
    if (strategy.close_at_profit_enabled) {
      exitChips.push(`TP ${(strategy.close_at_profit_pct * 100).toFixed(0)}%`);
    }
    if (strategy.close_at_loss_enabled) {
      const isCred = CREDIT_STRATEGIES.has(strategy.type);
      exitChips.push(`SL ${isCred ? `${strategy.close_at_loss_pct.toFixed(1)}x` : `${(strategy.close_at_loss_pct * 100).toFixed(0)}%`}`);
    }
    if (strategy.close_at_dte_enabled) {
      exitChips.push(`Close ${strategy.close_at_dte}d`);
    }
    if (strategy.close_on_short_breach) {
      exitChips.push('Short Breach');
    }
    chips.push({ label: 'Exit', value: exitChips.length > 0 ? exitChips.join(' · ') : 'Hold until expiry' });
    return chips;
  };

  const filterSummary = (): Chip[] => {
    const chips: Chip[] = [];
    if (filters.time_of_day.enabled) chips.push({ label: 'Hours', value: `${filters.time_of_day.entry_start}–${filters.time_of_day.entry_end}` });
    if (filters.rsi.enabled) chips.push({ label: 'RSI', value: `${filters.rsi.rsi_min}–${filters.rsi.rsi_max}` });
    if (filters.bollinger.enabled) chips.push({ label: 'Bollinger', value: filters.bollinger.position.replace(/_/g, ' ') });
    if (filters.moving_average.enabled) {
      const active = [
        filters.moving_average.sma_20 !== 'ignore' && `SMA20 ${filters.moving_average.sma_20}`,
        filters.moving_average.sma_50 !== 'ignore' && `SMA50 ${filters.moving_average.sma_50}`,
        filters.moving_average.sma_200 !== 'ignore' && `SMA200 ${filters.moving_average.sma_200}`,
      ].filter(Boolean);
      chips.push({ label: 'Moving Avg', value: active.length ? active.join(', ') : 'Enabled' });
    }
    if (filters.vwap.enabled) chips.push({ label: 'VWAP', value: `Price ${filters.vwap.direction}` });
    return chips;
  };

  const fmtEst = (v: number) => v === Infinity ? 'Unlimited' : formatCurrency(v);

  const handleRun = async () => {
    // Validate required fields
    if (!ticker.trim()) { setError('Symbol is required'); return; }
    if (!startDate) { setError('Start Date is required'); return; }
    if (!endDate) { setError('End Date is required'); return; }

    // Switch to loading — show progress bar on setup view
    setActiveSection('setup');
    setIsLoading(true);
    setLoadingElapsed(0);
    setError(null);
    setResult(null);
    setIsStale(false);

    // Track elapsed seconds — bar fill is an indeterminate CSS animation.
    const startTime = Date.now();
    progressRef.current = setInterval(() => {
      setLoadingElapsed((Date.now() - startTime) / 1000);
    }, 250);

    abortRef.current = new AbortController();

    try {
      const res = await runBacktest({
        ticker,
        start_date: startDate,
        end_date: endDate,
        starting_cash: startingCash,
        commission,
        strategy,
        advanced_filters: filters,
        data_source: dataSource,
        synthetic_config: syntheticConfig,
      }, abortRef.current.signal);
      if (progressRef.current) clearInterval(progressRef.current);
      setResult(res);
      setActiveSection('results');
      setChartTab('equity');
    } catch (err) {
      // User-cancelled abort — silently return to setup, no error banner
      if (err instanceof DOMException && err.name === 'AbortError') {
        // state already preserved
      } else {
        setError(err instanceof Error ? err.message : 'Backtest failed');
      }
    } finally {
      if (progressRef.current) clearInterval(progressRef.current);
      abortRef.current = null;
      setIsLoading(false);
    }
  };

  const handleStop = () => {
    abortRef.current?.abort();
  };

  /* ── Step bar helpers ── */
  const hasFiltersActive = filters.time_of_day.enabled || filters.rsi.enabled || filters.bollinger.enabled || filters.moving_average.enabled || filters.vwap.enabled;
  const hasResults = !!result && !isLoading;

  // Refs for scroll-to-section
  const sectionRefs = {
    1: useRef<HTMLDivElement>(null),
    2: useRef<HTMLDivElement>(null),
    3: useRef<HTMLDivElement>(null),
    4: useRef<HTMLDivElement>(null),
  };

  const scrollToSection = (num: number) => {
    if (activeSection === 'results') setActiveSection('setup');
    const ref = sectionRefs[num as keyof typeof sectionRefs];
    if (ref?.current) {
      setTimeout(() => ref.current?.scrollIntoView({ behavior: 'smooth', block: 'start' }), 50);
    }
  };

  const steps: { num: number; label: string; sublabel?: string; enabled: boolean; active: boolean }[] = [
    { num: 1, label: 'Details', enabled: true, active: true },
    { num: 2, label: 'Strategy', enabled: true, active: hasSelectedStrategy },
    { num: 3, label: 'Entry & Exit', enabled: hasSelectedStrategy, active: hasSelectedStrategy },
    { num: 4, label: 'Advanced', sublabel: 'optional', enabled: hasSelectedStrategy, active: hasFiltersActive },
    { num: 5, label: 'Results', enabled: hasResults, active: hasResults },
  ];


  return (
    <div className="min-h-screen">
      <header className="px-6 py-4 flex items-center gap-3" style={{ background: 'linear-gradient(to right, #12E5CD, #12BAE6)' }}>
        <button onClick={() => window.location.reload()} className="flex items-center gap-3" style={{ background: 'none', border: 'none', cursor: 'pointer', padding: 0 }}>
          <img src="/XL logo transparent.png" alt="ThesisLab" className="w-8 h-8" />
          <h1 className="text-xl font-bold text-white tracking-tight">ThesisLab</h1>
        </button>
        <div style={{ flex: 1 }} />
        {user && (
          <button
            onClick={() => nav('/account')}
            style={{
              width: 34, height: 34, borderRadius: '50%', display: 'flex', alignItems: 'center', justifyContent: 'center',
              fontSize: '14px', fontWeight: 700, color: 'hsl(var(--primary-foreground))',
              backgroundColor: 'rgba(0,0,0,0.2)', border: '2px solid rgba(255,255,255,0.4)',
              cursor: 'pointer', overflow: 'hidden', padding: 0,
            }}
            title="Account"
          >
            {user.photoURL
              ? <img src={user.photoURL} alt="" style={{ width: '100%', height: '100%', objectFit: 'cover' }} />
              : (user.email?.[0] || 'U').toUpperCase()
            }
          </button>
        )}
      </header>

      {/* ── Horizontal step bar ── */}
      <nav style={{
        position: 'sticky',
        top: 0,
        zIndex: 40,
        backgroundColor: 'hsl(220 14% 10% / 0.95)',
        backdropFilter: 'blur(12px)',
        borderBottom: '1px solid rgba(255,255,255,0.06)',
        padding: '0 24px',
      }}>
        <div style={{ display: 'flex', alignItems: 'center', gap: '0px' }}>
          {steps.map((step, idx) => {
            const isSetupStep = step.num <= 4;
            const isResultsStep = step.num === 5;
            const isCurrent = isSetupStep ? activeSection === 'setup' : activeSection === 'results';
            const isEnabled = step.enabled;
            return (
              <div key={step.num} style={{ display: 'flex', alignItems: 'center' }}>
                {/* Connector line between steps */}
                {idx > 0 && (
                  <div style={{
                    width: idx === 4 ? '32px' : '24px',
                    height: '2px',
                    backgroundColor: step.enabled ? 'rgba(255,255,255,0.15)' : 'rgba(255,255,255,0.04)',
                    transition: 'background-color 0.2s',
                  }} />
                )}
                <button
                  onClick={() => {
                    if (!isEnabled) return;
                    if (isResultsStep) {
                      setActiveSection('results');
                    } else {
                      setActiveSection('setup');
                      scrollToSection(step.num);
                    }
                  }}
                  disabled={!isEnabled}
                  style={{
                    padding: '10px 16px',
                    fontSize: '13px',
                    fontWeight: 600,
                    color: (isCurrent && (isResultsStep || isSetupStep)) ? (step.active ? 'white' : '#d1d5db') : isEnabled ? (step.active ? '#d1d5db' : '#9ca3af') : '#4b5563',
                    backgroundColor: 'transparent',
                    border: 'none',
                    borderBottom: (isResultsStep && activeSection === 'results') ? '2px solid hsl(var(--accent))' : '2px solid transparent',
                    cursor: isEnabled ? 'pointer' : 'default',
                    transition: 'color 0.15s, border-color 0.15s',
                    display: 'flex',
                    alignItems: 'center',
                    gap: '8px',
                    opacity: isEnabled ? 1 : 0.35,
                    whiteSpace: 'nowrap',
                  }}
                >
                  <span style={{
                    display: 'inline-flex',
                    alignItems: 'center',
                    justifyContent: 'center',
                    width: '22px',
                    height: '22px',
                    borderRadius: '50%',
                    fontSize: '11px',
                    fontWeight: 700,
                    backgroundColor: step.active ? 'hsl(var(--accent))' : 'rgba(255,255,255,0.06)',
                    color: step.active ? 'hsl(var(--primary-foreground))' : '#6b7280',
                    border: '1.5px solid transparent',
                    transition: 'all 0.2s',
                  }}>{step.num}</span>
                  {step.label}
                  {step.sublabel && (
                    <span style={{ fontSize: '10px', color: '#6b7280', fontWeight: 400, fontStyle: 'italic' }}>{step.sublabel}</span>
                  )}
                  {step.num === 5 && isStale && (
                    <span style={{ width: '6px', height: '6px', borderRadius: '50%', backgroundColor: '#fbbf24', flexShrink: 0 }} />
                  )}
                </button>
              </div>
            );
          })}
        </div>
      </nav>

      <main className="p-6" style={{ paddingTop: '1.5rem' }}>
        {/* ── Error ── */}
        {error && (
          <div className="bg-[hsl(var(--danger)/0.1)] border border-[hsl(var(--danger)/0.3)] rounded-lg p-4 mb-6">
            <p className="text-[hsl(var(--danger))] text-sm">{error}</p>
          </div>
        )}

        {/* ── Loading progress (full-screen centered) ── */}
        {isLoading && (
          <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'center', minHeight: 'calc(100vh - 160px)' }}>
            <div className="card" style={{ maxWidth: '540px', width: '100%', textAlign: 'center', padding: '3rem 2.5rem' }}>
              <p className="text-white text-lg font-semibold" style={{ marginBottom: '1rem' }}>Running backtest...</p>
              <p className="text-sm" style={{ color: '#9ca3af', marginBottom: '1.25rem' }}>
                Simulating {ticker} from {fmtShortDate(startDate)} to {fmtShortDate(endDate)}
              </p>
              <div style={{ height: '6px', borderRadius: '3px', backgroundColor: 'rgba(255,255,255,0.08)', overflow: 'hidden', marginBottom: '0.75rem', position: 'relative' }}>
                <div style={{
                  position: 'absolute',
                  height: '100%',
                  width: '40%',
                  borderRadius: '3px',
                  background: 'linear-gradient(90deg, hsl(var(--accent)), #12BAE6)',
                  animation: 'indeterminate 1.4s ease-in-out infinite',
                }} />
              </div>
              <p className="text-xs" style={{ color: '#6b7280' }}>
                {loadingElapsed < 1
                  ? 'Starting...'
                  : `Elapsed ${loadingElapsed < 60 ? `${Math.floor(loadingElapsed)}s` : `${Math.floor(loadingElapsed / 60)}m ${Math.floor(loadingElapsed % 60)}s`}`}
                {dataSource === 'thetadata' && loadingElapsed > 5 && (
                  <span style={{ display: 'block', marginTop: '4px', color: '#6b7280' }}>
                    First run for a new ticker/range fetches and caches all option chains — can take a few minutes.
                  </span>
                )}
              </p>
              <button
                onClick={handleStop}
                style={{
                  marginTop: '1.5rem',
                  padding: '8px 20px',
                  borderRadius: '6px',
                  fontWeight: 600,
                  fontSize: '13px',
                  backgroundColor: 'rgba(248,113,113,0.1)',
                  color: '#f87171',
                  border: '1px solid rgba(248,113,113,0.3)',
                  cursor: 'pointer',
                }}
              >
                Stop backtest
              </button>
            </div>
          </div>
        )}

        {/* ── Setup view: Sections 1–4 all visible ── */}
        {activeSection === 'setup' && !isLoading && (
          <div style={{ display: 'flex', flexDirection: 'column', gap: '1.5rem' }}>
            {/* Section 1: Backtest Details */}
            <div ref={sectionRefs[1]} style={{ scrollMarginTop: '60px' }}>
              <h3 style={{ fontSize: '13px', fontWeight: 600, color: '#9ca3af', textTransform: 'uppercase', letterSpacing: '0.05em', marginBottom: '0.5rem', display: 'flex', alignItems: 'center', gap: '8px' }}>
                <span style={{ display: 'inline-flex', alignItems: 'center', justifyContent: 'center', width: '20px', height: '20px', borderRadius: '50%', fontSize: '10px', fontWeight: 700, backgroundColor: 'hsl(var(--accent))', color: 'hsl(var(--primary-foreground))' }}>1</span>
                Backtest Details
              </h3>
              <div className="card">
                <div className="flex flex-wrap items-end gap-4">
                  <div className="w-24">
                    <label className="block mb-1" style={{ fontSize: '14px', color: '#d1d5db' }}>Symbol <span style={{ color: '#f87171' }}>*</span></label>
                    <input className="input-field !text-lg !font-bold !tracking-widest !text-center" value={ticker}
                      placeholder="SPY"
                      onChange={(e) => handleSetTicker(e.target.value.toUpperCase())} />
                  </div>
                  <div className="w-40">
                    <label className="block mb-1" style={{ fontSize: '14px', color: '#d1d5db' }}>Start Date <span style={{ color: '#f87171' }}>*</span></label>
                    <input type="date" className="input-field" value={startDate}
                      onChange={(e) => handleSetStartDate(e.target.value)} />
                  </div>
                  <div className="w-40">
                    <label className="block mb-1" style={{ fontSize: '14px', color: '#d1d5db' }}>End Date <span style={{ color: '#f87171' }}>*</span></label>
                    <input type="date" className="input-field" value={endDate}
                      onChange={(e) => handleSetEndDate(e.target.value)} />
                  </div>
                  <div className="w-32">
                    <label className="block mb-1" style={{ fontSize: '14px', color: '#d1d5db' }}>Starting Cash</label>
                    <div className="relative">
                      <span className="absolute left-3 top-1/2 -translate-y-1/2 text-gray-500 text-sm">$</span>
                      <input type="number" className="input-field !pl-7" value={startingCash}
                        onChange={(e) => handleSetStartingCash(Number(e.target.value))} />
                    </div>
                  </div>
                  <div className="w-24">
                    <label className="block mb-1" style={{ fontSize: '14px', color: '#d1d5db' }}>Commission</label>
                    <div className="relative">
                      <span className="absolute left-3 top-1/2 -translate-y-1/2 text-gray-500 text-sm">$</span>
                      <input type="number" className="input-field !pl-7" step="0.05" min="0" value={commission}
                        onChange={(e) => handleSetCommission(Number(e.target.value))} />
                    </div>
                  </div>
                  <div>
                    <label className="block mb-1" style={{ fontSize: '14px', color: '#d1d5db' }}>Data Source</label>
                    <div style={{ display: 'inline-flex', borderRadius: '8px', backgroundColor: 'rgba(255,255,255,0.04)', padding: '3px', border: '1px solid rgba(255,255,255,0.08)' }}>
                      {(['synthetic', 'thetadata'] as const).map((src) => (
                        <button
                          key={src}
                          type="button"
                          onClick={() => { setDataSource(src); markStale(); }}
                          style={{
                            padding: '6px 14px', borderRadius: '6px', fontSize: '13px', fontWeight: 600,
                            backgroundColor: dataSource === src ? 'hsl(var(--accent))' : 'transparent',
                            color: dataSource === src ? 'hsl(var(--primary-foreground))' : '#9ca3af',
                            border: 'none', cursor: 'pointer',
                          }}
                        >
                          {src === 'synthetic' ? 'Synthetic' : 'ThetaData'}
                        </button>
                      ))}
                    </div>
                  </div>
                </div>
                {dataSource === 'thetadata' && (
                  <p className="text-xs text-gray-500" style={{ marginTop: '0.75rem' }}>
                    Using real EOD options data via ThetaData. First run for a new ticker/range may take a few minutes to fetch and cache locally; repeat runs are instant.
                  </p>
                )}
              </div>
            </div>

            {/* Section 2: Strategy */}
            <div ref={sectionRefs[2]} style={{ scrollMarginTop: '60px' }}>
              <h3 style={{ fontSize: '13px', fontWeight: 600, color: '#9ca3af', textTransform: 'uppercase', letterSpacing: '0.05em', marginBottom: '0.5rem', display: 'flex', alignItems: 'center', gap: '8px' }}>
                <span style={{ display: 'inline-flex', alignItems: 'center', justifyContent: 'center', width: '20px', height: '20px', borderRadius: '50%', fontSize: '10px', fontWeight: 700, backgroundColor: hasSelectedStrategy ? 'hsl(var(--accent))' : 'rgba(255,255,255,0.06)', color: hasSelectedStrategy ? 'hsl(var(--primary-foreground))' : '#6b7280' }}>2</span>
                Strategy
              </h3>
              <div className="card" onMouseLeave={() => setHoveredStrategy(null)} style={{ display: 'flex', gap: '1.5rem' }}>
                {/* Left side — strategy tiles */}
                <div style={{ flex: '1 1 0', minWidth: 0 }}>
                  <div style={{ marginBottom: '2.5rem' }}>
                    <h3 className="text-lg font-bold text-white text-center" style={{ marginBottom: '1rem' }}>Select a Leg</h3>
                    <div className="flex flex-wrap gap-3 justify-center">
                      {SINGLE_LEG.map((s) => (
                        <StrategyCard key={s.key} name={s.name} tag={s.tag}
                          selected={strategy.type === s.key}
                          onClick={() => handleStrategyChange(s.key)}
                          onHover={() => setHoveredStrategy(s.key)} />
                      ))}
                    </div>
                  </div>
                  <div>
                    <h3 className="text-lg font-bold text-white text-center" style={{ marginBottom: '1rem' }}>...or Choose a Strategy</h3>
                    <div style={{ display: 'flex', gap: '1rem', justifyContent: 'center' }}>
                      {STRATEGY_GROUPS.map((group, i) => (
                        <div key={group.label} style={{ display: 'flex', flexDirection: 'column', gap: '8px', width: '14rem', paddingLeft: i > 0 ? '1rem' : undefined, borderLeft: i > 0 ? '1px solid rgba(255,255,255,0.06)' : undefined }}>
                          <p style={{ fontSize: '14px', color: '#d1d5db', textAlign: 'center', marginBottom: '4px' }}>{group.label}</p>
                          {group.items.map((s) => (
                            <StrategyCard key={s.key} name={s.name} tag={s.tag}
                              selected={strategy.type === s.key}
                              onClick={() => handleStrategyChange(s.key)}
                              onHover={() => setHoveredStrategy(s.key)} />
                          ))}
                        </div>
                      ))}
                    </div>
                  </div>
                </div>
                {/* Right side — hover preview */}
                <div style={{ width: '440px', flexShrink: 0, borderLeft: '1px solid rgba(255,255,255,0.06)', paddingLeft: '1.25rem', display: 'flex', flexDirection: 'column', alignItems: 'center', justifyContent: 'center', minHeight: '300px' }}>
                  {hoveredStrategy && STRATEGY_META[hoveredStrategy] ? (() => {
                    const meta = STRATEGY_META[hoveredStrategy];
                    const strat = ALL_STRATEGIES.find((s) => s.key === hoveredStrategy);
                    if (!strat) return null;
                    return (
                      <>
                        <PayoffDiagram points={meta.points} strikes={meta.strikes} />
                        <div style={{ textAlign: 'center', marginTop: '1rem' }}>
                          <div className="text-white font-semibold text-base" style={{ marginBottom: '6px' }}>{strat.name}</div>
                          <div style={{ display: 'flex', gap: '0.375rem', justifyContent: 'center', marginBottom: '8px' }}>
                            <span className={`px-2 py-0.5 rounded text-[11px] font-semibold ${TAG_COLORS[strat.tag]}`} style={{ backgroundColor: 'rgba(255,255,255,0.05)' }}>
                              {strat.tag}
                            </span>
                            <span className={`px-2 py-0.5 rounded text-[11px] font-semibold ${meta.type === 'credit' ? 'text-emerald-400' : 'text-blue-400'}`} style={{ backgroundColor: 'rgba(255,255,255,0.05)' }}>
                              {meta.type === 'credit' ? 'Credit' : 'Debit'}
                            </span>
                            <span className={`px-2 py-0.5 rounded text-[11px] font-semibold ${meta.risk === 'defined' ? 'text-gray-400' : 'text-amber-400'}`} style={{ backgroundColor: 'rgba(255,255,255,0.05)' }}>
                              {meta.risk === 'defined' ? 'Defined Risk' : 'Undefined Risk'}
                            </span>
                          </div>
                          <p className="text-sm text-gray-400" style={{ marginBottom: '8px' }}>{meta.desc}</p>
                          <div style={{ display: 'inline-flex', flexDirection: 'column', gap: '2px' }}>
                            {meta.legs.map((leg, i) => (
                              <span key={i} className="text-sm font-mono flex items-center gap-1.5">
                                <span style={{ width: 7, height: 7, borderRadius: '50%', display: 'inline-block', flexShrink: 0, backgroundColor: leg.action === 'Sell' ? '#f87171' : '#34d399' }} />
                                <span className="text-gray-400">{leg.action} {leg.label}</span>
                              </span>
                            ))}
                          </div>
                        </div>
                      </>
                    );
                  })() : (
                    <span className="text-sm text-gray-600">Hover a strategy to preview</span>
                  )}
                </div>
              </div>
            </div>

            {/* Section 3: Entry & Exit Rules */}
            {hasSelectedStrategy && (
              <div ref={sectionRefs[3]} style={{ scrollMarginTop: '60px' }}>
                <h3 style={{ fontSize: '13px', fontWeight: 600, color: '#9ca3af', textTransform: 'uppercase', letterSpacing: '0.05em', marginBottom: '0.5rem', display: 'flex', alignItems: 'center', gap: '8px' }}>
                  <span style={{ display: 'inline-flex', alignItems: 'center', justifyContent: 'center', width: '20px', height: '20px', borderRadius: '50%', fontSize: '10px', fontWeight: 700, backgroundColor: hasSelectedStrategy ? 'hsl(var(--accent))' : 'rgba(255,255,255,0.06)', color: hasSelectedStrategy ? 'hsl(var(--primary-foreground))' : '#6b7280' }}>3</span>
                  Entry & Exit Rules
                </h3>
                <StrategyPanel strategy={strategy} onChange={handleSetStrategy} underlyingPrice={syntheticConfig.start_price} />
              </div>
            )}

            {/* Section 4: Advanced Rules */}
            {hasSelectedStrategy && (
              <div ref={sectionRefs[4]} style={{ scrollMarginTop: '60px' }}>
                <h3 style={{ fontSize: '13px', fontWeight: 600, color: '#9ca3af', textTransform: 'uppercase', letterSpacing: '0.05em', marginBottom: '0.5rem', display: 'flex', alignItems: 'center', gap: '8px' }}>
                  <span style={{ display: 'inline-flex', alignItems: 'center', justifyContent: 'center', width: '20px', height: '20px', borderRadius: '50%', fontSize: '10px', fontWeight: 700, backgroundColor: hasFiltersActive ? 'hsl(var(--accent))' : 'rgba(255,255,255,0.06)', color: hasFiltersActive ? 'hsl(var(--primary-foreground))' : '#6b7280' }}>4</span>
                  Advanced Rules <span style={{ fontWeight: 400, fontStyle: 'italic', color: '#6b7280', fontSize: '11px' }}>— optional</span>
                </h3>
                <AdvancedSettings filters={filters} onChange={handleSetFilters} />
              </div>
            )}
          </div>
        )}

        {/* ── Results view: Section 5 ── */}
        {activeSection === 'results' && hasResults && (
          <div style={{ display: 'flex', flexDirection: 'column', gap: '1.5rem' }}>
            {/* Header: Save button + stale warning */}
            <div style={{ display: 'flex', alignItems: 'center', gap: '12px' }}>
              <h2 className="text-lg font-bold text-white" style={{ flex: 1 }}>Backtest Results</h2>
              {saveMsg && <span className="text-xs text-emerald-400">{saveMsg}</span>}
              <button
                onClick={() => { setSaveName(`${ticker} ${strategy.type || 'backtest'} ${new Date().toLocaleDateString()}`); setShowSaveModal(true); }}
                style={{
                  padding: '7px 16px', borderRadius: '6px', fontWeight: 600, fontSize: '13px',
                  backgroundColor: 'rgba(255,255,255,0.05)', color: '#d1d5db',
                  border: '1px solid rgba(255,255,255,0.1)', cursor: 'pointer',
                  display: 'flex', alignItems: 'center', gap: '6px',
                }}
              >
                <svg width="13" height="13" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
                  <path d="M19 21H5a2 2 0 0 1-2-2V5a2 2 0 0 1 2-2h11l5 5v11a2 2 0 0 1-2 2z" />
                  <polyline points="17 21 17 13 7 13 7 21" />
                  <polyline points="7 3 7 8 15 8" />
                </svg>
                Save
              </button>
            </div>
            {/* Stale warning */}
            {isStale && (
              <div style={{ textAlign: 'center', padding: '8px', borderRadius: '8px', backgroundColor: 'rgba(251,191,36,0.08)', border: '1px solid rgba(251,191,36,0.2)' }}>
                <span style={{ fontSize: '13px', color: '#fbbf24', fontWeight: 500 }}>Settings changed — re-run for updated results</span>
              </div>
            )}

            {/* Strategy details + Performance stats */}
            <div className="card" style={{ padding: '0.75rem 1.25rem' }}>
              <div style={{ display: 'flex', gap: '1rem', flexWrap: 'wrap', alignItems: 'flex-end', marginBottom: '0.75rem', paddingBottom: '0.75rem', borderBottom: '1px solid rgba(255,255,255,0.06)' }}>
                {strategySummary().map((item) => (
                  <div key={item.label} style={{ textAlign: 'center' }}>
                    <p style={{ fontSize: '10px', color: '#6b7280', marginBottom: '2px', textTransform: 'uppercase', letterSpacing: '0.05em', whiteSpace: 'nowrap' }}>{item.label}</p>
                    <p style={{ fontSize: '13px', color: 'white', fontWeight: 600, fontFamily: 'var(--font-mono, ui-monospace, monospace)', whiteSpace: 'nowrap' }}>{item.value}</p>
                  </div>
                ))}
                {filterSummary().length > 0 && (
                  <div style={{ width: '1px', height: '28px', backgroundColor: 'rgba(255,255,255,0.08)', flexShrink: 0 }} />
                )}
                {filterSummary().map((item) => (
                  <div key={item.label} style={{ textAlign: 'center' }}>
                    <p style={{ fontSize: '10px', color: 'hsl(var(--accent))', marginBottom: '2px', textTransform: 'uppercase', letterSpacing: '0.05em', whiteSpace: 'nowrap' }}>{item.label}</p>
                    <p style={{ fontSize: '13px', color: 'white', fontWeight: 600, fontFamily: 'var(--font-mono, ui-monospace, monospace)', whiteSpace: 'nowrap' }}>{item.value}</p>
                  </div>
                ))}
              </div>
              <div style={{ display: 'flex', gap: '1rem', flexWrap: 'wrap', justifyContent: 'space-between' }}>
                {[
                  { label: 'Total Return', value: formatPct(result.total_return_pct), color: result.total_return_pct >= 0 ? '#10b981' : '#f87171' },
                  { label: 'Annual', value: formatPct(result.annualized_return), color: result.annualized_return >= 0 ? '#10b981' : '#f87171' },
                  { label: 'Total P&L', value: formatCurrency(result.total_pnl), color: result.total_pnl >= 0 ? '#10b981' : '#f87171' },
                  { label: 'Avg P&L', value: formatCurrency(result.avg_pnl_per_trade), color: result.avg_pnl_per_trade >= 0 ? '#10b981' : '#f87171' },
                  { label: 'Win Rate', value: `${result.win_rate.toFixed(1)}%`, color: result.win_rate >= 50 ? '#10b981' : '#f87171' },
                  { label: 'Drawdown', value: `${result.max_drawdown_pct.toFixed(2)}%`, color: '#f87171' },
                  { label: 'Trades', value: `${result.total_trades}`, color: 'white' },
                  { label: 'Sharpe', value: result.sharpe_ratio.toFixed(2), color: result.sharpe_ratio >= 0 ? '#10b981' : '#f87171' },
                  { label: 'Profit Factor', value: result.profit_factor >= 9999 ? '∞' : result.profit_factor.toFixed(2), color: result.profit_factor >= 1 ? '#10b981' : '#f87171' },
                  { label: 'Hold Days', value: result.avg_holding_days.toFixed(1), color: 'white' },
                ].map((stat) => (
                  <div key={stat.label} style={{ textAlign: 'center', flex: '1 1 0', minWidth: 0 }}>
                    <p style={{ fontSize: '10px', color: '#9ca3af', marginBottom: '2px', textTransform: 'uppercase', letterSpacing: '0.05em', whiteSpace: 'nowrap' }}>{stat.label}</p>
                    <p style={{ fontSize: '14px', color: stat.color, fontWeight: 600, fontFamily: 'var(--font-mono, ui-monospace, monospace)', whiteSpace: 'nowrap' }}>{stat.value}</p>
                  </div>
                ))}
              </div>
            </div>

            {/* Tabbed charts */}
            <div className="card" style={{ padding: 0 }}>
              <div style={{ display: 'flex', borderBottom: '1px solid rgba(255,255,255,0.08)' }}>
                {[
                  { key: 'equity' as const, label: 'Equity Curve' },
                  ...(result.indicators.length > 0 ? [{ key: 'price' as const, label: 'Price & Indicators' }] : []),
                ].map((tab) => (
                  <button
                    key={tab.key}
                    onClick={() => setChartTab(tab.key)}
                    style={{
                      padding: '10px 20px',
                      fontSize: '13px',
                      fontWeight: 600,
                      color: chartTab === tab.key ? 'white' : '#6b7280',
                      backgroundColor: 'transparent',
                      border: 'none',
                      borderBottom: chartTab === tab.key ? '2px solid hsl(var(--accent))' : '2px solid transparent',
                      cursor: 'pointer',
                      transition: 'color 0.15s, border-color 0.15s',
                    }}
                  >
                    {tab.label}
                  </button>
                ))}
              </div>
              <div style={{ padding: '1rem 1.5rem' }}>
                {chartTab === 'equity' && (
                  <div>
                    <p className="text-xs text-gray-400 mb-3">
                      Your portfolio's total value over time, including cash and open positions.
                      A rising curve means the strategy is growing capital; dips represent drawdowns.
                    </p>
                    <EquityChart data={result.equity_curve} trades={result.trades} sp500={result.sp500_benchmark} buyHold={result.buy_hold_benchmark} ticker={ticker} startingCash={startingCash} />
                  </div>
                )}
                {chartTab === 'price' && result.indicators.length > 0 && (
                  <div>
                    <p className="text-xs text-gray-400 mb-3">
                      Underlying price with optional technical indicator overlays.
                    </p>
                    <PriceChart data={result.indicators} trades={result.trades} sp500={result.sp500_benchmark} buyHold={result.buy_hold_benchmark} ticker={ticker} startingCash={startingCash} />
                  </div>
                )}
              </div>
            </div>

            {/* Trade Log */}
            <div className="card">
              <h3 className="card-title" style={{ marginBottom: '0.5rem' }}>Trade Log</h3>
              <TradeLog trades={result.trades} />
            </div>

            {/* Open Positions */}
            {result.open_positions_count > 0 && (
              <div className="card">
                <h3 className="card-title">Open Positions: {result.open_positions_count}</h3>
              </div>
            )}
          </div>
        )}

        {/* Spacer for sticky bottom bar */}
        <div style={{ height: hasSelectedStrategy ? '160px' : '90px' }} />
      </main>

      {/* ── Sticky bottom bar ── */}
      <div style={{
        position: 'fixed',
        bottom: 0,
        left: 0,
        right: 0,
        zIndex: 50,
        backgroundColor: 'hsl(220 14% 11% / 0.95)',
        backdropFilter: 'blur(12px)',
        borderTop: '1px solid rgba(255,255,255,0.08)',
        padding: '12px 28px',
      }}>
        {hasSelectedStrategy ? (
          <div style={{ display: 'flex', flexDirection: 'column', alignItems: 'center', gap: '10px' }}>
            {/* Summary row — hidden on results view */}
            {activeSection !== 'results' && (
              <div style={{ display: 'flex', gap: '1.25rem', flexWrap: 'nowrap', alignItems: 'flex-end', justifyContent: 'center' }}>
                {strategySummary().map((item) => (
                  <div key={item.label} style={{ textAlign: 'center' }}>
                    <p style={{ fontSize: '10px', color: '#9ca3af', marginBottom: '2px', textTransform: 'uppercase', letterSpacing: '0.05em', whiteSpace: 'nowrap' }}>{item.label}</p>
                    <p style={{ fontSize: '13px', color: 'white', fontWeight: 600, fontFamily: 'var(--font-mono, ui-monospace, monospace)', whiteSpace: 'nowrap' }}>{item.value}</p>
                  </div>
                ))}
                {filterSummary().map((item) => (
                  <div key={item.label} style={{ textAlign: 'center' }}>
                    <p style={{ fontSize: '10px', color: 'hsl(var(--accent))', marginBottom: '2px', textTransform: 'uppercase', letterSpacing: '0.05em', whiteSpace: 'nowrap' }}>{item.label}</p>
                    <p style={{ fontSize: '13px', color: 'white', fontWeight: 600, fontFamily: 'var(--font-mono, ui-monospace, monospace)', whiteSpace: 'nowrap' }}>{item.value}</p>
                  </div>
                ))}
                {tradeEstimate && (
                  <>
                    <div style={{ width: '1px', height: '32px', backgroundColor: 'rgba(255,255,255,0.1)', flexShrink: 0 }} />
                    <div style={{ textAlign: 'center' }}>
                      <p style={{ fontSize: '10px', color: '#9ca3af', marginBottom: '2px', textTransform: 'uppercase', letterSpacing: '0.05em', whiteSpace: 'nowrap' }}>{tradeEstimate.isCredit ? 'Credit' : 'Debit'}</p>
                      <p style={{ fontSize: '13px', color: tradeEstimate.isCredit ? '#10b981' : '#f87171', fontWeight: 600, fontFamily: 'var(--font-mono, ui-monospace, monospace)', whiteSpace: 'nowrap' }}>{fmtEst(Math.abs(tradeEstimate.creditOrDebit))}</p>
                    </div>
                    <div style={{ textAlign: 'center' }}>
                      <p style={{ fontSize: '10px', color: '#9ca3af', marginBottom: '2px', textTransform: 'uppercase', letterSpacing: '0.05em', whiteSpace: 'nowrap' }}>BPR</p>
                      <p style={{ fontSize: '13px', color: 'white', fontWeight: 600, fontFamily: 'var(--font-mono, ui-monospace, monospace)', whiteSpace: 'nowrap' }}>{fmtEst(tradeEstimate.marginRequired)}</p>
                    </div>
                    <div style={{ textAlign: 'center' }}>
                      <p style={{ fontSize: '10px', color: '#9ca3af', marginBottom: '2px', textTransform: 'uppercase', letterSpacing: '0.05em', whiteSpace: 'nowrap' }}>Max Gain</p>
                      <p style={{ fontSize: '13px', color: '#10b981', fontWeight: 600, fontFamily: 'var(--font-mono, ui-monospace, monospace)', whiteSpace: 'nowrap' }}>{fmtEst(tradeEstimate.maxGain)}</p>
                    </div>
                    <div style={{ textAlign: 'center' }}>
                      <p style={{ fontSize: '10px', color: '#9ca3af', marginBottom: '2px', textTransform: 'uppercase', letterSpacing: '0.05em', whiteSpace: 'nowrap' }}>Max Loss</p>
                      <p style={{ fontSize: '13px', color: '#f87171', fontWeight: 600, fontFamily: 'var(--font-mono, ui-monospace, monospace)', whiteSpace: 'nowrap' }}>{fmtEst(tradeEstimate.maxLoss)}</p>
                    </div>
                  </>
                )}
              </div>
            )}
            {/* Centered Run button */}
            <div style={{ display: 'flex', alignItems: 'center', gap: '8px' }}>
              {isStale && (
                <span style={{ display: 'inline-flex', alignItems: 'center', gap: '5px', fontSize: '11px', color: '#fbbf24', fontWeight: 500 }}>
                  <span style={{ width: 6, height: 6, borderRadius: '50%', backgroundColor: '#f59e0b', animation: 'pulse 2s ease-in-out infinite' }} />
                  Settings changed
                </span>
              )}
              <button
                onClick={handleRun}
                disabled={isLoading}
                style={{
                  padding: '10px 52px', borderRadius: '8px', fontWeight: 700, fontSize: '15px',
                  backgroundColor: isStale ? '#f59e0b' : 'hsl(var(--accent))',
                  color: isStale ? '#000' : 'hsl(var(--primary-foreground))',
                  border: 'none', cursor: isLoading ? 'not-allowed' : 'pointer',
                  opacity: isLoading ? 0.5 : 1, whiteSpace: 'nowrap',
                  boxShadow: isStale ? '0 0 16px rgba(245,158,11,0.4)' : 'none',
                  transition: 'background-color 0.2s, box-shadow 0.2s',
                }}
              >
                {isLoading ? 'Running...' : isStale ? 'Re-run Backtest' : 'Run Backtest'}
              </button>
            </div>
          </div>
        ) : (
          <div style={{ display: 'flex', justifyContent: 'center', padding: '8px 0' }}>
            <span style={{ fontSize: '14px', color: '#6b7280', fontWeight: 500 }}>Select a strategy to get started</span>
          </div>
        )}
      </div>

      {/* ── Save backtest modal ── */}
      {showSaveModal && result && (
        <div
          onClick={() => setShowSaveModal(false)}
          style={{ position: 'fixed', inset: 0, zIndex: 100, backgroundColor: 'rgba(0,0,0,0.6)', backdropFilter: 'blur(4px)', display: 'flex', alignItems: 'center', justifyContent: 'center' }}
        >
          <div
            onClick={(e) => e.stopPropagation()}
            className="card"
            style={{ width: '100%', maxWidth: '400px', margin: '0 1rem' }}
          >
            <h3 className="card-title" style={{ marginBottom: '0.75rem' }}>Save Backtest</h3>
            <p className="text-xs text-gray-400" style={{ marginBottom: '0.75rem' }}>Give this run a name so you can find it later in your account.</p>
            <input
              autoFocus
              className="input-field"
              value={saveName}
              onChange={(e) => setSaveName(e.target.value)}
              placeholder="e.g. AAPL short put spread Q1"
              style={{ width: '100%', marginBottom: '1rem' }}
              onKeyDown={(e) => {
                if (e.key === 'Enter' && saveName.trim()) {
                  saveBacktest({
                    id: `bt_${Date.now()}`,
                    name: saveName.trim(),
                    savedAt: new Date().toISOString(),
                    ticker, startDate, endDate, startingCash, commission,
                    strategy, filters,
                    totalReturn: result.total_return_pct,
                    totalTrades: result.total_trades,
                    winRate: result.win_rate / 100,
                    sharpe: result.sharpe_ratio,
                    result,
                  });
                  setShowSaveModal(false);
                  setSaveMsg('Saved to your account');
                  setTimeout(() => setSaveMsg(''), 3000);
                }
              }}
            />
            <div style={{ display: 'flex', gap: '8px', justifyContent: 'flex-end' }}>
              <button
                onClick={() => setShowSaveModal(false)}
                style={{ padding: '8px 16px', borderRadius: '6px', fontWeight: 600, fontSize: '13px', backgroundColor: 'rgba(255,255,255,0.05)', color: '#9ca3af', border: 'none', cursor: 'pointer' }}
              >
                Cancel
              </button>
              <button
                disabled={!saveName.trim()}
                onClick={() => {
                  saveBacktest({
                    id: `bt_${Date.now()}`,
                    name: saveName.trim(),
                    savedAt: new Date().toISOString(),
                    ticker, startDate, endDate, startingCash, commission,
                    strategy, filters,
                    totalReturn: result.total_return_pct,
                    totalTrades: result.total_trades,
                    winRate: result.win_rate / 100,
                    sharpe: result.sharpe_ratio,
                    result,
                  });
                  setShowSaveModal(false);
                  setSaveMsg('Saved to your account');
                  setTimeout(() => setSaveMsg(''), 3000);
                }}
                style={{
                  padding: '8px 20px', borderRadius: '6px', fontWeight: 600, fontSize: '13px',
                  backgroundColor: saveName.trim() ? 'hsl(var(--accent))' : 'rgba(255,255,255,0.1)',
                  color: saveName.trim() ? 'hsl(var(--primary-foreground))' : '#6b7280',
                  border: 'none', cursor: saveName.trim() ? 'pointer' : 'not-allowed',
                }}
              >
                Save
              </button>
            </div>
          </div>
        </div>
      )}
    </div>
  );
}

export default App;
