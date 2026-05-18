import { useEffect, useState } from 'react';
import { useSite } from '../context/SiteContext.jsx';
import { api } from '../api.js';

export default function StatsBar() {
  const { settings } = useSite();
  const [auto, setAuto] = useState({ products: null, platforms: null });

  useEffect(() => {
    if (settings.stats_products === 'auto' || settings.stats_partners === 'auto') {
      api.stats()
        .then((s) => setAuto({ products: s.active_products, platforms: s.platforms_count }))
        .catch(() => {});
    }
  }, [settings.stats_products, settings.stats_partners]);

  const value1 = settings.stats_products === 'auto' ? auto.products : settings.stats_products;
  const value2 = settings.stats_partners === 'auto' ? auto.platforms : settings.stats_partners;
  const value3 = settings.stats_countries || '';

  return (
    <div className="grid grid-cols-3 gap-4 mt-6 max-w-2xl">
      <Stat value={value1} label={settings.stats_label_1} />
      <Stat value={value2} label={settings.stats_label_2} />
      <Stat value={value3} label={settings.stats_label_3} />
    </div>
  );
}

function Stat({ value, label }) {
  return (
    <div>
      <div className="text-[28px] leading-none font-medium">
        {value == null || value === '' ? <span className="inline-block w-10 h-6 skeleton rounded" /> : value}
      </div>
      <div className="text-xs text-sub mt-1">{label}</div>
    </div>
  );
}
