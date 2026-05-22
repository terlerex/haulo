const { z } = require('zod');

const optionalUrl = z.union([z.string().url(), z.literal('')]).optional().nullable();
const hexColor   = z.string().regex(/^#[0-9A-Fa-f]{6}$/, 'Couleur hex invalide (#xxxxxx)');
const slugStr    = z.string().regex(/^[a-z0-9-]{1,50}$/, 'Slug : minuscules/chiffres/tirets uniquement');

const boolish = z.union([z.boolean(), z.literal(0), z.literal(1)]).transform((v) => (v ? 1 : 0));
const nullableNumber = z.union([z.number(), z.null(), z.literal('')]).transform((v) => (v === '' ? null : v));

// ---------- Auth ----------
const authSchema = z.object({
  username: z.string().min(3).max(30).regex(/^[a-zA-Z0-9_.-]+$/, 'Caractères autorisés : lettres, chiffres, _.-'),
  password: z.string().min(8).max(100),
});

const userCreateSchema = z.object({
  username: z.string().min(3).max(30),
  password: z.string().min(8).max(100),
});

const passwordChangeSchema = z.object({
  current_password: z.string().min(1).max(100),
  new_password:     z.string().min(8).max(100),
});

// ---------- Product ----------
const productSchema = z.object({
  name:               z.string().min(1).max(200),
  category_id:        nullableNumber.optional(),
  price_eur:          nullableNumber.optional(),
  price_cny:          nullableNumber.optional(),
  price_cny_numeric:  nullableNumber.optional(),
  price_eur_override: nullableNumber.optional(),
  image_url:          z.string().max(1000).optional().nullable(),
  description:        z.string().max(2000).optional().nullable(),
  badge_id:           nullableNumber.optional(),
  is_active:          boolish.optional(),
  is_featured:        boolish.optional(),
}).partial({ name: false });

// Pour PUT : tout optionnel sauf cohérence des types
const productPatchSchema = productSchema.partial();

// ---------- Platform ----------
const platformSchema = z.object({
  name:           z.string().min(1).max(100),
  slug:           slugStr.optional(),
  color_hex:      hexColor,
  tagline:        z.string().max(100).optional().nullable(),
  register_url:   z.string().max(1000).optional().nullable(),
  is_active:      boolish.optional(),
  sort_order:     z.number().int().min(0).optional(),
  url_template:   z.string().max(2000).optional().nullable(),
  affiliate_code: z.string().max(200).optional().nullable(),
});
const platformPatchSchema = platformSchema.partial();

// ---------- Badge ----------
const badgeSchema = z.object({
  slug:       slugStr,
  label:      z.string().min(1).max(30),
  color_bg:   hexColor,
  color_text: hexColor,
});

// ---------- Category ----------
const categorySchema = z.object({
  name:       z.string().min(1).max(50),
  emoji:      z.string().max(4).optional().nullable(),
  sort_order: z.number().int().min(0).optional(),
});
const categoryPatchSchema = categorySchema.partial();

// ---------- Social link ----------
const socialLinkSchema = z.object({
  platform:   z.string().min(1).max(30),
  label:      z.string().min(1).max(50),
  url:        z.string().max(1000).optional().nullable(),
  icon:       z.string().max(50).optional().nullable(),
  icon_name:  z.string().max(50).optional().nullable(),
  sort_order: z.number().int().min(0).optional(),
  is_active:  boolish.optional(),
});
const socialLinkPatchSchema = socialLinkSchema.partial();

// ---------- Settings ----------
const settingEntry = z.object({
  key:   z.string().min(1).max(100),
  value: z.string().max(5000).nullable(),
});
const settingUpdateSchema = z.union([
  settingEntry,
  z.object({ settings: z.array(settingEntry).min(1).max(100) }),
]);

// ---------- Affiliate link ----------
const affiliateLinkSchema = z.object({
  platform_id: z.number().int().positive(),
  url:         z.string().min(1).max(1000),
  price_cny:   nullableNumber.optional(),
});

// ---------- Tracking ----------
const trackViewSchema = z.object({
  path:     z.string().min(1).max(500).startsWith('/'),
  referrer: z.string().max(500).optional().nullable(),
});

module.exports = {
  authSchema,
  userCreateSchema,
  passwordChangeSchema,
  productSchema,
  productPatchSchema,
  platformSchema,
  platformPatchSchema,
  badgeSchema,
  categorySchema,
  categoryPatchSchema,
  socialLinkSchema,
  socialLinkPatchSchema,
  settingUpdateSchema,
  affiliateLinkSchema,
  trackViewSchema,
};
