import { useEffect, useState } from 'react';
import { api } from '../../api.js';
import { useToast } from '../../components/Toast.jsx';
import { useAuth } from '../../context/AuthContext.jsx';

export default function Settings() {
  const [users, setUsers] = useState([]);
  const [loading, setLoading] = useState(true);
  const toast = useToast();
  const { user: me } = useAuth();

  const [newUsername, setNewUsername] = useState('');
  const [newPassword, setNewPassword] = useState('');
  const [addBusy, setAddBusy] = useState(false);

  const [currentPwd, setCurrentPwd] = useState('');
  const [newPwd, setNewPwd] = useState('');
  const [confirmPwd, setConfirmPwd] = useState('');
  const [pwdBusy, setPwdBusy] = useState(false);

  const load = () => {
    setLoading(true);
    api.listUsers().then(setUsers).finally(() => setLoading(false));
  };
  useEffect(() => { load(); }, []);

  const addUser = async (e) => {
    e.preventDefault();
    if (!newUsername.trim() || newPassword.length < 8) {
      return toast.error('Username requis, mot de passe ≥ 8 caractères');
    }
    setAddBusy(true);
    try {
      await api.createUser({ username: newUsername, password: newPassword });
      toast.success('Utilisateur créé');
      setNewUsername(''); setNewPassword('');
      load();
    } catch (err) { toast.error(err.message); }
    finally { setAddBusy(false); }
  };

  const removeUser = async (u) => {
    if (!confirm(`Supprimer l'utilisateur "${u.username}" ?`)) return;
    try {
      await api.deleteUser(u.id);
      toast.success('Utilisateur supprimé');
      load();
    } catch (err) { toast.error(err.message); }
  };

  const changePwd = async (e) => {
    e.preventDefault();
    if (newPwd !== confirmPwd) return toast.error('Les mots de passe ne correspondent pas');
    if (newPwd.length < 8) return toast.error('Nouveau mot de passe ≥ 8 caractères');
    setPwdBusy(true);
    try {
      await api.changePassword(me.id, { current_password: currentPwd, new_password: newPwd });
      toast.success('Mot de passe changé');
      setCurrentPwd(''); setNewPwd(''); setConfirmPwd('');
    } catch (err) { toast.error(err.message); }
    finally { setPwdBusy(false); }
  };

  return (
    <div className="max-w-4xl mx-auto px-4 py-8 space-y-10">
      <div>
        <h1 className="text-2xl font-bold mb-1">Utilisateurs admin</h1>
        <p className="text-sub text-sm mb-4">Gestion des comptes ayant accès au back-office.</p>

        <div className="rounded-xl border border-zinc-800 overflow-hidden bg-zinc-900 mb-6">
          <table className="w-full text-sm">
            <thead className="bg-zinc-950 text-sub text-xs uppercase">
              <tr>
                <th className="text-left p-3">Username</th>
                <th className="text-left p-3 hidden sm:table-cell">Créé le</th>
                <th className="text-left p-3 hidden md:table-cell">Dernière connexion</th>
                <th className="text-right p-3">Actions</th>
              </tr>
            </thead>
            <tbody>
              {loading && <tr><td colSpan={4} className="p-6 text-center text-sub">Chargement…</td></tr>}
              {users.map((u) => (
                <tr key={u.id} className="border-t border-zinc-800">
                  <td className="p-3 font-medium">
                    {u.username} {u.id === me?.id && <span className="text-xs text-emerald-400 ml-1">(vous)</span>}
                  </td>
                  <td className="p-3 hidden sm:table-cell text-sub">{u.created_at}</td>
                  <td className="p-3 hidden md:table-cell text-sub">{u.last_login || '—'}</td>
                  <td className="p-3 text-right">
                    <button
                      disabled={u.id === me?.id}
                      onClick={() => removeUser(u)}
                      className="px-2 py-1 rounded-md bg-red-900/40 hover:bg-red-800/60 text-xs text-red-200 disabled:opacity-30"
                      title={u.id === me?.id ? 'Vous ne pouvez pas vous supprimer' : ''}
                    >
                      Supprimer
                    </button>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>

        <h2 className="text-lg font-semibold mb-3">Ajouter un utilisateur</h2>
        <form onSubmit={addUser} className="rounded-xl border border-zinc-800 bg-zinc-900 p-4 grid sm:grid-cols-2 gap-3">
          <label>
            <span className="block text-xs uppercase tracking-wider text-sub mb-1">Username</span>
            <input value={newUsername} onChange={(e) => setNewUsername(e.target.value)} className="w-full bg-ink border border-zinc-800 rounded-md px-3 py-2 text-sm" />
          </label>
          <label>
            <span className="block text-xs uppercase tracking-wider text-sub mb-1">Mot de passe (8+)</span>
            <input type="password" value={newPassword} onChange={(e) => setNewPassword(e.target.value)} className="w-full bg-ink border border-zinc-800 rounded-md px-3 py-2 text-sm" />
          </label>
          <div className="sm:col-span-2 flex justify-end">
            <button type="submit" disabled={addBusy} className="px-4 py-2 rounded-lg bg-emerald-600 hover:bg-emerald-500 font-semibold disabled:opacity-50">
              {addBusy ? 'Création…' : 'Créer'}
            </button>
          </div>
        </form>
      </div>

      <div>
        <h2 className="text-lg font-semibold mb-3">Changer mon mot de passe</h2>
        <form onSubmit={changePwd} className="rounded-xl border border-zinc-800 bg-zinc-900 p-4 grid sm:grid-cols-3 gap-3">
          <label>
            <span className="block text-xs uppercase tracking-wider text-sub mb-1">Actuel</span>
            <input type="password" value={currentPwd} onChange={(e) => setCurrentPwd(e.target.value)} className="w-full bg-ink border border-zinc-800 rounded-md px-3 py-2 text-sm" />
          </label>
          <label>
            <span className="block text-xs uppercase tracking-wider text-sub mb-1">Nouveau</span>
            <input type="password" value={newPwd} onChange={(e) => setNewPwd(e.target.value)} className="w-full bg-ink border border-zinc-800 rounded-md px-3 py-2 text-sm" />
          </label>
          <label>
            <span className="block text-xs uppercase tracking-wider text-sub mb-1">Confirmer</span>
            <input type="password" value={confirmPwd} onChange={(e) => setConfirmPwd(e.target.value)} className="w-full bg-ink border border-zinc-800 rounded-md px-3 py-2 text-sm" />
          </label>
          <div className="sm:col-span-3 flex justify-end">
            <button type="submit" disabled={pwdBusy} className="px-4 py-2 rounded-lg bg-emerald-600 hover:bg-emerald-500 font-semibold disabled:opacity-50">
              {pwdBusy ? 'Enregistrement…' : 'Changer'}
            </button>
          </div>
        </form>
      </div>
    </div>
  );
}
