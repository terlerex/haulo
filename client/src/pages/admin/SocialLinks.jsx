import { useEffect, useState } from 'react';
import { api } from '../../api.js';
import { useToast } from '../../components/Toast.jsx';
import { useSite } from '../../context/SiteContext.jsx';

const PRESETS = [
  { platform: 'discord',   label: 'Discord',   icon: 'ti-brand-discord' },
  { platform: 'instagram', label: 'Instagram', icon: 'ti-brand-instagram' },
  { platform: 'tiktok',    label: 'TikTok',    icon: 'ti-brand-tiktok' },
  { platform: 'telegram',  label: 'Telegram',  icon: 'ti-brand-telegram' },
  { platform: 'youtube',   label: 'YouTube',   icon: 'ti-brand-youtube' },
  { platform: 'twitter',   label: 'Twitter/X', icon: 'ti-brand-x' },
  { platform: 'facebook',  label: 'Facebook',  icon: 'ti-brand-facebook' },
  { platform: 'reddit',    label: 'Reddit',    icon: 'ti-brand-reddit' },
  { platform: 'twitch',    label: 'Twitch',    icon: 'ti-brand-twitch' },
  { platform: 'snapchat',  label: 'Snapchat',  icon: 'ti-brand-snapchat' },
];

export default function SocialLinks() {
  const [items, setItems] = useState([]);
  const [loading, setLoading] = useState(true);
  const toast = useToast();
  const { reload } = useSite();

  const load = () => {
    setLoading(true);
    api.listSocialLinksAdmin().then(setItems).finally(() => setLoading(false));
  };
  useEffect(() => { load(); }, []);

  const after = async () => { await reload(); load(); };

  const persist = async (id, patch) => {
    try { await api.updateSocialLink(id, patch); toast.success('Modifié'); after(); }
    catch (err) { toast.error(err.message); }
  };

  const remove = async (s) => {
    if (!confirm(`Supprimer le lien "${s.label}" ?`)) return;
    try { await api.deleteSocialLink(s.id); toast.success('Supprimé'); after(); }
    catch (err) { toast.error(err.message); }
  };

  const move = async (idx, dir) => {
    const target = idx + dir;
    if (target < 0 || target >= items.length) return;
    const a = items[idx], b = items[target];
    await api.updateSocialLink(a.id, { sort_order: b.sort_order });
    await api.updateSocialLink(b.id, { sort_order: a.sort_order });
    after();
  };

  // Ajout
  const [presetKey, setPresetKey] = useState('discord');
  const [customPlatform, setCustomPlatform] = useState('');
  const [customIcon, setCustomIcon] = useState('');
  const [label, setLabel] = useState('Discord');
  const [url, setUrl] = useState('');
  const [saving, setSaving] = useState(false);

  const isCustom = presetKey === 'other';
  const chosenPreset = PRESETS.find((p) => p.platform === presetKey);
  const platform = isCustom ? customPlatform.toLowerCase().trim() : chosenPreset?.platform;
  const icon = isCustom ? customIcon.trim() : chosenPreset?.icon;

  const submit = async (e) => {
    e.preventDefault();
    if (!platform || !label.trim()) return toast.error('Plateforme et label requis');
    setSaving(true);
    try {
      const sort_order = items.length;
      await api.createSocialLink({ platform, label, url, icon, sort_order, is_active: 0 });
      toast.success('Réseau ajouté');
      setLabel(''); setUrl(''); setCustomPlatform(''); setCustomIcon('');
      after();
    } catch (err) { toast.error(err.message); }
    finally { setSaving(false); }
  };

  return (
    <div className="max-w-5xl mx-auto px-4 py-8">
      <h1 className="text-2xl font-bold mb-1">Réseaux sociaux</h1>
      <p className="text-sub text-sm mb-6">
        Liens affichés dans le footer public. Active un réseau pour qu'il apparaisse.
      </p>

      <div className="rounded-xl border border-zinc-800 overflow-hidden bg-zinc-900 mb-8">
        <table className="w-full text-sm">
          <thead className="bg-zinc-950 text-sub text-xs uppercase">
            <tr>
              <th className="text-center p-3 w-12">Ord.</th>
              <th className="text-left p-3 w-14">Icône</th>
              <th className="text-left p-3">Plateforme</th>
              <th className="text-left p-3">Label</th>
              <th className="text-left p-3">URL</th>
              <th className="text-center p-3">Actif</th>
              <th className="text-right p-3">Actions</th>
            </tr>
          </thead>
          <tbody>
            {loading && <tr><td colSpan={7} className="p-6 text-center text-sub">Chargement…</td></tr>}
            {!loading && items.length === 0 && <tr><td colSpan={7} className="p-6 text-center text-sub">Aucun réseau.</td></tr>}
            {items.map((s, idx) => (
              <Row
                key={s.id}
                s={s}
                idx={idx}
                onMove={move}
                onPersist={persist}
                onRemove={remove}
                isLast={idx === items.length - 1}
              />
            ))}
          </tbody>
        </table>
      </div>

      <h2 className="text-lg font-semibold mb-3">Ajouter un réseau</h2>
      <form onSubmit={submit} className="rounded-xl border border-zinc-800 bg-zinc-900 p-4 grid sm:grid-cols-2 gap-3">
        <label>
          <span className="block text-xs uppercase tracking-wider text-sub mb-1">Réseau</span>
          <select
            value={presetKey}
            onChange={(e) => {
              setPresetKey(e.target.value);
              const p = PRESETS.find((x) => x.platform === e.target.value);
              if (p) setLabel(p.label);
            }}
            className="w-full bg-ink border border-zinc-800 rounded-md px-3 py-2 text-sm"
          >
            {PRESETS.map((p) => <option key={p.platform} value={p.platform}>{p.label}</option>)}
            <option value="other">Autre…</option>
          </select>
        </label>

        {isCustom ? (
          <>
            <label>
              <span className="block text-xs uppercase tracking-wider text-sub mb-1">Slug plateforme</span>
              <input value={customPlatform} onChange={(e) => setCustomPlatform(e.target.value)} placeholder="mastodon" className="w-full bg-ink border border-zinc-800 rounded-md px-3 py-2 text-sm" />
            </label>
            <label className="sm:col-span-2">
              <span className="block text-xs uppercase tracking-wider text-sub mb-1">Nom d'icône Tabler</span>
              <input value={customIcon} onChange={(e) => setCustomIcon(e.target.value)} placeholder="ti-brand-mastodon" className="w-full bg-ink border border-zinc-800 rounded-md px-3 py-2 text-sm" />
              <span className="text-xs text-sub mt-1 block">
                Trouve les icônes sur <a href="https://tabler.io/icons" target="_blank" rel="noreferrer" className="underline">tabler.io/icons</a> (préfixe <code>ti-</code>)
              </span>
            </label>
          </>
        ) : null}

        <label>
          <span className="block text-xs uppercase tracking-wider text-sub mb-1">Label</span>
          <input value={label} onChange={(e) => setLabel(e.target.value)} className="w-full bg-ink border border-zinc-800 rounded-md px-3 py-2 text-sm" />
        </label>
        <label>
          <span className="block text-xs uppercase tracking-wider text-sub mb-1">URL</span>
          <input type="url" value={url} onChange={(e) => setUrl(e.target.value)} placeholder="https://…" className="w-full bg-ink border border-zinc-800 rounded-md px-3 py-2 text-sm" />
        </label>

        <div className="sm:col-span-2 flex items-center justify-between">
          <div className="flex items-center gap-2 text-sub text-sm">
            <span>Aperçu icône :</span>
            <i className={`ti ${icon || 'ti-link'}`} style={{ fontSize: 22 }} />
            <code className="text-xs">{icon || '—'}</code>
          </div>
          <button type="submit" disabled={saving} className="px-4 py-2 rounded-lg bg-emerald-600 hover:bg-emerald-500 font-semibold disabled:opacity-50">
            {saving ? 'Ajout…' : 'Ajouter'}
          </button>
        </div>
      </form>
    </div>
  );
}

function Row({ s, idx, onMove, onPersist, onRemove, isLast }) {
  const [url, setUrl] = useState(s.url || '');
  const [label, setLabel] = useState(s.label);
  return (
    <tr className="border-t border-zinc-800">
      <td className="p-2 text-center">
        <div className="inline-flex flex-col gap-0.5">
          <button onClick={() => onMove(idx, -1)} disabled={idx === 0} className="px-1 rounded bg-zinc-800 hover:bg-zinc-700 disabled:opacity-30 text-xs">↑</button>
          <button onClick={() => onMove(idx, +1)} disabled={isLast} className="px-1 rounded bg-zinc-800 hover:bg-zinc-700 disabled:opacity-30 text-xs">↓</button>
        </div>
      </td>
      <td className="p-3"><i className={`ti ${s.icon_name || 'ti-link'}`} style={{ fontSize: 22 }} /></td>
      <td className="p-3 text-sub">{s.platform}</td>
      <td className="p-2">
        <div className="flex gap-1">
          <input value={label} onChange={(e) => setLabel(e.target.value)} className="flex-1 bg-ink border border-zinc-800 rounded-md px-2 py-1 text-sm" />
          {label !== s.label && (
            <button onClick={() => onPersist(s.id, { label })} className="px-2 rounded bg-emerald-600 hover:bg-emerald-500 text-xs">OK</button>
          )}
        </div>
      </td>
      <td className="p-2">
        <div className="flex gap-1">
          <input value={url} onChange={(e) => setUrl(e.target.value)} placeholder="https://…" className="flex-1 bg-ink border border-zinc-800 rounded-md px-2 py-1 text-sm" />
          {url !== (s.url || '') && (
            <button onClick={() => onPersist(s.id, { url })} className="px-2 rounded bg-emerald-600 hover:bg-emerald-500 text-xs">OK</button>
          )}
        </div>
      </td>
      <td className="p-3 text-center">
        <button
          type="button"
          onClick={() => onPersist(s.id, { is_active: s.is_active ? 0 : 1 })}
          aria-pressed={!!s.is_active}
          className={`relative inline-block w-10 h-5 rounded-full transition-colors ${s.is_active ? 'bg-emerald-500' : 'bg-zinc-700'}`}
        >
          <span
            className="absolute top-0.5 w-4 h-4 bg-white rounded-full transition-all"
            style={{ left: s.is_active ? '22px' : '2px' }}
          />
        </button>
      </td>
      <td className="p-3 text-right">
        <button onClick={() => onRemove(s)} className="px-2 py-1 rounded-md bg-red-900/40 hover:bg-red-800/60 text-xs text-red-200">Suppr</button>
      </td>
    </tr>
  );
}
