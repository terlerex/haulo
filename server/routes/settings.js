const express = require('express');
const db = require('../db');
const { requireAuth } = require('../middleware/auth');
const validateBody = require('../middleware/validate');
const { settingUpdateSchema } = require('../validators');

const router = express.Router();

// GET public — toutes les settings sous forme d'objet { key: value }
router.get('/', (_, res) => {
  const rows = db.prepare('SELECT key, value FROM settings').all();
  const out = {};
  for (const r of rows) out[r.key] = r.value;
  res.json(out);
});

module.exports = router;

// Sous-routeur admin
const adminRouter = express.Router();
adminRouter.use(requireAuth);

adminRouter.put('/', validateBody(settingUpdateSchema), (req, res) => {
  const body = req.body || {};
  let updates = [];
  if (Array.isArray(body.settings)) {
    updates = body.settings;
  } else if (body.key !== undefined) {
    updates = [{ key: body.key, value: body.value }];
  } else {
    return res.status(400).json({ error: 'Body invalide : attendu { key, value } ou { settings: [...] }' });
  }

  const upsert = db.prepare(`
    INSERT INTO settings (key, value, updated_at) VALUES (?, ?, datetime('now'))
    ON CONFLICT(key) DO UPDATE SET value = excluded.value, updated_at = datetime('now')
  `);
  db.exec('BEGIN');
  try {
    for (const u of updates) {
      if (!u || typeof u.key !== 'string') continue;
      upsert.run(u.key, u.value == null ? null : String(u.value));
    }
    db.exec('COMMIT');
  } catch (e) {
    db.exec('ROLLBACK');
    throw e;
  }

  const rows = db.prepare('SELECT key, value FROM settings').all();
  const out = {};
  for (const r of rows) out[r.key] = r.value;
  res.json(out);
});

module.exports.admin = adminRouter;
