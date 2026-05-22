const BASE = '/api';

async function request(path, options = {}) {
  const res = await fetch(BASE + path, {
    credentials: 'include',
    headers: { 'Content-Type': 'application/json', ...(options.headers || {}) },
    ...options,
  });
  if (!res.ok) {
    let msg = `HTTP ${res.status}`;
    try { const j = await res.json(); if (j.error) msg = j.error; } catch (_) {}
    const err = new Error(msg);
    err.status = res.status;
    throw err;
  }
  if (res.status === 204) return null;
  return res.json();
}

export const api = {
  // Auth
  login: (username, password) =>
    request('/auth/login', { method: 'POST', body: JSON.stringify({ username, password }) }),
  logout: () => request('/auth/logout', { method: 'POST' }),
  me: () => request('/auth/me'),

  // Admin users
  listUsers: () => request('/admin/users'),
  createUser: (data) => request('/admin/users', { method: 'POST', body: JSON.stringify(data) }),
  deleteUser: (id) => request(`/admin/users/${id}`, { method: 'DELETE' }),
  changePassword: (id, data) =>
    request(`/admin/users/${id}/password`, { method: 'PUT', body: JSON.stringify(data) }),

  // Products
  listProducts: (params = {}) => {
    const qs = new URLSearchParams();
    Object.entries(params).forEach(([k, v]) => {
      if (v !== undefined && v !== null && v !== '') qs.set(k, v);
    });
    const s = qs.toString();
    return request(`/products${s ? `?${s}` : ''}`);
  },
  getProduct: (id) => request(`/products/${id}`),
  createProduct: (data) => request('/products', { method: 'POST', body: JSON.stringify(data) }),
  updateProduct: (id, data) => request(`/products/${id}`, { method: 'PUT', body: JSON.stringify(data) }),
  deleteProduct: (id) => request(`/products/${id}`, { method: 'DELETE' }),

  // Links
  upsertLink: (productId, data) =>
    request(`/products/${productId}/links`, { method: 'POST', body: JSON.stringify(data) }),
  deleteLink: (productId, linkId) =>
    request(`/products/${productId}/links/${linkId}`, { method: 'DELETE' }),

  // Badges
  listBadges: () => request('/badges'),
  createBadge: (data) => request('/badges', { method: 'POST', body: JSON.stringify(data) }),
  deleteBadge: (id) => request(`/badges/${id}`, { method: 'DELETE' }),

  // Categories
  listCategories: () => request('/categories'),
  createCategory: (data) => request('/categories', { method: 'POST', body: JSON.stringify(data) }),
  updateCategory: (id, data) =>
    request(`/categories/${id}`, { method: 'PUT', body: JSON.stringify(data) }),
  deleteCategory: (id) => request(`/categories/${id}`, { method: 'DELETE' }),

  // Platforms / Agents
  listPlatforms: () => request('/platforms'),
  listPlatformsAdmin: () => request('/admin/platforms'),
  createPlatform: (data) =>
    request('/admin/platforms', { method: 'POST', body: JSON.stringify(data) }),
  updatePlatform: (id, data) =>
    request(`/admin/platforms/${id}`, { method: 'PUT', body: JSON.stringify(data) }),
  deletePlatform: (id) =>
    request(`/admin/platforms/${id}`, { method: 'DELETE' }),

  // Stats
  stats: () => request('/stats'),

  // Link generator (admin)
  generateLinks: (source_url) =>
    request('/admin/generate-links', { method: 'POST', body: JSON.stringify({ source_url }) }),

  // Exchange rate (admin)
  refreshExchangeRate: () =>
    request('/admin/exchange-rate/refresh', { method: 'POST' }),
  recalculatePrices: () =>
    request('/admin/products/recalculate-prices', { method: 'POST' }),

  // Analytics (admin)
  analyticsOverview:   (days = 30) => request(`/admin/analytics/overview?days=${days}`),
  analyticsTimeseries: (days = 30, metric = 'views') => request(`/admin/analytics/timeseries?days=${days}&metric=${metric}`),
  analyticsProducts:   (days = 30, sort = 'views', limit = 10) => request(`/admin/analytics/products?days=${days}&sort=${sort}&limit=${limit}`),
  analyticsPlatforms:  (days = 30) => request(`/admin/analytics/platforms?days=${days}`),
  analyticsPages:      (days = 30, limit = 10) => request(`/admin/analytics/pages?days=${days}&limit=${limit}`),

  // Upload (DELETE)
  deleteUpload: (filename) =>
    request('/upload', { method: 'DELETE', body: JSON.stringify({ filename }) }),

  // Settings
  getSettings: () => request('/settings'),
  updateSettings: (settings) =>
    request('/admin/settings', { method: 'PUT', body: JSON.stringify({ settings }) }),

  // Logo
  deleteLogo: () => request('/admin/upload/logo', { method: 'DELETE' }),

  // Social links
  listSocialLinks: () => request('/social-links'),
  listSocialLinksAdmin: () => request('/admin/social-links'),
  createSocialLink: (data) =>
    request('/admin/social-links', { method: 'POST', body: JSON.stringify(data) }),
  updateSocialLink: (id, data) =>
    request(`/admin/social-links/${id}`, { method: 'PUT', body: JSON.stringify(data) }),
  deleteSocialLink: (id) => request(`/admin/social-links/${id}`, { method: 'DELETE' }),
};

// Conversion CNY → EUR côté client (mirroir de server/jobs/exchangeRate.js)
export function convertCnyToEur(cny, rate, margin) {
  if (cny == null || cny === '') return null;
  const n = Number(cny);
  if (!Number.isFinite(n)) return null;
  const r = parseFloat(rate);
  const m = parseFloat(margin);
  const rr = Number.isFinite(r) ? r : 0.128;
  const mm = Number.isFinite(m) ? m : 0;
  return Math.round(n * rr * (1 + mm / 100) * 100) / 100;
}

// Slugify helper (badges)
export function slugify(s) {
  return String(s)
    .normalize('NFD').replace(/[̀-ͯ]/g, '')
    .toLowerCase()
    .trim()
    .replace(/[^a-z0-9]+/g, '-')
    .replace(/^-+|-+$/g, '');
}
