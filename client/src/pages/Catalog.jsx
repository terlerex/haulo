import { useEffect, useState, useCallback } from 'react';
import { api } from '../api.js';
import ProductCard from '../components/ProductCard.jsx';
import PlatformChips from '../components/PlatformChips.jsx';
import { ProductGridSkeleton } from '../components/Skeleton.jsx';
import StatsBar from '../components/StatsBar.jsx';
import HowItWorks from '../components/HowItWorks.jsx';
import DiscordCTA from '../components/DiscordCTA.jsx';
import { useSite } from '../context/SiteContext.jsx';

const PAGE_SIZE = 24;

export default function Catalog() {
  const { settings } = useSite();
  const [products, setProducts] = useState([]);
  const [platforms, setPlatforms] = useState([]);
  const [categories, setCategories] = useState([]);
  const [total, setTotal] = useState(0);
  const [offset, setOffset] = useState(0);
  const [loading, setLoading] = useState(true);
  const [loadingMore, setLoadingMore] = useState(false);
  const [categoryId, setCategoryId] = useState(null);
  const [search, setSearch] = useState('');
  const [searchInput, setSearchInput] = useState('');

  useEffect(() => {
    api.listPlatforms().then(setPlatforms).catch(() => {});
    api.listCategories().then(setCategories).catch(() => {});
  }, []);

  const fetchProducts = useCallback(
    async (opts = {}) => {
      const append = !!opts.append;
      const nextOffset = append ? offset + PAGE_SIZE : 0;
      if (append) setLoadingMore(true); else setLoading(true);
      try {
        const data = await api.listProducts({
          category_id: categoryId ?? '',
          search,
          limit: PAGE_SIZE,
          offset: nextOffset,
        });
        setTotal(data.total);
        setOffset(nextOffset);
        setProducts((prev) => (append ? [...prev, ...data.items] : data.items));
      } finally {
        setLoading(false); setLoadingMore(false);
      }
    },
    [categoryId, search, offset]
  );

  useEffect(() => {
    fetchProducts({ append: false });
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [categoryId, search]);

  const submitSearch = (e) => { e.preventDefault(); setSearch(searchInput.trim()); };
  const hasMore = products.length < total;

  return (
    <div className="max-w-7xl mx-auto px-4 py-6 sm:py-10">
      {/* Hero */}
      <section className="mb-8">
        <h1 className="text-3xl sm:text-5xl font-extrabold tracking-tight">
          {settings.site_tagline || 'Trouve tes produits chez les meilleurs agents'}
        </h1>
        {settings.site_subtitle && (
          <p className="mt-3 text-sub max-w-2xl">{settings.site_subtitle}</p>
        )}
        <form onSubmit={submitSearch} className="mt-5 flex gap-2 max-w-xl">
          <input
            type="search"
            value={searchInput}
            onChange={(e) => setSearchInput(e.target.value)}
            placeholder="Rechercher un produit…"
            className="flex-1 rounded-lg bg-zinc-900 border border-zinc-800 px-4 py-2.5 focus:outline-none focus:border-zinc-500"
          />
          <button type="submit" className="px-4 py-2.5 rounded-lg bg-white text-ink font-semibold hover:bg-zinc-200 transition-colors">
            Chercher
          </button>
        </form>
        <StatsBar />
      </section>

      {/* Plateformes */}
      <section className="mb-10">
        <h2 className="text-xs uppercase tracking-wider text-sub mb-2">Nos agents partenaires</h2>
        <PlatformChips platforms={platforms} />
      </section>

      <HowItWorks />
      <DiscordCTA />

      {/* Filtres catégories */}
      <section className="mb-6 flex gap-2 overflow-x-auto pb-2">
        <CategoryChip active={categoryId === null} onClick={() => setCategoryId(null)} label="Tous" />
        {categories.map((c) => (
          <CategoryChip
            key={c.id}
            active={categoryId === c.id}
            onClick={() => setCategoryId(c.id)}
            label={`${c.emoji ? c.emoji + ' ' : ''}${c.name}`}
          />
        ))}
      </section>

      {loading ? (
        <ProductGridSkeleton count={8} />
      ) : products.length === 0 ? (
        <div className="text-center py-16 text-sub">
          Aucun produit trouvé. {search && (
            <button onClick={() => { setSearch(''); setSearchInput(''); }} className="text-emerald-400 underline">
              Réinitialiser
            </button>
          )}
        </div>
      ) : (
        <>
          <div className="grid grid-cols-2 sm:grid-cols-3 lg:grid-cols-4 gap-3 sm:gap-4">
            {products.map((p) => (<ProductCard key={p.id} product={p} />))}
          </div>
          {hasMore && (
            <div className="flex justify-center mt-8">
              <button
                onClick={() => fetchProducts({ append: true })}
                disabled={loadingMore}
                className="px-6 py-2.5 rounded-lg bg-zinc-900 border border-zinc-800 hover:bg-zinc-800 disabled:opacity-50"
              >
                {loadingMore ? 'Chargement…' : 'Charger plus'}
              </button>
            </div>
          )}
        </>
      )}
    </div>
  );
}

function CategoryChip({ active, onClick, label }) {
  return (
    <button
      onClick={onClick}
      className={`shrink-0 px-4 py-1.5 rounded-full text-sm border transition-colors ${
        active ? 'bg-white text-ink border-white'
              : 'bg-zinc-900 text-sub border-zinc-800 hover:text-white hover:border-zinc-600'
      }`}
    >
      {label}
    </button>
  );
}
