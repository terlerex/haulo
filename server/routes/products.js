const express = require('express');
const db = require('../db');
const { requireAuth } = require('../middleware/auth');
const { deleteUploadedFile } = require('./upload');

const router = express.Router();

const BASE_FIELDS = ['name', 'category_id', 'price_eur', 'price_cny', 'image_url', 'description', 'badge_id', 'is_active', 'is_featured'];

function normalizeProductInput(body, { partial = false } = {}) {
  const out = {};
  for (const k of BASE_FIELDS) {
    if (body[k] === undefined) {
      if (!partial && k === 'name') {
        const err = new Error('Field "name" is required');
        err.status = 400;
        throw err;
      }
      continue;
    }
    let v = body[k];
    if (k === 'is_active' || k === 'is_featured') v = v ? 1 : 0;
    if (k === 'category_id' || k === 'badge_id') {
      v = v === '' || v === null || v === undefined ? null : Number(v);
    }
    if (k === 'price_eur' || k === 'price_cny') {
      v = v === '' || v === null ? null : Number(v);
      if (v !== null && Number.isNaN(v)) {
        const err = new Error(`${k} must be a number`);
        err.status = 400;
        throw err;
      }
    }
    out[k] = v;
  }
  return out;
}

const PRODUCT_SELECT = `
  SELECT p.id, p.name, p.price_eur, p.price_cny, p.image_url, p.description,
         p.is_active, p.is_featured, p.created_at,
         p.category_id, c.name AS category_name, c.emoji AS category_emoji,
         p.badge_id, b.slug AS badge_slug, b.label AS badge_label,
         b.color_bg AS badge_color_bg, b.color_text AS badge_color_text,
         (SELECT COUNT(*) FROM affiliate_links al WHERE al.product_id = p.id) AS links_count
  FROM products p
  LEFT JOIN categories c ON c.id = p.category_id
  LEFT JOIN badges b ON b.id = p.badge_id
`;

function shapeProduct(row) {
  if (!row) return row;
  const out = {
    id: row.id,
    name: row.name,
    price_eur: row.price_eur,
    price_cny: row.price_cny,
    image_url: row.image_url,
    description: row.description,
    is_active: row.is_active,
    is_featured: !!row.is_featured,
    created_at: row.created_at,
    category_id: row.category_id,
    category: row.category_id
      ? { id: row.category_id, name: row.category_name, emoji: row.category_emoji }
      : null,
    badge_id: row.badge_id,
    badge: row.badge_id
      ? {
          id: row.badge_id,
          slug: row.badge_slug,
          label: row.badge_label,
          color_bg: row.badge_color_bg,
          color_text: row.badge_color_text,
        }
      : null,
    links_count: row.links_count,
  };
  return out;
}

// GET /api/products
router.get('/', (req, res) => {
  const { category_id, search } = req.query;
  const limit = Math.min(parseInt(req.query.limit, 10) || 24, 200);
  const offset = parseInt(req.query.offset, 10) || 0;

  const where = [];
  const params = [];
  const includeInactive = req.query.include_inactive === '1';
  if (!includeInactive) where.push('p.is_active = 1');

  if (category_id) {
    where.push('p.category_id = ?');
    params.push(Number(category_id));
  }
  if (search) {
    where.push('(p.name LIKE ? OR p.description LIKE ?)');
    const s = `%${search}%`;
    params.push(s, s);
  }
  const whereSql = where.length ? `WHERE ${where.join(' AND ')}` : '';

  const rows = db.prepare(`
    ${PRODUCT_SELECT}
    ${whereSql}
    ORDER BY p.is_featured DESC, p.created_at DESC, p.id DESC
    LIMIT ? OFFSET ?
  `).all(...params, limit, offset);

  const total = db.prepare(`SELECT COUNT(*) AS c FROM products p ${whereSql}`).get(...params).c;
  res.json({ items: rows.map(shapeProduct), total, limit, offset });
});

router.get('/:id', (req, res) => {
  const row = db.prepare(`${PRODUCT_SELECT} WHERE p.id = ?`).get(req.params.id);
  if (!row) return res.status(404).json({ error: 'Not found' });
  const product = shapeProduct(row);
  product.links = db.prepare(`
    SELECT al.id, al.platform_id, al.url, al.price_cny,
           pl.slug, pl.name, pl.color_hex, pl.tagline, pl.register_url
    FROM affiliate_links al
    JOIN platforms pl ON pl.id = al.platform_id
    WHERE al.product_id = ? AND pl.is_active = 1
    ORDER BY pl.sort_order, pl.id
  `).all(req.params.id);
  res.json(product);
});

router.post('/', requireAuth, (req, res) => {
  const data = normalizeProductInput(req.body);
  const stmt = db.prepare(`
    INSERT INTO products (name, category_id, price_eur, price_cny, image_url, description, badge_id, is_active, is_featured)
    VALUES (@name, @category_id, @price_eur, @price_cny, @image_url, @description, @badge_id, @is_active, @is_featured)
  `);
  const filled = {
    name: data.name,
    category_id: data.category_id ?? null,
    price_eur: data.price_eur ?? null,
    price_cny: data.price_cny ?? null,
    image_url: data.image_url ?? null,
    description: data.description ?? null,
    badge_id: data.badge_id ?? null,
    is_active: data.is_active ?? 1,
    is_featured: data.is_featured ?? 0,
  };
  const info = stmt.run(filled);
  const row = db.prepare(`${PRODUCT_SELECT} WHERE p.id = ?`).get(Number(info.lastInsertRowid));
  res.status(201).json(shapeProduct(row));
});

router.put('/:id', requireAuth, (req, res) => {
  const existing = db.prepare('SELECT image_url FROM products WHERE id = ?').get(req.params.id);
  if (!existing) return res.status(404).json({ error: 'Not found' });
  const data = normalizeProductInput(req.body, { partial: true });
  if (!Object.keys(data).length) {
    const row = db.prepare(`${PRODUCT_SELECT} WHERE p.id = ?`).get(req.params.id);
    return res.json(shapeProduct(row));
  }

  // si on remplace image_url et que l'ancienne était un upload local, on la supprime
  if (data.image_url !== undefined && data.image_url !== existing.image_url) {
    deleteUploadedFile(existing.image_url);
  }

  const sets = Object.keys(data).map((k) => `${k} = @${k}`).join(', ');
  db.prepare(`UPDATE products SET ${sets} WHERE id = @id`).run({ ...data, id: Number(req.params.id) });
  const row = db.prepare(`${PRODUCT_SELECT} WHERE p.id = ?`).get(req.params.id);
  res.json(shapeProduct(row));
});

router.delete('/:id', requireAuth, (req, res) => {
  const existing = db.prepare('SELECT image_url FROM products WHERE id = ?').get(req.params.id);
  if (!existing) return res.status(404).json({ error: 'Not found' });
  // soft delete : on garde l'image pour l'instant (le produit pourrait être réactivé)
  const info = db.prepare('UPDATE products SET is_active = 0 WHERE id = ?').run(req.params.id);
  if (!info.changes) return res.status(404).json({ error: 'Not found' });
  res.json({ ok: true });
});

router.post('/:id/links', requireAuth, (req, res) => {
  const { platform_id, url, price_cny } = req.body || {};
  if (!platform_id || !url) return res.status(400).json({ error: 'platform_id et url requis' });
  const product = db.prepare('SELECT id FROM products WHERE id = ?').get(req.params.id);
  if (!product) return res.status(404).json({ error: 'Produit introuvable' });
  const platform = db.prepare('SELECT id FROM platforms WHERE id = ?').get(platform_id);
  if (!platform) return res.status(400).json({ error: 'platform_id invalide' });

  const existing = db.prepare(
    'SELECT id FROM affiliate_links WHERE product_id = ? AND platform_id = ?'
  ).get(req.params.id, platform_id);

  let row;
  if (existing) {
    db.prepare('UPDATE affiliate_links SET url = ?, price_cny = ? WHERE id = ?')
      .run(url, price_cny ?? null, existing.id);
    row = db.prepare('SELECT * FROM affiliate_links WHERE id = ?').get(existing.id);
  } else {
    const info = db.prepare(
      'INSERT INTO affiliate_links (product_id, platform_id, url, price_cny) VALUES (?, ?, ?, ?)'
    ).run(req.params.id, platform_id, url, price_cny ?? null);
    row = db.prepare('SELECT * FROM affiliate_links WHERE id = ?').get(Number(info.lastInsertRowid));
  }
  res.json(row);
});

router.delete('/:id/links/:lid', requireAuth, (req, res) => {
  const info = db.prepare('DELETE FROM affiliate_links WHERE id = ? AND product_id = ?')
    .run(req.params.lid, req.params.id);
  if (!info.changes) return res.status(404).json({ error: 'Not found' });
  res.json({ ok: true });
});

module.exports = router;
