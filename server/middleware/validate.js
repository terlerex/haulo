// Middleware d'application d'un schéma Zod sur req.body.
// Mute req.body avec les données parsées (typage propre + valeurs par défaut).
module.exports = function validateBody(schema) {
  return (req, res, next) => {
    const result = schema.safeParse(req.body);
    if (!result.success) return next(result.error);
    req.body = result.data;
    next();
  };
};
