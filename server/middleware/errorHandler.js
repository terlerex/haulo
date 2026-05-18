const { IS_PROD } = require('../config');
const logger = require('../utils/logger');

// Le handler final. Ne JAMAIS renvoyer la stack au client en prod.
function errorHandler(err, req, res, next) {
  // Erreur de validation Zod : status 400 + détails
  if (err?.name === 'ZodError') {
    return res.status(400).json({
      error: 'Validation invalide',
      issues: err.issues?.map((i) => ({ path: i.path.join('.'), message: i.message })),
    });
  }

  const status = err.status || err.statusCode || 500;

  // Log côté serveur (pas les bodies, pas d'info perso)
  if (status >= 500) {
    logger.error('Unhandled error', {
      path: req.path,
      method: req.method,
      message: err.message,
      stack: IS_PROD ? undefined : err.stack,
    });
  } else if (status >= 400) {
    logger.warn('Client error', { path: req.path, method: req.method, message: err.message, status });
  }

  // Réponse client : message simple, jamais de stack
  res.status(status).json({
    error: status >= 500 && IS_PROD ? 'Erreur interne' : (err.message || 'Erreur'),
  });
}

// 404 pour les routes API non matchées (avant errorHandler)
function notFoundApi(req, res, next) {
  if (req.path.startsWith('/api/')) {
    return res.status(404).json({ error: 'Not found' });
  }
  next();
}

module.exports = { errorHandler, notFoundApi };
