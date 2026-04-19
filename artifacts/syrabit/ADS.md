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

The `learn.afterPyqs` / `learn.afterFlashcards` slots only mount when the
parent section (Important Questions / Flashcards) is present, so notes
without PYQs or flashcards don't render an empty ad rail there. The
`learn.sidebar` slot is mounted only at the `lg:` breakpoint, so mobile
and tablet viewports never reserve the 600px column.

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

## Consent + environment gate

`<AdSlot />` calls `adsConsentGranted()` from `adsConfig.js` before
injecting any script. The current policy is:

1. **Production builds only.** `import.meta.env.PROD` must be true. Dev
   builds never call ad networks, even when env vars are set.
2. **Manual opt-out.** A user can set
   `localStorage.setItem('syrabit_ads_optout', '1')` to disable ads
   entirely in their browser (handy for QA and privacy-conscious users).
3. **Future CMP.** When Syrabit ships a consent-management platform,
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
