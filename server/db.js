// SQLite via better-sqlite3 (driver natif synchrone, prebuilds Linux pour Railway).
// API : prepare/run/get/all + db.exec + db.pragma + db.transaction.
// Les transactions sont gérées en BEGIN/COMMIT manuel dans seed.js.
//
// IMPORTANT : utilise config.DB_PATH (lu depuis env DB_PATH).
// Sur Railway, DB_PATH doit pointer sur un Volume monté (ex: /app/data/db.sqlite),
// sinon la DB est éphémère et perdue à chaque redéploiement.
//
// Pour Postgres (Railway/Neon) : remplacer ce fichier par un pool `pg` activé via
// process.env.DATABASE_URL. Adapter placeholders (? -> $1) et types
// (INTEGER PRIMARY KEY AUTOINCREMENT -> SERIAL PRIMARY KEY).

const fs = require('fs');
const path = require('path');
const Database = require('better-sqlite3');
const config = require('./config');
const migrate = require('./db/migrate');

const DB_PATH = config.DB_PATH;

// S'assurer que le dossier parent existe (ex: /app/data/ sur Railway Volume)
fs.mkdirSync(path.dirname(DB_PATH), { recursive: true });

console.log(`[DB] Opening SQLite at ${DB_PATH}`);

const db = new Database(DB_PATH);

db.exec('PRAGMA journal_mode = WAL');
db.exec('PRAGMA foreign_keys = ON');

migrate(db);

module.exports = db;
