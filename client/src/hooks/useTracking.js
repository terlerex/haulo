import { useEffect } from 'react';
import { useLocation } from 'react-router-dom';

// Fire-and-forget : une erreur réseau ne bloque jamais la navigation.
export function usePageView() {
  const location = useLocation();
  useEffect(() => {
    if (location.pathname.startsWith('/admin')) return;
    const timer = setTimeout(() => {
      fetch('/api/track/view', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          path: location.pathname,
          referrer: document.referrer || null,
        }),
      }).catch(() => {});
    }, 500);
    return () => clearTimeout(timer);
  }, [location.pathname]);
}

export function trackProductClick(productId) {
  fetch(`/api/track/product/${productId}`, { method: 'POST' }).catch(() => {});
}

// Renvoie l'URL à ouvrir (depuis la réponse serveur). Timeout 1s : si trop lent,
// on ouvre quand même l'URL fournie en fallback.
export async function trackAffiliateClick(productId, platformId, fallbackUrl) {
  const trackReq = fetch(`/api/track/affiliate/${productId}/${platformId}`, { method: 'POST' })
    .then((r) => (r.ok ? r.json() : null))
    .catch(() => null);
  const timeout = new Promise((resolve) => setTimeout(() => resolve(null), 1000));
  const result = await Promise.race([trackReq, timeout]);
  return result?.url || fallbackUrl;
}
