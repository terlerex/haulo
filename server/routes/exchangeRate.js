// Routes admin pour le taux de change.
//   POST /api/admin/exchange-rate/refresh     → force un fetch frankfurter
//   POST /api/admin/products/recalculate-prices → réécrit price_eur des produits
//                                                  ayant price_cny_numeric, sauf override

const express = require('express');
const db = require('../db');
const logger = require('../utils/logger');
const asyncHandler = require('../utils/asyncHandler');
const { requireAuth } = require('../middleware/auth');
const { fetchRate, convertCnyToEur, getRateAndMargin } = require('../jobs/exchangeRate');

const router = express.Router();
router.use(requireAuth);

// POST /refresh — force un fetch immédiat indépendamment de auto_update
router.post(
  '/refresh',
  asyncHandler(async (req, res) => {
    try {
      const eur = await fetchRate();
      db.prepare(`
        INSERT INTO settings (key, value, updated_at) VALUES ('exchange_rate_cny_eur', ?, datetime('now'))
        ON CONFLICT(key) DO UPDATE SET value = excluded.value, updated_at = datetime('now')
      `).run(String(eur));
      db.prepare(`
        INSERT INTO settings (key, value, updated_at) VALUES ('exchange_rate_last_update', ?, datetime('now'))
        ON CONFLICT(key) DO UPDATE SET value = excluded.value, updated_at = datetime('now')
      `).run(new Date().toISOString());
      logger.info(`[Exchange] Manual refresh: ${eur}`);
      res.json({ rate: eur, last_update: new Date().toISOString() });
    } catch (e) {
      logger.warn('[Exchange] Manual refresh failed', { error: e.message });
      res.status(502).json({ error: 'Impossible de récupérer le taux : ' + e.message });
    }
  })
);

module.exports = router;

// Sous-routeur pour /api/admin/products/recalculate-prices
const productPriceRouter = express.Router();
productPriceRouter.use(requireAuth);

productPriceRouter.post('/recalculate-prices', (req, res) => {
  const { rate, margin } = getRateAndMargin();
  const rows = db.prepare(`
    SELECT id, price_cny_numeric FROM products
    WHERE price_cny_numeric IS NOT NULL AND price_eur_override IS NULL
  `).all();

  const update = db.prepare('UPDATE products SET price_eur = ? WHERE id = ?');
  let count = 0;
  db.exec('BEGIN');
  try {
    for (const r of rows) {
      const eur = convertCnyToEur(r.price_cny_numeric, rate, margin);
      if (eur != null) {
        update.run(eur, r.id);
        count++;
      }
    }
    db.exec('COMMIT');
  } catch (e) {
    db.exec('ROLLBACK');
    throw e;
  }
  logger.info(`[Exchange] Recalculated EUR for ${count} products`);
  res.json({ updated: count, rate, margin });
});

module.exports.productPriceRouter = productPriceRouter;
