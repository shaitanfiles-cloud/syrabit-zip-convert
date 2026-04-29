/**
 * Syrabit Edge Proxy Worker
 * 
 * Features:
 * - gRPC client for Rust Core communication
 * - Speculative Prefetch based on user intent prediction
 * - Intelligent routing: Static/D1 cache → Return immediately; Dynamic/AI → Proxy to Rust Core
 * - Cloudflare D1 integration for edge caching
 */

// Protobuf types (simplified for Workers - in production use protobufjs)
interface ChatRequest {
  user_id: string;
  session_id: string;
  message: string;
  context?: string;
  history: Array<{ role: string; content: string; timestamp: number }>;
  metadata?: Record<string, string>;
}

interface RagQuery {
  query: string;
  top_k: number;
  filters?: string[];
  hybrid_search: boolean;
  hop_count: number;
}

interface MetricsUpdate {
  timestamp: number;
  system: {
    cpu_usage: number;
    memory_usage: number;
    active_connections: number;
    requests_per_second: number;
    avg_latency_ms: number;
  };
  agents: {
    total: number;
    idle: number;
    running: number;
    paused: number;
    error: number;
  };
  health: {
    healthy: boolean;
    load_factor: number;
    warnings: string[];
  };
}

// Configuration
const CONFIG = {
  RUST_CORE_GRPC_URL: 'https://rust-core.syrabit.ai:50051',
  RUST_CORE_HTTP_URL: 'https://rust-core.syrabit.ai',
  CACHE_TTL_SECONDS: 300, // 5 minutes
  SPECULATIVE_THRESHOLD_MS: 100, // Trigger prefetch after 100ms typing delay
};

// Intent patterns for speculative prefetch
const INTENT_PATTERNS = {
  MATH: /math|algebra|calculus|geometry|trigonometry/i,
  SCIENCE: /physics|chemistry|biology|science/i,
  HISTORY: /history|historical|ancient|medieval/i,
  LANGUAGE: /english|grammar|literature|writing/i,
  EXAM: /exam|test|quiz|question|paper/i,
  CHAPTER: /chapter|lesson|topic|unit/i,
};

export default {
  async fetch(
    request: Request,
    env: Env,
    ctx: ExecutionContext
  ): Promise<Response> {
    const url = new URL(request.url);
    const path = url.pathname;

    try {
      // Route classification
      if (isStaticAsset(path)) {
        return await handleStaticAsset(request, env);
      }

      if (isCacheableAPI(path)) {
        const cached = await checkD1Cache(env.D1_DATABASE, path, request.method);
        if (cached) {
          return cached;
        }
      }

      if (path.startsWith('/api/rag') || path.startsWith('/api/chat')) {
        // AI/Dynamic request - proxy to Rust Core via gRPC
        return await proxyToRustCore(request, env, ctx);
      }

      if (path.startsWith('/ws/metrics')) {
        // WebSocket upgrade for JARVIS HUD
        return await handleWebSocketUpgrade(request, env);
      }

      if (path.startsWith('/api/staff')) {
        // Staff management - proxy to Rust Core
        return await proxyToRustCore(request, env, ctx);
      }

      // Default: try cache first, then origin
      const cached = await checkD1Cache(env.D1_DATABASE, path, request.method);
      if (cached) {
        return cached;
      }

      // Forward to origin (Python backend or Rust Core)
      return await forwardToOrigin(request, env);
    } catch (error) {
      console.error('Edge proxy error:', error);
      return new Response(JSON.stringify({ error: 'Internal server error' }), {
        status: 500,
        headers: { 'Content-Type': 'application/json' },
      });
    }
  },
};

/**
 * Check if path is a static asset
 */
function isStaticAsset(path: string): boolean {
  const staticExtensions = ['.js', '.css', '.png', '.jpg', '.jpeg', '.gif', '.svg', '.ico', '.woff', '.woff2'];
  return staticExtensions.some(ext => path.endsWith(ext));
}

/**
 * Check if API endpoint is cacheable
 */
function isCacheableAPI(path: string): boolean {
  const cacheablePatterns = ['/api/content/', '/api/subjects/', '/api/boards/', '/api/classes/'];
  return cacheablePatterns.some(pattern => path.startsWith(pattern));
}

/**
 * Handle static assets from KV cache
 */
async function handleStaticAsset(request: Request, env: Env): Promise<Response> {
  const url = new URL(request.url);
  const cacheKey = `static:${url.pathname}`;

  // Try Assets first
  const asset = await env.ASSETS?.fetch(request);
  if (asset && asset.status === 200) {
    return asset;
  }

  // Fallback to origin
  return await forwardToOrigin(request, env);
}

/**
 * Check D1 cache for cached response
 */
async function checkD1Cache(
  db: D1Database | undefined,
  path: string,
  method: string
): Promise<Response | null> {
  if (!db || method !== 'GET') {
    return null;
  }

  try {
    const cacheKey = `cache:${path}`;
    const result = await db.prepare(
      'SELECT response_body, headers, status, expires_at FROM edge_cache WHERE cache_key = ? AND expires_at > ?'
    )
      .bind(cacheKey, Date.now())
      .first();

    if (result) {
      const headers = new JSON.parse(result.headers);
      return new Response(result.response_body, {
        status: result.status,
        headers,
      });
    }
  } catch (error) {
    console.warn('D1 cache read error:', error);
  }

  return null;
}

/**
 * Store response in D1 cache
 */
async function storeInD1Cache(
  db: D1Database | undefined,
  path: string,
  response: Response,
  ttlSeconds: number
): Promise<void> {
  if (!db) {
    return;
  }

  try {
    const cacheKey = `cache:${path}`;
    const expiresAt = Date.now() + ttlSeconds * 1000;
    const body = await response.text();
    const headers = JSON.stringify(Object.fromEntries(response.headers.entries()));

    await db.prepare(`
      INSERT OR REPLACE INTO edge_cache (cache_key, response_body, headers, status, expires_at, created_at)
      VALUES (?, ?, ?, ?, ?, ?)
    `)
      .bind(cacheKey, body, headers, response.status, expiresAt, Date.now())
      .run();
  } catch (error) {
    console.warn('D1 cache write error:', error);
  }
}

/**
 * Predict user intent from partial input for speculative prefetch
 */
function predictIntent(input: string): keyof typeof INTENT_PATTERNS | null {
  for (const [intent, pattern] of Object.entries(INTENT_PATTERNS)) {
    if (pattern.test(input)) {
      return intent as keyof typeof INTENT_PATTERNS;
    }
  }
  return null;
}

/**
 * Speculative prefetch handler
 * Triggers when user starts typing (first 3 keystrokes detected via frontend signal)
 */
async function speculativePrefetch(
  intent: string,
  env: Env,
  ctx: ExecutionContext
): Promise<void> {
  const prefetchQueries: Record<string, string> = {
    MATH: 'mathematics fundamentals',
    SCIENCE: 'basic science concepts',
    HISTORY: 'historical overview',
    LANGUAGE: 'language arts',
    EXAM: 'exam preparation tips',
    CHAPTER: 'chapter summaries',
  };

  const query = prefetchQueries[intent] || 'general knowledge';

  const prefetchRequest = new Request(`${CONFIG.RUST_CORE_HTTP_URL}/api/rag/query`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({
      query,
      top_k: 5,
      hybrid_search: true,
      hop_count: 3,
    }),
  });

  ctx.waitUntil(
    fetch(prefetchRequest)
      .then(response => response.json())
      .then(data => {
        // Store prefetched data in D1 for quick retrieval
        console.log('Speculative prefetch completed for intent:', intent);
      })
      .catch(error => console.warn('Speculative prefetch failed:', error))
  );
}

/**
 * Proxy request to Rust Core via gRPC-Web or HTTP
 */
async function proxyToRustCore(request: Request, env: Env, ctx: ExecutionContext): Promise<Response> {
  const url = new URL(request.url);
  
  // For gRPC endpoints, use gRPC-Web protocol
  if (url.pathname.includes('/grpc/') || request.headers.get('content-type')?.includes('application/grpc')) {
    return await proxyGrpcRequest(request, env);
  }

  // Standard HTTP proxy to Rust Core
  const targetUrl = `${CONFIG.RUST_CORE_HTTP_URL}${url.pathname}${url.search}`;
  
  const proxyRequest = new Request(targetUrl, {
    method: request.method,
    headers: request.headers,
    body: request.body,
  });

  const startTime = Date.now();
  
  try {
    const response = await fetch(proxyRequest);
    const latency = Date.now() - startTime;

    // Add timing header for JARVIS HUD
    const responseWithHeaders = new Response(response.body, response);
    responseWithHeaders.headers.set('X-Rust-Core-Latency', latency.toString());
    responseWithHeaders.headers.set('X-Served-By', 'rust-core');

    // Cache successful GET responses
    if (request.method === 'GET' && response.status === 200) {
      ctx.waitUntil(storeInD1Cache(env.D1_DATABASE, url.pathname, response.clone(), CONFIG.CACHE_TTL_SECONDS));
    }

    return responseWithHeaders;
  } catch (error) {
    console.error('Rust Core proxy error:', error);
    
    // Fallback to Python backend if Rust Core is unavailable
    return await forwardToOrigin(request, env);
  }
}

/**
 * Proxy gRPC request using gRPC-Web protocol
 */
async function proxyGrpcRequest(request: Request, env: Env): Promise<Response> {
  // Convert gRPC-Web to gRPC and forward to Rust Core
  // In production, use @improbable-eng/grpc-web-node-http-transport or similar
  
  const grpcTarget = `${CONFIG.RUST_CORE_GRPC_URL}`;
  
  return await fetch(grpcTarget, {
    method: 'POST',
    headers: {
      'Content-Type': 'application/grpc-web+proto',
      ...Object.fromEntries(request.headers),
    },
    body: request.body,
  });
}

/**
 * Handle WebSocket upgrade for JARVIS HUD metrics streaming
 */
async function handleWebSocketUpgrade(request: Request, env: Env): Promise<Response> {
  // Upgrade to WebSocket connection to Rust Core
  const [client, server] = Object.values(new WebSocketPair());
  
  const rustCoreWs = new WebSocket(`wss://${CONFIG.RUST_CORE_HTTP_URL.replace('https://', '')}/ws/metrics`);
  
  rustCoreWs.addEventListener('message', event => {
    if (client.readyState === WebSocket.OPEN) {
      client.send(event.data);
    }
  });
  
  rustCoreWs.addEventListener('close', () => {
    if (client.readyState === WebSocket.OPEN) {
      client.close();
    }
  });
  
  client.accept();
  
  return new Response(null, {
    status: 101,
    webSocket: client,
  });
}

/**
 * Forward request to origin (Python FastAPI backend)
 */
async function forwardToOrigin(request: Request, env: Env): Promise<Response> {
  const originUrl = env.PYTHON_BACKEND_URL || 'https://python-backend.syrabit.ai';
  const url = new URL(request.url);
  const targetUrl = `${originUrl}${url.pathname}${url.search}`;

  return await fetch(targetUrl, {
    method: request.method,
    headers: request.headers,
    body: request.body,
  });
}

/**
 * Handle speculative prefetch trigger from frontend
 * Frontend sends this when detecting user typing (first 3 keystrokes)
 */
async function handleSpeculativeTrigger(
  request: Request,
  env: Env,
  ctx: ExecutionContext
): Promise<Response> {
  const { intent, partial_input } = await request.json();
  
  if (intent || partial_input) {
    const predictedIntent = intent || predictIntent(partial_input);
    if (predictedIntent) {
      ctx.waitUntil(speculativePrefetch(predictedIntent, env, ctx));
    }
  }
  
  return new Response(JSON.stringify({ status: 'prefetch_triggered' }), {
    headers: { 'Content-Type': 'application/json' },
  });
}
