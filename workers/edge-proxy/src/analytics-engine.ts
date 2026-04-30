/**
 * analytics-engine.ts — Task #109 Phase 5: Workers Analytics Engine query utility.
 *
 * Queries Cloudflare Workers Analytics Engine via the SQL API to return
 * edge metrics for the syrabit-edge worker (dataset: syrabit-edge-metrics).
 *
 * The dataset is written to by the edge worker on every request (see index.ts
 * ANALYTICS.writeDataPoint calls). Fields:
 *
 *   blob1  — cacheStatus:  "hit" | "miss" | "bypass" | "pass"
 *   blob2  — chapterId:    slug of the chapter being viewed, or "" if not a chapter
 *   blob3  — aiProvider:   "groq" | "gemini" | "workers-ai" | "none"
 *   blob4  — pathname:     request pathname (first 64 chars)
 *   blob5  — rateLimitResult: "ok" | "ai_limited" | "ip_limited"
 *
 *   double1 — responseTimeMs: end-to-end response time in milliseconds
 *   double2 — isAiRequest:    1 if the request hit an AI route, else 0
 *   double3 — httpStatus:     HTTP response status code
 *
 * Required env:
 *   CF_ANALYTICS_TOKEN  — Cloudflare API token with Account Analytics: Read scope.
 *                         Set via: wrangler secret put CF_ANALYTICS_TOKEN
 *   CLOUDFLARE_ACCOUNT_ID — account ID (hardcoded default for syrabit account)
 */

const ACCOUNT_ID    = 'd66e40eac539fff1db270fddf384a5ec';
const DATASET_NAME  = 'syrabit_edge_metrics';    // AE SQL uses underscores
const AE_SQL_URL    = `https://api.cloudflare.com/client/v4/accounts/${ACCOUNT_ID}/analytics_engine/sql`;

/** Number of seconds in each range option. */
const RANGE_SECONDS: Record<string, number> = {
  '1h':  3_600,
  '6h':  21_600,
  '24h': 86_400,
  '7d':  604_800,
};

export interface EdgeMetrics {
  rangeLabel: string;
  totalRequests: number;
  cacheHitRate: number;          // 0–1 fraction
  cacheHits: number;
  cacheMisses: number;
  aiRequests: number;
  avgResponseMs: number;
  topChapters: { chapterId: string; requests: number }[];
  ragByProvider: { provider: string; requests: number }[];
  rateLimitEvents: number;
}

async function runSql(token: string, query: string): Promise<Record<string, unknown>[]> {
  const res = await fetch(AE_SQL_URL, {
    method:  'POST',
    headers: {
      'Authorization': `Bearer ${token}`,
      'Content-Type':  'text/plain',
    },
    body: query,
  });

  if (!res.ok) {
    const text = await res.text().catch(() => '');
    throw new Error(`AE SQL ${res.status}: ${text.slice(0, 200)}`);
  }

  const json = await res.json() as {
    data?: Record<string, unknown>[];
    meta?: unknown;
    statistics?: unknown;
  };
  return json.data ?? [];
}

export async function queryEdgeMetrics(
  token: string,
  range: string = '24h',
): Promise<EdgeMetrics> {
  const windowSecs = RANGE_SECONDS[range] ?? RANGE_SECONDS['24h'];
  const rangeLabel = range;

  // ── Cache hit/miss aggregate ─────────────────────────────────────────
  const cacheQuery = `
    SELECT
      blob1                    AS cacheStatus,
      count()                  AS requests,
      avg(double1)             AS avgResponseMs
    FROM ${DATASET_NAME}
    WHERE timestamp >= now() - INTERVAL '${windowSecs}' SECOND
    GROUP BY cacheStatus
    ORDER BY requests DESC
    LIMIT 20
  `.trim();

  // ── Top chapters ─────────────────────────────────────────────────────
  const chaptersQuery = `
    SELECT
      blob2          AS chapterId,
      count()        AS requests
    FROM ${DATASET_NAME}
    WHERE timestamp >= now() - INTERVAL '${windowSecs}' SECOND
      AND blob2 != ''
    GROUP BY chapterId
    ORDER BY requests DESC
    LIMIT 5
  `.trim();

  // ── RAG volume by AI provider ─────────────────────────────────────────
  const ragQuery = `
    SELECT
      blob3          AS aiProvider,
      count()        AS requests
    FROM ${DATASET_NAME}
    WHERE timestamp >= now() - INTERVAL '${windowSecs}' SECOND
      AND double2 = 1
    GROUP BY aiProvider
    ORDER BY requests DESC
    LIMIT 10
  `.trim();

  const [cacheRows, chapterRows, ragRows] = await Promise.all([
    runSql(token, cacheQuery),
    runSql(token, chaptersQuery),
    runSql(token, ragQuery),
  ]);

  // ── Aggregate cache metrics ──────────────────────────────────────────
  let totalRequests = 0;
  let cacheHits     = 0;
  let cacheMisses   = 0;
  let sumResponseMs = 0;
  let countForAvg   = 0;
  let rateLimitEvents = 0;

  for (const row of cacheRows) {
    const status   = String(row.cacheStatus ?? '');
    const requests = Number(row.requests ?? 0);
    const avgMs    = Number(row.avgResponseMs ?? 0);
    totalRequests += requests;
    if (status === 'hit')                       cacheHits += requests;
    if (status === 'miss' || status === 'pass') cacheMisses += requests;
    sumResponseMs += avgMs * requests;
    countForAvg   += requests;
  }

  const cacheHitRate  = totalRequests > 0 ? cacheHits / totalRequests : 0;
  const avgResponseMs = countForAvg > 0 ? sumResponseMs / countForAvg : 0;

  // ── Top chapters ─────────────────────────────────────────────────────
  const topChapters = chapterRows.map((r) => ({
    chapterId: String(r.chapterId ?? ''),
    requests:  Number(r.requests ?? 0),
  }));

  // ── RAG by provider ──────────────────────────────────────────────────
  const aiRequests = ragRows.reduce((s, r) => s + Number(r.requests ?? 0), 0);
  const ragByProvider = ragRows
    .filter((r) => String(r.aiProvider ?? '') !== 'none')
    .map((r) => ({
      provider: String(r.aiProvider ?? ''),
      requests: Number(r.requests ?? 0),
    }));

  return {
    rangeLabel,
    totalRequests,
    cacheHitRate,
    cacheHits,
    cacheMisses,
    aiRequests,
    avgResponseMs: Math.round(avgResponseMs),
    topChapters,
    ragByProvider,
    rateLimitEvents,
  };
}
