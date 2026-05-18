import { useEffect, useState } from 'react';
import { api } from '../../api.js';
import { useToast } from '../../components/Toast.jsx';

const EMPTY = {
  name: '',
  tagline: '',
  color_hex: '#378ADD',
  register_url: '',
  affiliate_url: '',
  is_active: 1,
  sort_order: 1,
};

export default function PlatformsList() {
  const [items, setItems] = useState([]);
  const [loading, setLoading] = useState(true);
  const [editing, setEditing] = useState(null); // null = closed, {} = new, {id,...} = edit
  const [serverError, setServerError] = useState(null);
  const toast = useToast();

  const load = async () => {
    setLoading(true);
    try { setItems(await api.listPlatformsAdmin()); }
    finally { setLoading(false); }
  };

  useEffect(() => { load(); }, []);

  // efface le serverError au bout de 4s
  useEffect(() => {
    if (!serverError) return;
    const id = setTimeout(() => setServerError(null), 4000);
    return () => clearTimeout(id);
  }, [serverError]);

  const total = items.length;
  const actives = items.filter((p) => p.is_active).length;

  const toggleActive = async (p) => {
    try {
      await api.updatePlatform(p.id, { is_active: !p.is_active });
      load();
    } catch (err) { toast.error(err.message); }
  };

  const move = async (idx, dir) => {
    const target = idx + dir;
    if (target < 0 || target >= items.length) return;
    const a = items[idx], b = items[target];
    try {
      await api.updatePlatform(a.id, { sort_order: b.sort_order });
      await api.updatePlatform(b.id, { sort_order: a.sort_order });
      load();
    } catch (err) { toast.error(err.message); }
  };

  const remove = async (p) => {
    if (!confirm(`Supprimer "${p.name}" ?`)) return;
    try {
      await api.deletePlatform(p.id);
      toast.success('Agent supprimé');
      load();
    } catch (err) {
      setServerError(err.message);
    }
  };

  return (
    <div className="max-w-6xl mx-auto px-4 py-8">
      <header className="flex items-start justify-between gap-4 mb-1 flex-wrap">
        <div>
          <h1 className="text-2xl font-bold">Agents partenaires</h1>
          <p className="text-sub text-sm mt-0.5">
            {total} agent{total > 1 ? 's' : ''} configuré{total > 1 ? 's' : ''} · {actives} actif{actives > 1 ? 's' : ''}
          </p>
        </div>
        <button
          onClick={() => setEditing({ ...EMPTY, sort_order: (items.at(-1)?.sort_order || 0) + 1 })}
          className="px-4 py-2 rounded-lg bg-emerald-600 hover:bg-emerald-500 text-white font-semibold"
        >
          + Ajouter un agent
        </button>
      </header>

      {serverError && (
        <div className="my-4 px-4 py-3 rounded-lg bg-red-950/50 border border-red-900/60 text-red-300 text-sm">
          {serverError}
        </div>
      )}

      {loading ? (
        <div className="text-sub mt-6">Chargement…</div>
      ) : items.length === 0 ? (
        <div className="text-center py-16 rounded-xl border border-zinc-800 bg-zinc-900 mt-6">
          <div className="text-5xl mb-3">🌐</div>
          <p className="text-zinc-300 font-medium">Aucun agent configuré</p>
          <p className="text-sub text-sm mt-1">Ajoutez votre premier partenaire affilié.</p>
          <button
            onClick={() => setEditing({ ...EMPTY, sort_order: 1 })}
            className="mt-4 px-4 py-2 rounded-lg bg-emerald-600 hover:bg-emerald-500 font-semibold"
          >
            + Ajouter un agent
          </button>
        </div>
      ) : (
        <div className="rounded-xl border border-zinc-800 overflow-hidden bg-zinc-900 mt-4">
          <table className="w-full text-sm">
            <thead className="bg-zinc-950 text-sub text-xs uppercase">
              <tr>
                <th className="text-center p-3 w-12">Ord.</th>
                <th className="text-left p-3 w-8"></th>
                <th className="text-left p-3">Nom</th>
                <th className="text-left p-3 hidden md:table-cell">Tagline</th>
                <th className="text-left p-3 hidden lg:table-cell">URL d'inscription</th>
                <th className="text-center p-3">Actif</th>
                <th className="text-right p-3">Actions</th>
              </tr>
            </thead>
            <tbody>
              {items.map((p, idx) => (
                <tr key={p.id} className="border-t border-zinc-800">
                  <td className="p-2 text-center">
                    <div className="inline-flex flex-col gap-0.5">
                      <button onClick={() => move(idx, -1)} disabled={idx === 0} className="px-1 rounded bg-zinc-800 hover:bg-zinc-700 disabled:opacity-30 text-xs">↑</button>
                      <button onClick={() => move(idx, +1)} disabled={idx === items.length - 1} className="px-1 rounded bg-zinc-800 hover:bg-zinc-700 disabled:opacity-30 text-xs">↓</button>
                    </div>
                  </td>
                  <td className="p-3">
                    <span
                      className="inline-block w-3.5 h-3.5 rounded-full"
                      style={{ background: p.color_hex }}
                      title={p.color_hex}
                    />
                  </td>
                  <td className="p-3 font-medium">
                    {p.name}
                    <span className="text-xs text-sub ml-2">/{p.slug}</span>
                  </td>
                  <td className="p-3 hidden md:table-cell text-sub truncate max-w-[180px]">{p.tagline || '—'}</td>
                  <td className="p-3 hidden lg:table-cell text-sub truncate max-w-[260px]">
                    {p.register_url ? (
                      <a href={p.register_url} target="_blank" rel="noopener noreferrer" className="hover:text-white">
                        {truncate(p.register_url, 35)} ↗
                      </a>
                    ) : '—'}
                  </td>
                  <td className="p-3 text-center">
                    <Toggle checked={!!p.is_active} onChange={() => toggleActive(p)} />
                  </td>
                  <td className="p-3 text-right">
                    <div className="inline-flex gap-1">
                      <button onClick={() => setEditing(p)} className="px-2 py-1 rounded-md bg-zinc-800 hover:bg-zinc-700 text-xs">✏️ Éditer</button>
                      <button onClick={() => remove(p)} className="px-2 py-1 rounded-md bg-red-900/40 hover:bg-red-800/60 text-xs text-red-200">🗑️</button>
                    </div>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}

      {editing && (
        <PlatformModal
          initial={editing}
          onClose={() => setEditing(null)}
          onSaved={() => { setEditing(null); load(); }}
        />
      )}
    </div>
  );
}

function truncate(s, n) {
  if (!s) return '';
  return s.length > n ? s.slice(0, n) + '…' : s;
}

function Toggle({ checked, onChange }) {
  return (
    <button
      type="button"
      onClick={onChange}
      aria-pressed={!!checked}
      className={`relative inline-block w-10 h-5 rounded-full transition-colors ${checked ? 'bg-emerald-500' : 'bg-zinc-700'}`}
    >
      <span
        className="absolute top-0.5 w-4 h-4 bg-white rounded-full transition-all"
        style={{ left: checked ? '22px' : '2px' }}
      />
    </button>
  );
}

function PlatformModal({ initial, onClose, onSaved }) {
  const toast = useToast();
  const isEdit = !!initial?.id;
  const [form, setForm] = useState({
    name: initial.name || '',
    tagline: initial.tagline || '',
    color_hex: initial.color_hex || '#378ADD',
    register_url: initial.register_url || '',
    is_active: initial.is_active ? 1 : 0,
    sort_order: initial.sort_order ?? 1,
  });
  const [saving, setSaving] = useState(false);
  const [err, setErr] = useState(null);

  const update = (k, v) => setForm((f) => ({ ...f, [k]: v }));

  const submit = async (e) => {
    e.preventDefault();
    setErr(null);
    if (!form.name.trim()) return setErr('Nom requis');
    setSaving(true);
    try {
      const payload = {
        ...form,
        sort_order: Number(form.sort_order) || 1,
      };
      if (isEdit) await api.updatePlatform(initial.id, payload);
      else        await api.createPlatform(payload);
      toast.success(isEdit ? 'Agent modifié' : 'Agent ajouté');
      onSaved();
    } catch (e) {
      setErr(e.message);
    } finally {
      setSaving(false);
    }
  };

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center px-4 py-6 bg-black/60 backdrop-blur-sm" onClick={onClose}>
      <form
        onSubmit={submit}
        onClick={(e) => e.stopPropagation()}
        className="w-full max-w-xl bg-zinc-900 rounded-2xl border border-zinc-800 max-h-[90vh] overflow-auto"
      >
        <header className="px-5 py-4 border-b border-zinc-800 flex items-center justify-between">
          <h2 className="font-semibold">{isEdit ? 'Modifier l\'agent' : 'Nouvel agent'}</h2>
          <button type="button" onClick={onClose} className="text-sub hover:text-white text-xl leading-none">×</button>
        </header>

        <div className="p-5 space-y-3">
          <Field label="Nom de l'agent *">
            <input required value={form.name} onChange={(e) => update('name', e.target.value)} className="input" autoFocus />
          </Field>

          <Field label="Tagline">
            <input value={form.tagline} onChange={(e) => update('tagline', e.target.value)} className="input" placeholder="ex: QC gratuit" />
          </Field>

          <Field label="Couleur">
            <div className="flex items-center gap-2">
              <input type="color" value={form.color_hex} onChange={(e) => update('color_hex', e.target.value)} className="w-12 h-10 rounded border border-zinc-800 bg-ink" />
              <input value={form.color_hex} onChange={(e) => update('color_hex', e.target.value)} className="input flex-1" />
              <span className="w-7 h-7 rounded-full border border-zinc-700" style={{ background: form.color_hex }} />
            </div>
          </Field>

          <Field label="URL d'inscription (avec ton code affilié)">
            <input type="url" value={form.register_url} onChange={(e) => update('register_url', e.target.value)} className="input" placeholder="https://…" />
          </Field>

          <div className="grid grid-cols-2 gap-3">
            <Field label="Ordre d'affichage">
              <input type="number" min="1" value={form.sort_order} onChange={(e) => update('sort_order', e.target.value)} className="input" />
            </Field>
            <Field label="Actif">
              <label className="flex items-center gap-3 mt-2 cursor-pointer">
                <Toggle checked={!!form.is_active} onChange={() => update('is_active', form.is_active ? 0 : 1)} />
                <span className="text-sm text-sub">{form.is_active ? 'Visible publiquement' : 'Masqué'}</span>
              </label>
            </Field>
          </div>

          {/* Aperçu live */}
          <div className="pt-2">
            <div className="text-xs uppercase tracking-wider text-sub mb-2">Aperçu</div>
            <div className="space-y-2">
              <div className="flex items-center gap-2">
                <span className="text-xs text-sub">Chip catalogue :</span>
                <span
                  className="inline-flex items-center gap-1.5 px-3 py-1.5 rounded-full border bg-zinc-950 text-sm"
                  style={{ borderColor: form.color_hex + '55' }}
                >
                  <span className="w-2 h-2 rounded-full" style={{ background: form.color_hex }} />
                  <span>{form.name || 'Agent'}</span>
                </span>
              </div>
              <div className="flex items-center gap-2">
                <span className="text-xs text-sub">Ligne fiche produit :</span>
                <span className="flex items-center gap-2 rounded-lg p-2 bg-zinc-950 border border-zinc-800 text-sm flex-1">
                  <span className="w-2.5 h-2.5 rounded-full" style={{ background: form.color_hex }} />
                  <span className="font-medium">{form.name || 'Agent'}</span>
                  {form.tagline && <span className="text-xs text-sub">· {form.tagline}</span>}
                </span>
              </div>
            </div>
          </div>

          {err && (
            <div className="mt-3 px-3 py-2 rounded-md bg-red-950/50 border border-red-900/60 text-red-300 text-sm">
              {err}
            </div>
          )}
        </div>

        <footer className="px-5 py-4 border-t border-zinc-800 flex justify-end gap-2">
          <button type="button" onClick={onClose} className="px-4 py-2 rounded-lg bg-zinc-800 hover:bg-zinc-700">Annuler</button>
          <button type="submit" disabled={saving} className="px-5 py-2 rounded-lg bg-emerald-600 hover:bg-emerald-500 font-semibold disabled:opacity-50">
            {saving ? 'Enregistrement…' : 'Enregistrer'}
          </button>
        </footer>

        <style>{`
          .input {
            width: 100%;
            background: #0f1115;
            border: 1px solid #27272a;
            border-radius: 0.5rem;
            padding: 0.55rem 0.75rem;
            color: #fff;
            font-size: 0.9rem;
          }
          .input:focus { outline: none; border-color: #52525b; }
        `}</style>
      </form>
    </div>
  );
}

function Field({ label, children }) {
  return (
    <label className="block">
      <span className="text-xs uppercase tracking-wider text-sub mb-1 block">{label}</span>
      {children}
    </label>
  );
}
