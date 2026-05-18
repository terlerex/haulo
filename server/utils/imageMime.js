// Détection du vrai mimetype d'une image par magic bytes.
// Évite de faire confiance au Content-Type déclaré côté client.

const fs = require('fs');

const ALLOWED_MIME = new Set(['image/jpeg', 'image/png', 'image/webp', 'image/svg+xml']);

function detectMime(buffer) {
  if (!buffer || buffer.length < 12) return null;
  // JPEG : FF D8 FF
  if (buffer[0] === 0xFF && buffer[1] === 0xD8 && buffer[2] === 0xFF) {
    return 'image/jpeg';
  }
  // PNG : 89 50 4E 47 0D 0A 1A 0A
  if (
    buffer[0] === 0x89 && buffer[1] === 0x50 && buffer[2] === 0x4E && buffer[3] === 0x47 &&
    buffer[4] === 0x0D && buffer[5] === 0x0A && buffer[6] === 0x1A && buffer[7] === 0x0A
  ) {
    return 'image/png';
  }
  // WebP : RIFF....WEBP
  if (
    buffer[0] === 0x52 && buffer[1] === 0x49 && buffer[2] === 0x46 && buffer[3] === 0x46 &&
    buffer[8] === 0x57 && buffer[9] === 0x45 && buffer[10] === 0x42 && buffer[11] === 0x50
  ) {
    return 'image/webp';
  }
  // SVG : XML / contient <svg dans les 1024 premiers octets
  const head = buffer.slice(0, Math.min(buffer.length, 1024)).toString('utf8').toLowerCase();
  if ((head.includes('<?xml') || head.trimStart().startsWith('<')) && head.includes('<svg')) {
    return 'image/svg+xml';
  }
  return null;
}

/**
 * Lit les premiers octets du fichier sur disque et valide.
 * @param {string} filepath
 * @param {Set<string>} [allowed] sous-ensemble de ALLOWED_MIME à autoriser
 * @returns {string|null} mimetype détecté, ou null si invalide
 */
function detectMimeFromFile(filepath, allowed = ALLOWED_MIME) {
  let fd;
  try {
    fd = fs.openSync(filepath, 'r');
    const buf = Buffer.alloc(2048);
    const bytes = fs.readSync(fd, buf, 0, 2048, 0);
    const mime = detectMime(buf.slice(0, bytes));
    if (!mime || !allowed.has(mime)) return null;
    return mime;
  } catch (_) {
    return null;
  } finally {
    if (fd != null) try { fs.closeSync(fd); } catch (_) {}
  }
}

module.exports = { detectMime, detectMimeFromFile, ALLOWED_MIME };
