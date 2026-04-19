# Ad stack — Syrabit.ai

This document is the contract between the ad-ops team and the codebase.
All wiring lives in two files:

- `src/utils/adsConfig.js` — the only place that reads ad env vars.
- `src/components/ads/AdSlot.jsx` — the only component that injects an
  ad-network script into the page.

When real publisher IDs / script URLs land, plugging them in is a config
change (env vars + redeploy), not a code change.

## Routes that DO show ads

Notes (`/learn/:slug`) and PYQ (`/pyq/:slug`) are the **only** monetised
routes on Syrabit.ai. Both are intentionally ad-dense (Task #542).

| Route          | Component            | Placement keys                                                                                                                                |
| -------------- | -------------------- | --------------------------------------------------------------------------------------------------------------------------------------------- |
| `/pyq/:slug`   | `PYQReplicaPage.jsx` | `pyq.topOfContent`, `pyq.inContent`, `pyq.endOfContent`                                                                                       |
| `/learn/:slug` | `LearnPage.jsx`      | `learn.topOfContent`, `learn.inContent`, `learn.afterPyqs`, `learn.afterFlashcards`, `learn.endOfContent`, `learn.sidebar` (desktop `lg:` only) |

PYQ pages get **AdPushup / Magnite** demand (premium display). Notes
pages get **Adsterra** (top / in-content / after-flashcards / sidebar)
and **PropellerAds** (after-PYQs / end-of-content) as fallback networks.

In addition, **Google AdSense** (publisher `ca-pub-8958003374183515`)
runs alongside the above stack on the same two routes via the
`useAdsenseAutoAds` hook (Task #550). It loads in **Auto Ads** mode by
default: the AdSense loader is injected once per page from
`LearnPage.jsx` and `PYQReplicaPage.jsx`, and AdSense itself decides
where to render. Per-slot `<AdSlot placement="learn.adsense.*" />` /
`placement="pyq.adsense.*"` units are also defined in `adsConfig.js`
and stay disabled (no reserved space, no script tag) until per-slot
`data-ad-slot` env vars are provided — same disabled-by-default
pattern as every other network. AdSense is **additive**: it does not
replace Quge5, Adsterra, PropellerAds, or AdPushup.

The `learn.afterPyqs` / `learn.afterFlashcards` slots only mount when the
parent section (Important Questions / Flashcards) is present, so notes
without PYQs or flashcards don't render an empty ad rail there. The
`learn.sidebar` slot is mounted only at the `lg:` breakpoint, so mobile
and tablet viewports never reserve the 600px column.

### Build-time guard for required slots (Task #545)

The placement keys above are also enforced *positively* by
`scripts/verify-required-ads.mjs`, exposed as
`pnpm --filter @workspace/syrabit run lint:ads-required` and wired
into `pnpm build` right after `lint:ads`. It hard-fails the build if
any of the keys above stops appearing as a string literal in its
owning page file. Removing a slot during a refactor would otherwise
silently kill ad revenue on that page.

To change the policy:

1. Edit the `REQUIRED` map in `scripts/verify-required-ads.mjs`.
2. Update the routes table above so the docs match the guard.

## Routes that are intentionally AD-FREE

These pages must never import `<AdSlot />` or inject an ad script.
A comment block at the top of each file makes the intent explicit.

- `/chat`                 — `ChatPage.jsx`
- `/library`, `/browser`  — `LibraryPage.jsx`
- `/{board}/...` chapter routes — `ChapterPage.jsx`

### Build-time guard (Task #529)

The policy above is enforced by `scripts/verify-no-ads.mjs`, which runs
as the first step of `pnpm build` and is also exposed as
`pnpm --filter @workspace/syrabit run lint:ads`. It hard-fails if any
of the guarded route files imports a module under
`src/components/ads/` (e.g. `@/components/ads/AdSlot`). The comment
banners at the top of those files are a hint; this script is the
enforcement.

To change the policy:

1. Edit the `GUARDED_FILES` array in `scripts/verify-no-ads.mjs`.
2. Update the routes table above so the docs match the guard.

## Environment variables

Each placement is gated by **all** of: a network script URL **and** a
per-placement zone/slot ID. If any is empty, `<AdSlot />` renders
nothing — no reserved space, no script tag.

### AdPushup / Magnite (PYQ pages)

| Variable                                  | Used for                       |
| ----------------------------------------- | ------------------------------ |
| `VITE_ADS_ADPUSHUP_SCRIPT_URL`            | Network script URL             |
| `VITE_ADS_ADPUSHUP_PUBLISHER_ID`          | Publisher ID (optional)        |
| `VITE_ADS_ADPUSHUP_PYQ_TOP_ZONE`          | `pyq.topOfContent` zone ID     |
| `VITE_ADS_ADPUSHUP_PYQ_INCONTENT_ZONE`    | `pyq.inContent` zone ID        |
| `VITE_ADS_ADPUSHUP_PYQ_END_ZONE`          | `pyq.endOfContent` zone ID     |

### Adsterra (Notes / Learn — top, in-content, after-flashcards, sidebar)

| Variable                                          | Used for                              |
| ------------------------------------------------- | ------------------------------------- |
| `VITE_ADS_ADSTERRA_SCRIPT_URL`                    | Network script URL                    |
| `VITE_ADS_ADSTERRA_LEARN_TOP_ZONE`                | `learn.topOfContent` zone ID          |
| `VITE_ADS_ADSTERRA_LEARN_INCONTENT_ZONE`          | `learn.inContent` zone ID             |
| `VITE_ADS_ADSTERRA_LEARN_AFTER_FLASHCARDS_ZONE`   | `learn.afterFlashcards` zone ID       |
| `VITE_ADS_ADSTERRA_LEARN_SIDEBAR_ZONE`            | `learn.sidebar` zone ID (desktop)     |

### PropellerAds (Notes / Learn — after-PYQs, end-of-content)

| Variable                                          | Used for                          |
| ------------------------------------------------- | --------------------------------- |
| `VITE_ADS_PROPELLERADS_SCRIPT_URL`                | Network script URL                |
| `VITE_ADS_PROPELLERADS_LEARN_AFTER_PYQS_ZONE`     | `learn.afterPyqs` zone ID         |
| `VITE_ADS_PROPELLERADS_LEARN_END_ZONE`            | `learn.endOfContent` zone ID      |

### Google AdSense (Notes + PYQ — Auto Ads, Task #550)

The AdSense loader script and publisher client are pinned in
`adsConfig.js` (publisher `ca-pub-8958003374183515`); no env vars are
required for the page-level Auto Ads mode to fill on Notes + PYQ.

The per-slot env vars below are **optional** — they only enable the
matching `<AdSlot placement="…adsense.…" />` units. Leave them empty
to run AdSense in Auto Ads mode only.

| Variable                                            | Used for                           |
| --------------------------------------------------- | ---------------------------------- |
| `VITE_ADS_ADSENSE_PYQ_TOP_SLOT`                     | `pyq.adsense.top` slot ID          |
| `VITE_ADS_ADSENSE_PYQ_INCONTENT_SLOT`               | `pyq.adsense.inContent` slot ID    |
| `VITE_ADS_ADSENSE_PYQ_END_SLOT`                     | `pyq.adsense.end` slot ID          |
| `VITE_ADS_ADSENSE_LEARN_TOP_SLOT`                   | `learn.adsense.top` slot ID        |
| `VITE_ADS_ADSENSE_LEARN_INCONTENT_SLOT`             | `learn.adsense.inContent` slot ID  |
| `VITE_ADS_ADSENSE_LEARN_AFTER_PYQS_SLOT`            | `learn.adsense.afterPyqs` slot ID  |
| `VITE_ADS_ADSENSE_LEARN_AFTER_FLASHCARDS_SLOT`      | `learn.adsense.afterFlashcards` slot ID |
| `VITE_ADS_ADSENSE_LEARN_END_SLOT`                   | `learn.adsense.end` slot ID        |
| `VITE_ADS_ADSENSE_LEARN_SIDEBAR_SLOT`               | `learn.adsense.sidebar` slot ID    |

## Consent + environment gate

`<AdSlot />` calls `adsConsentGranted()` from `adsConfig.js` before
injecting any script. The current policy is:

1. **Production builds only.** `import.meta.env.PROD` must be true. Dev
   builds never call ad networks, even when env vars are set.
2. **Manual opt-out.** A user can set
   `localStorage.setItem('syrabit_ads_optout', '1')` to disable ads
   entirely in their browser (handy for QA and privacy-conscious users).
3. **Paid plans → ad-free (Task #552).** Signed-in users on a paid
   plan (`starter` or `pro`) see no ads on Notes / PYQ. `AuthContext`
   mirrors the user's plan into the ads module via `setAdsUserPlan()`
   on every login / signup / `/auth/me` hydrate / logout, and
   `adsConsentGranted()` returns `false` while a paid plan is active.
   This suppresses the AdSense Auto Ads loader, the Quge5 multitag,
   and every `<AdSlot />` (AdPushup, Adsterra, PropellerAds, AdSense
   per-slot units) without any extra server call. Free-plan users and
   anonymous visitors continue to see ads as before.

   Two extra guarantees back this up:
   - **Fail closed during auth hydration.** `adsConsentGranted()`
     returns `false` until `AuthContext.authChecked` flips true via
     `setAdsAuthChecked()`, so a returning paid subscriber on a
     cookie-only session never sees an ad flash before `/auth/me`
     resolves.
   - **Reactive teardown.** `setAdsUserPlan()`, `setAdsAuthChecked()`,
     and `setAdsOptOut()` all dispatch a unified
     `syrabit:ads-consent-changed` event. `<AdSlot />`,
     `useAdsenseAutoAds`, and `useQuge5Multitag` listen for it and
     re-evaluate. When consent flips off mid-session (paid upgrade,
     opt-out toggle, logout-then-login as a paid user), already-
     injected scripts are removed from `<head>` and rendered slots
     collapse without a page reload.
4. **Future CMP.** When Syrabit ships a consent-management platform,
   wire it into `adsConsentGranted()` — `<AdSlot />` is the single
   caller, so the change stays one-file.

## Adding a new placement / network

1. Add the env vars to your deployment.
2. Add a `NETWORKS` entry (if it's a new network) and a `PLACEMENTS`
   entry in `src/utils/adsConfig.js`.
3. Drop `<AdSlot placement="your.key" />` into the page that should
   render it. Done.

## Performance guarantees

- `<AdSlot />` reserves a fixed `minHeight` so enabled slots cause
  zero CLS once the script loads.
- The network script is only injected when the slot is within ~200px
  of the viewport (IntersectionObserver) and only **once per page**
  per script URL (de-duped by URL on the module).
- Disabled slots render nothing — not even a placeholder div — so
  they cost nothing on routes where the env var is empty.
