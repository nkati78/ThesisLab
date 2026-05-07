import { useState } from 'react';
import { updateProfile, updatePassword, EmailAuthProvider, reauthenticateWithCredential } from 'firebase/auth';
import { useAuth } from '../lib/AuthContext';
import { useNavigate } from 'react-router-dom';
import {
  getSavedBacktests, deleteBacktest, type SavedBacktest,
  getDefaultSettings, saveDefaultSettings, clearDefaultSettings,
} from '../lib/storage';

type Tab = 'profile' | 'saved' | 'defaults';

const TABS: { key: Tab; label: string }[] = [
  { key: 'profile', label: 'Profile' },
  { key: 'saved', label: 'Saved Backtests' },
  { key: 'defaults', label: 'Default Settings' },
];

export default function Account() {
  const { user, logout, isDemo } = useAuth();
  const navigate = useNavigate();
  const [tab, setTab] = useState<Tab>('profile');

  return (
    <div className="min-h-screen" style={{ backgroundColor: 'hsl(220 15% 8%)' }}>
      <header className="px-6 py-4 flex items-center gap-3" style={{ background: 'linear-gradient(to right, #12E5CD, #12BAE6)' }}>
        <button onClick={() => navigate('/')} className="flex items-center gap-3" style={{ background: 'none', border: 'none', cursor: 'pointer', padding: 0 }}>
          <img src="/XL logo transparent.png" alt="ThesisLab" className="w-8 h-8" />
          <h1 className="text-xl font-bold text-white tracking-tight">ThesisLab</h1>
        </button>
        <div style={{ flex: 1 }} />
        <button
          onClick={() => navigate('/')}
          style={{ background: 'rgba(0,0,0,0.15)', border: 'none', cursor: 'pointer', padding: '6px 14px', borderRadius: '6px', fontSize: '13px', fontWeight: 600, color: 'white' }}
        >
          Back to app
        </button>
      </header>

      <div style={{ maxWidth: '720px', margin: '0 auto', padding: '2rem 1.5rem' }}>
        <h2 className="text-2xl font-bold text-white" style={{ marginBottom: '1.5rem' }}>Account</h2>

        {/* Tab bar */}
        <div style={{ display: 'flex', gap: '4px', marginBottom: '1.5rem', borderBottom: '1px solid rgba(255,255,255,0.08)', paddingBottom: '0' }}>
          {TABS.map((t) => (
            <button
              key={t.key}
              onClick={() => setTab(t.key)}
              style={{
                padding: '10px 20px', fontSize: '14px', fontWeight: 600, cursor: 'pointer',
                background: 'none', border: 'none',
                color: tab === t.key ? 'hsl(var(--accent))' : '#9ca3af',
                borderBottom: tab === t.key ? '2px solid hsl(var(--accent))' : '2px solid transparent',
                marginBottom: '-1px',
                transition: 'color 0.15s',
              }}
            >
              {t.label}
            </button>
          ))}
        </div>

        {tab === 'profile' && <ProfileTab user={user} isDemo={isDemo} logout={logout} navigate={navigate} />}
        {tab === 'saved' && <SavedTab navigate={navigate} />}
        {tab === 'defaults' && <DefaultsTab />}
      </div>
    </div>
  );
}

/* ── Profile Tab ── */
function ProfileTab({ user, isDemo, logout, navigate }: { user: ReturnType<typeof useAuth>['user']; isDemo: boolean; logout: () => Promise<void>; navigate: ReturnType<typeof useNavigate> }) {
  const [displayName, setDisplayName] = useState(user?.displayName || '');
  const [nameMsg, setNameMsg] = useState('');
  const [currentPw, setCurrentPw] = useState('');
  const [newPw, setNewPw] = useState('');
  const [pwMsg, setPwMsg] = useState('');
  const [pwError, setPwError] = useState('');

  const handleSaveName = async () => {
    if (!user || isDemo) { setNameMsg('Demo mode — changes not saved'); return; }
    try {
      await updateProfile(user, { displayName });
      setNameMsg('Name updated');
    } catch { setNameMsg('Failed to update name'); }
    setTimeout(() => setNameMsg(''), 3000);
  };

  const handleChangePassword = async (e: React.FormEvent) => {
    e.preventDefault();
    setPwMsg(''); setPwError('');
    if (isDemo) { setPwError('Demo mode — changes not saved'); return; }
    if (!user?.email) return;
    if (newPw.length < 6) { setPwError('New password must be at least 6 characters'); return; }
    try {
      const cred = EmailAuthProvider.credential(user.email, currentPw);
      await reauthenticateWithCredential(user, cred);
      await updatePassword(user, newPw);
      setPwMsg('Password updated');
      setCurrentPw(''); setNewPw('');
    } catch (err: unknown) {
      const msg = err instanceof Error ? err.message : '';
      if (msg.includes('wrong-password') || msg.includes('invalid-credential')) setPwError('Current password is incorrect');
      else setPwError('Failed to update password');
    }
    setTimeout(() => { setPwMsg(''); setPwError(''); }, 4000);
  };

  const isGoogleOnly = user?.providerData?.[0]?.providerId === 'google.com';

  return (
    <div style={{ display: 'flex', flexDirection: 'column', gap: '1.5rem' }}>
      {/* Avatar + email */}
      <div className="card" style={{ display: 'flex', alignItems: 'center', gap: '1rem' }}>
        <div style={{
          width: 56, height: 56, borderRadius: '50%', display: 'flex', alignItems: 'center', justifyContent: 'center',
          fontSize: '20px', fontWeight: 700, color: 'hsl(var(--primary-foreground))',
          backgroundColor: 'hsl(var(--accent))',
          overflow: 'hidden',
        }}>
          {user?.photoURL
            ? <img src={user.photoURL} alt="" style={{ width: '100%', height: '100%', objectFit: 'cover' }} />
            : (user?.email?.[0] || 'U').toUpperCase()
          }
        </div>
        <div>
          <p className="text-white font-semibold">{user?.displayName || user?.email}</p>
          <p className="text-sm text-gray-400">{user?.email}</p>
          {isDemo && <p className="text-xs text-amber-400" style={{ marginTop: '2px' }}>Demo mode</p>}
        </div>
      </div>

      {/* Display name */}
      <div className="card">
        <h3 className="card-title">Display Name</h3>
        <div className="flex items-end gap-3">
          <div style={{ flex: 1 }}>
            <input
              className="input-field"
              value={displayName}
              onChange={(e) => setDisplayName(e.target.value)}
              placeholder="Your name"
              style={{ width: '100%' }}
            />
          </div>
          <button
            onClick={handleSaveName}
            style={{
              padding: '8px 20px', borderRadius: '6px', fontWeight: 600, fontSize: '13px',
              backgroundColor: 'hsl(var(--accent))', color: 'hsl(var(--primary-foreground))',
              border: 'none', cursor: 'pointer',
            }}
          >
            Save
          </button>
        </div>
        {nameMsg && <p className="text-xs text-emerald-400" style={{ marginTop: '6px' }}>{nameMsg}</p>}
      </div>

      {/* Change password — hide for Google-only accounts */}
      {!isGoogleOnly && (
        <div className="card">
          <h3 className="card-title">Change Password</h3>
          <form onSubmit={handleChangePassword} style={{ display: 'flex', flexDirection: 'column', gap: '0.75rem' }}>
            <input
              type="password"
              className="input-field"
              placeholder="Current password"
              value={currentPw}
              onChange={(e) => setCurrentPw(e.target.value)}
              required
            />
            <input
              type="password"
              className="input-field"
              placeholder="New password"
              value={newPw}
              onChange={(e) => setNewPw(e.target.value)}
              required
            />
            <button
              type="submit"
              style={{
                alignSelf: 'flex-start', padding: '8px 20px', borderRadius: '6px', fontWeight: 600, fontSize: '13px',
                backgroundColor: 'hsl(var(--accent))', color: 'hsl(var(--primary-foreground))',
                border: 'none', cursor: 'pointer',
              }}
            >
              Update password
            </button>
            {pwMsg && <p className="text-xs text-emerald-400">{pwMsg}</p>}
            {pwError && <p className="text-xs text-red-400">{pwError}</p>}
          </form>
        </div>
      )}

      {/* Log out */}
      <button
        onClick={async () => { await logout(); navigate('/login'); }}
        style={{
          alignSelf: 'flex-start', padding: '8px 20px', borderRadius: '6px', fontWeight: 600, fontSize: '13px',
          backgroundColor: 'rgba(248,113,113,0.1)', color: '#f87171', border: '1px solid rgba(248,113,113,0.3)',
          cursor: 'pointer',
        }}
      >
        Log out
      </button>
    </div>
  );
}

/* ── Saved Backtests Tab ── */
function SavedTab({ navigate }: { navigate: ReturnType<typeof useNavigate> }) {
  const [backtests, setBacktests] = useState<SavedBacktest[]>(getSavedBacktests);
  const [confirmDelete, setConfirmDelete] = useState<string | null>(null);

  const handleDelete = (id: string) => {
    deleteBacktest(id);
    setBacktests(getSavedBacktests());
    setConfirmDelete(null);
  };

  if (backtests.length === 0) {
    return (
      <div className="card" style={{ textAlign: 'center', padding: '3rem 1.5rem' }}>
        <p className="text-gray-400" style={{ marginBottom: '4px' }}>No saved backtests yet</p>
        <p className="text-sm text-gray-600">Run a backtest and click "Save" to store it here for later.</p>
      </div>
    );
  }

  return (
    <div style={{ display: 'flex', flexDirection: 'column', gap: '0.75rem' }}>
      {backtests.map((bt) => (
        <div
          key={bt.id}
          className="card"
          onClick={() => navigate('/', { state: { loadBacktest: bt } })}
          style={{ display: 'flex', alignItems: 'center', gap: '1rem', cursor: 'pointer', transition: 'background-color 0.15s' }}
          onMouseEnter={(e) => e.currentTarget.style.backgroundColor = 'rgba(255,255,255,0.03)'}
          onMouseLeave={(e) => e.currentTarget.style.backgroundColor = ''}
        >
          <div style={{ flex: 1, minWidth: 0 }}>
            <div className="flex items-center gap-2" style={{ marginBottom: '4px' }}>
              <span className="text-white font-semibold text-sm">{bt.name}</span>
              <span className="text-xs text-gray-500">{bt.ticker}</span>
              <span className="text-xs text-gray-600">{bt.startDate} → {bt.endDate}</span>
            </div>
            <div className="flex gap-4 text-xs font-mono">
              <span className={bt.totalReturn >= 0 ? 'text-emerald-400' : 'text-red-400'}>
                {bt.totalReturn >= 0 ? '+' : ''}{bt.totalReturn.toFixed(1)}%
              </span>
              <span className="text-gray-400">{bt.totalTrades} trades</span>
              <span className="text-gray-400">{(bt.winRate * 100).toFixed(0)}% win</span>
              <span className="text-gray-400">Sharpe {bt.sharpe.toFixed(2)}</span>
            </div>
            <p className="text-xs text-gray-600" style={{ marginTop: '2px' }}>
              Saved {new Date(bt.savedAt).toLocaleDateString()}
            </p>
          </div>
          <div className="flex items-center gap-2">
            {confirmDelete === bt.id ? (
              <>
                <button
                  onClick={(e) => { e.stopPropagation(); handleDelete(bt.id); }}
                  style={{ padding: '6px 12px', borderRadius: '6px', fontSize: '12px', fontWeight: 600, backgroundColor: 'rgba(248,113,113,0.15)', color: '#f87171', border: '1px solid rgba(248,113,113,0.3)', cursor: 'pointer' }}
                >
                  Confirm
                </button>
                <button
                  onClick={(e) => { e.stopPropagation(); setConfirmDelete(null); }}
                  style={{ padding: '6px 12px', borderRadius: '6px', fontSize: '12px', fontWeight: 600, backgroundColor: 'rgba(255,255,255,0.05)', color: '#9ca3af', border: 'none', cursor: 'pointer' }}
                >
                  Cancel
                </button>
              </>
            ) : (
              <button
                onClick={(e) => { e.stopPropagation(); setConfirmDelete(bt.id); }}
                style={{ padding: '6px 12px', borderRadius: '6px', fontSize: '12px', fontWeight: 600, backgroundColor: 'rgba(255,255,255,0.05)', color: '#9ca3af', border: 'none', cursor: 'pointer' }}
              >
                Delete
              </button>
            )}
          </div>
        </div>
      ))}
    </div>
  );
}

/* ── Default Settings Tab ── */
function DefaultsTab() {
  const existing = getDefaultSettings();
  const [ticker, setTicker] = useState(existing?.ticker || '');
  const [startDate, setStartDate] = useState(existing?.startDate || '');
  const [endDate, setEndDate] = useState(existing?.endDate || '');
  const [startingCash, setStartingCash] = useState(existing?.startingCash || 100000);
  const [commission, setCommission] = useState(existing?.commission ?? 0);
  const [strategy, setStrategy] = useState(existing?.strategy || '');
  const [msg, setMsg] = useState('');

  const handleSave = () => {
    saveDefaultSettings({ ticker, startDate, endDate, startingCash, commission, strategy });
    setMsg('Defaults saved');
    setTimeout(() => setMsg(''), 3000);
  };

  const handleClear = () => {
    clearDefaultSettings();
    setTicker(''); setStartDate(''); setEndDate(''); setStartingCash(100000); setCommission(0.65); setStrategy('');
    setMsg('Defaults cleared');
    setTimeout(() => setMsg(''), 3000);
  };

  // Build strategy options from the same list used in App
  const strategyOptions = [
    { key: '', label: 'None (use app default)' },
    { key: 'long_call', label: 'Long Call' },
    { key: 'long_put', label: 'Long Put' },
    { key: 'short_call', label: 'Short Call' },
    { key: 'short_put', label: 'Short Put' },
    { key: 'short_put_spread', label: 'Short Put Spread' },
    { key: 'short_call_spread', label: 'Short Call Spread' },
    { key: 'debit_call_spread', label: 'Debit Call Spread' },
    { key: 'debit_put_spread', label: 'Debit Put Spread' },
    { key: 'iron_condor', label: 'Iron Condor' },
    { key: 'straddle', label: 'Straddle' },
    { key: 'short_straddle', label: 'Short Straddle' },
    { key: 'long_strangle', label: 'Long Strangle' },
    { key: 'short_strangle', label: 'Short Strangle' },
    { key: 'iron_butterfly', label: 'Iron Butterfly' },
    { key: 'long_call_butterfly', label: 'Long Call Butterfly' },
    { key: 'long_put_butterfly', label: 'Long Put Butterfly' },
    { key: 'calendar_call_spread', label: 'Calendar Call Spread' },
    { key: 'calendar_put_spread', label: 'Calendar Put Spread' },
    { key: 'covered_call', label: 'Covered Call' },
    { key: 'protective_put', label: 'Protective Put' },
  ];

  return (
    <div style={{ display: 'flex', flexDirection: 'column', gap: '1.5rem' }}>
      <p className="text-sm text-gray-400">Set defaults that pre-populate Step 1 when you start a new backtest.</p>

      <div className="card">
        <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: '1rem' }}>
          <div>
            <label className="block text-sm text-gray-300" style={{ marginBottom: '6px' }}>Symbol</label>
            <input className="input-field" value={ticker} onChange={(e) => setTicker(e.target.value.toUpperCase())} placeholder="e.g. AAPL" style={{ width: '100%' }} />
          </div>
          <div>
            <label className="block text-sm text-gray-300" style={{ marginBottom: '6px' }}>Default Strategy</label>
            <select
              className="input-field"
              value={strategy}
              onChange={(e) => setStrategy(e.target.value)}
              style={{ width: '100%' }}
            >
              {strategyOptions.map((s) => (
                <option key={s.key} value={s.key}>{s.label}</option>
              ))}
            </select>
          </div>
          <div>
            <label className="block text-sm text-gray-300" style={{ marginBottom: '6px' }}>Start Date</label>
            <input type="date" className="input-field" value={startDate} onChange={(e) => setStartDate(e.target.value)} style={{ width: '100%' }} />
          </div>
          <div>
            <label className="block text-sm text-gray-300" style={{ marginBottom: '6px' }}>End Date</label>
            <input type="date" className="input-field" value={endDate} onChange={(e) => setEndDate(e.target.value)} style={{ width: '100%' }} />
          </div>
          <div>
            <label className="block text-sm text-gray-300" style={{ marginBottom: '6px' }}>Starting Cash</label>
            <div className="relative">
              <span className="absolute left-3 top-1/2 -translate-y-1/2 text-gray-500 text-sm">$</span>
              <input type="number" className="input-field !pl-7" value={startingCash} onChange={(e) => setStartingCash(Number(e.target.value))} style={{ width: '100%' }} />
            </div>
          </div>
          <div>
            <label className="block text-sm text-gray-300" style={{ marginBottom: '6px' }}>Commission</label>
            <div className="relative">
              <span className="absolute left-3 top-1/2 -translate-y-1/2 text-gray-500 text-sm">$</span>
              <input type="number" className="input-field !pl-7" step="0.05" min="0" value={commission} onChange={(e) => setCommission(Number(e.target.value))} style={{ width: '100%' }} />
            </div>
          </div>
        </div>
      </div>

      <div className="flex items-center gap-3">
        <button
          onClick={handleSave}
          style={{
            padding: '8px 24px', borderRadius: '6px', fontWeight: 600, fontSize: '13px',
            backgroundColor: 'hsl(var(--accent))', color: 'hsl(var(--primary-foreground))',
            border: 'none', cursor: 'pointer',
          }}
        >
          Save defaults
        </button>
        <button
          onClick={handleClear}
          style={{
            padding: '8px 20px', borderRadius: '6px', fontWeight: 600, fontSize: '13px',
            backgroundColor: 'rgba(255,255,255,0.05)', color: '#9ca3af',
            border: 'none', cursor: 'pointer',
          }}
        >
          Clear all
        </button>
        {msg && <span className="text-xs text-emerald-400">{msg}</span>}
      </div>
    </div>
  );
}
