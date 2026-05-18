// Configuration centralisée. Toutes les variables d'env sont lues ici.
// Fail-fast en prod si SESSION_SECRET manque.

const path = require('path');

const NODE_ENV = process.env.NODE_ENV || 'development';
const IS_PROD = NODE_ENV === 'production';

if (IS_PROD && !process.env.SESSION_SECRET) {
  console.error('FATAL: SESSION_SECRET manquant en production');
  process.exit(1);
}

module.exports = {
  PORT:              parseInt(process.env.PORT, 10) || 3001,
  NODE_ENV,
  IS_PROD,
  SESSION_SECRET:    process.env.SESSION_SECRET || 'dev-secret-not-for-prod',
  SESSION_EXPIRY:    7 * 24 * 60 * 60 * 1000,
  DB_PATH:           process.env.DB_PATH || path.join(__dirname, '..', 'db.sqlite'),
  UPLOADS_DIR:       process.env.UPLOADS_DIR || path.join(__dirname, 'uploads'),
  MAX_FILE_SIZE:     5 * 1024 * 1024,
  MAX_LOGO_SIZE:     2 * 1024 * 1024,
  CORS_ORIGIN:       process.env.CORS_ORIGIN || 'http://localhost:5173',
  RATE_LIMIT_WINDOW: 15 * 60 * 1000,
  RATE_LIMIT_MAX:    300,
};
