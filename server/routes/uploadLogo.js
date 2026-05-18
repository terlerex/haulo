// Upload du logo. ATTENTION en prod : /uploads/ éphémère sans Volume Railway.
// Préférer /client/public/ pour un logo stable, ou Cloudinary/S3.

const express = require('express');
const fs = require('fs');
const path = require('path');
const multer = require('multer');
const db = require('../db');
const config = require('../config');
const logger = require('../utils/logger');
const { requireAuth } = require('../middleware/auth');
const { detectMimeFromFile } = require('../utils/imageMime');

const router = express.Router();
router.use(requireAuth);

const UPLOAD_DIR = config.UPLOADS_DIR;
fs.mkdirSync(UPLOAD_DIR, { recursive: true });
const UPLOAD_DIR_ABS = path.resolve(UPLOAD_DIR);

const ALLOWED_EXT = new Set(['.jpg', '.jpeg', '.png', '.webp', '.svg']);
const ALLOWED_MIME_DECLARED = new Set(['image/jpeg', 'image/png', 'image/webp', 'image/svg+xml']);
const ALLOWED_MIME_DETECTED = new Set(['image/jpeg', 'image/png', 'image/webp', 'image/svg+xml']);

const storage = multer.diskStorage({
  destination: (_, __, cb) => cb(null, UPLOAD_DIR),
  filename: (_, file, cb) => {
    const ext = (path.extname(file.originalname || '') || '').toLowerCase();
    cb(null, `logo-${Date.now()}${ext}`);
  },
});

const upload = multer({
  storage,
  limits: { fileSize: config.MAX_LOGO_SIZE },
  fileFilter: (_, file, cb) => {
    const ext = (path.extname(file.originalname || '') || '').toLowerCase();
    if (ALLOWED_MIME_DECLARED.has(file.mimetype) && ALLOWED_EXT.has(ext)) return cb(null, true);
    cb(new Error('Format non autorisé (jpg, jpeg, png, webp, svg)'));
  },
});

function safeUnlinkLogo(url) {
  if (!url || typeof url !== 'string' || !url.startsWith('/uploads/logo-')) return;
  const safe = path.basename(url);
  const fp = path.resolve(UPLOAD_DIR, safe);
  if (!fp.startsWith(UPLOAD_DIR_ABS + path.sep) && fp !== UPLOAD_DIR_ABS) return;
  fs.unlink(fp, () => {});
}

function getCurrentLogo() {
  return db.prepare("SELECT value FROM settings WHERE key = 'site_logo_url'").get()?.value || '';
}

function setLogoValue(url) {
  db.prepare(`
    INSERT INTO settings (key, value, updated_at) VALUES ('site_logo_url', ?, datetime('now'))
    ON CONFLICT(key) DO UPDATE SET value = excluded.value, updated_at = datetime('now')
  `).run(url);
}

router.post('/', (req, res) => {
  upload.single('file')(req, res, (err) => {
    if (err) return res.status(400).json({ error: err.message });
    if (!req.file) return res.status(400).json({ error: 'Aucun fichier reçu' });

    const realMime = detectMimeFromFile(req.file.path, ALLOWED_MIME_DETECTED);
    if (!realMime) {
      fs.unlink(req.file.path, () => {});
      logger.warn('Logo upload rejected: invalid magic bytes', { declared: req.file.mimetype });
      return res.status(400).json({ error: 'Contenu du fichier invalide' });
    }

    const oldUrl = getCurrentLogo();
    const newUrl = `/uploads/${req.file.filename}`;
    safeUnlinkLogo(oldUrl);
    setLogoValue(newUrl);
    logger.info('Logo updated', { filename: req.file.filename, mime: realMime });
    res.json({ url: newUrl });
  });
});

router.delete('/', (req, res) => {
  const current = getCurrentLogo();
  safeUnlinkLogo(current);
  setLogoValue('');
  res.json({ ok: true });
});

module.exports = router;
