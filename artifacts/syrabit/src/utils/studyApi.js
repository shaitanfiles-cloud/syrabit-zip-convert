/**
 * Study API helpers — quizzes, notebook, flashcards, settings, voice.
 * Works for both authenticated users (cookie session) and anon (x-anon-id).
 */
import { API_BASE, getAnonId } from '@/utils/api';

const baseHeaders = () => ({
  'Content-Type': 'application/json',
  'x-anon-id': getAnonId(),
});

async function _json(res) {
  if (!res.ok) {
    const err = await res.json().catch(() => ({}));
    const e = new Error(err.detail || err.error || `HTTP ${res.status}`);
    e.status = res.status;
    e.code = err.detail;
    throw e;
  }
  return res.json();
}

export const studyApi = {
  // Quiz ────────────────────────────────────────────────
  generateQuiz: (payload) =>
    fetch(`${API_BASE}/edu/quiz/generate`, {
      method: 'POST', credentials: 'include',
      headers: baseHeaders(), body: JSON.stringify(payload),
    }).then(_json),

  // Notes ───────────────────────────────────────────────
  listNotes: ({ q = '', tag = '', limit = 100, offset = 0 } = {}) => {
    const qs = new URLSearchParams();
    if (q) qs.set('q', q);
    if (tag) qs.set('tag', tag);
    qs.set('limit', String(limit));
    qs.set('offset', String(offset));
    return fetch(`${API_BASE}/edu/notes?${qs.toString()}`,
      { credentials: 'include', headers: baseHeaders() }).then(_json);
  },
  createNote: (payload) =>
    fetch(`${API_BASE}/edu/notes`, {
      method: 'POST', credentials: 'include',
      headers: baseHeaders(), body: JSON.stringify(payload),
    }).then(_json),
  patchNote: (id, payload) =>
    fetch(`${API_BASE}/edu/notes/${id}`, {
      method: 'PATCH', credentials: 'include',
      headers: baseHeaders(), body: JSON.stringify(payload),
    }).then(_json),
  deleteNote: (id) =>
    fetch(`${API_BASE}/edu/notes/${id}`, {
      method: 'DELETE', credentials: 'include', headers: baseHeaders(),
    }).then(_json),
  exportNotesUrl: (format = 'md') =>
    `${API_BASE}/edu/notes/export?format=${encodeURIComponent(format)}`,

  // Flashcards ──────────────────────────────────────────
  buildFlashcards: (note_ids = null) =>
    fetch(`${API_BASE}/edu/flashcards/build`, {
      method: 'POST', credentials: 'include',
      headers: baseHeaders(), body: JSON.stringify({ note_ids }),
    }).then(_json),
  dueFlashcards: (limit = 30) =>
    fetch(`${API_BASE}/edu/flashcards/due?limit=${limit}`, {
      credentials: 'include', headers: baseHeaders(),
    }).then(_json),
  reviewFlashcard: (card_id, quality) =>
    fetch(`${API_BASE}/edu/flashcards/review`, {
      method: 'POST', credentials: 'include',
      headers: baseHeaders(), body: JSON.stringify({ card_id, quality }),
    }).then(_json),
  streak: () =>
    fetch(`${API_BASE}/edu/flashcards/streak`, {
      credentials: 'include', headers: baseHeaders(),
    }).then(_json),

  // Settings ────────────────────────────────────────────
  getSettings: () =>
    fetch(`${API_BASE}/edu/study/settings`, {
      credentials: 'include', headers: baseHeaders(),
    }).then(_json),
  setSettings: ({ strict_mode, pin = '' }) => {
    const qs = pin ? `?pin=${encodeURIComponent(pin)}` : '';
    return fetch(`${API_BASE}/edu/study/settings${qs}`, {
      method: 'POST', credentials: 'include',
      headers: baseHeaders(), body: JSON.stringify({ strict_mode }),
    }).then(_json);
  },

  // Guardian PIN ────────────────────────────────────────
  setPin: (new_pin, current_pin = '') =>
    fetch(`${API_BASE}/edu/guardian/pin/set`, {
      method: 'POST', credentials: 'include',
      headers: baseHeaders(), body: JSON.stringify({ new_pin, current_pin }),
    }).then(_json),
  verifyPin: (pin) =>
    fetch(`${API_BASE}/edu/guardian/pin/verify`, {
      method: 'POST', credentials: 'include',
      headers: baseHeaders(), body: JSON.stringify({ pin }),
    }).then(_json),

  // Sync anon → user ────────────────────────────────────
  claimAnonData: () =>
    fetch(`${API_BASE}/edu/sync/claim`, {
      method: 'POST', credentials: 'include', headers: baseHeaders(),
    }).then(_json),

  // Voice ───────────────────────────────────────────────
  voiceStatus: () =>
    fetch(`${API_BASE}/edu/voice/status`, { credentials: 'include' }).then(_json),
  stt: async (blob, language = 'en-IN') => {
    const fd = new FormData();
    fd.append('audio', blob, 'speech.webm');
    fd.append('language', language);
    const res = await fetch(`${API_BASE}/edu/stt`, {
      method: 'POST', credentials: 'include',
      headers: { 'x-anon-id': getAnonId() },
      body: fd,
    });
    return _json(res);
  },
};
