const express = require('express');
const db = require('../db');
const { requireAuth } = require('../middleware/auth');
const { parseSourceUrl, buildAffiliateUrl } = require('../utils/sourceParser');

const router = express.Router();
router.use(requireAuth);

router.post('/', (req, res) => {
  const { source_url } = req.body || {};
  if (!source_url || typeof source_url !== 'string') {
    return res.status(400).json({ error: 'source_url requis' });
  }

  const source = parseSourceUrl(source_url);
  if (!source) {
    return res.status(400).json({
      error: 'URL non reconnue. Formats acceptés : Taobao, Weidian, 1688, Tmall',
    });
  }

  const platforms = db.prepare(`
    SELECT id, slug, name, color_hex, url_template, affiliate_code, sort_order
    FROM platforms
    WHERE is_active = 1
    ORDER BY sort_order, id
  `).all();

  const links = [];
  for (const pl of platforms) {
    if (!pl.url_template) continue; // skip si pas de template
    const url = buildAffiliateUrl(pl.url_template, source, pl.affiliate_code);
    links.push({
      platform_id: pl.id,
      platform_slug: pl.slug,
      platform_name: pl.name,
      platform_color: pl.color_hex,
      generated_url: url,
      has_affcode: pl.url_template.includes('{affcode}')
        ? !!(pl.affiliate_code && pl.affiliate_code.trim())
        : true, // si le template n'utilise pas {affcode}, on considère que c'est OK
    });
  }

  res.json({ source, links });
});

module.exports = router;
