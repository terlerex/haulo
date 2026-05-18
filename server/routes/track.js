// Tracking events. Routes publiques, rate-limitées, fire-and-forget côté client.
// RGPD : on ne stocke jamais d'IP en clair, uniquement des hashs MD5.

const express = require('express');
const crypto = require('crypto');
const db = require('../db');
const { makeRateLimit } = require('../middleware/rateLimit');
const validateBody = require('../middleware/validate');
const { trackViewSchema } = require('../validators');

const router = express.Router();
router.use(makeRateLimit(50));

const BOT_RE = /bot|crawler|spider|headless|http-client|curl|wget|python|requests/i;

function md5(s) {
  return crypto.createHash('md5').update(s).digest('hex');
}

function sessionHash(req) {
  const ip = req.ip || req.socket.remoteAddress || 'unknown';
  const ua = req.headers['user-agent'] || '';
  const day = new Date().toISOString().slice(0, 10);
  return md5(`${ip}|${ua}|${day}`);
}

function uaHash(req) {
  const ua = req.headers['user-agent'] || '';
  return md5(ua);
}

router.post('/view', validateBody(trackViewSchema), (req, res) => {
  const ua = req.headers['user-agent'] || '';
  if (BOT_RE.test(ua)) return res.json({ ok: true }); // ignore silencieusement

  const path = (req.body?.path || '').toString().slice(0, 500);
  if (!path) return res.json({ ok: true });

  const referrer = (req.body?.referrer || req.headers['referer'] || '').toString().slice(0, 500) || null;

  db.prepare(`
    INSERT INTO page_views (path, referrer, user_agent_hash, session_hash)
    VALUES (?, ?, ?, ?)
  `).run(path, referrer, uaHash(req), sessionHash(req));

  res.json({ ok: true });
});

router.post('/product/:id', (req, res) => {
  const product = db.prepare('SELECT id FROM products WHERE id = ?').get(req.params.id);
  if (!product) return res.status(404).json({ error: 'Produit introuvable' });
  db.prepare('INSERT INTO product_clicks (product_id) VALUES (?)').run(req.params.id);
  res.json({ ok: true });
});

router.post('/affiliate/:productId/:platformId', (req, res) => {
  const link = db.prepare(`
    SELECT al.url FROM affiliate_links al
    WHERE al.product_id = ? AND al.platform_id = ?
  `).get(req.params.productId, req.params.platformId);
  if (!link) return res.status(404).json({ error: 'Lien introuvable' });

  db.prepare('INSERT INTO affiliate_clicks (product_id, platform_id) VALUES (?, ?)')
    .run(req.params.productId, req.params.platformId);

  res.json({ ok: true, url: link.url });
});

module.exports = router;
