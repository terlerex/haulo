import { useEffect, useState, useRef } from 'react';
import { api } from '../../api.js';
import { useToast } from '../../components/Toast.jsx';
import { useSite } from '../../context/SiteContext.jsx';

export default function Settings() {
  const { reload } = useSite();
  const toast = useToast();
  const [all, setAll] = useState({});
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    api.getSettings().then((s) => { setAll(s); setLoading(false); });
  }, []);

  const set = (k, v) => setAll((s) => ({ ...s, [k]: v }));

  const saveSection = async (keys) => {
    try {
      const payload = keys.map((k) => ({ key: k, value: all[k] ?? '' }));
      await api.updateSettings(payload);
      await reload();
      toast.success('Enregistré');
    } catch (err) {
      toast.error(err.message);
    }
  };

  if (loading) return <div className="max-w-4xl mx-auto px-4 py-8 text-sub">Chargement…</div>;

  return (
    <div className="max-w-4xl mx-auto px-4 py-8 space-y-8">
      <h1 className="text-2xl font-bold">Paramètres du site</h1>

      <LogoSection />

      <ExchangeRateSection all={all} set={set} saveSection={saveSection} />

      {/* Identité */}
      <Section
        title="Identité du site"
        onSave={() => saveSection(['site_name', 'site_tagline', 'site_subtitle'])}
      >
        <Field label="Nom du site">
          <input value={all.site_name || ''} onChange={(e) => set('site_name', e.target.value)} className="input" />
        </Field>
        <Field label="Tagline (titre hero)">
          <input value={all.site_tagline || ''} onChange={(e) => set('site_tagline', e.target.value)} className="input" />
        </Field>
        <Field label="Sous-titre hero">
          <textarea rows={3} value={all.site_subtitle || ''} onChange={(e) => set('site_subtitle', e.target.value)} className="input resize-y" />
        </Field>
      </Section>

      {/* Bandeau */}
      <Section
        title="Bandeau annonce"
        subtitle="Affiché en haut de la page. Laisser vide pour le masquer."
        onSave={() => saveSection(['hero_badge'])}
      >
        <Field label="Texte du bandeau">
          <input value={all.hero_badge || ''} onChange={(e) => set('hero_badge', e.target.value)} className="input" />
        </Field>
        {all.hero_badge?.trim() && (
          <div className="mt-2">
            <div className="text-xs text-sub mb-1">Aperçu</div>
            <div className="bg-zinc-950 border border-zinc-800 rounded-md px-4 py-2 text-sm text-center">
              {all.hero_badge}
            </div>
          </div>
        )}
      </Section>

      {/* Stats */}
      <Section
        title="Statistiques"
        subtitle='Mettre "auto" pour calculer en DB, sinon saisir une valeur libre.'
        onSave={() => saveSection([
          'stats_products', 'stats_partners', 'stats_countries',
          'stats_label_1', 'stats_label_2', 'stats_label_3',
        ])}
      >
        <StatRow
          label="Produits"
          mode={all.stats_products}
          value={all.stats_products}
          labelText={all.stats_label_1}
          onModeChange={(m) => set('stats_products', m === 'auto' ? 'auto' : '')}
          onValueChange={(v) => set('stats_products', v)}
          onLabelChange={(v) => set('stats_label_1', v)}
        />
        <StatRow
          label="Partenaires"
          mode={all.stats_partners}
          value={all.stats_partners}
          labelText={all.stats_label_2}
          onModeChange={(m) => set('stats_partners', m === 'auto' ? 'auto' : '')}
          onValueChange={(v) => set('stats_partners', v)}
          onLabelChange={(v) => set('stats_label_2', v)}
        />
        <StatRow
          label="Pays"
          mode="manual"
          value={all.stats_countries}
          labelText={all.stats_label_3}
          hideToggle
          onValueChange={(v) => set('stats_countries', v)}
          onLabelChange={(v) => set('stats_label_3', v)}
        />
      </Section>

      {/* How it works */}
      <Section
        title='Section "Comment ça marche"'
        onSave={() => saveSection([
          'howto_enabled',
          'howto_step1_title', 'howto_step1_desc',
          'howto_step2_title', 'howto_step2_desc',
          'howto_step3_title', 'howto_step3_desc',
        ])}
      >
        <Toggle
          checked={all.howto_enabled === 'true'}
          onChange={(v) => set('howto_enabled', v ? 'true' : 'false')}
          label="Afficher la section"
        />
        {[1, 2, 3].map((n) => (
          <div key={n} className="border-t border-zinc-800 pt-3 mt-3">
            <Field label={`Étape ${n} — titre`}>
              <input value={all[`howto_step${n}_title`] || ''} onChange={(e) => set(`howto_step${n}_title`, e.target.value)} className="input" />
            </Field>
            <Field label={`Étape ${n} — description`}>
              <textarea rows={2} value={all[`howto_step${n}_desc`] || ''} onChange={(e) => set(`howto_step${n}_desc`, e.target.value)} className="input resize-y" />
            </Field>
          </div>
        ))}
      </Section>

      {/* Discord */}
      <Section
        title="Bloc Discord"
        subtitle="L'URL est gérée dans Réseaux sociaux (platform = discord)."
        onSave={() => saveSection(['discord_cta_enabled', 'discord_cta_title', 'discord_cta_desc', 'discord_cta_label'])}
      >
        <Toggle
          checked={all.discord_cta_enabled === 'true'}
          onChange={(v) => set('discord_cta_enabled', v ? 'true' : 'false')}
          label="Afficher le bloc"
        />
        <Field label="Titre">
          <input value={all.discord_cta_title || ''} onChange={(e) => set('discord_cta_title', e.target.value)} className="input" />
        </Field>
        <Field label="Description">
          <textarea rows={2} value={all.discord_cta_desc || ''} onChange={(e) => set('discord_cta_desc', e.target.value)} className="input resize-y" />
        </Field>
        <Field label="Label du bouton">
          <input value={all.discord_cta_label || ''} onChange={(e) => set('discord_cta_label', e.target.value)} className="input" />
        </Field>
      </Section>

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

function Section({ title, subtitle, children, onSave }) {
  return (
    <section className="rounded-xl border border-zinc-800 bg-zinc-900 p-5">
      <header className="flex items-start justify-between mb-4 gap-4">
        <div>
          <h2 className="text-lg font-semibold">{title}</h2>
          {subtitle && <p className="text-sm text-sub mt-0.5">{subtitle}</p>}
        </div>
        <button onClick={onSave} className="px-4 py-1.5 rounded-md bg-emerald-600 hover:bg-emerald-500 text-sm font-semibold">
          Enregistrer
        </button>
      </header>
      <div className="space-y-3">{children}</div>
    </section>
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

function Toggle({ checked, onChange, label }) {
  return (
    <label className="flex items-center gap-3 cursor-pointer">
      <input type="checkbox" checked={checked} onChange={(e) => onChange(e.target.checked)} className="w-4 h-4 accent-emerald-500" />
      <span className="text-sm">{label}</span>
    </label>
  );
}

function timeAgo(iso) {
  if (!iso) return 'jamais';
  const ms = Date.now() - new Date(iso).getTime();
  if (!Number.isFinite(ms) || ms < 0) return iso;
  const m = Math.floor(ms / 60000);
  if (m < 1) return 'à l’instant';
  if (m < 60) return `il y a ${m} min`;
  const h = Math.floor(m / 60);
  if (h < 24) return `il y a ${h}h`;
  const d = Math.floor(h / 24);
  return `il y a ${d}j`;
}

function convertCnyToEurLocal(cny, rate, margin) {
  const n = Number(cny);
  if (!Number.isFinite(n)) return null;
  const r = parseFloat(rate);
  const m = parseFloat(margin);
  const rr = Number.isFinite(r) ? r : 0.128;
  const mm = Number.isFinite(m) ? m : 0;
  return Math.round(n * rr * (1 + mm / 100) * 100) / 100;
}

function ExchangeRateSection({ all, set, saveSection }) {
  const { reload } = useSite();
  const toast = useToast();
  const [refreshing, setRefreshing] = useState(false);
  const [recalculating, setRecalculating] = useState(false);

  const rate = all.exchange_rate_cny_eur || '0.128';
  const margin = all.exchange_rate_margin_pct || '0';
  const auto = all.exchange_rate_auto_update === 'true';
  const lastUpdate = all.exchange_rate_last_update || '';

  const onRefresh = async () => {
    setRefreshing(true);
    try {
      const r = await api.refreshExchangeRate();
      toast.success(`Taux rafraîchi : ${r.rate}`);
      await reload();
      // Met aussi à jour l'état local pour refléter immédiatement
      set('exchange_rate_cny_eur', String(r.rate));
      set('exchange_rate_last_update', r.last_update);
    } catch (err) {
      toast.error(err.message);
    } finally {
      setRefreshing(false);
    }
  };

  const onRecalculate = async () => {
    if (!confirm('Recalculer le prix EUR de tous les produits non-override ?')) return;
    setRecalculating(true);
    try {
      const r = await api.recalculatePrices();
      toast.success(`${r.updated} produit(s) recalculé(s)`);
    } catch (err) {
      toast.error(err.message);
    } finally {
      setRecalculating(false);
    }
  };

  return (
    <section className="rounded-xl border border-zinc-800 bg-zinc-900 p-5">
      <header className="flex items-start justify-between mb-4 gap-4 flex-wrap">
        <div>
          <h2 className="text-lg font-semibold">💱 Taux de change CNY → EUR</h2>
          <p className="text-sm text-sub mt-0.5">
            Conversion automatique des prix produits. Source : frankfurter.app
          </p>
        </div>
        <button
          onClick={() => saveSection(['exchange_rate_cny_eur', 'exchange_rate_margin_pct', 'exchange_rate_auto_update'])}
          className="px-4 py-1.5 rounded-md bg-emerald-600 hover:bg-emerald-500 text-sm font-semibold"
        >
          Enregistrer
        </button>
      </header>

      <div className="grid sm:grid-cols-2 gap-3">
        <Field label="Taux actuel (1 ¥ = X €)">
          <input
            type="number" step="0.0001" min="0"
            value={rate}
            onChange={(e) => set('exchange_rate_cny_eur', e.target.value)}
            className="input"
          />
        </Field>
        <Field label="Marge à appliquer (%)">
          <input
            type="number" step="0.1" min="0"
            value={margin}
            onChange={(e) => set('exchange_rate_margin_pct', e.target.value)}
            className="input"
          />
        </Field>
      </div>

      <Toggle
        checked={auto}
        onChange={(v) => set('exchange_rate_auto_update', v ? 'true' : 'false')}
        label="Mise à jour automatique quotidienne (frankfurter.app)"
      />

      <div className="text-xs text-sub mt-1">
        Dernière mise à jour : {timeAgo(lastUpdate)}
        {lastUpdate && <span className="ml-2 opacity-60">({lastUpdate.slice(0, 16).replace('T', ' ')} UTC)</span>}
      </div>

      <div className="flex flex-wrap gap-2 pt-4 border-t border-zinc-800 mt-4">
        <button
          onClick={onRefresh}
          disabled={refreshing}
          className="px-4 py-2 rounded-lg bg-zinc-800 hover:bg-zinc-700 text-sm disabled:opacity-50"
        >
          {refreshing ? 'Récupération…' : '🔄 Rafraîchir le taux maintenant'}
        </button>
        <button
          onClick={onRecalculate}
          disabled={recalculating}
          className="px-4 py-2 rounded-lg bg-zinc-800 hover:bg-zinc-700 text-sm disabled:opacity-50"
        >
          {recalculating ? 'Calcul…' : '🧮 Recalculer tous les prix EUR'}
        </button>
      </div>

      <div className="mt-4 pt-3 border-t border-zinc-800">
        <div className="text-xs uppercase tracking-wider text-sub mb-2">Aperçu</div>
        <div className="text-sm space-y-1 font-mono">
          {[100, 500, 1000].map((v) => (
            <div key={v} className="flex gap-3">
              <span className="text-sub w-20 text-right">{v} ¥</span>
              <span>→</span>
              <span className="text-emerald-400 font-semibold">€{convertCnyToEurLocal(v, rate, margin)?.toFixed(2)}</span>
              <span className="text-sub text-xs opacity-60">(taux {parseFloat(rate).toFixed(4)} + marge {margin}%)</span>
            </div>
          ))}
        </div>
      </div>
    </section>
  );
}

const CHECKER_BG = {
  backgroundColor: '#ffffff',
  backgroundImage:
    'linear-gradient(45deg, #cbd5e1 25%, transparent 25%),' +
    'linear-gradient(-45deg, #cbd5e1 25%, transparent 25%),' +
    'linear-gradient(45deg, transparent 75%, #cbd5e1 75%),' +
    'linear-gradient(-45deg, transparent 75%, #cbd5e1 75%)',
  backgroundSize: '16px 16px',
  backgroundPosition: '0 0, 0 8px, 8px -8px, 8px 0',
};

function uploadLogoWithProgress(file, onProgress) {
  return new Promise((resolve, reject) => {
    const xhr = new XMLHttpRequest();
    xhr.open('POST', '/api/admin/upload/logo');
    xhr.withCredentials = true;
    xhr.upload.onprogress = (e) => {
      if (e.lengthComputable) onProgress(Math.round((e.loaded / e.total) * 100));
    };
    xhr.onload = () => {
      if (xhr.status >= 200 && xhr.status < 300) {
        try { resolve(JSON.parse(xhr.responseText)); } catch (e) { reject(e); }
      } else {
        let msg = `HTTP ${xhr.status}`;
        try { const j = JSON.parse(xhr.responseText); if (j.error) msg = j.error; } catch (_) {}
        reject(new Error(msg));
      }
    };
    xhr.onerror = () => reject(new Error('Erreur réseau'));
    const fd = new FormData();
    fd.append('file', file);
    xhr.send(fd);
  });
}

function LogoSection() {
  const { settings, reload } = useSite();
  const toast = useToast();
  const logoUrl = settings?.site_logo_url || '';
  const savedSize = parseInt(settings?.site_logo_size, 10) || 32;

  const [size, setSize] = useState(savedSize);
  const [uploading, setUploading] = useState(false);
  const [progress, setProgress] = useState(0);
  const [error, setError] = useState(null);
  const inputRef = useRef(null);

  useEffect(() => { setSize(savedSize); }, [savedSize]);

  const handleFile = async (file) => {
    setError(null);
    if (!file) return;
    if (file.size > 2 * 1024 * 1024) { setError('Fichier > 2 MB'); return; }
    const okExt = /\.(jpe?g|png|webp|svg)$/i.test(file.name || '');
    if (!okExt) { setError('Format non autorisé (png, svg, webp, jpg)'); return; }
    setUploading(true);
    setProgress(0);
    try {
      await uploadLogoWithProgress(file, setProgress);
      await reload();
      toast.success('Logo mis à jour');
    } catch (err) {
      setError(err.message);
    } finally {
      setUploading(false);
    }
  };

  const onDrop = (e) => {
    e.preventDefault();
    const file = e.dataTransfer.files?.[0];
    if (file) handleFile(file);
  };

  const onPick = (e) => {
    const file = e.target.files?.[0];
    if (file) handleFile(file);
    e.target.value = '';
  };

  const saveSize = async () => {
    try {
      await api.updateSettings([{ key: 'site_logo_size', value: String(size) }]);
      await reload();
      toast.success('Taille enregistrée');
    } catch (err) { toast.error(err.message); }
  };

  const removeLogo = async () => {
    if (!confirm('Supprimer le logo actuel ?')) return;
    try {
      await api.deleteLogo();
      await reload();
      toast.success('Logo supprimé');
    } catch (err) { toast.error(err.message); }
  };

  return (
    <section className="rounded-xl border border-zinc-800 bg-zinc-900 p-5">
      <header className="mb-4">
        <h2 className="text-lg font-semibold">Logo du site</h2>
        <p className="text-sm text-sub mt-0.5">Affiché à gauche du nom du site dans le header et utilisé comme favicon.</p>
      </header>

      {/* État actuel */}
      <div className="mb-5">
        <div className="text-xs uppercase tracking-wider text-sub mb-2">État actuel</div>
        {logoUrl ? (
          <div
            className="inline-block rounded-md border border-zinc-800 p-3"
            style={CHECKER_BG}
          >
            <img src={logoUrl} alt="logo" style={{ maxHeight: 80, width: 'auto', display: 'block' }} />
          </div>
        ) : (
          <p className="text-sm text-sub">Aucun logo configuré</p>
        )}
      </div>

      {/* Dropzone */}
      <div className="mb-5">
        <div className="text-xs uppercase tracking-wider text-sub mb-2">Uploader un nouveau logo</div>
        <div
          onDragOver={(e) => e.preventDefault()}
          onDrop={onDrop}
          onClick={() => inputRef.current?.click()}
          className="cursor-pointer rounded-lg border-2 border-dashed border-zinc-700 hover:border-zinc-500 bg-zinc-950/50 p-6 text-center transition-colors"
        >
          <div className="text-3xl mb-2">📤</div>
          <p className="text-sm text-zinc-300">Glisse ton logo ici ou clique pour parcourir</p>
          <p className="text-xs text-sub mt-1">PNG, SVG ou WebP recommandé · Fond transparent · 2 MB max</p>
          <input
            ref={inputRef}
            type="file"
            accept=".png,.svg,.webp,.jpg,.jpeg"
            onChange={onPick}
            className="hidden"
          />
        </div>

        {uploading && (
          <div className="mt-3">
            <div className="text-xs text-sub mb-1">Upload {progress}%</div>
            <div className="h-2 bg-zinc-800 rounded overflow-hidden">
              <div className="h-full bg-emerald-500 transition-all" style={{ width: `${progress}%` }} />
            </div>
          </div>
        )}

        {error && (
          <div className="mt-2 text-sm text-red-400 bg-red-950/40 border border-red-900/50 rounded-md px-3 py-2">
            {error}
          </div>
        )}
      </div>

      {/* Slider taille */}
      <div className="mb-5">
        <div className="text-xs uppercase tracking-wider text-sub mb-2">
          Hauteur du logo dans le header : <span className="text-white font-semibold">{size}px</span>
        </div>
        <div className="flex items-center gap-4">
          <input
            type="range"
            min="20" max="64" step="1"
            value={size}
            onChange={(e) => setSize(parseInt(e.target.value, 10))}
            className="flex-1 accent-emerald-500"
          />
          <input
            type="number"
            min="20" max="64"
            value={size}
            onChange={(e) => setSize(Math.max(20, Math.min(64, parseInt(e.target.value, 10) || 32)))}
            className="w-20 bg-ink border border-zinc-800 rounded-md px-2 py-1 text-sm"
          />
          <button
            onClick={saveSize}
            disabled={size === savedSize}
            className="px-3 py-1.5 rounded-md bg-emerald-600 hover:bg-emerald-500 text-sm font-semibold disabled:opacity-40"
          >
            Enregistrer la taille
          </button>
        </div>

        {/* Aperçu live */}
        {logoUrl && (
          <div className="mt-3 flex items-center gap-2.5 p-3 rounded-md border border-zinc-800 bg-ink">
            <img src={logoUrl} alt="" style={{ height: `${size}px`, width: 'auto', display: 'block' }} />
            <span className="font-medium text-[17px] text-white">{settings?.site_name}</span>
            <span className="text-xs text-sub ml-auto">Aperçu header</span>
          </div>
        )}
      </div>

      {/* Supprimer */}
      {logoUrl && (
        <button
          onClick={removeLogo}
          className="px-3 py-1.5 rounded-md bg-red-900/40 hover:bg-red-800/60 text-sm text-red-200"
        >
          Supprimer le logo
        </button>
      )}
    </section>
  );
}

function StatRow({ label, mode, value, labelText, onModeChange, onValueChange, onLabelChange, hideToggle }) {
  const isAuto = mode === 'auto';
  return (
    <div className="border-t border-zinc-800 pt-3 first:border-t-0 first:pt-0 grid sm:grid-cols-[120px_1fr_1fr] gap-3 items-end">
      <div className="text-sm font-medium pb-2">{label}</div>
      <div>
        {!hideToggle && (
          <div className="flex gap-1 mb-2">
            <button type="button" onClick={() => onModeChange('auto')} className={`px-2 py-1 rounded text-xs ${isAuto ? 'bg-emerald-600' : 'bg-zinc-800'}`}>Auto</button>
            <button type="button" onClick={() => onModeChange('manual')} className={`px-2 py-1 rounded text-xs ${!isAuto ? 'bg-emerald-600' : 'bg-zinc-800'}`}>Manuel</button>
          </div>
        )}
        <input
          disabled={isAuto && !hideToggle}
          value={isAuto && !hideToggle ? 'auto' : value || ''}
          onChange={(e) => onValueChange(e.target.value)}
          className="input"
          placeholder="Valeur"
        />
      </div>
      <input value={labelText || ''} onChange={(e) => onLabelChange(e.target.value)} className="input" placeholder="Label affiché" />
    </div>
  );
}
