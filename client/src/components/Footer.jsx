import { useSite } from '../context/SiteContext.jsx';

export default function Footer() {
  const { settings, socialLinks } = useSite();
  const name = settings?.site_name || 'Haulo';
  const tagline = settings?.site_tagline || '';
  const year = new Date().getFullYear();

  const validSocials = (socialLinks || []).filter((s) => s.url && s.url.trim());

  return (
    <footer className="border-t border-zinc-800 mt-16">
      <div className="max-w-7xl mx-auto px-4 py-8 flex flex-col items-center gap-4 text-center">
        <div>
          <div className="text-lg font-bold flex items-center justify-center gap-2">
            <span>🛒</span><span>{name}</span>
          </div>
          {tagline && <p className="text-sm text-sub mt-1">{tagline}</p>}
        </div>

        {validSocials.length > 0 && (
          <>
            <div className="w-16 border-t border-zinc-800" />
            <div className="flex items-center gap-4">
              {validSocials.map((s) => (
                <a
                  key={s.id}
                  href={s.url}
                  target="_blank"
                  rel="noopener noreferrer"
                  aria-label={s.label}
                  title={s.label}
                  className="text-sub hover:text-emerald-400 transition-colors"
                >
                  <i className={`ti ${s.icon_name || 'ti-link'}`} style={{ fontSize: 22 }} />
                </a>
              ))}
            </div>
          </>
        )}

        <p className="text-xs text-sub">
          © {year} {name} · Catalogue d'affiliation
        </p>
      </div>
    </footer>
  );
}
