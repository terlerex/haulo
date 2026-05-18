import { useEffect, useState } from 'react';
import { Link } from 'react-router-dom';
import { LineChart, Line, ResponsiveContainer } from 'recharts';
import { api } from '../../api.js';

export default function Dashboard() {
  const [stats, setStats] = useState(null);
  const [overview, setOverview] = useState(null);
  const [series, setSeries] = useState({});

  useEffect(() => {
    api.stats().then(setStats).catch(() => {});
    api.analyticsOverview(7).then(setOverview).catch(() => {});
    Promise.all([
      api.analyticsTimeseries(7, 'views'),
      api.analyticsTimeseries(7, 'product_clicks'),
      api.analyticsTimeseries(7, 'affiliate_clicks'),
    ]).then(([v, pc, ac]) => setSeries({ views: v, product_clicks: pc, affiliate_clicks: ac }))
      .catch(() => {});
  }, []);

  return (
    <div className="max-w-7xl mx-auto px-4 py-8">
      <div className="flex items-center justify-between mb-6 flex-wrap gap-3">
        <h1 className="text-2xl font-bold">Dashboard</h1>
        <div className="flex gap-2">
          <Link
            to="/admin/analytics"
            className="px-4 py-2 rounded-lg bg-zinc-800 hover:bg-zinc-700 text-sm"
          >
            📈 Voir les analytics
          </Link>
          <Link
            to="/admin/products/new"
            className="px-4 py-2 rounded-lg bg-emerald-600 text-white font-semibold hover:bg-emerald-500"
          >
            + Nouveau produit
          </Link>
        </div>
      </div>

      <div className="grid sm:grid-cols-2 lg:grid-cols-4 gap-3">
        <MetricCard
          label="Produits actifs"
          value={stats?.active_products}
          sub={`${stats?.total_products ?? 0} au total`}
        />
        <MetricCard
          label="Visites (7j)"
          value={overview?.total_views}
          sub="visites sur 7 jours"
          series={series.views}
          color="#378ADD"
        />
        <MetricCard
          label="Clics affiliés (7j)"
          value={overview?.total_affiliate_clicks}
          sub="redirections vers agents"
          series={series.affiliate_clicks}
          color="#E24B4A"
        />
        <MetricCard
          label="Taux conversion"
          value={overview?.conversion_rate != null ? `${overview.conversion_rate}%` : null}
          sub="aff. / clics produits"
          series={series.product_clicks}
          color="#BA7517"
        />
      </div>

      <div className="mt-10 grid sm:grid-cols-2 gap-3">
        <Link to="/admin/products" className="rounded-xl border border-zinc-800 p-5 bg-zinc-900 hover:border-zinc-600">
          <div className="text-lg font-semibold">Gérer les produits</div>
          <div className="text-sub text-sm mt-1">Ajouter, modifier, mettre en avant des produits.</div>
        </Link>
        <Link to="/admin/platforms" className="rounded-xl border border-zinc-800 p-5 bg-zinc-900 hover:border-zinc-600">
          <div className="text-lg font-semibold">Gérer les agents</div>
          <div className="text-sub text-sm mt-1">Plateformes affiliées et liens d'inscription.</div>
        </Link>
      </div>
    </div>
  );
}

function MetricCard({ label, value, sub, series, color }) {
  const empty = !series || series.every((s) => s.value === 0);
  return (
    <div className="rounded-xl border border-zinc-800 bg-zinc-900 p-5">
      <div className="text-xs uppercase tracking-wider text-sub">{label}</div>
      <div className="mt-2 text-3xl font-extrabold">
        {value == null ? <span className="inline-block w-12 h-7 skeleton rounded" /> : value}
      </div>
      <div className="text-xs text-sub mt-1">{sub}</div>
      {series && !empty && (
        <div className="mt-3" style={{ height: 36 }}>
          <ResponsiveContainer width="100%" height="100%">
            <LineChart data={series}>
              <Line type="monotone" dataKey="value" stroke={color} strokeWidth={1.5} dot={false} />
            </LineChart>
          </ResponsiveContainer>
        </div>
      )}
    </div>
  );
}
