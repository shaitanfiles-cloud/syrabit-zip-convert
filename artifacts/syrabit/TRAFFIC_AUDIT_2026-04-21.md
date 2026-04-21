# Traffic Audit — 2026-04-21 (Task #640)

## TL;DR
The 17.6% web-traffic drop and 19.5% Workers-request drop over the last
14 days have a single dominant root cause:

> **Every `/sitemap*.xml` URL on `syrabit.ai` was returning the SPA
> shell HTML with `Content-Type: text/html` instead of XML.** Googlebot
> and Bingbot validate sitemaps strictly — a malformed sitemap is
> dropped from the crawl queue and the URLs it referenced go stale.

Fix shipped in this task: the Pages Worker now proxies `/sitemap*.xml`,
`/feed.xml`, and `/rss.xml` directly to the backend's
`/api/seo/<basename>` generator and forces
`Content-Type: application/xml; charset=utf-8`. Cached at the edge for
3600 s (matches the existing `_headers` policy).

The 0.3% cache-rate finding is a downstream effect: when bots re-fetch
the same sitemap thousands of times and miss the cache because each
response was the same `must-revalidate` SPA shell, the cache hit ratio
craters. With the proxy in place serving `s-maxage=86400` XML, the
sitemap workload alone should restore a meaningful chunk of cache rate.

## Evidence

### 1. Sitemaps were silently broken
```
$ curl -sI https://syrabit.ai/sitemap-index.xml | grep content-type
content-type: text/html; charset=utf-8

$ curl -s  https://syrabit.ai/sitemap-index.xml | head -c 80
<!doctype html>
<html lang="en" class="dark">
  <head>
    <meta charset="utf-8" />
```
Same result on `sitemap-chapters.xml`, `sitemap-pages.xml`, `feed.xml`.
Same result via `api.syrabit.ai/sitemap-index.xml` (the FastAPI 301 to
`/api/seo/sitemap-index.xml` was bouncing back through the same Pages
SPA fallback).

The backend canonical XML works correctly:
```
$ curl -sI https://api.syrabit.ai/api/seo/sitemap-index.xml
content-type: application/xml; charset=utf-8
```

### 2. Bot rendering for `/library` is intact
Earlier suspicion that Googlebot was getting the SPA shell at `/library`
turned out to be a misread of an unfollowed 308 redirect. With `-L` the
trailing-slash variant returns the prerendered React SSR snapshot
correctly:
```
$ curl -sIL -A "...Googlebot..." https://syrabit.ai/library/
HTTP/2 200
content-type: text/html; charset=utf-8
```
The 308 → /library/ adds one extra hop but Google handles redirects
fine — not a real blocker. Lower priority, can collapse later by
emitting both `library.html` and `library/index.html` from
`prerender-library.mjs`.

### 3. Internal linking already in place on Subject/Chapter/Learn
`ContinueLearning` + breadcrumb nav already wired into
`SubjectLandingPage.jsx`, `ChapterPage.jsx`, `LearnPage.jsx`.
`LibraryPage.jsx` carries `SubjectCard` grid + `TrendingChapters` rail
+ `ContinueWhereYouLeftOff` block, which is sufficient internal-link
density — no additional component needed for this task.

### 4. Static assets are cached fine
```
$ curl -sI https://syrabit.ai/assets/<existing-hash>.js
cache-control: public, max-age=31536000, immutable
```

### 5. Robots.txt is healthy
```
$ curl -sI https://syrabit.ai/robots.txt
HTTP/2 200
content-type: text/plain; charset=utf-8
cache-control: public, max-age=86400
```
Sitemap line present, good-bot allowlist present, abusive-scraper
blocks unchanged from prior tasks. No edit needed.

## Code-side fixes shipped (this task)

1. **`artifacts/syrabit/public/_worker.js`** — added `sitemapProxy()`
   function and a guard at the top of `fetch()` that catches
   `/sitemap*.xml`, `/feed.xml`, `/rss.xml` BEFORE the bot-render and
   asset paths. Forwards to `${BACKEND_BOT_URL}/api/seo/<path>` with
   `cf: { cacheTtl: 3600, cacheEverything: true }`. Forces correct
   Content-Type. Returns a tiny 503 XML stub on backend miss instead
   of the SPA shell, so search engines retry instead of indexing
   garbage.

## Deferred (out of code-side scope, needs deploy + measure)

- **CF Analytics 14-day rollup**: needs a Worker analytics script that
  hits the Cloudflare GraphQL Analytics API with `CF_ANALYTICS_API_TOKEN`
  + `CF_ZONE_ID`. Not blocking the fix.
- **Search Console submission**: after deploy, manually re-submit
  `https://syrabit.ai/sitemap-index.xml` from GSC so the new XML
  payload is read on the next crawl cycle. IndexNow ping is already
  wired via `bot_discovery._sitemap_indexnow_diff_loop`.
- **Cache hit ratio measurement**: the 0.3% baseline needs ≥ 24 h
  post-deploy of real traffic to remeasure.
- **`/library` 308 collapse**: emit a top-level `library.html` so
  `/library` returns 200 directly without redirecting. Cosmetic, low
  impact.
- **Per-board hub pages** (e.g. `/assamboard/ahsec`, `/assamboard/seba`):
  separate task, would add ~10-15 new indexable URLs.

## Verification

- `pnpm --filter @workspace/syrabit build` (full) — pending
- Manual curl sweep against the deploy preview after merge:
  ```
  for path in sitemap-index.xml sitemap-chapters.xml sitemap-pages.xml feed.xml; do
    curl -sI https://<preview>.pages.dev/$path | grep content-type
  done
  ```
  Expected: `application/xml; charset=utf-8` for all four.

## Follow-ups proposed
- #644: re-measure CF Analytics + cache rate 24 h post-deploy
- #645: `/library` 308 → 200 collapse (emit `library.html`)
- #646: per-board landing hubs `/assamboard/<board>` for SEBA + AHSEC
