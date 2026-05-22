const express = require('express');
const db = require('../db');
const { requireAuth } = require('../middleware/auth');
const validateBody = require('../middleware/validate');
const { platformSchema, platformPatchSchema } = require('../validators');

function slugify(s) {
  return String(s)
    .normalize('NFD').replace(/[̀-ͯ]/g, '')
    .toLowerCase().trim()
    .replace(/[^a-z0-9]+/g, '-')
    .replace(/^-+|-+$/g, '');
}

function validateHex(c) {
  return typeof c === 'string' && /^#[0-9a-fA-F]{3}([0-9a-fA-F]{3})?$/.test(c);
}

// ---------- Public ----------
const publicRouter = express.Router();

publicRouter.get('/', (req, res) => {
  const includeInactive = req.query.include_inactive === '1';
  // include_inactive sur le routeur public n'a plus d'effet ici (backward compat)
  const rows = includeInactive
    ? db.prepare('SELECT * FROM platforms ORDER BY sort_order, id').all()
    : db.prepare('SELECT * FROM platforms WHERE is_active = 1 ORDER BY sort_order, id').all();
  res.json(rows);
});

// ---------- Admin ----------
const adminRouter = express.Router();
adminRouter.use(requireAuth);

adminRouter.get('/', (_, res) => {
  res.json(db.prepare('SELECT * FROM platforms ORDER BY sort_order, id').all());
});

adminRouter.post('/', validateBody(platformSchema), (req, res) => {
  const { name, color_hex, tagline, register_url, is_active, sort_order } = req.body || {};
  if (!name || !name.trim()) return res.status(400).json({ error: 'name requis' });
  if (!validateHex(color_hex)) return res.status(400).json({ error: 'color_hex invalide (ex: #1D9E75)' });

  const slug = (req.body.slug && slugify(req.body.slug)) || slugify(name);
  if (!slug) return res.status(400).json({ error: 'Impossible de générer un slug à partir du nom' });

  const exists = db.prepare('SELECT id FROM platforms WHERE slug = ?').get(slug);
  if (exists) return res.status(409).json({ error: 'Un agent avec ce nom existe déjà' });

  const order = sort_order != null ? Number(sort_order)
                                   : (db.prepare('SELECT IFNULL(MAX(sort_order), 0) + 1 AS n FROM platforms').get().n);

  const info = db.prepare(`
    INSERT INTO platforms (slug, name, color_hex, tagline, register_url, is_active, sort_order)
    VALUES (?, ?, ?, ?, ?, ?, ?)
  `).run(slug, name.trim(), color_hex, tagline ?? null, register_url ?? '', is_active ? 1 : 0, order);

  res.status(201).json(
    db.prepare('SELECT * FROM platforms WHERE id = ?').get(Number(info.lastInsertRowid))
  );
});

adminRouter.put('/:id', validateBody(platformPatchSchema), (req, res) => {
  const existing = db.prepare('SELECT * FROM platforms WHERE id = ?').get(req.params.id);
  if (!existing) return res.status(404).json({ error: 'Agent introuvable' });

  const allowed = ['name', 'color_hex', 'tagline', 'register_url', 'is_active', 'sort_order', 'slug', 'url_template', 'affiliate_code'];
  const updates = {};
  for (const k of allowed) {
    if (req.body[k] === undefined) continue;
    let v = req.body[k];
    if (k === 'is_active') v = v ? 1 : 0;
    if (k === 'color_hex' && !validateHex(v)) return res.status(400).json({ error: 'color_hex invalide' });
    if (k === 'slug') {
      v = slugify(v);
      if (!v) return res.status(400).json({ error: 'slug invalide' });
      const conflict = db.prepare('SELECT id FROM platforms WHERE slug = ? AND id <> ?').get(v, req.params.id);
      if (conflict) return res.status(409).json({ error: 'Slug déjà utilisé' });
    }
    updates[k] = v;
  }
  if (!Object.keys(updates).length) return res.json(existing);
  const sets = Object.keys(updates).map((k) => `${k} = @${k}`).join(', ');
  db.prepare(`UPDATE platforms SET ${sets} WHERE id = @id`).run({ ...updates, id: Number(req.params.id) });
  res.json(db.prepare('SELECT * FROM platforms WHERE id = ?').get(req.params.id));
});

adminRouter.delete('/:id', (req, res) => {
  const existing = db.prepare('SELECT id, name FROM platforms WHERE id = ?').get(req.params.id);
  if (!existing) return res.status(404).json({ error: 'Agent introuvable' });
  const used = db.prepare('SELECT COUNT(*) AS c FROM affiliate_links WHERE platform_id = ?').get(req.params.id).c;
  if (used > 0) {
    return res.status(409).json({
      error: `Cet agent est utilisé par ${used} produit(s). Supprimez d'abord ses liens dans les fiches produit.`,
    });
  }
  db.prepare('DELETE FROM platforms WHERE id = ?').run(req.params.id);
  res.json({ ok: true });
});

module.exports = { publicRouter, adminRouter };
