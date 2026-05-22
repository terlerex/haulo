import { useEffect, useState, useMemo } from 'react';
import { Link, useNavigate, useParams } from 'react-router-dom';
import { api, convertCnyToEur } from '../../api.js';
import { useToast } from '../../components/Toast.jsx';
import ImagePicker from '../../components/ImagePicker.jsx';
import { useSite } from '../../context/SiteContext.jsx';

const EMPTY = {
  name: '',
  category_id: '',
  price_cny_numeric: '',
  price_eur_override: '',
  // legacy strings (rétrocompat, plus saisies manuellement)
  price_eur: '',
  price_cny: '',
  image_url: '',
  description: '',
  badge_id: '',
  is_active: 1,
};

export default function ProductForm() {
  const { id } = useParams();
  const isEdit = !!id;
  const nav = useNavigate();
  const toast = useToast();
  const { settings } = useSite();

  const [form, setForm] = useState(EMPTY);
  const [overrideEnabled, setOverrideEnabled] = useState(false);
  const [categories, setCategories] = useState([]);
  const [badges, setBadges] = useState([]);
  const [platforms, setPlatforms] = useState([]);
  const [links, setLinks] = useState({});
  const [loading, setLoading] = useState(isEdit);
  const [saving, setSaving] = useState(false);

  const rate = settings?.exchange_rate_cny_eur ?? '0.128';
  const margin = settings?.exchange_rate_margin_pct ?? '0';

  // Calcul du prix EUR affiché live sous le champ CNY
  const livePriceEur = useMemo(() => {
    if (overrideEnabled && form.price_eur_override !== '') {
      return Number(form.price_eur_override);
    }
    return convertCnyToEur(form.price_cny_numeric, rate, margin);
  }, [form.price_cny_numeric, form.price_eur_override, overrideEnabled, rate, margin]);

  useEffect(() => {
    Promise.all([api.listCategories(), api.listBadges(), api.listPlatforms()])
      .then(([cats, bdgs, plats]) => {
        setCategories(cats);
        setBadges(bdgs);
        setPlatforms(plats);
        if (!isEdit && cats.length) {
          setForm((f) => ({ ...f, category_id: cats[0].id }));
        }
      });
  }, [isEdit]);

  useEffect(() => {
    if (!isEdit) return;
    setLoading(true);
    api.getProduct(id)
      .then((p) => {
        setForm({
          name: p.name || '',
          category_id: p.category_id ?? '',
          price_cny_numeric: p.price_cny_numeric ?? '',
          price_eur_override: p.price_eur_override ?? '',
          price_eur: p.price_eur ?? '',
          price_cny: p.price_cny ?? '',
          image_url: p.image_url || '',
          description: p.description || '',
          badge_id: p.badge_id ?? '',
          is_active: p.is_active ? 1 : 0,
        });
        setOverrideEnabled(p.price_eur_override != null);
        const map = {};
        (p.links || []).forEach((l) => {
          map[l.platform_id] = { url: l.url, price_cny: l.price_cny ?? '', id: l.id };
        });
        setLinks(map);
      })
      .catch(() => toast.error('Produit introuvable'))
      .finally(() => setLoading(false));
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [id]);

  const update = (k, v) => setForm((f) => ({ ...f, [k]: v }));

  const setLink = (platformId, key, value) => {
    setLinks((s) => ({
      ...s,
      [platformId]: { ...(s[platformId] || { url: '', price_cny: '' }), [key]: value },
    }));
  };

  const onSubmit = async (e) => {
    e.preventDefault();
    if (!form.name.trim()) return toast.error('Nom requis');
    setSaving(true);
    try {
      const cnyNum = form.price_cny_numeric === '' ? null : Number(form.price_cny_numeric);
      const overrideNum = overrideEnabled && form.price_eur_override !== ''
        ? Number(form.price_eur_override)
        : null;

      const payload = {
        name: form.name,
        category_id: form.category_id === '' ? null : Number(form.category_id),
        badge_id: form.badge_id === '' ? null : Number(form.badge_id),
        price_cny_numeric: cnyNum,
        price_eur_override: overrideNum,
        // Le serveur recalcule price_eur (legacy) automatiquement, on l'envoie pas
        image_url: form.image_url,
        description: form.description,
        is_active: form.is_active ? 1 : 0,
      };

      const saved = isEdit
        ? await api.updateProduct(id, payload)
        : await api.createProduct(payload);

      for (const pl of platforms) {
        const l = links[pl.id];
        if (l && l.url && l.url.trim()) {
          await api.upsertLink(saved.id, {
            platform_id: pl.id,
            url: l.url.trim(),
            price_cny: l.price_cny === '' || l.price_cny == null ? null : Number(l.price_cny),
          });
        } else if (l && l.id && (!l.url || !l.url.trim())) {
          await api.deleteLink(saved.id, l.id);
        }
      }

      toast.success(isEdit ? 'Produit modifié' : 'Produit ajouté');
      nav('/admin/products');
    } catch (err) {
      toast.error(err.message);
    } finally {
      setSaving(false);
    }
  };

  if (loading) {
    return <div className="max-w-5xl mx-auto px-4 py-8 text-sub">Chargement…</div>;
  }

  return (
    <div className="max-w-5xl mx-auto px-4 py-8">
      <div className="mb-6">
        <Link to="/admin/products" className="text-sm text-sub hover:text-white">← Retour</Link>
        <h1 className="text-2xl font-bold mt-2">
          {isEdit ? 'Modifier le produit' : 'Nouveau produit'}
        </h1>
      </div>

      <form onSubmit={onSubmit} className="space-y-6">
        <div className="grid sm:grid-cols-2 gap-4">
          <Field label="Nom">
            <input required value={form.name} onChange={(e) => update('name', e.target.value)} className="input" />
          </Field>
          <Field label="Catégorie">
            <select value={form.category_id} onChange={(e) => update('category_id', e.target.value)} className="input">
              <option value="">— Aucune —</option>
              {categories.map((c) => (
                <option key={c.id} value={c.id}>{c.emoji ? c.emoji + ' ' : ''}{c.name}</option>
              ))}
            </select>
          </Field>
        </div>

        {/* Section prix — refonte */}
        <div className="rounded-xl border border-zinc-800 bg-zinc-900/40 p-4 space-y-3">
          <h2 className="text-sm font-semibold uppercase tracking-wider text-sub">Prix</h2>

          <Field label="Prix en ¥ CNY">
            <input
              type="number"
              step="0.01"
              min="0"
              value={form.price_cny_numeric}
              onChange={(e) => update('price_cny_numeric', e.target.value)}
              className="input"
              placeholder="Ex: 500"
            />
            <div className="text-xs text-sub mt-1">
              {form.price_cny_numeric === '' ? (
                <span>Saisis un prix en ¥ pour voir l'équivalent EUR calculé automatiquement.</span>
              ) : (
                <>
                  ≈ <span className="text-emerald-400 font-semibold">€{livePriceEur != null ? livePriceEur.toFixed(2) : '—'}</span>
                  {' '}<span className="opacity-60">(taux: {parseFloat(rate).toFixed(3)} · marge: {margin}%)</span>
                </>
              )}
            </div>
          </Field>

          <label className="flex items-center gap-3 cursor-pointer pt-2 border-t border-zinc-800">
            <input
              type="checkbox"
              checked={overrideEnabled}
              onChange={(e) => {
                setOverrideEnabled(e.target.checked);
                if (!e.target.checked) update('price_eur_override', '');
              }}
              className="w-4 h-4 accent-emerald-500"
            />
            <span className="text-sm">Forcer un prix EUR personnalisé</span>
          </label>

          {overrideEnabled && (
            <Field label="Prix EUR personnalisé (override)">
              <input
                type="number"
                step="0.01"
                min="0"
                value={form.price_eur_override}
                onChange={(e) => update('price_eur_override', e.target.value)}
                className="input"
                placeholder="Ex: 65.00"
              />
              <div className="text-xs text-amber-400 mt-1">
                ⚠️ Cette valeur écrase le calcul automatique CNY → EUR.
              </div>
            </Field>
          )}
        </div>

        <div>
          <Field label="Badge">
            <select value={form.badge_id} onChange={(e) => update('badge_id', e.target.value)} className="input max-w-xs">
              <option value="">— Aucun —</option>
              {badges.map((b) => (
                <option key={b.id} value={b.id}>{b.label}</option>
              ))}
            </select>
          </Field>
        </div>

        <Field label="Image">
          <ImagePicker value={form.image_url} onChange={(url) => update('image_url', url)} />
        </Field>

        <Field label="Description">
          <textarea rows={4} value={form.description} onChange={(e) => update('description', e.target.value)} className="input resize-y" />
        </Field>

        <label className="flex items-center gap-3 cursor-pointer">
          <input
            type="checkbox"
            checked={!!form.is_active}
            onChange={(e) => update('is_active', e.target.checked ? 1 : 0)}
            className="w-4 h-4 accent-emerald-500"
          />
          <span className="text-sm">Produit actif (visible sur le site public)</span>
        </label>

        <div>
          <h2 className="text-lg font-semibold mb-1">Liens affiliés</h2>
          <p className="text-sm text-sub mb-3">URL + prix ¥ par plateforme. Laisser vide pour ne pas créer de lien.</p>
          <div className="space-y-2">
            {platforms.map((pl) => {
              const l = links[pl.id] || { url: '', price_cny: '' };
              const filled = !!l.url;
              return (
                <div
                  key={pl.id}
                  className="grid grid-cols-1 sm:grid-cols-[180px_1fr_120px_auto] gap-2 items-center p-3 rounded-lg border border-zinc-800 bg-zinc-900"
                >
                  <div className="flex items-center gap-2">
                    <span className="w-2.5 h-2.5 rounded-full" style={{ background: pl.color_hex }} />
                    <span className="font-medium">{pl.name}</span>
                  </div>
                  <input
                    type="url"
                    placeholder={`URL chez ${pl.name}`}
                    value={l.url || ''}
                    onChange={(e) => setLink(pl.id, 'url', e.target.value)}
                    className="input"
                  />
                  <input
                    type="number"
                    step="0.01"
                    placeholder="Prix ¥"
                    value={l.price_cny ?? ''}
                    onChange={(e) => setLink(pl.id, 'price_cny', e.target.value)}
                    className="input"
                  />
                  <span className={`text-xs text-right ${filled ? 'text-emerald-400' : 'text-sub'}`}>
                    {filled ? 'Renseigné' : 'Vide'}
                  </span>
                </div>
              );
            })}
          </div>
        </div>

        <div className="flex justify-end gap-2 pt-2">
          <Link to="/admin/products" className="px-4 py-2 rounded-lg bg-zinc-800 hover:bg-zinc-700">Annuler</Link>
          <button type="submit" disabled={saving} className="px-5 py-2 rounded-lg bg-emerald-600 hover:bg-emerald-500 font-semibold disabled:opacity-50">
            {saving ? 'Enregistrement…' : 'Enregistrer'}
          </button>
        </div>
      </form>

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
