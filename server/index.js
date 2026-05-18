// Haulo — serveur Express + SQLite (better-sqlite3)
//
// Postgres (Railway/Neon) : voir db.js et db/migrate.js. Brancher un pool `pg`
// quand process.env.DATABASE_URL est défini.
//
// IMPORTANT prod (Railway) : server/uploads est éphémère sans Volume monté.
// Pour persister les images, monter un Volume Railway ou utiliser Cloudinary/S3.

// --- Diagnostics process-level (AVANT tout require/import) ---
process.on('uncaughtException', (err) => {
  console.error('=== UNCAUGHT EXCEPTION ===');
  console.error('Message:', err.message);
  console.error('Stack:', err.stack);
  process.exit(1);
});

process.on('unhandledRejection', (err) => {
  console.error('=== UNHANDLED REJECTION ===');
  console.error('Error:', err);
  process.exit(1);
});

require('dotenv').config({ path: require('path').join(__dirname, '..', '.env') });

const path = require('path');
const fs = require('fs');
const express = require('express');
const cors = require('cors');
const cookieParser = require('cookie-parser');
const helmet = require('helmet');
const rateLimit = require('express-rate-limit');

const config = require('./config');
const logger = require('./utils/logger');
const { errorHandler, notFoundApi } = require('./middleware/errorHandler');

require('./db'); // init schema + migrations + seeds référentiels

const productsRouter = require('./routes/products');
const { publicRouter: platformsPublic, adminRouter: platformsAdmin } = require('./routes/platforms');
const statsRouter = require('./routes/stats');
const authRouter = require('./routes/auth');
const usersRouter = require('./routes/users');
const badgesRouter = require('./routes/badges');
const categoriesRouter = require('./routes/categories');
const uploadRouter = require('./routes/upload');
const uploadLogoRouter = require('./routes/uploadLogo');
const settingsRouter = require('./routes/settings');
const { publicRouter: socialPublic, adminRouter: socialAdmin } = require('./routes/socialLinks');
const trackRouter = require('./routes/track');
const analyticsRouter = require('./routes/analytics');

const app = express();
app.get('/health', (req, res) => res.json({ ok: true }))
// En prod (Railway), Express est derrière un proxy
if (config.IS_PROD) app.set('trust proxy', 1);

// Helmet — headers HTTP sécurisés. CSP autorise les images externes (catalog),
// et 'unsafe-inline' sur styleSrc pour Tailwind injected styles.
app.use(
  helmet({
    contentSecurityPolicy: {
      directives: {
        defaultSrc: ["'self'"],
        imgSrc:     ["'self'", 'data:', 'blob:', 'https:', 'http:'],
        scriptSrc:  ["'self'"],
        styleSrc:   ["'self'", "'unsafe-inline'", 'https:'],
        fontSrc:    ["'self'", 'https:', 'data:'],
        connectSrc: ["'self'"],
      },
    },
    crossOriginEmbedderPolicy: false,
    crossOriginResourcePolicy: { policy: 'cross-origin' },
  })
);

app.use(
  cors({
    origin:         config.CORS_ORIGIN,
    credentials:    true,
    methods:        ['GET', 'POST', 'PUT', 'DELETE'],
    allowedHeaders: ['Content-Type'],
  })
);

app.use(express.json({ limit: '1mb' }));
app.use(cookieParser());

// Rate limiters
const generalLimiter = rateLimit({
  windowMs: config.RATE_LIMIT_WINDOW,
  max: config.RATE_LIMIT_MAX,
  standardHeaders: true,
  legacyHeaders: false,
  message: { error: 'Trop de requêtes' },
});

const authLimiter = rateLimit({
  windowMs: 15 * 60 * 1000,
  max: 10,
  standardHeaders: true,
  legacyHeaders: false,
  message: { error: 'Trop de tentatives de connexion. Réessayez dans 15 minutes.' },
});

const uploadLimiter = rateLimit({
  windowMs: 60 * 60 * 1000,
  max: 30,
  standardHeaders: true,
  legacyHeaders: false,
  message: { error: "Limite d'uploads atteinte (30/h)." },
});

app.use('/api', generalLimiter);
app.use('/api/auth/login', authLimiter);
app.use('/api/upload', uploadLimiter);
app.use('/api/admin/upload', uploadLimiter);

// Uploads statiques (le tracking a son propre limiter dans track.js)
app.use('/uploads', express.static(config.UPLOADS_DIR));

// Public
app.use('/api/settings', settingsRouter);
app.use('/api/social-links', socialPublic);
app.use('/api/auth', authRouter);
app.use('/api/products', productsRouter);
app.use('/api/platforms', platformsPublic);
app.use('/api/badges', badgesRouter);
app.use('/api/categories', categoriesRouter);
app.use('/api/stats', statsRouter);
app.use('/api/upload', uploadRouter);
app.use('/api/track', trackRouter);

// Admin
app.use('/api/admin/users', usersRouter);
app.use('/api/admin/upload/logo', uploadLogoRouter);
app.use('/api/admin/platforms', platformsAdmin);
app.use('/api/admin/settings', settingsRouter.admin);
app.use('/api/admin/social-links', socialAdmin);
app.use('/api/admin/analytics', analyticsRouter);

app.get('/api/health', (_, res) => res.json({ ok: true }));

// ---- Build prod : Express sert le dist Vite + SPA fallback ----
if (config.IS_PROD) {
  const distPath = path.join(__dirname, '..', 'client', 'dist');
  if (fs.existsSync(distPath)) {
    app.use(express.static(distPath));
    app.get('*', (req, res, next) => {
      if (req.path.startsWith('/api/') || req.path.startsWith('/uploads/')) return next();
      res.sendFile(path.join(distPath, 'index.html'));
    });
  }
}

app.use(notFoundApi);
app.use(errorHandler);

const PORT = config.PORT;
app.listen(PORT, '0.0.0.0', () => {
  logger.info('Serveur démarré', { port: PORT, env: config.NODE_ENV });
  console.log('[STARTUP] Server is now listening');
  console.log('[STARTUP] PORT:', PORT);
  console.log('[STARTUP] DB_PATH:', process.env.DB_PATH || 'default');
  console.log('[STARTUP] UPLOADS_DIR:', process.env.UPLOADS_DIR || 'default');
  console.log('[STARTUP] NODE_ENV:', process.env.NODE_ENV);
});
