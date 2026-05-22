// Migrations idempotentes. S'exécutent au démarrage du serveur ET dans seed.js.
// Stratégie :
//   - CREATE TABLE IF NOT EXISTS pour les nouvelles tables
//   - PRAGMA table_info(...) pour détecter les colonnes manquantes / vieilles
//   - ALTER TABLE ADD/DROP COLUMN pour évoluer les tables existantes
//   - Les seeds par défaut ne s'appliquent que si la table est vide

const bcrypt = require('bcryptjs');

const DEFAULT_ADMIN = { username: 'admin', password: 'admin1234' };

const DEFAULT_PLATFORMS = [
  ['basetao',  'Basetao',  '#378ADD', 'Agent populaire',     'https://www.basetao.com/?ref=YOURCODE'],
  ['hipobuy',  'Hipobuy',  '#1D9E75', 'Frais réduits',       'https://www.hipobuy.com/register'],
  ['kakobuy',  'Kakobuy',  '#D4537E', 'QC gratuit',          'https://www.kakobuy.com/register'],
  ['wegobuy',  'Wegobuy',  '#BA7517', 'App mobile',          'https://www.wegobuy.com/en/page/login?tp=register'],
  ['superbuy', 'Superbuy', '#E24B4A', 'Leader marché',       'https://www.superbuy.com/en/page/login/?partnercode=YOURCODE'],
  ['cnfans',   'CNFans',   '#7F77DD', 'Sans frais service',  'https://cnfans.com/register/'],
  ['mulebuy',  'Mulebuy',  '#639922', 'Nouveau venu',        'https://www.mulebuy.com/register'],
  ['joyabuy',  'Joyabuy',  '#993C1D', 'Économique',          'https://joyabuy.com/register'],
];

const DEFAULT_BADGES = [
  ['hot',   'HOT',   '#FCEBEB', '#A32D2D'],
  ['new',   'NEW',   '#EAF3DE', '#3B6D11'],
  ['promo', 'PROMO', '#FAEEDA', '#854F0B'],
];

const DEFAULT_SETTINGS = {
  exchange_rate_cny_eur:     '0.128',
  exchange_rate_auto_update: 'true',
  exchange_rate_last_update: '',
  exchange_rate_margin_pct:  '10',
  site_logo_url:       '',
  site_logo_size:      '32',
  site_name:           'Haulo',
  site_tagline:        'Trouve tes produits chez les meilleurs agents',
  site_subtitle:       "Catalogue de produits importés de Chine avec liens directs vers nos plateformes d'achat. Comparez, choisissez, commandez.",
  hero_badge:          '🔥 Nouveau site',
  stats_products:      'auto',
  stats_partners:      'auto',
  stats_label_1:       'produits référencés',
  stats_label_2:       'agents partenaires',
  stats_label_3:       'pays livrés',
  stats_countries:     '30+',
  howto_enabled:       'true',
  howto_step1_title:   'Trouve ton produit',
  howto_step1_desc:    "Parcours le catalogue et trouve l'article qui t'intéresse.",
  howto_step2_title:   'Choisis ton agent',
  howto_step2_desc:    'Compare les prix sur nos agents partenaires et sélectionne le meilleur.',
  howto_step3_title:   'Reçois ta commande',
  howto_step3_desc:    "L'agent achète en Chine et te livre partout dans le monde.",
  discord_cta_enabled: 'true',
  discord_cta_title:   'Rejoins la communauté',
  discord_cta_desc:    'Pose tes questions, partage tes hauls et découvre les bons plans en avant-première.',
  discord_cta_label:   'Rejoindre le Discord',
};

const DEFAULT_SOCIALS = [
  { platform: 'discord',   label: 'Discord',   icon: 'ti-brand-discord',   sort_order: 1 },
  { platform: 'instagram', label: 'Instagram', icon: 'ti-brand-instagram', sort_order: 2 },
  { platform: 'tiktok',    label: 'TikTok',    icon: 'ti-brand-tiktok',    sort_order: 3 },
  { platform: 'telegram',  label: 'Telegram',  icon: 'ti-brand-telegram',  sort_order: 4 },
];

const DEFAULT_CATEGORIES = [
  ['Sneakers',      '👟'],
  ['Vêtements',     '👕'],
  ['Montres',       '⌚'],
  ['Accessoires',   '🧢'],
  ['Electronique',  '📱'],
  ['Sacs',          '👜'],
  ['Bijoux',        '💎'],
  ['Autres',        '📦'],
];

function tableExists(db, name) {
  return !!db.prepare("SELECT name FROM sqlite_master WHERE type='table' AND name=?").get(name);
}
function colNames(db, table) {
  return new Set(db.prepare(`PRAGMA table_info(${table})`).all().map((c) => c.name));
}

function migrate(db) {
  // --- Tables référentielles ---------------------------------------------
  db.exec(`
    CREATE TABLE IF NOT EXISTS platforms (
      id INTEGER PRIMARY KEY AUTOINCREMENT,
      slug TEXT NOT NULL UNIQUE,
      name TEXT NOT NULL,
      color_hex TEXT NOT NULL,
      tagline TEXT,
      register_url TEXT NOT NULL,
      is_active INTEGER NOT NULL DEFAULT 1,
      sort_order INTEGER NOT NULL DEFAULT 0,
      url_template TEXT DEFAULT '',
      affiliate_code TEXT DEFAULT ''
    );

    CREATE TABLE IF NOT EXISTS badges (
      id INTEGER PRIMARY KEY AUTOINCREMENT,
      slug TEXT NOT NULL UNIQUE,
      label TEXT NOT NULL,
      color_bg TEXT NOT NULL,
      color_text TEXT NOT NULL,
      created_at TEXT NOT NULL DEFAULT (datetime('now'))
    );

    CREATE TABLE IF NOT EXISTS categories (
      id INTEGER PRIMARY KEY AUTOINCREMENT,
      name TEXT NOT NULL UNIQUE,
      emoji TEXT,
      sort_order INTEGER NOT NULL DEFAULT 0,
      created_at TEXT NOT NULL DEFAULT (datetime('now'))
    );
  `);

  // Migration des colonnes affiliate sur platforms (idempotent)
  if (tableExists(db, 'platforms')) {
    const plCols = colNames(db, 'platforms');
    if (!plCols.has('url_template')) {
      db.exec("ALTER TABLE platforms ADD COLUMN url_template TEXT DEFAULT ''");
    }
    if (!plCols.has('affiliate_code')) {
      db.exec("ALTER TABLE platforms ADD COLUMN affiliate_code TEXT DEFAULT ''");
    }
  }

  // Templates par défaut — UPSERT idempotent : ne touche pas un template déjà rempli
  const DEFAULT_TEMPLATES = {
    kakobuy:  'https://www.kakobuy.com/item/details?url={source_url_encoded}&affcode={affcode}',
    hipobuy:  'https://hipobuy.com/product/{platform}/{id}?inviteCode={affcode}',
    cnfans:   'https://cnfans.com/product/?shop_type={platform}&id={id}&ref={affcode}',
    mulebuy:  'https://mulebuy.com/product/?shop_type={platform}&id={id}&affcode={affcode}',
    superbuy: 'https://www.superbuy.com/en/page/buy?from=search-input&url={source_url_encoded}&partnercode={affcode}',
    basetao:  'https://www.basetao.com/products/agent/{platform}/{id}.html?ref={affcode}',
    wegobuy:  'https://www.wegobuy.com/en/page/buy?from=search-input&url={source_url_encoded}&promotionCode={affcode}',
    joyabuy:  'https://joyabuy.com/product/?shop_type={platform}&id={id}&ref={affcode}',
  };
  if (tableExists(db, 'platforms')) {
    const upd = db.prepare(`
      UPDATE platforms SET url_template = ?
      WHERE slug = ? AND (url_template IS NULL OR url_template = '')
    `);
    Object.entries(DEFAULT_TEMPLATES).forEach(([slug, tpl]) => upd.run(tpl, slug));
  }

  // Seed catégories d'abord (référencées par products)
  if (db.prepare('SELECT COUNT(*) AS c FROM categories').get().c === 0) {
    const stmt = db.prepare('INSERT INTO categories (name, emoji, sort_order) VALUES (?, ?, ?)');
    DEFAULT_CATEGORIES.forEach(([name, emoji], i) => stmt.run(name, emoji, i));
  }
  if (db.prepare('SELECT COUNT(*) AS c FROM badges').get().c === 0) {
    const stmt = db.prepare('INSERT INTO badges (slug, label, color_bg, color_text) VALUES (?, ?, ?, ?)');
    DEFAULT_BADGES.forEach((b) => stmt.run(...b));
  }
  if (db.prepare('SELECT COUNT(*) AS c FROM platforms').get().c === 0) {
    const stmt = db.prepare(
      'INSERT INTO platforms (slug, name, color_hex, tagline, register_url, sort_order) VALUES (?, ?, ?, ?, ?, ?)'
    );
    DEFAULT_PLATFORMS.forEach((p, i) => stmt.run(...p, i));
  }

  // --- Products (avec migration de badge TEXT → badge_id, idem category) ---
  if (!tableExists(db, 'products')) {
    db.exec(`
      CREATE TABLE products (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        name TEXT NOT NULL,
        category_id INTEGER REFERENCES categories(id) ON DELETE SET NULL,
        price_eur REAL,
        price_cny REAL,
        price_cny_numeric REAL DEFAULT NULL,
        price_eur_override REAL DEFAULT NULL,
        image_url TEXT,
        description TEXT,
        badge_id INTEGER REFERENCES badges(id) ON DELETE SET NULL,
        is_active INTEGER NOT NULL DEFAULT 1,
        is_featured INTEGER NOT NULL DEFAULT 0,
        created_at TEXT NOT NULL DEFAULT (datetime('now'))
      );
      CREATE INDEX IF NOT EXISTS idx_products_category ON products(category_id);
      CREATE INDEX IF NOT EXISTS idx_products_active ON products(is_active);
      CREATE INDEX IF NOT EXISTS idx_products_featured ON products(is_featured);
    `);
  } else {
    const cols = colNames(db, 'products');
    if (!cols.has('category_id')) db.exec('ALTER TABLE products ADD COLUMN category_id INTEGER');
    if (!cols.has('badge_id'))    db.exec('ALTER TABLE products ADD COLUMN badge_id INTEGER');
    if (!cols.has('is_featured')) {
      db.exec('ALTER TABLE products ADD COLUMN is_featured INTEGER NOT NULL DEFAULT 0');
      db.exec('CREATE INDEX IF NOT EXISTS idx_products_featured ON products(is_featured)');
    }
    if (!cols.has('price_cny_numeric')) {
      db.exec('ALTER TABLE products ADD COLUMN price_cny_numeric REAL DEFAULT NULL');
    }
    if (!cols.has('price_eur_override')) {
      db.exec('ALTER TABLE products ADD COLUMN price_eur_override REAL DEFAULT NULL');
    }

    // Migrer données depuis anciennes colonnes textuelles si présentes
    if (cols.has('category')) {
      db.exec(`
        UPDATE products
        SET category_id = (SELECT id FROM categories WHERE categories.name = products.category)
        WHERE category_id IS NULL
      `);
      try { db.exec('ALTER TABLE products DROP COLUMN category'); } catch (e) { /* SQLite < 3.35 */ }
    }
    if (cols.has('badge')) {
      db.exec(`
        UPDATE products
        SET badge_id = (SELECT id FROM badges WHERE badges.slug = products.badge)
        WHERE badge_id IS NULL AND products.badge IS NOT NULL AND products.badge <> ''
      `);
      try { db.exec('ALTER TABLE products DROP COLUMN badge'); } catch (e) {}
    }
  }

  // --- affiliate_links ---------------------------------------------------
  db.exec(`
    CREATE TABLE IF NOT EXISTS affiliate_links (
      id INTEGER PRIMARY KEY AUTOINCREMENT,
      product_id INTEGER NOT NULL,
      platform_id INTEGER NOT NULL,
      url TEXT NOT NULL,
      price_cny REAL,
      UNIQUE (product_id, platform_id),
      FOREIGN KEY (product_id) REFERENCES products(id) ON DELETE CASCADE,
      FOREIGN KEY (platform_id) REFERENCES platforms(id) ON DELETE CASCADE
    );
    CREATE INDEX IF NOT EXISTS idx_links_product ON affiliate_links(product_id);
  `);

  // --- Auth --------------------------------------------------------------
  db.exec(`
    CREATE TABLE IF NOT EXISTS admin_users (
      id INTEGER PRIMARY KEY AUTOINCREMENT,
      username TEXT NOT NULL UNIQUE,
      password_hash TEXT NOT NULL,
      created_at TEXT NOT NULL DEFAULT (datetime('now')),
      last_login TEXT
    );

    CREATE TABLE IF NOT EXISTS sessions (
      id TEXT PRIMARY KEY,
      user_id INTEGER NOT NULL,
      created_at TEXT NOT NULL DEFAULT (datetime('now')),
      expires_at TEXT NOT NULL,
      FOREIGN KEY (user_id) REFERENCES admin_users(id) ON DELETE CASCADE
    );

    CREATE INDEX IF NOT EXISTS idx_sessions_expires ON sessions(expires_at);
  `);

  // Purge sessions expirées au démarrage
  db.exec("DELETE FROM sessions WHERE expires_at < datetime('now')");

  // Seed admin par défaut si aucun admin n'existe (création ponctuelle, jamais écrasée)
  const adminCount = db.prepare('SELECT COUNT(*) AS c FROM admin_users').get().c;
  if (adminCount === 0) {
    const hash = bcrypt.hashSync(DEFAULT_ADMIN.password, 12);
    db.prepare('INSERT INTO admin_users (username, password_hash) VALUES (?, ?)')
      .run(DEFAULT_ADMIN.username, hash);
    console.log(`[migrate] admin créé : ${DEFAULT_ADMIN.username} / ${DEFAULT_ADMIN.password}`);
    console.log('⚠️  Changez le mot de passe admin par défaut');
  }

  // --- Settings (clé/valeur) --------------------------------------------
  db.exec(`
    CREATE TABLE IF NOT EXISTS settings (
      key TEXT PRIMARY KEY,
      value TEXT,
      updated_at TEXT NOT NULL DEFAULT (datetime('now'))
    );
  `);
  const settingsCount = db.prepare('SELECT COUNT(*) AS c FROM settings').get().c;
  if (settingsCount === 0) {
    const ins = db.prepare('INSERT INTO settings (key, value) VALUES (?, ?)');
    Object.entries(DEFAULT_SETTINGS).forEach(([k, v]) => ins.run(k, v));
  } else {
    // Pour les nouvelles clés ajoutées plus tard : insert si manquante (sans écraser)
    const ins = db.prepare('INSERT OR IGNORE INTO settings (key, value) VALUES (?, ?)');
    Object.entries(DEFAULT_SETTINGS).forEach(([k, v]) => ins.run(k, v));
  }

  // --- Social links ------------------------------------------------------
  db.exec(`
    CREATE TABLE IF NOT EXISTS social_links (
      id INTEGER PRIMARY KEY AUTOINCREMENT,
      platform TEXT NOT NULL,
      label TEXT NOT NULL,
      url TEXT,
      icon_name TEXT,
      sort_order INTEGER NOT NULL DEFAULT 0,
      is_active INTEGER NOT NULL DEFAULT 0,
      created_at TEXT NOT NULL DEFAULT (datetime('now'))
    );
  `);
  if (db.prepare('SELECT COUNT(*) AS c FROM social_links').get().c === 0) {
    const ins = db.prepare(
      'INSERT INTO social_links (platform, label, url, icon_name, sort_order, is_active) VALUES (?, ?, ?, ?, ?, ?)'
    );
    DEFAULT_SOCIALS.forEach((s) => ins.run(s.platform, s.label, '', s.icon, s.sort_order, 0));
  }

  // --- Analytics --------------------------------------------------------
  db.exec(`
    CREATE TABLE IF NOT EXISTS page_views (
      id INTEGER PRIMARY KEY AUTOINCREMENT,
      path TEXT NOT NULL,
      referrer TEXT,
      user_agent_hash TEXT,
      session_hash TEXT,
      created_at DATETIME DEFAULT CURRENT_TIMESTAMP
    );

    CREATE TABLE IF NOT EXISTS product_clicks (
      id INTEGER PRIMARY KEY AUTOINCREMENT,
      product_id INTEGER NOT NULL,
      created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
      FOREIGN KEY (product_id) REFERENCES products(id) ON DELETE CASCADE
    );

    CREATE TABLE IF NOT EXISTS affiliate_clicks (
      id INTEGER PRIMARY KEY AUTOINCREMENT,
      product_id INTEGER NOT NULL,
      platform_id INTEGER NOT NULL,
      created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
      FOREIGN KEY (product_id) REFERENCES products(id) ON DELETE CASCADE,
      FOREIGN KEY (platform_id) REFERENCES platforms(id) ON DELETE CASCADE
    );

    CREATE INDEX IF NOT EXISTS idx_pv_created  ON page_views(created_at);
    CREATE INDEX IF NOT EXISTS idx_pv_path     ON page_views(path);
    CREATE INDEX IF NOT EXISTS idx_pc_created  ON product_clicks(created_at);
    CREATE INDEX IF NOT EXISTS idx_pc_product  ON product_clicks(product_id);
    CREATE INDEX IF NOT EXISTS idx_ac_created  ON affiliate_clicks(created_at);
    CREATE INDEX IF NOT EXISTS idx_ac_platform ON affiliate_clicks(platform_id);
    CREATE INDEX IF NOT EXISTS idx_ac_product  ON affiliate_clicks(product_id);
  `);

  // Cleanup > 90 jours
  db.exec("DELETE FROM page_views       WHERE created_at < datetime('now', '-90 days')");
  db.exec("DELETE FROM product_clicks   WHERE created_at < datetime('now', '-90 days')");
  db.exec("DELETE FROM affiliate_clicks WHERE created_at < datetime('now', '-90 days')");
}

module.exports = migrate;
module.exports.DEFAULT_PLATFORMS = DEFAULT_PLATFORMS;
module.exports.DEFAULT_SETTINGS = DEFAULT_SETTINGS;
module.exports.DEFAULT_SOCIALS = DEFAULT_SOCIALS;
module.exports.DEFAULT_BADGES = DEFAULT_BADGES;
module.exports.DEFAULT_CATEGORIES = DEFAULT_CATEGORIES;
