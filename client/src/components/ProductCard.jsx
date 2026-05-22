import { Link } from 'react-router-dom';
import { useState } from 'react';
import { trackProductClick } from '../hooks/useTracking.js';

export default function ProductCard({ product }) {
  const [broken, setBroken] = useState(false);
  const hasImage = product.image_url && !broken;
  const emoji = product.category?.emoji || '📦';
  const categoryName = product.category?.name || '—';
  const badge = product.badge;

  return (
    <Link
      to={`/product/${product.id}`}
      onClick={() => trackProductClick(product.id)}
      className="group rounded-xl bg-zinc-900 border border-zinc-800 overflow-hidden hover:border-zinc-600 transition-colors flex flex-col relative"
    >
      <div className="aspect-square bg-zinc-950 relative overflow-hidden">
        {hasImage ? (
          <img
            src={product.image_url}
            alt={product.name}
            loading="lazy"
            onError={() => setBroken(true)}
            className="w-full h-full object-cover group-hover:scale-105 transition-transform duration-300"
          />
        ) : (
          <div className="w-full h-full flex items-center justify-center text-6xl">{emoji}</div>
        )}
        {badge && (
          <span
            className="absolute top-2 left-2 px-2 py-0.5 rounded-md text-xs font-bold uppercase tracking-wider"
            style={{ background: badge.color_bg, color: badge.color_text }}
          >
            {badge.label}
          </span>
        )}
        {product.is_featured && (
          <span
            className="absolute top-2 right-2 px-1.5 py-0.5 rounded-md text-[10px] font-bold uppercase tracking-wider bg-amber-400/95 text-amber-950"
            title="Sélection"
          >
            ⭐ Sélection
          </span>
        )}
      </div>
      <div className="p-3 flex flex-col gap-1 flex-1">
        <span className="text-xs text-sub uppercase tracking-wide">{categoryName}</span>
        <h3 className="font-medium text-sm line-clamp-2 flex-1">{product.name}</h3>
        <div className="flex items-center justify-between pt-1">
          <div className="flex items-baseline gap-1.5">
            <span className="font-bold">
              {product.price_eur_computed != null
                ? `€${Number(product.price_eur_computed).toFixed(2)}`
                : product.price_eur != null
                  ? `${product.price_eur} €`
                  : '—'}
            </span>
            {product.price_cny_numeric != null && (
              <span className="text-xs text-sub">¥{product.price_cny_numeric}</span>
            )}
          </div>
          {product.links_count !== undefined && (
            <span className="text-xs text-sub">
              {product.links_count} agent{product.links_count > 1 ? 's' : ''}
            </span>
          )}
        </div>
      </div>
    </Link>
  );
}
