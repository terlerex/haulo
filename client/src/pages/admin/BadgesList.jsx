import { useEffect, useState } from 'react';
import { api, slugify } from '../../api.js';
import { useToast } from '../../components/Toast.jsx';

function BadgePreview({ label, color_bg, color_text }) {
  return (
    <span
      className="px-2 py-0.5 rounded-md text-xs font-bold uppercase tracking-wider inline-block"
      style={{ background: color_bg, color: color_text }}
    >
      {label || 'EXEMPLE'}
    </span>
  );
}

export default function BadgesList() {
  const [items, setItems] = useState([]);
  const [loading, setLoading] = useState(true);
  const toast = useToast();

  const [label, setLabel] = useState('');
  const [slug, setSlug] = useState('');
  const [slugTouched, setSlugTouched] = useState(false);
  const [colorBg, setColorBg] = useState('#FCEBEB');
  const [colorText, setColorText] = useState('#A32D2D');
  const [saving, setSaving] = useState(false);

  const load = () => {
    setLoading(true);
    api.listBadges().then(setItems).finally(() => setLoading(false));
  };
  useEffect(() => { load(); }, []);

  const onLabelChange = (v) => {
    setLabel(v);
    if (!slugTouched) setSlug(slugify(v));
  };

  const submit = async (e) => {
    e.preventDefault();
    if (!label.trim() || !slug.trim()) return toast.error('Label et slug requis');
    setSaving(true);
    try {
      await api.createBadge({ label, slug, color_bg: colorBg, color_text: colorText });
      toast.success('Badge ajouté');
      setLabel(''); setSlug(''); setSlugTouched(false);
      load();
    } catch (err) {
      toast.error(err.message);
    } finally {
      setSaving(false);
    }
  };

  const remove = async (b) => {
    if (!confirm(`Supprimer le badge "${b.label}" ?`)) return;
    try {
      await api.deleteBadge(b.id);
      toast.success('Badge supprimé');
      load();
    } catch (err) { toast.error(err.message); }
  };

  return (
    <div className="max-w-5xl mx-auto px-4 py-8">
      <h1 className="text-2xl font-bold mb-1">Badges</h1>
      <p className="text-sub text-sm mb-6">Étiquettes affichées sur les fiches produits.</p>

      <div className="rounded-xl border border-zinc-800 overflow-hidden bg-zinc-900 mb-8">
        <table className="w-full text-sm">
          <thead className="bg-zinc-950 text-sub text-xs uppercase">
            <tr>
              <th className="text-left p-3">Aperçu</th>
              <th className="text-left p-3">Label</th>
              <th className="text-left p-3 hidden sm:table-cell">Slug</th>
              <th className="text-left p-3 hidden md:table-cell">Couleurs</th>
              <th className="text-right p-3">Actions</th>
            </tr>
          </thead>
          <tbody>
            {loading && <tr><td colSpan={5} className="p-6 text-center text-sub">Chargement…</td></tr>}
            {!loading && items.length === 0 && <tr><td colSpan={5} className="p-6 text-center text-sub">Aucun badge.</td></tr>}
            {items.map((b) => (
              <tr key={b.id} className="border-t border-zinc-800">
                <td className="p-3"><BadgePreview {...b} /></td>
                <td className="p-3 font-medium">{b.label}</td>
                <td className="p-3 hidden sm:table-cell text-sub">{b.slug}</td>
                <td className="p-3 hidden md:table-cell text-xs">
                  <span className="inline-flex items-center gap-1"><i className="inline-block w-3 h-3 rounded" style={{background: b.color_bg}} /> {b.color_bg}</span>
                  <span className="ml-2 inline-flex items-center gap-1"><i className="inline-block w-3 h-3 rounded" style={{background: b.color_text}} /> {b.color_text}</span>
                </td>
                <td className="p-3 text-right">
                  <button
                    onClick={() => remove(b)}
                    className="px-2 py-1 rounded-md bg-red-900/40 hover:bg-red-800/60 text-xs text-red-200"
                  >Supprimer</button>
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>

      <h2 className="text-lg font-semibold mb-3">Ajouter un badge</h2>
      <form onSubmit={submit} className="rounded-xl border border-zinc-800 bg-zinc-900 p-4 grid sm:grid-cols-2 gap-3">
        <label className="block">
          <span className="block text-xs uppercase tracking-wider text-sub mb-1">Label</span>
          <input
            value={label}
            onChange={(e) => onLabelChange(e.target.value)}
            placeholder="SOLDES"
            className="w-full bg-ink border border-zinc-800 rounded-md px-3 py-2 text-sm"
          />
        </label>
        <label className="block">
          <span className="block text-xs uppercase tracking-wider text-sub mb-1">Slug (auto)</span>
          <input
            value={slug}
            onChange={(e) => { setSlug(slugify(e.target.value)); setSlugTouched(true); }}
            placeholder="soldes"
            className="w-full bg-ink border border-zinc-800 rounded-md px-3 py-2 text-sm"
          />
        </label>
        <label className="block">
          <span className="block text-xs uppercase tracking-wider text-sub mb-1">Couleur fond</span>
          <div className="flex gap-2 items-center">
            <input type="color" value={colorBg} onChange={(e) => setColorBg(e.target.value)} className="w-12 h-10 rounded border border-zinc-800 bg-ink" />
            <input value={colorBg} onChange={(e) => setColorBg(e.target.value)} className="flex-1 bg-ink border border-zinc-800 rounded-md px-3 py-2 text-sm" />
          </div>
        </label>
        <label className="block">
          <span className="block text-xs uppercase tracking-wider text-sub mb-1">Couleur texte</span>
          <div className="flex gap-2 items-center">
            <input type="color" value={colorText} onChange={(e) => setColorText(e.target.value)} className="w-12 h-10 rounded border border-zinc-800 bg-ink" />
            <input value={colorText} onChange={(e) => setColorText(e.target.value)} className="flex-1 bg-ink border border-zinc-800 rounded-md px-3 py-2 text-sm" />
          </div>
        </label>
        <div className="sm:col-span-2 flex items-center justify-between pt-2">
          <div className="flex items-center gap-2">
            <span className="text-sub text-sm">Aperçu :</span>
            <BadgePreview label={label || 'EXEMPLE'} color_bg={colorBg} color_text={colorText} />
          </div>
          <button
            type="submit"
            disabled={saving}
            className="px-4 py-2 rounded-lg bg-emerald-600 hover:bg-emerald-500 font-semibold disabled:opacity-50"
          >
            {saving ? 'Ajout…' : 'Ajouter'}
          </button>
        </div>
      </form>
    </div>
  );
}
