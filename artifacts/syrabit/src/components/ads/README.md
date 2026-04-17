# Ads (Task #401)

Centralized AdSense integration for syrabit.ai. All ad markup lives in
prerendered/SSR HTML so AdSense crawlers see the slots without JS.

## Files
- `adsConfig.js` — single source of truth: `AD_CLIENT`, slot IDs,
  `AD_DENY_PREFIXES`, `isAdsAllowed(pathname)`.
- `AdSlot.jsx`   — variant-driven `<ins class="adsbygoogle">` renderer.
  Always renders the `<ins>` tag for SSR; defers `adsbygoogle.push()`
  until the slot intersects the viewport (CLS-safe min-height).
- `AdAutoEnabler.jsx` — mounted once in `App.jsx`. On the first allowed
  route, it pushes `enable_page_level_ads` to activate AdSense Auto Ads
  (anchor + vignette + in-page). Also mirrors the current route's
  allow/deny status onto `<html data-ads="...">` for CSS / Tag Manager
  use, and stubs `window.adsbygoogle` so early manual pushes never throw.

## Loader
The AdSense JS is loaded as a static `<script async crossorigin>` in
`index.html` `<head>`:

```html
<script async crossorigin="anonymous"
  src="https://pagead2.googlesyndication.com/pagead/js/adsbygoogle.js?client=ca-pub-8958003374183515"></script>
```

This satisfies the AdSense crawler requirement (loader visible in static
HTML) and is non-blocking thanks to `async`.

## Slot map

| variant         | slot ID       | format        | min-h | typical placement                    |
| --------------- | ------------- | ------------- | ----- | ------------------------------------ |
| `inArticle`     | `8964159403`  | fluid/article | 250   | between content blocks               |
| `inFeed`        | `5324297294`  | fluid/in-feed | 200   | every 6 cards in subject grids       |
| `topDisplay`    | `1100000001`* | auto          | 100   | above-the-fold leaderboard           |
| `bottomDisplay` | `1100000002`* | auto          | 250   | end-of-page leaderboard / empty CTA  |
| `sidebar`       | `1100000003`* | auto          | 600   | desktop ≥lg sticky right rail        |
| `multiplex`     | `1100000004`* | autorelaxed   | 300   | related-content grid (long pages)    |

`*` = placeholder until real units are minted in AdSense (Follow-up #409).

## Route policy
Manual `<ins>` units are blocked on:
`/login`, `/signup`, `/reset-password`, `/payment/*`, `/admin/*`,
`/profile`, `/onboarding`, `/history` — `AdSlot`, `InArticleAd`, and
`InFeedAd` all return `null` on those paths via `isAdsAllowed()`.

## Auto Ads policy
Auto Ads are activated from code: `AdAutoEnabler` pushes
`{ google_ad_client, enable_page_level_ads: true, overlays: { bottom: true } }`
on the first allowed route the user visits. Because AdSense retains Auto
Ads for the full tab session once enabled, denied-route safety also
requires **matching dashboard URL exclusions**:

1. In **AdSense › Sites › syrabit.ai › Auto Ads**, add URL exclusions
   that mirror `AD_DENY_PREFIXES` exactly: `/login`, `/signup`,
   `/reset-password`, `/payment`, `/admin`, `/profile`, `/onboarding`,
   `/history` (each as a "URL starts with" rule).
2. Dashboard exclusions are authoritative on both direct loads and SPA
   navigation; the JS-side allow check only defers the activation
   push.
3. `<html data-ads="allowed|denied">` is kept in sync with the current
   route so CSS / Tag Manager rules can suppress residual surfaces if
   needed.

## Pages with ad placements
ChapterPage, SubjectLandingPage, LearnPage, PYQReplicaPage, LibraryPage,
ExamRoutinePage, CurriculumMap, ChatPage (empty state + every 5 turns),
AboutPage, TechnologyPage, NotFoundPage.

## AdSense dashboard setup
1. Verify ownership: the `google-adsense-account` meta tag in
   `index.html` matches `AD_CLIENT`.
2. In **Sites › syrabit.ai › Auto Ads**, enable: anchor, vignette,
   in-page. Per-route exclusions are enforced in code, but mirroring
   `AD_DENY_PREFIXES` in the dashboard is a belt-and-braces backup.
3. Create the four PLACEHOLDER units (top leaderboard, bottom
   leaderboard, sidebar skyscraper, multiplex) and replace the
   placeholder IDs in `adsConfig.js`.
4. Set up reporting channels per `variant` if per-placement revenue
   visibility is needed (Follow-up #410).
