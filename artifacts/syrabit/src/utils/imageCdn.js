/**
 * Image CDN helper — rewrites raw thumbnail URLs into Cloudflare's
 * `/cdn-cgi/image/<options>/<source>` transformation endpoint so we get
 *   • format=auto  → AVIF / WebP delivery to browsers that support them
 *   • width=N      → properly-sized responses (saves 60–80% bytes on mobile)
 *   • quality=85   → near-lossless visual quality at a fraction of the bytes
 *
 * Requires Cloudflare Image Resizing (Pages Pro or Cloudflare Images add-on)
 * to be enabled on the zone. If it is not, set VITE_DISABLE_IMAGE_CDN=1 and
 * URLs will pass through unchanged.
 *
 * Task #383.
 */

const DISABLED =
  typeof import.meta !== 'undefined' &&
  import.meta.env &&
  import.meta.env.VITE_DISABLE_IMAGE_CDN === '1';

const DEFAULT_WIDTHS = [320, 640, 960];
const DEFAULT_OPTS = { quality: 85, format: 'auto', fit: 'cover' };

function isPassThrough(src) {
  if (!src || typeof src !== 'string') return true;
  if (src.startsWith('data:')) return true;
  if (src.startsWith('blob:')) return true;
  // Already routed through CF transformations — don't double-wrap.
  if (src.includes('/cdn-cgi/image/')) return true;
  return false;
}

/**
 * Rewrite `src` into a Cloudflare image-transform URL at the given width.
 * Returns the input unchanged when the helper is disabled or the input is
 * a data/blob URI / already-transformed URL.
 */
export function cdnImage(src, { width, quality, format, fit } = {}) {
  if (DISABLED || isPassThrough(src)) return src;
  const opts = {
    ...DEFAULT_OPTS,
    ...(width != null ? { width } : null),
    ...(quality != null ? { quality } : null),
    ...(format != null ? { format } : null),
    ...(fit != null ? { fit } : null),
  };
  const optString = Object.entries(opts)
    .map(([k, v]) => `${k}=${v}`)
    .join(',');
  // encodeURI preserves the URL structure (protocol slashes, query separator)
  // while escaping whitespace and other characters that would otherwise
  // produce a malformed CDN URL on edge cases (e.g. spaces in CMS-uploaded
  // filenames).
  return `/cdn-cgi/image/${optString}/${encodeURI(src)}`;
}

/**
 * Build a `srcset` string for responsive `<img>` rendering.
 * Returns `undefined` (so React drops the attribute) when the helper is
 * disabled or the source is unsuitable.
 */
export function cdnSrcSet(src, widths = DEFAULT_WIDTHS, opts = {}) {
  if (DISABLED || isPassThrough(src)) return undefined;
  return widths
    .map((w) => `${cdnImage(src, { ...opts, width: w })} ${w}w`)
    .join(', ');
}
