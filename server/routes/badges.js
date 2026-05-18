const express = require('express');
const db = require('../db');
const { requireAuth } = require('../middleware/auth');
const validateBody = require('../middleware/validate');
const { badgeSchema } = require('../validators');

const router = express.Router();

router.get('/', (_, res) => {
  res.json(db.prepare('SELECT * FROM badges ORDER BY id').all());
});

router.post('/', requireAuth, validateBody(badgeSchema), (req, res) => {
  const { slug, label, color_bg, color_text } = req.body || {};
  if (!slug || !label || !color_bg || !color_text) {
    return res.status(400).json({ error: 'slug, label, color_bg, color_text requis' });
  }
  const cleanSlug = String(slug).toLowerCase().trim();
  const exists = db.prepare('SELECT id FROM badges WHERE slug = ?').get(cleanSlug);
  if (exists) return res.status(409).json({ error: 'Slug déjà utilisé' });
  const info = db.prepare(
    'INSERT INTO badges (slug, label, color_bg, color_text) VALUES (?, ?, ?, ?)'
  ).run(cleanSlug, label, color_bg, color_text);
  res.status(201).json(db.prepare('SELECT * FROM badges WHERE id = ?').get(Number(info.lastInsertRowid)));
});

router.delete('/:id', requireAuth, (req, res) => {
  const used = db.prepare(
    'SELECT COUNT(*) AS c FROM products WHERE badge_id = ? AND is_active = 1'
  ).get(req.params.id).c;
  if (used > 0) {
    return res.status(409).json({ error: `${used} produit(s) utilisent ce badge` });
  }
  const info = db.prepare('DELETE FROM badges WHERE id = ?').run(req.params.id);
  if (!info.changes) return res.status(404).json({ error: 'Badge introuvable' });
  res.json({ ok: true });
});

module.exports = router;
