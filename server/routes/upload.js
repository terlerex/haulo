// Upload local. ATTENTION en prod Railway/Vercel : le filesystem est éphémère.
// Pour la persistance, monter un Volume Railway sur server/uploads ou Cloudinary/S3.

const express = require('express');
const fs = require('fs');
const path = require('path');
const multer = require('multer');
const { v4: uuidv4 } = require('uuid');
const config = require('../config');
const logger = require('../utils/logger');
const { requireAuth } = require('../middleware/auth');
const { detectMimeFromFile } = require('../utils/imageMime');

const router = express.Router();

const UPLOAD_DIR = config.UPLOADS_DIR;
fs.mkdirSync(UPLOAD_DIR, { recursive: true });
const UPLOAD_DIR_ABS = path.resolve(UPLOAD_DIR);

const ALLOWED_EXT = new Set(['.jpg', '.jpeg', '.png', '.webp']);
const ALLOWED_MIME_DECLARED = new Set(['image/jpeg', 'image/png', 'image/webp']);
const ALLOWED_MIME_DETECTED = new Set(['image/jpeg', 'image/png', 'image/webp']);

const storage = multer.diskStorage({
  destination: (_, __, cb) => cb(null, UPLOAD_DIR),
  // Filename généré côté serveur — on n'utilise jamais le nom fourni par le client
  filename: (_, file, cb) => {
    const ext = (path.extname(file.originalname || '') || '').toLowerCase();
    cb(null, `${uuidv4()}${ext}`);
  },
});

const upload = multer({
  storage,
  limits: { fileSize: config.MAX_FILE_SIZE },
  fileFilter: (_, file, cb) => {
    const ext = (path.extname(file.originalname || '') || '').toLowerCase();
    if (ALLOWED_MIME_DECLARED.has(file.mimetype) && ALLOWED_EXT.has(ext)) return cb(null, true);
    cb(new Error('Format non autorisé (jpg, jpeg, png, webp uniquement)'));
  },
});

router.post('/', requireAuth, (req, res, next) => {
  upload.single('file')(req, res, (err) => {
    if (err) return res.status(400).json({ error: err.message });
    if (!req.file) return res.status(400).json({ error: 'Aucun fichier reçu' });

    // Validation des vrais magic bytes : on ne fait pas confiance au mimetype déclaré
    const filepath = req.file.path;
    const realMime = detectMimeFromFile(filepath, ALLOWED_MIME_DETECTED);
    if (!realMime) {
      fs.unlink(filepath, () => {});
      logger.warn('Upload rejected: invalid magic bytes', { declared: req.file.mimetype });
      return res.status(400).json({ error: 'Contenu du fichier invalide' });
    }

    logger.info('Upload OK', { filename: req.file.filename, mime: realMime });
    res.json({ url: `/uploads/${req.file.filename}` });
  });
});

router.delete('/', requireAuth, (req, res) => {
  const filename = (req.body?.filename || '').toString();
  if (!filename) return res.status(400).json({ error: 'filename requis' });

  // Path traversal protection
  const safe = path.basename(filename);
  const fp = path.resolve(UPLOAD_DIR, safe);
  if (!fp.startsWith(UPLOAD_DIR_ABS + path.sep) && fp !== UPLOAD_DIR_ABS) {
    logger.warn('Path traversal attempt blocked', { filename });
    return res.status(400).json({ error: 'Chemin invalide' });
  }
  fs.unlink(fp, (err) => {
    if (err && err.code !== 'ENOENT') return res.status(500).json({ error: err.message });
    res.json({ ok: true });
  });
});

function deleteUploadedFile(imageUrl) {
  if (!imageUrl || typeof imageUrl !== 'string') return;
  if (!imageUrl.startsWith('/uploads/')) return;
  const filename = path.basename(imageUrl);
  const fp = path.resolve(UPLOAD_DIR, filename);
  if (!fp.startsWith(UPLOAD_DIR_ABS + path.sep) && fp !== UPLOAD_DIR_ABS) return;
  fs.unlink(fp, () => {});
}

module.exports = router;
module.exports.UPLOAD_DIR = UPLOAD_DIR;
module.exports.deleteUploadedFile = deleteUploadedFile;
