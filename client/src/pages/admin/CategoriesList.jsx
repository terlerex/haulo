import { useEffect, useState } from 'react';
import { api } from '../../api.js';
import { useToast } from '../../components/Toast.jsx';

export default function CategoriesList() {
  const [items, setItems] = useState([]);
  const [loading, setLoading] = useState(true);
  const [editingId, setEditingId] = useState(null);
  const [editName, setEditName] = useState('');
  const [editEmoji, setEditEmoji] = useState('');
  const toast = useToast();

  const [newName, setNewName] = useState('');
  const [newEmoji, setNewEmoji] = useState('');
  const [saving, setSaving] = useState(false);

  const load = () => {
    setLoading(true);
    api.listCategories().then(setItems).finally(() => setLoading(false));
  };
  useEffect(() => { load(); }, []);

  const startEdit = (c) => {
    setEditingId(c.id);
    setEditName(c.name);
    setEditEmoji(c.emoji || '');
  };
  const cancelEdit = () => { setEditingId(null); };

  const saveEdit = async (c) => {
    try {
      await api.updateCategory(c.id, { name: editName, emoji: editEmoji });
      toast.success('Catégorie modifiée');
      setEditingId(null);
      load();
    } catch (err) { toast.error(err.message); }
  };

  const move = async (idx, dir) => {
    const target = idx + dir;
    if (target < 0 || target >= items.length) return;
    const a = items[idx], b = items[target];
    try {
      await api.updateCategory(a.id, { sort_order: b.sort_order });
      await api.updateCategory(b.id, { sort_order: a.sort_order });
      load();
    } catch (err) { toast.error(err.message); }
  };

  const remove = async (c) => {
    if (!confirm(`Supprimer "${c.name}" ?`)) return;
    try {
      await api.deleteCategory(c.id);
      toast.success('Catégorie supprimée');
      load();
    } catch (err) { toast.error(err.message); }
  };

  const add = async (e) => {
    e.preventDefault();
    if (!newName.trim()) return toast.error('Nom requis');
    setSaving(true);
    try {
      const sort_order = items.length;
      await api.createCategory({ name: newName, emoji: newEmoji, sort_order });
      toast.success('Catégorie ajoutée');
      setNewName(''); setNewEmoji('');
      load();
    } catch (err) { toast.error(err.message); }
    finally { setSaving(false); }
  };

  return (
    <div className="max-w-4xl mx-auto px-4 py-8">
      <h1 className="text-2xl font-bold mb-1">Catégories</h1>
      <p className="text-sub text-sm mb-6">Catégories de produits utilisées sur le catalogue et le formulaire.</p>

      {loading ? (
        <div className="text-sub">Chargement…</div>
      ) : (
        <ul className="space-y-2 mb-8">
          {items.map((c, idx) => (
            <li key={c.id} className="rounded-xl border border-zinc-800 bg-zinc-900 p-3 flex items-center gap-3">
              <div className="flex items-center gap-1">
                <button onClick={() => move(idx, -1)} disabled={idx === 0} className="px-2 py-1 rounded bg-zinc-800 hover:bg-zinc-700 disabled:opacity-30 text-xs">↑</button>
                <button onClick={() => move(idx, +1)} disabled={idx === items.length - 1} className="px-2 py-1 rounded bg-zinc-800 hover:bg-zinc-700 disabled:opacity-30 text-xs">↓</button>
              </div>

              {editingId === c.id ? (
                <>
                  <input
                    value={editEmoji}
                    maxLength={4}
                    onChange={(e) => setEditEmoji(e.target.value)}
                    className="w-14 text-center bg-ink border border-zinc-800 rounded-md py-1.5 text-lg"
                  />
                  <input
                    value={editName}
                    onChange={(e) => setEditName(e.target.value)}
                    className="flex-1 bg-ink border border-zinc-800 rounded-md px-3 py-1.5"
                  />
                  <button onClick={() => saveEdit(c)} className="px-3 py-1.5 rounded-md bg-emerald-600 hover:bg-emerald-500 text-sm">OK</button>
                  <button onClick={cancelEdit} className="px-3 py-1.5 rounded-md bg-zinc-800 hover:bg-zinc-700 text-sm">Annuler</button>
                </>
              ) : (
                <>
                  <span className="text-2xl w-10 text-center">{c.emoji || '·'}</span>
                  <button onClick={() => startEdit(c)} className="flex-1 text-left font-medium hover:text-emerald-300">
                    {c.name}
                  </button>
                  <span className="text-xs text-sub">{c.products_count} produit{c.products_count > 1 ? 's' : ''}</span>
                  <button onClick={() => remove(c)} className="px-2 py-1 rounded-md bg-red-900/40 hover:bg-red-800/60 text-xs text-red-200">Suppr</button>
                </>
              )}
            </li>
          ))}
        </ul>
      )}

      <h2 className="text-lg font-semibold mb-3">Ajouter une catégorie</h2>
      <form onSubmit={add} className="rounded-xl border border-zinc-800 bg-zinc-900 p-4 flex flex-wrap gap-3 items-end">
        <label className="block">
          <span className="block text-xs uppercase tracking-wider text-sub mb-1">Emoji</span>
          <input value={newEmoji} maxLength={4} onChange={(e) => setNewEmoji(e.target.value)} className="w-16 text-center bg-ink border border-zinc-800 rounded-md py-2 text-lg" placeholder="🎁" />
        </label>
        <label className="block flex-1 min-w-[200px]">
          <span className="block text-xs uppercase tracking-wider text-sub mb-1">Nom</span>
          <input value={newName} onChange={(e) => setNewName(e.target.value)} className="w-full bg-ink border border-zinc-800 rounded-md px-3 py-2 text-sm" placeholder="Cadeaux" />
        </label>
        <button type="submit" disabled={saving} className="px-4 py-2 rounded-lg bg-emerald-600 hover:bg-emerald-500 font-semibold disabled:opacity-50">
          {saving ? 'Ajout…' : 'Ajouter'}
        </button>
      </form>
    </div>
  );
}
