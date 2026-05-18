import { Outlet, NavLink, Link, useNavigate } from 'react-router-dom';
import { useAuth } from '../../context/AuthContext.jsx';
import { useSite } from '../../context/SiteContext.jsx';

const NAV = [
  { to: '/admin', label: 'Dashboard', icon: '📊', end: true },
  { to: '/admin/analytics', label: 'Analytics', icon: '📈' },
  { to: '/admin/products', label: 'Produits', icon: '📦' },
  { to: '/admin/badges', label: 'Badges', icon: '🏷️' },
  { to: '/admin/categories', label: 'Catégories', icon: '📂' },
  { to: '/admin/platforms', label: 'Agents', icon: '🔗' },
  { to: '/admin/social-links', label: 'Réseaux', icon: '🌐' },
  { to: '/admin/settings', label: 'Paramètres', icon: '⚙️' },
  { to: '/admin/users', label: 'Utilisateurs', icon: '👥' },
];

export default function AdminLayout() {
  const { user, logout } = useAuth();
  const { settings } = useSite();
  const nav = useNavigate();

  const handleLogout = async () => {
    await logout();
    nav('/admin/login', { replace: true });
  };

  return (
    <div className="min-h-screen flex flex-col bg-ink">
      <header className="sticky top-0 z-30 bg-ink/95 backdrop-blur border-b border-zinc-800">
        <div
          className="max-w-7xl mx-auto"
          style={{
            display: 'flex',
            alignItems: 'center',
            justifyContent: 'space-between',
            padding: '0 1.5rem',
            height: 56,
            gap: 16,
            overflow: 'hidden',
          }}
        >
          {/* GAUCHE — logo + nom site */}
          <Link
            to="/admin"
            className="no-underline text-white"
            style={{ display: 'flex', alignItems: 'center', gap: 10, flexShrink: 0 }}
          >
            <span style={{ fontSize: 20 }}>🛠️</span>
            <span className="font-semibold whitespace-nowrap" style={{ fontSize: 15 }}>
              {settings?.site_name || 'Admin'}
            </span>
          </Link>

          {/* CENTRE — navigation (desktop uniquement, scrollable si déborde) */}
          <nav
            className="hidden xl:flex scrollbar-thin"
            style={{
              gap: 4,
              flex: 1,
              justifyContent: 'flex-start',
              overflowX: 'auto',
              overflowY: 'hidden',
              minWidth: 0,
              padding: '0 8px',
            }}
          >
            {NAV.map((n) => (
              <NavLink key={n.to} to={n.to} end={n.end} className={navCls}>
                <span className="mr-1">{n.icon}</span>{n.label}
              </NavLink>
            ))}
          </nav>

          {/* DROITE — user + logout */}
          <div
            style={{
              display: 'flex',
              alignItems: 'center',
              gap: 12,
              flexShrink: 0,
              whiteSpace: 'nowrap',
            }}
          >
            {user && (
              <span className="hidden md:inline text-sub" style={{ fontSize: 13 }}>
                Connecté : <strong className="text-white" style={{ fontWeight: 500 }}>{user.username}</strong>
              </span>
            )}
            <Link
              to="/"
              className="hidden md:inline text-sub hover:text-white"
              style={{ fontSize: 13 }}
            >
              ↗ Site
            </Link>
            <button
              onClick={handleLogout}
              className="rounded-md bg-zinc-800 hover:bg-zinc-700"
              style={{ fontSize: 13, padding: '6px 12px' }}
            >
              Déconnexion
            </button>
          </div>
        </div>

        {/* Mobile / tablet nav — barre dédiée, défilable horizontalement */}
        <nav
          className="xl:hidden border-t border-zinc-800 flex gap-1 overflow-x-auto"
          style={{ padding: '8px 12px', WebkitOverflowScrolling: 'touch' }}
        >
          {NAV.map((n) => (
            <NavLink key={n.to} to={n.to} end={n.end} className={navCls}>
              <span className="mr-1">{n.icon}</span>{n.label}
            </NavLink>
          ))}
        </nav>
      </header>

      <main className="flex-1">
        <Outlet />
      </main>
    </div>
  );
}

function navCls({ isActive }) {
  return `shrink-0 inline-flex items-center px-3.5 py-2 rounded-md text-sm whitespace-nowrap leading-none ${
    isActive ? 'bg-zinc-800 text-white' : 'text-sub hover:text-white'
  }`;
}
