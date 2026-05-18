import { useEffect, useState } from 'react';
import { Link } from 'react-router-dom';
import { api } from '../../api.js';
import { useToast } from '../../components/Toast.jsx';

export default function ProductsList() {
  const [items, setItems] = useState([]);
  const [loading, setLoading] = useState(true);
  const toast = useToast();

  const load = () => {
    setLoading(true);
    api.listProducts({ include_inactive: 1, limit: 200 })
      .then((d) => setItems(d.items))
      .finally(() => setLoading(false));
  };

  useEffect(() => { load(); }, []);

  const toggleActive = async (p) => {
    try {
      await api.updateProduct(p.id, { is_active: !p.is_active });
      toast.success(p.is_active ? 'Produit désactivé' : 'Produit activé');
      load();
    } catch (e) { toast.error(e.message); }
  };

  const toggleFeatured = async (p) => {
    try {
      await api.updateProduct(p.id, { is_featured: !p.is_featured });
      toast.success(p.is_featured ? 'Retiré de la sélection' : 'Mis en avant');
      load();
    } catch (e) { toast.error(e.message); }
  };

  const remove = async (p) => {
    if (!confirm(`Supprimer "${p.name}" ? (soft delete — il sera désactivé)`)) return;
    try {
      await api.deleteProduct(p.id);
      toast.success('Produit supprimé');
      load();
    } catch (e) { toast.error(e.message); }
  };

  return (
    <div className="max-w-7xl mx-auto px-4 py-8">
      <div className="flex items-center justify-between mb-6">
        <h1 className="text-2xl font-bold">Produits ({items.length})</h1>
        <Link to="/admin/products/new" className="px-4 py-2 rounded-lg bg-emerald-600 text-white font-semibold hover:bg-emerald-500">
          + Nouveau produit
        </Link>
      </div>

      <div className="rounded-xl border border-zinc-800 overflow-hidden bg-zinc-900">
        <table className="w-full text-sm">
          <thead className="bg-zinc-950 text-sub text-xs uppercase">
            <tr>
              <th className="text-left p-3"></th>
              <th className="text-center p-3 w-8">⭐</th>
              <th className="text-left p-3">Nom</th>
              <th className="text-left p-3 hidden sm:table-cell">Catégorie</th>
              <th className="text-left p-3 hidden md:table-cell">Prix €</th>
              <th className="text-left p-3 hidden md:table-cell">Liens</th>
              <th className="text-left p-3">Statut</th>
              <th className="text-right p-3">Actions</th>
            </tr>
          </thead>
          <tbody>
            {loading && (<tr><td colSpan={8} className="p-8 text-center text-sub">Chargement…</td></tr>)}
            {!loading && items.length === 0 && (<tr><td colSpan={8} className="p-8 text-center text-sub">Aucun produit.</td></tr>)}
            {items.map((p) => (
              <tr key={p.id} className="border-t border-zinc-800">
                <td className="p-2 w-14">
                  {p.image_url ? (
                    <img src={p.image_url} alt="" className="w-10 h-10 object-cover rounded-md" />
                  ) : (
                    <div className="w-10 h-10 flex items-center justify-center bg-zinc-800 rounded-md text-xl">
                      {p.category?.emoji || '📦'}
                    </div>
                  )}
                </td>
                <td className="p-3 text-center">
                  <button
                    onClick={() => toggleFeatured(p)}
                    title={p.is_featured ? 'Retirer de la sélection' : 'Mettre en avant'}
                    className={`text-xl leading-none ${p.is_featured ? 'text-amber-400' : 'text-zinc-700 hover:text-amber-400'}`}
                  >
                    {p.is_featured ? '★' : '☆'}
                  </button>
                </td>
                <td className="p-3 font-medium">{p.name}</td>
                <td className="p-3 hidden sm:table-cell text-sub">{p.category?.name || '—'}</td>
                <td className="p-3 hidden md:table-cell">{p.price_eur ?? '—'}</td>
                <td className="p-3 hidden md:table-cell text-sub">{p.links_count}</td>
                <td className="p-3">
                  <span className={`px-2 py-0.5 rounded-md text-xs font-semibold ${p.is_active ? 'bg-emerald-900/50 text-emerald-300' : 'bg-zinc-800 text-sub'}`}>
                    {p.is_active ? 'Actif' : 'Inactif'}
                  </span>
                </td>
                <td className="p-3 text-right">
                  <div className="inline-flex gap-1">
                    <Link to={`/admin/products/${p.id}/edit`} className="px-2 py-1 rounded-md bg-zinc-800 hover:bg-zinc-700 text-xs">Éditer</Link>
                    <button onClick={() => toggleActive(p)} className="px-2 py-1 rounded-md bg-zinc-800 hover:bg-zinc-700 text-xs">
                      {p.is_active ? 'Désactiver' : 'Activer'}
                    </button>
                    <button onClick={() => remove(p)} className="px-2 py-1 rounded-md bg-red-900/40 hover:bg-red-800/60 text-xs text-red-200">Suppr</button>
                  </div>
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </div>
  );
}
