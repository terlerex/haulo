import { Navigate, useLocation } from 'react-router-dom';
import { useAuth } from '../context/AuthContext.jsx';

export default function ProtectedRoute({ children }) {
  const { user, checking, authError, refresh } = useAuth();
  const location = useLocation();

  if (checking) {
    return (
      <div className="min-h-screen flex items-center justify-center bg-ink">
        <div className="w-8 h-8 rounded-full border-2 border-zinc-700 border-t-white animate-spin" />
      </div>
    );
  }

  if (authError) {
    return (
      <div className="min-h-screen flex items-center justify-center bg-ink px-4">
        <div className="max-w-md text-center">
          <div className="text-5xl mb-3">⚠️</div>
          <h1 className="text-xl font-bold mb-2">Erreur de connexion</h1>
          <p className="text-sub text-sm mb-4">
            {authError === 'timeout'
              ? 'Le serveur met trop de temps à répondre.'
              : 'Impossible de joindre le serveur.'} Réessayez.
          </p>
          <button
            onClick={refresh}
            className="px-4 py-2 rounded-lg bg-emerald-600 hover:bg-emerald-500 font-semibold"
          >
            Réessayer
          </button>
        </div>
      </div>
    );
  }

  if (!user) {
    return <Navigate to="/admin/login" replace state={{ from: location }} />;
  }

  return children;
}
