import { useEffect, useState } from 'react';
import { Link, useParams } from 'react-router-dom';
import { api } from '../api.js';
import PlatformChips from '../components/PlatformChips.jsx';
import { trackProductClick, trackAffiliateClick } from '../hooks/useTracking.js';

export default function ProductDetail() {
  const { id } = useParams();
  const [product, setProduct] = useState(null);
  const [platforms, setPlatforms] = useState([]);
  const [loading, setLoading] = useState(true);
  const [imgBroken, setImgBroken] = useState(false);

  useEffect(() => {
    setLoading(true);
    trackProductClick(id);
    Promise.all([api.getProduct(id), api.listPlatforms()])
      .then(([p, pls]) => { setProduct(p); setPlatforms(pls); })
      .catch(() => setProduct(null))
      .finally(() => setLoading(false));
  }, [id]);

  const handleAffiliateClick = async (e, link) => {
    e.preventDefault();
    const url = await trackAffiliateClick(product.id, link.platform_id, link.url);
    window.open(url, '_blank', 'noopener,noreferrer');
  };

  if (loading) {
    return (
      <div className="max-w-5xl mx-auto px-4 py-8">
        <div className="grid md:grid-cols-2 gap-6">
          <div className="aspect-square skeleton rounded-xl" />
          <div className="space-y-3">
            <div className="h-8 w-3/4 skeleton rounded" />
            <div className="h-5 w-1/2 skeleton rounded" />
            <div className="h-20 w-full skeleton rounded" />
          </div>
        </div>
      </div>
    );
  }

  if (!product) {
    return (
      <div className="max-w-5xl mx-auto px-4 py-16 text-center">
        <p className="text-sub">Produit introuvable.</p>
        <Link to="/" className="inline-block mt-4 text-emerald-400 underline">Retour catalogue</Link>
      </div>
    );
  }

  const hasImage = product.image_url && !imgBroken;
  const linkedPlatformIds = new Set((product.links || []).map((l) => l.platform_id));
  const notLinkedPlatforms = platforms.filter((p) => !linkedPlatformIds.has(p.id));
  const emoji = product.category?.emoji || '📦';
  const categoryName = product.category?.name || '—';
  const badge = product.badge;

  return (
    <div className="max-w-5xl mx-auto px-4 py-6 sm:py-10">
      <Link to="/" className="text-sm text-sub hover:text-white inline-flex items-center gap-1 mb-4">
        ← Retour catalogue
      </Link>

      <div className="grid md:grid-cols-2 gap-6 sm:gap-10">
        <div className="aspect-square rounded-xl bg-zinc-900 border border-zinc-800 overflow-hidden flex items-center justify-center">
          {hasImage ? (
            <img src={product.image_url} alt={product.name} onError={() => setImgBroken(true)} className="w-full h-full object-cover" />
          ) : (
            <div className="text-9xl">{emoji}</div>
          )}
        </div>

        <div className="flex flex-col">
          <div className="flex items-center gap-2 mb-2">
            <span className="text-xs uppercase tracking-wider text-sub">{categoryName}</span>
            {badge && (
              <span
                className="px-2 py-0.5 rounded-md text-xs font-bold uppercase tracking-wider"
                style={{ background: badge.color_bg, color: badge.color_text }}
              >
                {badge.label}
              </span>
            )}
          </div>
          <h1 className="text-2xl sm:text-3xl font-bold">{product.name}</h1>

          <div className="mt-3 flex items-baseline gap-3">
            {product.price_eur_computed != null ? (
              <span className="text-3xl font-extrabold">€{Number(product.price_eur_computed).toFixed(2)}</span>
            ) : product.price_eur != null ? (
              <span className="text-3xl font-extrabold">{product.price_eur} €</span>
            ) : null}
            {product.price_cny_numeric != null ? (
              <span className="text-sub">¥{product.price_cny_numeric}</span>
            ) : product.price_cny ? (
              <span className="text-sub">≈ ¥{product.price_cny}</span>
            ) : null}
          </div>

          {product.description && <p className="mt-4 text-sub leading-relaxed">{product.description}</p>}

          <div className="mt-8">
            <h2 className="text-sm uppercase tracking-wider text-sub mb-3">Acheter via un agent</h2>
            {product.links?.length ? (
              <ul className="space-y-2">
                {product.links.map((l) => (
                  <li key={l.id} className="flex items-center gap-3 rounded-lg p-3 bg-zinc-900 border border-zinc-800">
                    <span className="w-3 h-3 rounded-full shrink-0" style={{ background: l.color_hex }} />
                    <div className="flex-1 min-w-0">
                      <div className="font-medium">{l.name}</div>
                      {l.tagline && <div className="text-xs text-sub">{l.tagline}</div>}
                    </div>
                    {l.price_cny != null && <span className="text-sm font-semibold">¥{l.price_cny}</span>}
                    <a
                      href={l.url}
                      onClick={(e) => handleAffiliateClick(e, l)}
                      target="_blank"
                      rel="noopener noreferrer"
                      className="px-3 py-1.5 rounded-md bg-white text-ink text-sm font-semibold hover:bg-zinc-200"
                    >
                      Voir →
                    </a>
                  </li>
                ))}
              </ul>
            ) : (
              <p className="text-sub text-sm">Aucun lien d'agent disponible pour ce produit.</p>
            )}
          </div>

          {notLinkedPlatforms.length > 0 && (
            <div className="mt-8">
              <h2 className="text-sm uppercase tracking-wider text-sub mb-3">Pas encore inscrit ?</h2>
              <PlatformChips platforms={notLinkedPlatforms} variant="grid" />
            </div>
          )}
        </div>
      </div>
    </div>
  );
}
