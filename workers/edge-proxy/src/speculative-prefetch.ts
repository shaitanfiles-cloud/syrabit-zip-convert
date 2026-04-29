/**
 * Speculative Prefetch Module
 * 
 * Analyzes user intent from first 3 keystrokes/request patterns to preload resources.
 * Supports Math, Science, History subject categories with intelligent caching.
 */

interface PrefetchIntent {
  category: 'math' | 'science' | 'history' | 'language' | 'general';
  confidence: number;
  predictedResources: string[];
}

interface PrefetchResult {
  success: boolean;
  resources: Array<{
    url: string;
    status: 'prefetched' | 'cached' | 'failed';
    latencyMs: number;
  }>;
}

/**
 * Subject keyword mappings for intent detection
 */
const SUBJECT_KEYWORDS: Record<string, string[]> = {
  math: ['algebra', 'geometry', 'calculus', 'trig', 'equation', 'formula', 'number', 'math', 'maths'],
  science: ['physics', 'chemistry', 'biology', 'experiment', 'atom', 'cell', 'energy', 'force', 'reaction'],
  history: ['history', 'war', 'king', 'empire', 'ancient', 'medieval', 'revolution', 'dynasty', 'civilization'],
  language: ['grammar', 'verb', 'noun', 'sentence', 'paragraph', 'essay', 'literature', 'poem', 'writing'],
};

/**
 * Resource templates for each subject category
 */
const RESOURCE_TEMPLATES: Record<string, string[]> = {
  math: [
    '/api/subjects/math/formulas',
    '/api/subjects/math/practice-problems',
    '/api/subjects/math/video-tutorials',
  ],
  science: [
    '/api/subjects/science/diagrams',
    '/api/subjects/science/labs',
    '/api/subjects/science/summaries',
  ],
  history: [
    '/api/subjects/history/timelines',
    '/api/subjects/history/maps',
    '/api/subjects/history/biographies',
  ],
  language: [
    '/api/subjects/language/grammar-rules',
    '/api/subjects/language/vocabulary',
    '/api/subjects/language/examples',
  ],
};

/**
 * Detect user intent from request path, query params, or partial input
 */
export function detectIntent(pathname: string, query: string = ''): PrefetchIntent {
  const searchStr = `${pathname}${query}`.toLowerCase();
  
  let bestMatch: { category: string; score: number } = { category: 'general', score: 0 };
  
  for (const [category, keywords] of Object.entries(SUBJECT_KEYWORDS)) {
    let score = 0;
    for (const keyword of keywords) {
      if (searchStr.includes(keyword)) {
        score += keyword.length; // Longer matches = higher confidence
      }
    }
    if (score > bestMatch.score) {
      bestMatch = { category, score };
    }
  }
  
  // Calculate confidence (0-1 scale)
  const maxPossibleScore = Math.max(...Object.values(SUBJECT_KEYWORDS).map(kws => 
    kws.reduce((sum, kw) => sum + kw.length, 0)
  ));
  const confidence = Math.min(1, bestMatch.score / maxPossibleScore);
  
  // Get predicted resources for this category
  const predictedResources = RESOURCE_TEMPLATES[bestMatch.category] || [];
  
  return {
    category: bestMatch.category as any,
    confidence,
    predictedResources,
  };
}

/**
 * Prefetch resources based on detected intent
 * Only prefetches if confidence > threshold
 */
export async function speculativePrefetch(
  intent: PrefetchIntent,
  env: any,
  ctx: ExecutionContext,
  threshold: number = 0.3
): Promise<PrefetchResult> {
  if (intent.confidence < threshold) {
    return { success: false, resources: [] };
  }
  
  const results: PrefetchResult['resources'] = [];
  
  for (const url of intent.predictedResources) {
    const startMs = Date.now();
    try {
      // Check D1 cache first
      const cached = await checkD1Cache(env.CONTENT_DB, url);
      if (cached) {
        results.push({
          url,
          status: 'cached',
          latencyMs: Date.now() - startMs,
        });
        continue;
      }
      
      // Prefetch from backend
      const response = await fetch(`${env.BACKEND_URL}${url}`, {
        method: 'GET',
        headers: { 'Accept': 'application/json' },
      });
      
      if (response.ok) {
        const data = await response.json();
        // Store in D1 cache asynchronously
        ctx.waitUntil(storeInD1Cache(env.CONTENT_DB, url, data));
        
        results.push({
          url,
          status: 'prefetched',
          latencyMs: Date.now() - startMs,
        });
      } else {
        results.push({
          url,
          status: 'failed',
          latencyMs: Date.now() - startMs,
        });
      }
    } catch (error) {
      console.error(`[speculative-prefetch] Failed to prefetch ${url}:`, error);
      results.push({
        url,
        status: 'failed',
        latencyMs: Date.now() - startMs,
      });
    }
  }
  
  return { success: true, resources: results };
}

/**
 * Check if resource exists in D1 cache
 */
async function checkD1Cache(db: D1Database, url: string): Promise<any | null> {
  try {
    const stmt = db.prepare('SELECT data, expires_at FROM edge_cache WHERE url = ? AND expires_at > ?');
    const result = await stmt.bind(url, Date.now()).first<any>();
    return result ? result.data : null;
  } catch {
    return null;
  }
}

/**
 * Store resource in D1 cache
 */
async function storeInD1Cache(db: D1Database, url: string, data: any): Promise<void> {
  try {
    const expiresAt = Date.now() + (6 * 60 * 60 * 1000); // 6 hours
    const stmt = db.prepare(`
      INSERT OR REPLACE INTO edge_cache (url, data, expires_at, cached_at)
      VALUES (?, ?, ?, ?)
    `);
    await stmt.bind(url, JSON.stringify(data), expiresAt, Date.now()).run();
  } catch (error) {
    console.error('[storeInD1Cache] Error:', error);
  }
}

/**
 * Generate prefetch hints for Link header
 */
export function generatePrefetchHints(intent: PrefetchIntent): string[] {
  if (intent.confidence < 0.3) return [];
  
  return intent.predictedResources.map(url => 
    `<${url}>; rel=prefetch; as=fetch; type=application/json`
  );
}
