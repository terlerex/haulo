// SQLite via le module natif intégré à Node 22.5+ — aucune compilation requise.
// API quasi-identique à better-sqlite3 (prepare/run/get/all), avec ces différences :
//   - pas de db.pragma(), on passe par db.exec('PRAGMA ...')
//   - pas de db.transaction(fn), on gère BEGIN/COMMIT manuellement (cf. seed.js)
//
// Pour Postgres (Railway/Neon) : remplacer ce fichier par un pool `pg` activé via
// process.env.DATABASE_URL. Adapter placeholders (? → $1) et types
// (INTEGER PRIMARY KEY AUTOINCREMENT → SERIAL PRIMARY KEY).

const path = require('path');
const { DatabaseSync } = require('node:sqlite');
const migrate = require('./db/migrate');

const DB_PATH = path.join(__dirname, '..', 'db.sqlite');
const db = new DatabaseSync(DB_PATH);

db.exec('PRAGMA journal_mode = WAL');
db.exec('PRAGMA foreign_keys = ON');

migrate(db);

module.exports = db;
