import { useState, useEffect } from 'react';
import { Outlet, Link, NavLink } from 'react-router-dom';
import AnnouncementBar from './AnnouncementBar.jsx';
import Footer from './Footer.jsx';
import { useSite } from '../context/SiteContext.jsx';
import { usePageView } from '../hooks/useTracking.js';

export default function Layout() {
  usePageView();
  const { settings } = useSite();
  const name = settings?.site_name || 'Haulo';
  const logoUrl = settings?.site_logo_url || '';
  const logoSize = parseInt(settings?.site_logo_size, 10) || 32;
  const [logoBroken, setLogoBroken] = useState(false);

  useEffect(() => { setLogoBroken(false); }, [logoUrl]);

  return (
    <div className="min-h-screen flex flex-col">
      <AnnouncementBar />
      <header className="border-b border-zinc-800 sticky top-0 z-30 bg-ink/90 backdrop-blur">
        <div className="max-w-7xl mx-auto px-4 h-14 flex items-center justify-between">
          <Link to="/" className="flex items-center gap-2.5 no-underline">
            {logoUrl && !logoBroken && (
              <img
                src={logoUrl}
                alt={name}
                onError={() => setLogoBroken(true)}
                style={{ height: `${logoSize}px`, width: 'auto', display: 'block' }}
              />
            )}
            <span className="font-medium text-[17px] text-white">{name}</span>
          </Link>
          <nav className="flex items-center gap-1 text-sm">
            <NavLink to="/" end className={navCls}>Catalogue</NavLink>
            <NavLink to="/admin" className={navCls}>Admin</NavLink>
          </nav>
        </div>
      </header>
      <main className="flex-1">
        <Outlet />
      </main>
      <Footer />
    </div>
  );
}

function navCls({ isActive }) {
  return `px-3 py-1.5 rounded-md ${isActive ? 'bg-zinc-800 text-white' : 'text-sub hover:text-white'}`;
}
