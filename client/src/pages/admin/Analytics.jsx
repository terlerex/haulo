import { useEffect, useState } from 'react';
import { Link } from 'react-router-dom';
import {
  LineChart, Line, XAxis, YAxis, Tooltip, ResponsiveContainer,
  BarChart, Bar, Cell,
} from 'recharts';
import { api } from '../../api.js';
import { useToast } from '../../components/Toast.jsx';

const METRICS = [
  { key: 'views',            label: 'Visites',         color: '#378ADD' },
  { key: 'unique_sessions',  label: 'Uniques',         color: '#1D9E75' },
  { key: 'product_clicks',   label: 'Clics produits',  color: '#BA7517' },
  { key: 'affiliate_clicks', label: 'Clics affiliés',  color: '#E24B4A' },
];

const PERIODS = [
  { days: 7,  label: '7 jours' },
  { days: 30, label: '30 jours' },
  { days: 90, label: '90 jours' },
];

export default function Analytics() {
  const [days, setDays] = useState(30);
  const [overview, setOverview] = useState(null);
  const [metric, setMetric] = useState('views');
  const [series, setSeries] = useState([]);
  const [topSort, setTopSort] = useState('views');
  const [topProducts, setTopProducts] = useState([]);
  const [platforms, setPlatforms] = useState([]);
  const [pages, setPages] = useState([]);
  const [loading, setLoading] = useState(true);
  const toast = useToast();

  // Charge overview + platforms + pages quand days change
  useEffect(() => {
    setLoading(true);
    Promise.all([
      api.analyticsOverview(days),
      api.analyticsPlatforms(days),
      api.analyticsPages(days),
    ])
      .then(([o, p, pg]) => { setOverview(o); setPlatforms(p); setPages(pg); })
      .catch(() => {})
      .finally(() => setLoading(false));
  }, [days]);

  // Timeseries quand days ou metric change
  useEffect(() => {
    api.analyticsTimeseries(days, metric).then(setSeries).catch(() => setSeries([]));
  }, [days, metric]);

  // Top produits quand days ou topSort change
  const reloadTop = () => api.analyticsProducts(days, topSort, 10).then(setTopProducts).catch(() => {});
  useEffect(() => { reloadTop(); }, [days, topSort]);

  const toggleFeatured = async (p) => {
    try {
      await api.updateProduct(p.id, { is_featured: !p.is_featured });
      toast.success(p.is_featured ? 'Retiré de la sélection' : 'Mis en avant');
      reloadTop();
    } catch (err) { toast.error(err.message); }
  };

  const currentMetric = METRICS.find((m) => m.key === metric);

  return (
    <div className="max-w-7xl mx-auto px-4 py-8 space-y-8">
      {/* Header */}
      <header className="flex items-center justify-between gap-4 flex-wrap">
        <div>
          <h1 className="text-2xl font-bold">Analytics</h1>
          <p className="text-sub text-sm">Vue d'ensemble du trafic et des conversions.</p>
        </div>
        <div className="flex gap-1 bg-zinc-900 rounded-lg border border-zinc-800 p-0.5">
          {PERIODS.map((p) => (
            <button
              key={p.days}
              onClick={() => setDays(p.days)}
              className={`px-3 py-1.5 rounded-md text-sm transition-colors ${
                days === p.days ? 'bg-zinc-700 text-white' : 'text-sub hover:text-white'
              }`}
            >
              {p.label}
            </button>
          ))}
        </div>
      </header>

      {/* Section 1 — Métriques clés */}
      <div className="grid grid-cols-2 lg:grid-cols-4 gap-3">
        <MetricCard
          label="Visites totales"
          value={overview?.total_views}
          delta={overview?.vs_previous_period?.views_delta_pct}
          sub={`visites sur ${days} jours`}
          loading={loading}
        />
        <MetricCard
          label="Visiteurs uniques"
          value={overview?.unique_sessions}
          delta={overview?.vs_previous_period?.views_delta_pct}
          sub="(estimation)"
          loading={loading}
        />
        <MetricCard
          label="Clics produits"
          value={overview?.total_product_clicks}
          delta={overview?.vs_previous_period?.clicks_delta_pct}
          sub="consultations produit"
          loading={loading}
        />
        <MetricCard
          label="Clics affiliés"
          value={overview?.total_affiliate_clicks}
          delta={overview?.vs_previous_period?.affiliate_delta_pct}
          sub="redirections vers agents"
          extra={
            <span className="mt-1 inline-block text-[10px] uppercase tracking-wider px-2 py-0.5 rounded-md bg-emerald-900/40 text-emerald-300">
              Conversion : {overview?.conversion_rate ?? 0}%
            </span>
          }
          loading={loading}
        />
      </div>

      {/* Section 2 — Courbe temporelle */}
      <section className="rounded-xl border border-zinc-800 bg-zinc-900 p-5">
        <div className="flex items-center justify-between gap-4 flex-wrap mb-4">
          <h2 className="text-lg font-semibold">Évolution dans le temps</h2>
          <div className="flex gap-1 flex-wrap">
            {METRICS.map((m) => (
              <button
                key={m.key}
                onClick={() => setMetric(m.key)}
                className={`px-3 py-1.5 rounded-full text-xs border transition-colors ${
                  metric === m.key
                    ? 'border-white text-white'
                    : 'border-zinc-800 text-sub hover:text-white'
                }`}
                style={metric === m.key ? { background: m.color + '20', borderColor: m.color } : {}}
              >
                <span className="inline-block w-2 h-2 rounded-full mr-2 align-middle" style={{ background: m.color }} />
                {m.label}
              </button>
            ))}
          </div>
        </div>

        <div style={{ width: '100%', height: 280 }}>
          {series.length === 0 || series.every((s) => s.value === 0) ? (
            <div className="h-full flex items-center justify-center text-sub text-sm">
              Aucune donnée sur cette période
            </div>
          ) : (
            <ResponsiveContainer>
              <LineChart data={series} margin={{ top: 10, right: 20, left: 0, bottom: 0 }}>
                <XAxis
                  dataKey="date"
                  tickFormatter={(d) => {
                    const x = new Date(d);
                    return `${String(x.getDate()).padStart(2, '0')}/${String(x.getMonth() + 1).padStart(2, '0')}`;
                  }}
                  stroke="#71717a"
                  tick={{ fontSize: 11 }}
                />
                <YAxis stroke="#71717a" tick={{ fontSize: 11 }} allowDecimals={false} />
                <Tooltip
                  contentStyle={{ background: '#18181b', border: '1px solid #27272a', borderRadius: 8, fontSize: 12 }}
                  labelStyle={{ color: '#9ca3af' }}
                  labelFormatter={(d) => new Date(d).toLocaleDateString('fr-FR')}
                />
                <Line
                  type="monotone"
                  dataKey="value"
                  stroke={currentMetric.color}
                  strokeWidth={2}
                  dot={false}
                />
              </LineChart>
            </ResponsiveContainer>
          )}
        </div>
      </section>

      {/* Section 3 — Top produits */}
      <section className="rounded-xl border border-zinc-800 bg-zinc-900 p-5">
        <div className="flex items-center justify-between gap-4 mb-4 flex-wrap">
          <h2 className="text-lg font-semibold">Produits les plus consultés</h2>
          <div className="flex gap-1 bg-zinc-950 rounded-lg p-0.5 border border-zinc-800">
            <button
              onClick={() => setTopSort('views')}
              className={`px-3 py-1 rounded-md text-xs ${topSort === 'views' ? 'bg-zinc-800 text-white' : 'text-sub hover:text-white'}`}
            >
              Par vues
            </button>
            <button
              onClick={() => setTopSort('affiliate_clicks')}
              className={`px-3 py-1 rounded-md text-xs ${topSort === 'affiliate_clicks' ? 'bg-zinc-800 text-white' : 'text-sub hover:text-white'}`}
            >
              Par clics affiliés
            </button>
          </div>
        </div>

        {topProducts.length === 0 ? (
          <div className="text-sub text-sm py-8 text-center">Aucune donnée</div>
        ) : (
          <ul className="divide-y divide-zinc-800">
            {topProducts.map((p) => (
              <li key={p.id} className="py-3 flex items-center gap-3">
                <div className="w-10 h-10 rounded-md bg-zinc-950 flex items-center justify-center overflow-hidden shrink-0">
                  {p.image_url ? (
                    <img src={p.image_url} alt="" className="w-full h-full object-cover" />
                  ) : (
                    <span className="text-xl">{p.category?.emoji || '📦'}</span>
                  )}
                </div>
                <div className="flex-1 min-w-0">
                  <Link to={`/admin/products/${p.id}/edit`} className="font-medium truncate block hover:text-emerald-300">
                    {p.name}
                  </Link>
                  {p.category && (
                    <span className="text-[10px] uppercase tracking-wider px-1.5 py-0.5 rounded bg-zinc-800 text-sub">
                      {p.category.emoji} {p.category.name}
                    </span>
                  )}
                </div>
                <Stat n={p.views} label="vues" />
                <Stat n={p.affiliate_clicks} label="aff." />
                <Stat n={`${p.conversion_rate}%`} label="conv." />
                <TrendIcon trend={p.trend} />
                <button
                  onClick={() => toggleFeatured(p)}
                  title={p.is_featured ? 'Retirer de la sélection' : 'Mettre en avant'}
                  className={`px-2 py-1 rounded-md text-sm transition-colors ${
                    p.is_featured ? 'bg-amber-400/20 text-amber-300' : 'bg-zinc-800 hover:bg-zinc-700 text-sub'
                  }`}
                >
                  {p.is_featured ? '⭐' : '☆'}
                </button>
              </li>
            ))}
          </ul>
        )}
      </section>

      {/* Section 4 — Performance par agent */}
      <section className="rounded-xl border border-zinc-800 bg-zinc-900 p-5">
        <h2 className="text-lg font-semibold mb-4">Clics par agent affilié</h2>
        {platforms.length === 0 || platforms.every((p) => p.clicks === 0) ? (
          <div className="text-sub text-sm py-8 text-center">Aucune donnée</div>
        ) : (
          <div style={{ width: '100%', height: Math.max(platforms.length * 40, 200) }}>
            <ResponsiveContainer>
              <BarChart data={platforms} layout="vertical" margin={{ top: 5, right: 80, left: 70, bottom: 5 }}>
                <XAxis type="number" stroke="#71717a" tick={{ fontSize: 11 }} allowDecimals={false} />
                <YAxis type="category" dataKey="name" stroke="#71717a" tick={{ fontSize: 12 }} width={70} />
                <Tooltip
                  contentStyle={{ background: '#18181b', border: '1px solid #27272a', borderRadius: 8, fontSize: 12 }}
                  formatter={(v, _, item) => [`${v} clics (${item.payload.pct_of_total}%)`, 'Clics']}
                />
                <Bar dataKey="clicks" radius={[0, 4, 4, 0]}>
                  {platforms.map((p, i) => <Cell key={i} fill={p.color_hex} />)}
                </Bar>
              </BarChart>
            </ResponsiveContainer>
          </div>
        )}
      </section>

      {/* Section 5 — Top pages */}
      <section className="rounded-xl border border-zinc-800 bg-zinc-900 p-5">
        <h2 className="text-lg font-semibold mb-4">Pages les plus visitées</h2>
        {pages.length === 0 ? (
          <div className="text-sub text-sm py-8 text-center">Aucune donnée</div>
        ) : (
          <table className="w-full text-sm">
            <thead className="text-sub text-xs uppercase">
              <tr>
                <th className="text-left py-2">Path</th>
                <th className="text-right py-2">Vues</th>
                <th className="text-right py-2">% du total</th>
              </tr>
            </thead>
            <tbody>
              {pages.map((p, i) => (
                <tr key={i} className="border-t border-zinc-800">
                  <td className="py-2 font-mono text-xs">{p.path}</td>
                  <td className="py-2 text-right">{p.views}</td>
                  <td className="py-2 text-right text-sub">{p.pct_of_total}%</td>
                </tr>
              ))}
            </tbody>
          </table>
        )}
      </section>
    </div>
  );
}

function MetricCard({ label, value, delta, sub, extra, loading }) {
  return (
    <div className="rounded-xl border border-zinc-800 bg-zinc-900 p-5">
      <div className="text-xs uppercase tracking-wider text-sub">{label}</div>
      <div className="mt-2 text-3xl font-extrabold">
        {loading ? <span className="inline-block w-16 h-7 skeleton rounded" /> : (value ?? 0).toLocaleString('fr-FR')}
      </div>
      <div className="text-xs text-sub mt-1 flex items-center gap-2">
        {sub}
        {delta != null && !loading && <DeltaBadge value={delta} />}
      </div>
      {extra}
    </div>
  );
}

function DeltaBadge({ value }) {
  if (value === 0) return <span className="text-sub">→ 0%</span>;
  const up = value > 0;
  return (
    <span className={up ? 'text-emerald-400' : 'text-red-400'}>
      {up ? '↑' : '↓'} {up ? '+' : ''}{value}%
    </span>
  );
}

function Stat({ n, label }) {
  return (
    <div className="text-center hidden sm:block">
      <div className="font-semibold text-sm">{n}</div>
      <div className="text-[10px] uppercase tracking-wider text-sub">{label}</div>
    </div>
  );
}

function TrendIcon({ trend }) {
  if (trend === 'up')   return <span className="text-emerald-400 text-lg" title="En hausse">↑</span>;
  if (trend === 'down') return <span className="text-red-400 text-lg"     title="En baisse">↓</span>;
  return <span className="text-sub text-lg" title="Stable">→</span>;
}
