// Logger minimal sans dépendance. Prod = JSON. Dev = lisible.
// Ne JAMAIS logger : password, password_hash, session_id, IP en clair, session_hash.

const { IS_PROD } = require('../config');

function format(level, msg, meta) {
  const ts = new Date().toISOString();
  if (IS_PROD) {
    return JSON.stringify({ ts, level, msg, ...(meta || {}) });
  }
  const metaStr = meta ? ' ' + JSON.stringify(meta) : '';
  return `[${ts}] ${level.toUpperCase()} ${msg}${metaStr}`;
}

const logger = {
  info:  (msg, meta) => console.log(format('info', msg, meta)),
  warn:  (msg, meta) => console.warn(format('warn', msg, meta)),
  error: (msg, meta) => console.error(format('error', msg, meta)),
};

module.exports = logger;
