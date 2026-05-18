import { useState } from 'react';
import { Link, Navigate, useLocation, useNavigate } from 'react-router-dom';
import { useAuth } from '../../context/AuthContext.jsx';
import { useSite } from '../../context/SiteContext.jsx';

export default function Login() {
  const { user, login, checking } = useAuth();
  const { settings } = useSite();
  const [username, setUsername] = useState('');
  const [password, setPassword] = useState('');
  const [showPwd, setShowPwd] = useState(false);
  const [error, setError] = useState(null);
  const [busy, setBusy] = useState(false);
  const nav = useNavigate();
  const location = useLocation();

  if (!checking && user) {
    const dest = location.state?.from?.pathname || '/admin';
    return <Navigate to={dest} replace />;
  }

  const submit = async (e) => {
    e.preventDefault();
    setError(null);
    setBusy(true);
    try {
      await login(username, password);
      nav(location.state?.from?.pathname || '/admin', { replace: true });
    } catch (err) {
      setError(err.message || 'Erreur de connexion');
    } finally {
      setBusy(false);
    }
  };

  return (
    <div className="min-h-screen flex items-center justify-center bg-ink px-4">
      <div className="w-full max-w-sm">
        <Link to="/" className="text-sub hover:text-white text-sm">← Retour site</Link>
        <h1 className="mt-4 text-2xl font-bold">Connexion admin</h1>
        <p className="text-sm text-sub mt-1">Accède au back-office {settings?.site_name || ''}.</p>

        <form onSubmit={submit} className="mt-6 space-y-3">
          <label className="block">
            <span className="text-xs uppercase tracking-wider text-sub block mb-1">Username</span>
            <input
              autoFocus
              required
              value={username}
              onChange={(e) => setUsername(e.target.value)}
              className="w-full rounded-lg bg-zinc-900 border border-zinc-800 px-4 py-2.5 focus:outline-none focus:border-zinc-500"
            />
          </label>
          <label className="block">
            <span className="text-xs uppercase tracking-wider text-sub block mb-1">Mot de passe</span>
            <div className="relative">
              <input
                required
                type={showPwd ? 'text' : 'password'}
                value={password}
                onChange={(e) => setPassword(e.target.value)}
                className="w-full rounded-lg bg-zinc-900 border border-zinc-800 px-4 py-2.5 pr-16 focus:outline-none focus:border-zinc-500"
              />
              <button
                type="button"
                onClick={() => setShowPwd((v) => !v)}
                className="absolute right-2 top-1/2 -translate-y-1/2 text-xs text-sub hover:text-white px-2 py-1"
              >
                {showPwd ? 'Cacher' : 'Voir'}
              </button>
            </div>
          </label>

          {error && (
            <div className="text-sm text-red-400 bg-red-950/40 border border-red-900/50 rounded-md px-3 py-2">
              {error}
            </div>
          )}

          <button
            type="submit"
            disabled={busy}
            className="w-full py-2.5 rounded-lg bg-white text-ink font-semibold hover:bg-zinc-200 disabled:opacity-50"
          >
            {busy ? 'Connexion…' : 'Se connecter'}
          </button>
        </form>

        <p className="mt-6 text-xs text-sub">
          Par défaut : <code className="text-zinc-300">admin</code> / <code className="text-zinc-300">admin1234</code>
        </p>
      </div>
    </div>
  );
}
