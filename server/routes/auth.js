const express = require('express');
const bcrypt = require('bcryptjs');
const { v4: uuidv4 } = require('uuid');
const db = require('../db');
const config = require('../config');
const logger = require('../utils/logger');
const asyncHandler = require('../utils/asyncHandler');
const validateBody = require('../middleware/validate');
const { authSchema } = require('../validators');
const { requireAuth, getSessionUser, COOKIE_NAME, cookieOptions } = require('../middleware/auth');

const router = express.Router();

router.post(
  '/login',
  validateBody(authSchema),
  asyncHandler(async (req, res) => {
    const { username, password } = req.body;

    const user = db.prepare('SELECT id, username, password_hash FROM admin_users WHERE username = ?').get(username);
    if (!user) {
      logger.warn('Login failed (unknown user)', { username });
      return res.status(401).json({ error: 'Identifiants incorrects' });
    }

    const ok = await bcrypt.compare(password, user.password_hash);
    if (!ok) {
      logger.warn('Login failed (bad password)', { username });
      return res.status(401).json({ error: 'Identifiants incorrects' });
    }

    const sid = uuidv4();
    const expires = new Date(Date.now() + config.SESSION_EXPIRY).toISOString().replace('T', ' ').slice(0, 19);
    db.prepare('INSERT INTO sessions (id, user_id, expires_at) VALUES (?, ?, datetime(?))').run(sid, user.id, expires);
    db.prepare("UPDATE admin_users SET last_login = datetime('now') WHERE id = ?").run(user.id);

    logger.info('Admin login', { username });
    res.cookie(COOKIE_NAME, sid, cookieOptions());
    res.json({ ok: true, username: user.username });
  })
);

router.post('/logout', (req, res) => {
  const sid = req.cookies?.[COOKIE_NAME];
  if (sid) db.prepare('DELETE FROM sessions WHERE id = ?').run(sid);
  res.clearCookie(COOKIE_NAME, { path: '/' });
  res.json({ ok: true });
});

router.get('/me', (req, res) => {
  const user = getSessionUser(req);
  if (!user) return res.status(401).json({ error: 'Non autorisé' });
  res.json({ username: user.username, id: user.id });
});

module.exports = router;
module.exports.requireAuth = requireAuth;
