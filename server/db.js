// SQLite via better-sqlite3 (driver natif synchrone, prebuilds Linux pour Railway).
// API : prepare/run/get/all + db.exec + db.pragma + db.transaction (helper natif).
// Le code n'utilise volontairement pas db.transaction(fn) (BEGIN/COMMIT manuel
// dans seed.js) pour rester portable si on revient un jour à node:sqlite.
//
// Pour Postgres (Railway/Neon) : remplacer ce fichier par un pool `pg` activé via
// process.env.DATABASE_URL. Adapter placeholders (? → $1) et types
// (INTEGER PRIMARY KEY AUTOINCREMENT → SERIAL PRIMARY KEY).

const path = require('path');
const Database = require('better-sqlite3');
const migrate = require('./db/migrate');

const DB_PATH = path.join(__dirname, '..', 'db.sqlite');
const db = new Database(DB_PATH);

db.exec('PRAGMA journal_mode = WAL');
db.exec('PRAGMA foreign_keys = ON');

migrate(db);

module.exports = db;
