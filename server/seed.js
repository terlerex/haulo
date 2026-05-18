// Seed des données démo. Idempotent :
//   - admin par défaut créé uniquement si aucun admin n'existe
//   - produits : table vidée puis repeuplée (DELETE + INSERT)
//   - plateformes / badges / catégories : déjà seedés par migrate.js si vides
//
// Usage : npm run seed
const bcrypt = require('bcryptjs');
const db = require('./db');

const DEFAULT_ADMIN = { username: 'admin', password: 'admin1234' };

const PRODUCTS = [
  { name: 'Nike Dunk Low Panda', category: 'Sneakers', price_eur: 89, price_cny: 680,
    image_url: 'https://images.unsplash.com/photo-1606107557195-0e29a4b5b4aa?w=600',
    description: 'Sneakers basses bicolores noir/blanc, version qualité supérieure. Cuir grainé, semelle EVA confort.',
    badge_slug: 'hot' },
  { name: 'Hoodie Essentials Beige', category: 'Vêtements', price_eur: 45, price_cny: 340,
    image_url: 'https://images.unsplash.com/photo-1556821840-3a63f95609a7?w=600',
    description: 'Sweat à capuche oversize, coton lourd 380gsm, broderie poitrine.',
    badge_slug: 'new' },
  { name: 'Rolex Submariner Black', category: 'Montres', price_eur: 220, price_cny: 1680,
    image_url: 'https://images.unsplash.com/photo-1523275335684-37898b6baf30?w=600',
    description: 'Montre automatique 40mm, mouvement clone 3135, bracelet acier oyster.',
    badge_slug: 'hot' },
  { name: 'Casquette NY Noire', category: 'Accessoires', price_eur: 25, price_cny: 190,
    image_url: 'https://images.unsplash.com/photo-1588850561407-ed78c282e89b?w=600',
    description: 'Casquette ajustable, logo brodé blanc, visière courbée.',
    badge_slug: null },
  { name: 'AirPods Pro 2 (clone)', category: 'Electronique', price_eur: 35, price_cny: 265,
    image_url: 'https://images.unsplash.com/photo-1606220588913-b3aacb4d2f46?w=600',
    description: 'Écouteurs bluetooth avec réduction de bruit, boitier de charge sans fil.',
    badge_slug: 'new' },
  { name: 'Sac LV Neverfull MM', category: 'Sacs', price_eur: 150, price_cny: 1140,
    image_url: 'https://images.unsplash.com/photo-1584917865442-de89df76afd3?w=600',
    description: 'Sac shopper monogrammé, cuir vachette, doublure rouge, pochette intérieure.',
    badge_slug: 'promo' },
];

function buildFakeUrl(slug, productName) {
  const handle = encodeURIComponent(productName.toLowerCase().replace(/\s+/g, '-'));
  return `https://www.${slug}.com/item/${handle}?ref=YOURCODE`;
}

async function seedAdmin() {
  const count = db.prepare('SELECT COUNT(*) AS c FROM admin_users').get().c;
  if (count > 0) {
    console.log('[seed] admin user(s) déjà présents, skip');
    return;
  }
  const hash = await bcrypt.hash(DEFAULT_ADMIN.password, 12);
  db.prepare('INSERT INTO admin_users (username, password_hash) VALUES (?, ?)').run(DEFAULT_ADMIN.username, hash);
  console.log(`[seed] admin créé → ${DEFAULT_ADMIN.username} / ${DEFAULT_ADMIN.password}`);
  console.log('⚠️  Changez le mot de passe admin par défaut');
}

function seedProducts() {
  db.exec('DELETE FROM affiliate_links');
  db.exec('DELETE FROM products');
  db.exec("DELETE FROM sqlite_sequence WHERE name IN ('products','affiliate_links')");

  const cats = db.prepare('SELECT id, name FROM categories').all().reduce((acc, c) => {
    acc[c.name] = c.id; return acc;
  }, {});
  const badges = db.prepare('SELECT id, slug FROM badges').all().reduce((acc, b) => {
    acc[b.slug] = b.id; return acc;
  }, {});
  const platforms = db.prepare('SELECT id, slug FROM platforms WHERE is_active = 1').all();

  const insertProduct = db.prepare(`
    INSERT INTO products (name, category_id, price_eur, price_cny, image_url, description, badge_id, is_active)
    VALUES (@name, @category_id, @price_eur, @price_cny, @image_url, @description, @badge_id, 1)
  `);
  const insertLink = db.prepare(`
    INSERT INTO affiliate_links (product_id, platform_id, url, price_cny) VALUES (?, ?, ?, ?)
  `);

  db.exec('BEGIN');
  try {
    for (const p of PRODUCTS) {
      const info = insertProduct.run({
        name: p.name,
        category_id: cats[p.category] ?? null,
        price_eur: p.price_eur,
        price_cny: p.price_cny,
        image_url: p.image_url,
        description: p.description,
        badge_id: p.badge_slug ? (badges[p.badge_slug] ?? null) : null,
      });
      const productId = Number(info.lastInsertRowid);
      for (const pl of platforms) {
        const variance = 0.95 + Math.random() * 0.15;
        const price = p.price_cny ? Math.round(p.price_cny * variance) : null;
        insertLink.run(productId, pl.id, buildFakeUrl(pl.slug, p.name), price);
      }
    }
    db.exec('COMMIT');
  } catch (e) {
    db.exec('ROLLBACK');
    throw e;
  }
  console.log(`[seed] ${PRODUCTS.length} produits insérés avec ${platforms.length} liens chacun`);
}

async function main() {
  await seedAdmin();
  seedProducts();
  console.log('[seed] done');
  process.exit(0);
}
main().catch((e) => { console.error(e); process.exit(1); });
