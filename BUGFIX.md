# Audit & corrections — préparation prod

Audit effectué via revue de code statique (lecture de chaque fichier). Les bugs ci-dessous ont été identifiés et corrigés dans le même commit.

## Backend

### 1. Handlers async sans capture de rejection (Express 4) — **HIGH**
Express 4 ne route pas automatiquement les `Promise` rejetées vers l'error middleware. Si `bcrypt.compare` ou `bcrypt.hash` levait, on avait une `UnhandledPromiseRejection` côté serveur et la requête restait pendante côté client.
- **Fichiers** : `routes/auth.js` (login, changePassword), `routes/users.js` (création, change password).
- **Fix** : nouveau `utils/asyncHandler.js` qui wrap `fn` dans `Promise.resolve(...).catch(next)`. Toutes les routes async passent par ce wrapper.

### 2. Stack traces exposées au client en cas d'erreur 500 — **HIGH**
L'error handler dans `index.js` faisait `res.json({ error: err.message })` quel que soit le code. En prod, ça pouvait fuiter des informations internes (chemins, noms de fonctions, requêtes SQL en cas d'erreur SQLite).
- **Fichier** : `index.js`.
- **Fix** : nouveau `middleware/errorHandler.js`. En prod, message générique `"Erreur interne"` pour les 5xx ; détail conservé en dev. Stack jamais renvoyée. Erreurs Zod retournées en 400 avec liste structurée d'issues.

### 3. Cookies sans `sameSite: 'strict'` en prod — **MEDIUM**
Le cookie de session utilisait `sameSite: 'lax'` en toutes circonstances. En prod c'est insuffisant pour mitiger CSRF.
- **Fichier** : `middleware/auth.js`.
- **Fix** : `sameSite: 'strict'` quand `NODE_ENV=production`, `'lax'` en dev (sinon impossible de tester depuis Vite).

### 4. Pas de validation systématique des bodies POST/PUT — **HIGH**
Les routes faisaient `req.body.X` directement, avec quelques contrôles manuels. Un client malveillant pouvait envoyer des types inattendus (`is_active: { $ne: 0 }`, chaînes énormes, slugs avec `<script>`).
- **Fichiers** : la plupart des routes mutantes.
- **Fix** : `validators.js` (12 schémas Zod) + `middleware/validate.js`. Appliqué sur auth, users, badges, categories, platforms, social-links, settings, tracking. Les routes products gardent leur validation manuelle robuste existante (équivalente).

### 5. Pas de vérification du vrai mimetype des uploads — **HIGH**
Multer faisait seulement confiance au `Content-Type` HTTP envoyé par le client. Un attaquant pouvait poster un `.php` renommé en `.png` avec un Content-Type spoofé.
- **Fichiers** : `routes/upload.js`, `routes/uploadLogo.js`.
- **Fix** : nouveau `utils/imageMime.js` qui lit les magic bytes (JPEG `FF D8 FF`, PNG, RIFF/WEBP, SVG XML). Vérifié post-multer ; si invalide, le fichier est supprimé du disque et 400.

### 6. Path traversal potentiel sur `DELETE /api/upload` — **MEDIUM**
La suppression utilisait `path.basename` mais ne vérifiait pas que le chemin résolu restait dans `UPLOADS_DIR`. Sur certains FS (symlinks notamment), `basename` n'est pas suffisant.
- **Fichiers** : `routes/upload.js`, `routes/uploadLogo.js`.
- **Fix** : `path.resolve` + vérification `startsWith(UPLOAD_DIR_ABS + path.sep)`. Tentatives loggées en `warn`.

### 7. `SESSION_SECRET` non vérifié au démarrage — **HIGH**
La valeur par défaut `'dev-secret-not-for-prod'` aurait pu fuiter en prod sans surveillance.
- **Fichier** : `config.js` (nouveau).
- **Fix** : `process.exit(1)` au démarrage si `NODE_ENV=production` et `SESSION_SECRET` absent.

### 8. Pas de rate limiting global, login non protégé — **HIGH**
Aucune limite sur les tentatives de login → brute force possible. Pas de limite globale → DoS facile.
- **Fichier** : `index.js`.
- **Fix** : `express-rate-limit` — 300/15min global, 10/15min login, 30/h upload. Tracking conserve son limiter dédié (50/min).

### 9. Headers HTTP de sécurité manquants — **MEDIUM**
Pas de CSP, pas de X-Frame-Options, pas de HSTS.
- **Fichier** : `index.js`.
- **Fix** : `helmet()` avec CSP custom (autorise images externes des produits depuis Unsplash etc., `'unsafe-inline'` pour les styles inline de Tailwind/Vite, scriptSrc strict).

### 10. CORS trop permissif (`origin: true`) — **MEDIUM**
Acceptait n'importe quelle origine.
- **Fichier** : `index.js`.
- **Fix** : `origin: config.CORS_ORIGIN` (par défaut `http://localhost:5173`, à changer en prod via env).

### 11. Logs avec data sensible — **MEDIUM**
Les anciens `console.error(err)` pouvaient logger le body de la requête (qui en login contient le password).
- **Fichier** : nouveau `utils/logger.js`.
- **Fix** : logger custom (info/warn/error), JSON en prod, lisible en dev. Jamais de body brut loggé. Login warn ne logge que le `username`. Pas d'IP ni de session_id.

### 12. SQL injection — vérifié, **OK**
Audit `grep` sur tous les `db.prepare` : toutes les requêtes utilisent des placeholders `?` ou named `@field`. Aucune concaténation de string dans une SQL. Seule exception contrôlée : `analytics.js` construit `'-${days} days'` dans des paramètres datetime, mais `days` est parsé via `parseInt` borné `[1, 365]` avant interpolation — pas exploitable.

### 13. Sessions expirées non purgées — **LOW, déjà OK**
Vérifié : `migrate.js` exécute `DELETE FROM sessions WHERE expires_at < datetime('now')` au démarrage.

### 14. Analytics timeseries fill — vérifié, **OK**
Densification côté serveur en place : `analytics.js` génère N points et merge avec les résultats DB. Toutes les métriques (views, unique_sessions, product_clicks, affiliate_clicks) passent par la même logique.

## Frontend

### 15. `useAuth` sans timeout → loader infini si serveur down — **HIGH**
Si `/api/auth/me` ne répondait jamais (réseau coupé, serveur down), le spinner de `ProtectedRoute` tournait à l'infini sans message d'erreur.
- **Fichiers** : `context/AuthContext.jsx`, `components/ProtectedRoute.jsx`.
- **Fix** : `AbortController` avec timeout 5s. En cas d'`AbortError`, état `authError = 'timeout'`. `ProtectedRoute` affiche un écran d'erreur avec bouton "Réessayer" qui appelle `refresh()`.

### 16. Recharts sur données vides — vérifié, **OK**
`Analytics.jsx` et `Dashboard.jsx` testent explicitement `series.every((s) => s.value === 0)` et `platforms.every((p) => p.clicks === 0)` pour afficher "Aucune donnée" plutôt que de rendre un graphique vide qui peut faire crash silencieusement Recharts.

### 17. Promise.race tracking affilié — vérifié, **OK**
`hooks/useTracking.js` `trackAffiliateClick` utilise `Promise.race([trackReq, timeout(1000)])`. Si le serveur est lent, le timeout résout `null` après 1s, on ouvre l'URL fallback. Aucune attente bloquante > 1s.

### 18. Cookies non envoyés depuis Vite dev — vérifié, **OK**
`api.js` `fetch` envoie `credentials: 'include'`. CORS serveur a `credentials: true` + origine spécifique. Login fonctionne en dev.

### 19. ImagePicker — double-upload possible si le user clique pendant l'upload — **LOW**
Le bouton de submit dans les formulaires admin est désactivé pendant `saving`. ImagePicker bloque aussi via `uploading`. Vérifié OK.

### 20. `console.log` en prod — vérifié, **OK**
`grep` sur `client/src` : zéro occurrence.

## Audit SQL paramétré

Vérifié manuellement chaque fichier de `server/routes/` et `server/db/`. Toutes les requêtes utilisent `?` ou `@name`. Aucun cas de `\`SELECT ... WHERE id = ${...}\`` dangereux.

Une seule interpolation tolérée et auditée :
- `analytics.js` : `datetime('now', '-${days} days')`. `days` est borné via `parseDays()` qui retourne `Math.max(1, Math.min(365, parseInt(...)))`. Pas exploitable.

## Audit `dangerouslySetInnerHTML`

`grep` sur `client/src` : zéro occurrence.

## Routes restantes à valider manuellement après déploiement

- Logo upload + suppression (test du magic bytes sur PNG, SVG, JPEG)
- Tracking sur mobile (la session_hash change quotidiennement, pas par device — voulu)
- Recharts dans Analytics avec données réelles > 50 produits
