import { createContext, useContext, useEffect, useState, useCallback, useRef } from 'react';
import { api } from '../api.js';

const SiteCtx = createContext(null);
const CACHE_MS = 60 * 1000;

const FALLBACK = {
  site_name: 'Haulo',
  site_tagline: 'Trouve tes produits chez les meilleurs agents',
  site_subtitle: '',
};

export function SiteProvider({ children }) {
  const [settings, setSettings] = useState(FALLBACK);
  const [socialLinks, setSocialLinks] = useState([]);
  const [loaded, setLoaded] = useState(false);
  const lastFetch = useRef(0);

  const reload = useCallback(async () => {
    try {
      const [s, links] = await Promise.all([api.getSettings(), api.listSocialLinks()]);
      setSettings({ ...FALLBACK, ...s });
      setSocialLinks(links || []);
      lastFetch.current = Date.now();
      setLoaded(true);
    } catch (e) {
      setLoaded(true);
    }
  }, []);

  // Charge une seule fois au mount, puis respecte le cache 60s
  useEffect(() => {
    if (Date.now() - lastFetch.current > CACHE_MS) reload();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  // Met à jour document.title quand le nom change
  useEffect(() => {
    if (settings?.site_name) document.title = settings.site_name;
  }, [settings.site_name]);

  return (
    <SiteCtx.Provider value={{ settings, socialLinks, loaded, reload }}>
      {children}
    </SiteCtx.Provider>
  );
}

export function useSite() {
  const ctx = useContext(SiteCtx);
  if (!ctx) throw new Error('useSite must be used inside SiteProvider');
  return ctx;
}
