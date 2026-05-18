const express = require('express');
const db = require('../db');

const router = express.Router();

router.get('/', (_, res) => {
  const total_products = db.prepare('SELECT COUNT(*) AS c FROM products').get().c;
  const active_products = db.prepare('SELECT COUNT(*) AS c FROM products WHERE is_active = 1').get().c;
  const total_links = db.prepare('SELECT COUNT(*) AS c FROM affiliate_links').get().c;
  const platforms_count = db.prepare('SELECT COUNT(*) AS c FROM platforms WHERE is_active = 1').get().c;
  res.json({ total_products, active_products, total_links, platforms_count });
});

module.exports = router;
