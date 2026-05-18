const express = require('express');
const db = require('../db');
const { requireAuth } = require('../middleware/auth');

const router = express.Router();
router.use(requireAuth);

function parseDays(req, def = 30) {
  const d = parseInt(req.query.days, 10);
  return Math.max(1, Math.min(365, Number.isFinite(d) ? d : def));
}

// Compte une métrique sur N jours en partant de offset_days en arrière.
// Ex: rangeCount('page_views', 30, 0) → derniers 30 jours
//     rangeCount('page_views', 30, 30) → 30j avant ça (période précédente)
function rangeCount(table, days, offsetDays = 0) {
  return db.prepare(`
    SELECT COUNT(*) AS c FROM ${table}
    WHERE created_at >= datetime('now', '-${days + offsetDays} days')
      AND created_at <  datetime('now', '-${offsetDays} days')
  `).get().c;
}

function deltaPct(curr, prev) {
  if (!prev) return curr > 0 ? 100 : 0;
  return Math.round(((curr - prev) / prev) * 1000) / 10;
}

// ---------- OVERVIEW ----------
router.get('/overview', (req, res) => {
  const days = parseDays(req);

  const views    = rangeCount('page_views', days);
  const products = rangeCount('product_clicks', days);
  const affs     = rangeCount('affiliate_clicks', days);

  const uniques = db.prepare(`
    SELECT COUNT(DISTINCT session_hash) AS c FROM page_views
    WHERE created_at >= datetime('now', ?)
  `).get(`-${days} days`).c;

  // période précédente
  const viewsPrev    = rangeCount('page_views', days, days);
  const productsPrev = rangeCount('product_clicks', days, days);
  const affsPrev     = rangeCount('affiliate_clicks', days, days);

  const topReferrers = db.prepare(`
    SELECT referrer, COUNT(*) AS count FROM page_views
    WHERE created_at >= datetime('now', ?)
      AND referrer IS NOT NULL AND referrer <> ''
    GROUP BY referrer
    ORDER BY count DESC
    LIMIT 5
  `).all(`-${days} days`);

  res.json({
    total_views: views,
    unique_sessions: uniques,
    total_product_clicks: products,
    total_affiliate_clicks: affs,
    conversion_rate: products > 0 ? Math.round((affs / products) * 1000) / 10 : 0,
    top_referrers: topReferrers,
    vs_previous_period: {
      views_delta_pct:     deltaPct(views, viewsPrev),
      clicks_delta_pct:    deltaPct(products, productsPrev),
      affiliate_delta_pct: deltaPct(affs, affsPrev),
    },
  });
});

// ---------- TIMESERIES ----------
const METRIC_TABLE = {
  views: 'page_views',
  product_clicks: 'product_clicks',
  affiliate_clicks: 'affiliate_clicks',
};

router.get('/timeseries', (req, res) => {
  const days = parseDays(req);
  const metric = req.query.metric || 'views';

  let rows;
  if (metric === 'unique_sessions') {
    rows = db.prepare(`
      SELECT DATE(created_at) AS date, COUNT(DISTINCT session_hash) AS value
      FROM page_views
      WHERE created_at >= datetime('now', ?)
      GROUP BY DATE(created_at)
    `).all(`-${days} days`);
  } else {
    const table = METRIC_TABLE[metric];
    if (!table) return res.status(400).json({ error: 'metric invalide' });
    rows = db.prepare(`
      SELECT DATE(created_at) AS date, COUNT(*) AS value
      FROM ${table}
      WHERE created_at >= datetime('now', ?)
      GROUP BY DATE(created_at)
    `).all(`-${days} days`);
  }

  // Densifie : 1 point par jour, 0 si rien
  const byDate = new Map(rows.map((r) => [r.date, r.value]));
  const out = [];
  for (let i = days - 1; i >= 0; i--) {
    const d = new Date();
    d.setDate(d.getDate() - i);
    const iso = d.toISOString().slice(0, 10);
    out.push({ date: iso, value: byDate.get(iso) || 0 });
  }
  res.json(out);
});

// ---------- TOP PRODUCTS ----------
router.get('/products', (req, res) => {
  const days = parseDays(req);
  const limit = Math.min(parseInt(req.query.limit, 10) || 10, 50);
  const sort = req.query.sort === 'affiliate_clicks' ? 'affiliate_clicks' : 'views';

  const rows = db.prepare(`
    SELECT
      p.id, p.name, p.image_url, p.is_featured,
      c.name AS category_name, c.emoji AS category_emoji,
      b.label AS badge_label, b.color_bg AS badge_bg, b.color_text AS badge_fg,
      (SELECT COUNT(*) FROM product_clicks pc
        WHERE pc.product_id = p.id AND pc.created_at >= datetime('now', ?)) AS views,
      (SELECT COUNT(*) FROM affiliate_clicks ac
        WHERE ac.product_id = p.id AND ac.created_at >= datetime('now', ?)) AS affiliate_clicks
    FROM products p
    LEFT JOIN categories c ON c.id = p.category_id
    LEFT JOIN badges b ON b.id = p.badge_id
    WHERE p.is_active = 1
  `).all(`-${days} days`, `-${days} days`);

  // Tendance 7j vs 7j précédents (par produit, simple)
  const trendStmt = db.prepare(`
    SELECT
      (SELECT COUNT(*) FROM product_clicks WHERE product_id = ? AND created_at >= datetime('now','-7 days')) AS curr,
      (SELECT COUNT(*) FROM product_clicks WHERE product_id = ?
         AND created_at >= datetime('now','-14 days') AND created_at < datetime('now','-7 days')) AS prev
  `);

  const out = rows.map((r) => {
    const t = trendStmt.get(r.id, r.id);
    let trend = 'stable';
    if (t.curr > t.prev * 1.1) trend = 'up';
    else if (t.curr < t.prev * 0.9) trend = 'down';
    return {
      id: r.id, name: r.name, image_url: r.image_url, is_featured: !!r.is_featured,
      category: r.category_name ? { name: r.category_name, emoji: r.category_emoji } : null,
      badge: r.badge_label ? { label: r.badge_label, color_bg: r.badge_bg, color_text: r.badge_fg } : null,
      views: r.views,
      affiliate_clicks: r.affiliate_clicks,
      conversion_rate: r.views > 0 ? Math.round((r.affiliate_clicks / r.views) * 1000) / 10 : 0,
      trend,
    };
  });

  out.sort((a, b) => (b[sort] - a[sort]) || (b.views - a.views));
  res.json(out.slice(0, limit));
});

// ---------- PLATFORMS ----------
router.get('/platforms', (req, res) => {
  const days = parseDays(req);
  const rows = db.prepare(`
    SELECT pl.id, pl.name, pl.color_hex,
      COUNT(ac.id) AS clicks
    FROM platforms pl
    LEFT JOIN affiliate_clicks ac ON ac.platform_id = pl.id
      AND ac.created_at >= datetime('now', ?)
    GROUP BY pl.id
    ORDER BY clicks DESC
  `).all(`-${days} days`);

  const total = rows.reduce((s, r) => s + r.clicks, 0);
  res.json(rows.map((r) => ({
    ...r,
    pct_of_total: total > 0 ? Math.round((r.clicks / total) * 1000) / 10 : 0,
  })));
});

// ---------- PAGES ----------
router.get('/pages', (req, res) => {
  const days = parseDays(req);
  const limit = Math.min(parseInt(req.query.limit, 10) || 10, 50);

  const rows = db.prepare(`
    SELECT path, COUNT(*) AS views FROM page_views
    WHERE created_at >= datetime('now', ?)
    GROUP BY path
    ORDER BY views DESC
    LIMIT ?
  `).all(`-${days} days`, limit);

  const total = db.prepare(
    "SELECT COUNT(*) AS c FROM page_views WHERE created_at >= datetime('now', ?)"
  ).get(`-${days} days`).c;

  res.json(rows.map((r) => ({
    ...r,
    pct_of_total: total > 0 ? Math.round((r.views / total) * 1000) / 10 : 0,
  })));
});

module.exports = router;
