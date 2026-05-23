import { Outlet, useLocation, useNavigate } from 'react-router-dom';
import { useAuth } from '../lib/AuthContext';

const RAIL_WIDTH = 60;

// Inline SVG icons keep the rail lightweight — no extra dependency.
const IconBacktest = () => (
  <svg width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
    <polyline points="3 17 9 11 13 15 21 7" />
    <polyline points="14 7 21 7 21 14" />
  </svg>
);
const IconHeatmap = () => (
  <svg width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
    <rect x="3" y="3" width="7" height="7" rx="1" />
    <rect x="14" y="3" width="7" height="7" rx="1" />
    <rect x="3" y="14" width="7" height="7" rx="1" />
    <rect x="14" y="14" width="7" height="7" rx="1" />
  </svg>
);

const NAV_ITEMS = [
  { path: '/', label: 'Backtest', Icon: IconBacktest, match: (p: string) => p === '/' || p === '' },
  { path: '/heatmap', label: 'Heatmap', Icon: IconHeatmap, match: (p: string) => p.startsWith('/heatmap') },
];

export default function Shell() {
  const nav = useNavigate();
  const loc = useLocation();
  const { user } = useAuth();
  const accountActive = loc.pathname.startsWith('/account');

  return (
    <div style={{ minHeight: '100vh' }}>
      {/* Fixed left rail */}
      <aside
        style={{
          position: 'fixed', left: 0, top: 0, bottom: 0, width: RAIL_WIDTH,
          backgroundColor: 'hsl(220 15% 6%)',
          borderRight: '1px solid rgba(255,255,255,0.06)',
          display: 'flex', flexDirection: 'column', alignItems: 'center',
          padding: '12px 0', zIndex: 50,
        }}
      >
        {/* Logo */}
        <button
          onClick={() => nav('/')}
          style={{ background: 'none', border: 'none', padding: 0, marginBottom: '12px', cursor: 'pointer' }}
          title="ThesisLab"
        >
          <img src="/XL logo transparent.png" alt="" style={{ width: 30, height: 30 }} />
        </button>
        <div style={{ width: 28, height: 1, backgroundColor: 'rgba(255,255,255,0.06)', marginBottom: 8 }} />

        {/* Primary tools */}
        {NAV_ITEMS.map(({ path, label, Icon, match }) => {
          const active = match(loc.pathname);
          return (
            <button
              key={path}
              onClick={() => nav(path)}
              title={label}
              style={{
                width: 40, height: 40, marginBottom: 6, borderRadius: 8,
                display: 'flex', alignItems: 'center', justifyContent: 'center',
                background: active ? 'hsl(var(--accent) / 0.15)' : 'transparent',
                border: active ? '1px solid hsl(var(--accent) / 0.35)' : '1px solid transparent',
                color: active ? 'hsl(var(--accent))' : '#9ca3af',
                cursor: 'pointer',
                transition: 'background 0.15s, color 0.15s, border-color 0.15s',
              }}
              onMouseEnter={(e) => { if (!active) e.currentTarget.style.color = '#e5e7eb'; }}
              onMouseLeave={(e) => { if (!active) e.currentTarget.style.color = '#9ca3af'; }}
            >
              <Icon />
            </button>
          );
        })}

        {/* Spacer pushes Account to bottom */}
        <div style={{ flex: 1 }} />

        {/* Account avatar */}
        {user && (
          <button
            onClick={() => nav('/account')}
            title={user.email || 'Account'}
            style={{
              width: 36, height: 36, borderRadius: '50%',
              display: 'flex', alignItems: 'center', justifyContent: 'center',
              fontSize: 13, fontWeight: 700,
              background: accountActive ? 'hsl(var(--accent) / 0.15)' : 'rgba(255,255,255,0.06)',
              border: accountActive ? '1.5px solid hsl(var(--accent))' : '1.5px solid rgba(255,255,255,0.12)',
              color: accountActive ? 'hsl(var(--accent))' : '#d1d5db',
              cursor: 'pointer', overflow: 'hidden', padding: 0,
            }}
          >
            {user.photoURL
              ? <img src={user.photoURL} alt="" style={{ width: '100%', height: '100%', objectFit: 'cover' }} />
              : (user.email?.[0] || 'U').toUpperCase()}
          </button>
        )}
      </aside>

      {/* Page content — shifted right by the rail width */}
      <div style={{ marginLeft: RAIL_WIDTH }}>
        <Outlet />
      </div>
    </div>
  );
}
