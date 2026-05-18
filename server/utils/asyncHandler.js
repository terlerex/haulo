// Wrap les handlers async pour que toute Promise rejetée parte dans Express
// error middleware (Express 4 ne capture pas les rejected promises tout seul).

module.exports = (fn) => (req, res, next) => {
  Promise.resolve(fn(req, res, next)).catch(next);
};
