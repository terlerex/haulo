// Parse une URL source (Taobao / Tmall / Weidian / 1688) en { platform, id, originalUrl }
// puis construit les URLs affiliées à partir d'un template configuré par plateforme.

function parseSourceUrl(url) {
  if (!url || typeof url !== 'string') return null;

  let u;
  try {
    u = new URL(url.trim());
  } catch {
    return null;
  }
  const host = u.hostname.toLowerCase();
  const params = u.searchParams;

  // Taobao : item.taobao.com/item.htm?id=XXX (et variants)
  if (host.includes('taobao.com')) {
    const id = params.get('id');
    if (id) return { platform: 'taobao', id, originalUrl: url };
  }

  // Tmall : detail.tmall.com/item.htm?id=XXX
  if (host.includes('tmall.com')) {
    const id = params.get('id');
    if (id) return { platform: 'tmall', id, originalUrl: url };
  }

  // Weidian : weidian.com/item.html?itemID=XXX ou shop123.v.weidian.com/item.html?itemID=XXX
  if (host.includes('weidian.com')) {
    const id = params.get('itemID') || params.get('itemId');
    if (id) return { platform: 'weidian', id, originalUrl: url };
  }

  // 1688 : detail.1688.com/offer/XXX.html
  if (host.includes('1688.com')) {
    const m = u.pathname.match(/\/offer\/(\d+)\.html/);
    if (m) return { platform: '1688', id: m[1], originalUrl: url };
  }

  return null;
}

function buildAffiliateUrl(template, source, affcode) {
  if (!template) return '';
  if (!source) return '';
  return template
    .replace(/\{source_url_encoded\}/g, encodeURIComponent(source.originalUrl))
    .replace(/\{source_url\}/g, source.originalUrl)
    .replace(/\{platform\}/g, source.platform)
    .replace(/\{id\}/g, source.id)
    .replace(/\{affcode\}/g, affcode || '');
}

module.exports = { parseSourceUrl, buildAffiliateUrl };
