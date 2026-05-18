const express = require('express');
const db = require('../db');
const { requireAuth } = require('../middleware/auth');
const validateBody = require('../middleware/validate');
const { socialLinkSchema, socialLinkPatchSchema } = require('../validators');

// Routeur public — uniquement les liens actifs
const publicRouter = express.Router();
publicRouter.get('/', (_, res) => {
  const rows = db.prepare(
    'SELECT * FROM social_links WHERE is_active = 1 ORDER BY sort_order, id'
  ).all();
  res.json(rows);
});

// Routeur admin — CRUD complet
const adminRouter = express.Router();
adminRouter.use(requireAuth);

adminRouter.get('/', (_, res) => {
  res.json(db.prepare('SELECT * FROM social_links ORDER BY sort_order, id').all());
});

adminRouter.post('/', validateBody(socialLinkSchema), (req, res) => {
  const { platform, label, url, icon, sort_order, is_active } = req.body || {};
  if (!platform || !label) return res.status(400).json({ error: 'platform et label requis' });
  const info = db.prepare(
    'INSERT INTO social_links (platform, label, url, icon_name, sort_order, is_active) VALUES (?, ?, ?, ?, ?, ?)'
  ).run(
    platform,
    label,
    url ?? '',
    icon ?? null,
    sort_order ?? 0,
    is_active ? 1 : 0
  );
  res.status(201).json(db.prepare('SELECT * FROM social_links WHERE id = ?').get(Number(info.lastInsertRowid)));
});

adminRouter.put('/:id', validateBody(socialLinkPatchSchema), (req, res) => {
  const existing = db.prepare('SELECT * FROM social_links WHERE id = ?').get(req.params.id);
  if (!existing) return res.status(404).json({ error: 'Lien introuvable' });
  const allowed = ['platform', 'label', 'url', 'icon_name', 'sort_order', 'is_active'];
  const updates = {};
  for (const k of allowed) {
    if (req.body[k] !== undefined) {
      updates[k] = k === 'is_active' ? (req.body[k] ? 1 : 0) : req.body[k];
    }
  }
  // accept "icon" alias
  if (req.body.icon !== undefined && updates.icon_name === undefined) {
    updates.icon_name = req.body.icon;
  }
  if (!Object.keys(updates).length) return res.json(existing);
  const sets = Object.keys(updates).map((k) => `${k} = @${k}`).join(', ');
  db.prepare(`UPDATE social_links SET ${sets} WHERE id = @id`).run({ ...updates, id: Number(req.params.id) });
  res.json(db.prepare('SELECT * FROM social_links WHERE id = ?').get(req.params.id));
});

adminRouter.delete('/:id', (req, res) => {
  const info = db.prepare('DELETE FROM social_links WHERE id = ?').run(req.params.id);
  if (!info.changes) return res.status(404).json({ error: 'Lien introuvable' });
  res.json({ ok: true });
});

module.exports = { publicRouter, adminRouter };
