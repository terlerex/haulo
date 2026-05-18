# Sécurité — Haulo

## Fait ✅

- **Helmet** : headers HTTP sécurisés (CSP, X-Frame-Options, etc.)
- **Rate limiting** (`express-rate-limit`) :
  - Général : 300 req / 15 min par IP sur tout `/api`
  - Login : 10 req / 15 min sur `POST /api/auth/login`
  - Upload : 30 req / heure sur `/api/upload` et `/api/admin/upload`
  - Tracking : 50 req / min par IP sur `/api/track/*` (limiter dédié maison, plus rapide)
- **CORS** restreint à `CORS_ORIGIN` avec `credentials: true`
- **Cookies de session** : `httpOnly`, `secure` auto en prod, `sameSite: 'strict'` en prod, `'lax'` en dev
- **Validation Zod** sur tous les POST/PUT mutants (auth, users, products, platforms, badges, categories, social-links, settings, tracking)
- **Magic bytes** validés côté serveur sur tous les uploads (JPEG / PNG / WebP / SVG) — on ne fait pas confiance au `Content-Type` déclaré
- **Path traversal protection** sur `DELETE /api/upload` et logo : `path.basename` + vérification que le chemin résolu reste dans `UPLOADS_DIR`
- **SESSION_SECRET** obligatoire en prod (fail-fast au démarrage si manquant)
- **Variables d'env centralisées** dans `server/config.js`
- **Logs anonymisés** : jamais d'IP en clair, jamais de password, jamais de session_id
- **Error handler global** : la stack trace ne sort jamais vers le client en prod
- **Nettoyage auto** : sessions expirées et données analytics > 90 jours purgées au démarrage
- **Session hash anonymisé** (MD5, rotation quotidienne, aucune IP stockée)
- **Trust proxy** activé en prod pour `req.ip` correct derrière Railway
- **Build prod** : Express sert `client/dist` + fallback SPA
- **`railway.toml`** prêt pour déploiement

## À faire avant mise en prod ⚠️

- [ ] Changer le mot de passe admin par défaut (admin / admin1234)
- [ ] Générer un `SESSION_SECRET` : `openssl rand -hex 32`
- [ ] Renseigner `CORS_ORIGIN` avec le vrai domaine du front
- [ ] Configurer un **Volume Railway** monté sur `/server/uploads` (sinon les uploads disparaissent à chaque redéploiement)
- [ ] Ou alternative : basculer les uploads vers **Cloudinary / S3** (les routes API conservent la même surface)
- [ ] Configurer un Volume Railway pour `db.sqlite` aussi (ou migrer vers Postgres)
- [ ] Tester toutes les routes admin après déploiement
- [ ] Vérifier le tracking sur mobile et les clics affiliés

## RGPD — note analytics

Les analytics sont anonymisés :
- `session_hash` = `md5(ip + user_agent + date_du_jour)` — non réversible vers l'IP, rotation quotidienne
- `user_agent_hash` = `md5(user_agent)` — pas d'UA en clair
- Bots filtrés par regex sur le user-agent (non trackés)
- Aucun cookie de tracking (le seul cookie `session_id` sert uniquement à l'auth admin)
- Données > 90 jours purgées automatiquement

**À ajouter dans la politique de confidentialité du site :**

> Nous utilisons un système d'analytics interne et anonymisé pour mesurer la fréquentation du site. Les données collectées sont des hashs cryptographiques non réversibles et ne permettent pas de vous identifier. Aucun cookie de tracking tiers (Google Analytics, etc.) n'est utilisé.

## Optionnel mais recommandé 💡

- 2FA pour le compte admin (TOTP via `speakeasy` + QR code)
- Migrer SQLite → PostgreSQL Railway (voir commentaires dans `server/db.js`)
- Backups automatiques de la DB (Railway scheduled job ou cron externe)
- Monitoring erreurs : **Sentry** (`@sentry/node` + `@sentry/react`)
- Politique de confidentialité publiée à `/privacy` (page à créer)
- HSTS via Helmet (déjà activé par défaut en prod via `helmet()`)
- CSRF token sur les mutations admin (sameSite=strict en prod le mitige déjà fortement)

## Headers de réponse en prod (Helmet par défaut)

```
Content-Security-Policy: default-src 'self'; img-src 'self' data: blob: https: http:; script-src 'self'; style-src 'self' 'unsafe-inline' https:; font-src 'self' https: data:; connect-src 'self'
Strict-Transport-Security: max-age=15552000; includeSubDomains
X-Content-Type-Options: nosniff
X-Frame-Options: SAMEORIGIN
X-DNS-Prefetch-Control: off
X-Download-Options: noopen
X-XSS-Protection: 0
Referrer-Policy: no-referrer
```

## Architecture des secrets

- Aucun secret hardcodé dans le code (vérifié par `grep`)
- Aucune variable `VITE_*` ne doit contenir de secret (toutes lisibles côté client)
- Le seul cookie du site est `session_id` (httpOnly, jamais lisible par JS)
