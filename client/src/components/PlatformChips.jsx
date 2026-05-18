export default function PlatformChips({ platforms, variant = 'chip' }) {
  if (!platforms?.length) return null;

  if (variant === 'grid') {
    return (
      <div className="grid grid-cols-2 sm:grid-cols-3 md:grid-cols-4 gap-2">
        {platforms.map((p) => (
          <a
            key={p.id}
            href={p.register_url}
            target="_blank"
            rel="noopener noreferrer"
            className="flex items-center gap-2 rounded-lg px-3 py-2 border border-zinc-800 bg-zinc-900 hover:bg-zinc-800 transition-colors"
            style={{ borderLeftColor: p.color_hex, borderLeftWidth: 3 }}
          >
            <span className="w-2 h-2 rounded-full" style={{ background: p.color_hex }} />
            <div className="flex-1 min-w-0">
              <div className="text-sm font-medium truncate">{p.name}</div>
              {p.tagline && <div className="text-xs text-sub truncate">{p.tagline}</div>}
            </div>
            <span className="text-xs text-sub">↗</span>
          </a>
        ))}
      </div>
    );
  }

  return (
    <div className="flex gap-2 overflow-x-auto py-1 -mx-1 px-1 scrollbar-thin">
      {platforms.map((p) => (
        <a
          key={p.id}
          href={p.register_url}
          target="_blank"
          rel="noopener noreferrer"
          title={p.tagline || ''}
          className="shrink-0 flex items-center gap-1.5 px-3 py-1.5 rounded-full border border-zinc-800 bg-zinc-900 hover:bg-zinc-800 text-sm transition-colors"
          style={{ borderColor: p.color_hex + '55' }}
        >
          <span className="w-2 h-2 rounded-full" style={{ background: p.color_hex }} />
          <span>{p.name}</span>
        </a>
      ))}
    </div>
  );
}
