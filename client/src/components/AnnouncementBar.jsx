import { useEffect, useState } from 'react';
import { useSite } from '../context/SiteContext.jsx';

const SS_KEY = 'announcement_dismissed';

export default function AnnouncementBar() {
  const { settings } = useSite();
  const message = settings?.hero_badge?.trim();
  const [dismissed, setDismissed] = useState(false);

  useEffect(() => {
    setDismissed(sessionStorage.getItem(SS_KEY) === message);
  }, [message]);

  if (!message || dismissed) return null;

  const close = () => {
    sessionStorage.setItem(SS_KEY, message);
    setDismissed(true);
  };

  return (
    <div className="bg-zinc-950 border-b border-zinc-800 text-sm">
      <div className="max-w-7xl mx-auto px-4 py-2 flex items-center justify-center gap-3">
        <span className="text-zinc-300">{message}</span>
        <button
          onClick={close}
          aria-label="Fermer"
          className="text-sub hover:text-white text-xs px-2"
        >
          ✕
        </button>
      </div>
    </div>
  );
}
