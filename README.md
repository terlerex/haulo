# RepFind

Application d'affiliation pour produits importés de Chine. Catalogue public + interface admin, agents/plateformes pré-configurés.

## Stack
- Frontend : React + Vite + React Router v6, Tailwind CSS v3
- Backend : Express.js (**Node 22.5+ requis** — utilise le module natif `node:sqlite`)
- DB : SQLite via `node:sqlite` (intégré à Node, zéro compilation), fichier `db.sqlite` à la racine

## Installation

```bash
npm install        # installe root + server + client
cp .env.example .env
npm run seed       # peuple la DB avec 6 produits + 8 plateformes
npm run dev        # client sur :5173, server sur :3001
```

L'app Vite proxifie `/api` vers le serveur Express en dev.

## Scripts

- `npm run dev` — lance client + server en parallèle
- `npm run build` — build du client dans `client/dist`
- `npm start` — démarre Express en prod (sert le dist)
- `npm run seed` — réinitialise la DB avec les données de démo

## Structure

```
/server         Express API + better-sqlite3
/client         Vite + React
db.sqlite       Base SQLite (gitignore)
```

## Routes API (préfixe `/api`)

- `GET    /api/products?category=&search=&limit=&offset=`
- `GET    /api/products/:id`
- `POST   /api/products`
- `PUT    /api/products/:id`
- `DELETE /api/products/:id` (soft delete)
- `POST   /api/products/:id/links` (upsert)
- `DELETE /api/products/:id/links/:lid`
- `GET    /api/platforms`
- `PUT    /api/platforms/:id`
- `GET    /api/stats`

## Routes frontend

- `/` — catalogue public
- `/product/:id` — détail produit
- `/admin` — dashboard
- `/admin/products` — liste produits
- `/admin/products/new` — ajout
- `/admin/products/:id/edit` — édition (avec gestion liens affiliés)
- `/admin/platforms` — gestion plateformes

## Déploiement Railway

Railway build le client puis lance Express qui sert `client/dist`. Un seul service.

1. Crée un projet Railway, connecte le repo.
2. Variables d'env : `PORT` (auto), `NODE_ENV=production`.
3. Build command : `npm install && npm run build`
4. Start command : `npm start`

### Passage SQLite → Postgres

Pour la persistance sur Railway/Vercel, remplacer better-sqlite3 par `pg` :

```bash
npm install pg --prefix server
```

Dans `server/db.js`, branche conditionnelle sur `process.env.DATABASE_URL` : si défini, on utilise un pool `pg` ; sinon SQLite local. Voir le commentaire en haut de `server/index.js` pour le détail des adaptations SQL (placeholders `$1` au lieu de `?`, `SERIAL` au lieu de `INTEGER PRIMARY KEY AUTOINCREMENT`).

## Déploiement Vercel

Vercel est moins naturel pour Express + SQLite (filesystem éphémère). Utiliser Railway ou Render pour la DB persistante, ou migrer en Postgres managé (Neon/Supabase) puis Vercel pour le frontend uniquement.

## TODO

- Authentification admin (basic auth ou JWT)
- Upload d'images locales (cloudinary ou S3)
- Migration Postgres en option via `DATABASE_URL`
