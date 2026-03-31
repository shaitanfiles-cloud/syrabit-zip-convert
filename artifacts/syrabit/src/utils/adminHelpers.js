export const API = `${import.meta.env.VITE_BACKEND_URL || ''}/api`;

export function authHeaders(token) {
  const isRealJwt = token && token.split('.').length === 3;
  return { headers: isRealJwt ? { Authorization: `Bearer ${token}` } : {}, withCredentials: true };
}

export function autoSlug(text) {
  return (text || '').toLowerCase().replace(/[^a-z0-9]+/g, '-').replace(/-+/g, '-').replace(/^-|-$/g, '');
}

export function wordCount(text) {
  return (text || '').trim().split(/\s+/).filter(Boolean).length;
}
