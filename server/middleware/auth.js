const db = require('../db');
const config = require('../config');

function getSessionUser(req) {
  const sid = req.cookies?.session_id;
  if (!sid) return null;
  const row = db.prepare(`
    SELECT s.id AS sid, s.expires_at, u.id, u.username
    FROM sessions s
    JOIN admin_users u ON u.id = s.user_id
    WHERE s.id = ? AND s.expires_at > datetime('now')
  `).get(sid);
  return row || null;
}

function requireAuth(req, res, next) {
  const user = getSessionUser(req);
  if (!user) return res.status(401).json({ error: 'Non autorisé' });
  req.user = user;
  next();
}

const COOKIE_NAME = 'session_id';
const COOKIE_DAYS = config.SESSION_EXPIRY / (24 * 60 * 60 * 1000);

function cookieOptions() {
  return {
    httpOnly: true,
    secure:   config.IS_PROD,
    sameSite: config.IS_PROD ? 'strict' : 'lax',
    maxAge:   config.SESSION_EXPIRY,
    path:     '/',
  };
}

module.exports = { requireAuth, getSessionUser, COOKIE_NAME, COOKIE_DAYS, cookieOptions };
