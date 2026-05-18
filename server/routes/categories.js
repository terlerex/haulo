const express = require('express');
const db = require('../db');
const { requireAuth } = require('../middleware/auth');
const validateBody = require('../middleware/validate');
const { categorySchema, categoryPatchSchema } = require('../validators');

const router = express.Router();

router.get('/', (_, res) => {
  const rows = db.prepare(`
    SELECT c.*,
      (SELECT COUNT(*) FROM products p WHERE p.category_id = c.id AND p.is_active = 1) AS products_count
    FROM categories c
    ORDER BY c.sort_order, c.id
  `).all();
  res.json(rows);
});

router.post('/', requireAuth, validateBody(categorySchema), (req, res) => {
  const { name, emoji, sort_order } = req.body || {};
  if (!name) return res.status(400).json({ error: 'name requis' });
  const exists = db.prepare('SELECT id FROM categories WHERE name = ?').get(name);
  if (exists) return res.status(409).json({ error: 'Nom déjà utilisé' });
  const info = db.prepare(
    'INSERT INTO categories (name, emoji, sort_order) VALUES (?, ?, ?)'
  ).run(name, emoji ?? null, sort_order ?? 0);
  res.status(201).json(db.prepare('SELECT * FROM categories WHERE id = ?').get(Number(info.lastInsertRowid)));
});

router.put('/:id', requireAuth, validateBody(categoryPatchSchema), (req, res) => {
  const existing = db.prepare('SELECT * FROM categories WHERE id = ?').get(req.params.id);
  if (!existing) return res.status(404).json({ error: 'Catégorie introuvable' });
  const allowed = ['name', 'emoji', 'sort_order'];
  const updates = {};
  for (const k of allowed) if (req.body[k] !== undefined) updates[k] = req.body[k];
  if (!Object.keys(updates).length) return res.json(existing);
  const sets = Object.keys(updates).map((k) => `${k} = @${k}`).join(', ');
  db.prepare(`UPDATE categories SET ${sets} WHERE id = @id`).run({ ...updates, id: Number(req.params.id) });
  res.json(db.prepare('SELECT * FROM categories WHERE id = ?').get(req.params.id));
});

router.delete('/:id', requireAuth, (req, res) => {
  const used = db.prepare(
    'SELECT COUNT(*) AS c FROM products WHERE category_id = ? AND is_active = 1'
  ).get(req.params.id).c;
  if (used > 0) return res.status(409).json({ error: `${used} produit(s) utilisent cette catégorie` });
  const info = db.prepare('DELETE FROM categories WHERE id = ?').run(req.params.id);
  if (!info.changes) return res.status(404).json({ error: 'Catégorie introuvable' });
  res.json({ ok: true });
});

module.exports = router;
