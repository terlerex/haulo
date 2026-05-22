// Job de rafraîchissement automatique du taux CNY → EUR via frankfurter.app.
// Au démarrage du serveur, puis toutes les 24h, si exchange_rate_auto_update = "true".
//
// Expose aussi convertCnyToEur(cny, rate?, margin?) pour calculer un prix EUR
// à partir d'un prix CNY + le taux et la marge stockés en settings.

const db = require('../db');
const logger = require('../utils/logger');

const FRANKFURTER_URL = 'https://api.frankfurter.app/latest?from=CNY&to=EUR';
const REFRESH_INTERVAL_MS = 24 * 60 * 60 * 1000; // 24h
const FETCH_TIMEOUT_MS = 8000;

function getSetting(key, fallback = null) {
  const row = db.prepare('SELECT value FROM settings WHERE key = ?').get(key);
  return row?.value ?? fallback;
}

function setSetting(key, value) {
  db.prepare(`
    INSERT INTO settings (key, value, updated_at) VALUES (?, ?, datetime('now'))
    ON CONFLICT(key) DO UPDATE SET value = excluded.value, updated_at = datetime('now')
  `).run(key, value);
}

function getRateAndMargin() {
  const rate = parseFloat(getSetting('exchange_rate_cny_eur', '0.128'));
  const margin = parseFloat(getSetting('exchange_rate_margin_pct', '0'));
  return {
    rate: Number.isFinite(rate) ? rate : 0.128,
    margin: Number.isFinite(margin) ? margin : 0,
  };
}

/**
 * Convertit un montant CNY en EUR avec la marge configurée.
 * Si rate / margin ne sont pas fournis, les lit depuis settings.
 * Retourne null si cnyValue n'est pas un nombre valide.
 */
function convertCnyToEur(cnyValue, rate, margin) {
  const n = Number(cnyValue);
  if (cnyValue == null || cnyValue === '' || !Number.isFinite(n)) return null;
  let r = rate, m = margin;
  if (r === undefined || m === undefined) {
    const { rate: rr, margin: mm } = getRateAndMargin();
    if (r === undefined) r = rr;
    if (m === undefined) m = mm;
  }
  return Math.round(n * r * (1 + m / 100) * 100) / 100;
}

async function fetchRate() {
  const controller = new AbortController();
  const timer = setTimeout(() => controller.abort(), FETCH_TIMEOUT_MS);
  try {
    const res = await fetch(FRANKFURTER_URL, { signal: controller.signal });
    if (!res.ok) throw new Error(`HTTP ${res.status}`);
    const data = await res.json();
    const eur = data?.rates?.EUR;
    if (!Number.isFinite(eur) || eur <= 0) throw new Error('Réponse invalide');
    return eur;
  } finally {
    clearTimeout(timer);
  }
}

async function refreshRate() {
  const autoUpdate = getSetting('exchange_rate_auto_update', 'true');
  // refreshRate force = true override l'auto-update check côté caller, mais ici
  // on respecte le setting pour le tick périodique. La route admin /refresh
  // appelle directement fetchRate sans passer par refreshRate.
  if (autoUpdate !== 'true') {
    logger.info('[Exchange] Auto-update disabled, skipping scheduled refresh');
    return null;
  }
  try {
    const eur = await fetchRate();
    setSetting('exchange_rate_cny_eur', String(eur));
    setSetting('exchange_rate_last_update', new Date().toISOString());
    logger.info(`[Exchange] Updated CNY/EUR rate to ${eur}`);
    return eur;
  } catch (e) {
    logger.warn('[Exchange] Failed to update, keeping current rate', { error: e.message });
    return null;
  }
}

let intervalHandle = null;

function start() {
  // Premier fetch au boot (non-bloquant)
  refreshRate().catch(() => {});
  if (intervalHandle) clearInterval(intervalHandle);
  intervalHandle = setInterval(() => {
    refreshRate().catch(() => {});
  }, REFRESH_INTERVAL_MS);
  if (intervalHandle.unref) intervalHandle.unref(); // ne bloque pas l'event loop
}

function stop() {
  if (intervalHandle) {
    clearInterval(intervalHandle);
    intervalHandle = null;
  }
}

module.exports = {
  start,
  stop,
  refreshRate,
  fetchRate,
  convertCnyToEur,
  getRateAndMargin,
};
