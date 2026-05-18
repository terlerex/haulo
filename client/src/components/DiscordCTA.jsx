import { useSite } from '../context/SiteContext.jsx';

export default function DiscordCTA() {
  const { settings, socialLinks } = useSite();
  if (settings.discord_cta_enabled !== 'true') return null;

  const discord = (socialLinks || []).find((s) => s.platform === 'discord' && s.is_active && s.url);
  const configured = !!discord;

  return (
    <section className="mb-10">
      <div className="rounded-2xl border border-zinc-800 bg-zinc-900 p-6 sm:p-8 text-center flex flex-col items-center gap-3">
        <i className="ti ti-brand-discord text-indigo-400" style={{ fontSize: 32 }} />
        <h2 className="text-xl sm:text-2xl font-bold">{settings.discord_cta_title}</h2>
        <p className="text-sub max-w-xl">{settings.discord_cta_desc}</p>
        {configured ? (
          <a
            href={discord.url}
            target="_blank"
            rel="noopener noreferrer"
            className="mt-2 inline-flex items-center gap-2 px-5 py-2.5 rounded-lg bg-indigo-500 hover:bg-indigo-400 text-white font-semibold"
          >
            <i className="ti ti-brand-discord" />
            {settings.discord_cta_label}
          </a>
        ) : (
          <button
            disabled
            className="mt-2 px-5 py-2.5 rounded-lg bg-zinc-800 text-sub font-semibold cursor-not-allowed"
          >
            Lien non configuré
          </button>
        )}
      </div>
    </section>
  );
}
