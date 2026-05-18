// Rate limiter en mémoire (sliding window 1 min). Suffisant pour un seul
// process Node ; en cluster il faudrait Redis ou un middleware partagé.

const WINDOW_MS = 60_000;

function makeRateLimit(maxPerMin = 50) {
  const buckets = new Map();
  return (req, res, next) => {
    const ip = req.ip || req.socket.remoteAddress || 'unknown';
    const now = Date.now();
    const arr = (buckets.get(ip) || []).filter((t) => now - t < WINDOW_MS);
    if (arr.length >= maxPerMin) {
      return res.status(429).json({ error: 'Trop de requêtes' });
    }
    arr.push(now);
    buckets.set(ip, arr);
    // GC opportuniste
    if (Math.random() < 0.01) {
      for (const [k, v] of buckets) {
        if (!v.length || now - v[v.length - 1] > WINDOW_MS) buckets.delete(k);
      }
    }
    next();
  };
}

module.exports = { makeRateLimit };
