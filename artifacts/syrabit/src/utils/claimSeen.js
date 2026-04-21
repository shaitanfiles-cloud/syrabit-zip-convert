/**
 * Track which sync-claim timestamp the learner has already seen so the
 * "Recently synced" badge on Notebook / Flashcards only shows during
 * the first session after sign-in (Task #612).
 *
 * The backend stamps `claimed_at` on notes & flashcards when an offline
 * (anon) row is adopted into the user's account. We compare that
 * timestamp to a localStorage high-water mark and hide the badge once
 * the user has visited the page.
 */
const SEEN_KEY = 'syrabit:claim_seen_at';

export function getClaimSeenAt() {
  try { return localStorage.getItem(SEEN_KEY) || ''; } catch { return ''; }
}

export function markClaimSeen(iso) {
  if (!iso) return;
  try {
    const cur = localStorage.getItem(SEEN_KEY) || '';
    if (!cur || iso > cur) localStorage.setItem(SEEN_KEY, iso);
  } catch {}
}

export function isRecentlyClaimed(claimedAt, seenAt) {
  if (!claimedAt) return false;
  if (!seenAt) return true;
  return claimedAt > seenAt;
}
