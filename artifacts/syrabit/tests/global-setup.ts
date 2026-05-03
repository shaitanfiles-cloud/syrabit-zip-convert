/**
 * Playwright global setup — fixture ↔ OpenAPI schema drift detection.
 *
 * Task #4: Connect test stubs to real API contracts so drift is caught
 * automatically.
 *
 * Three checks run before any test file is loaded:
 *
 * 1. URL-existence check
 *    Every URL substring key registered in admin-mocks.ts (FIXTURE_KEYS)
 *    and every exact path used in study-flows.spec.ts must correspond to
 *    at least one path in the committed OpenAPI snapshot
 *    (tests/api-schema.json).
 *
 * 2. Required-field check (schema-driven, automatic)
 *    For every (key, sample_body) pair, the validator resolves the
 *    matching OpenAPI path's 200-response schema (following $ref chains)
 *    and checks that every `required` field declared in the schema is
 *    present in the fixture body.  Coverage expands automatically as
 *    backend routes gain response_model annotations.
 *
 * 3. Property-type check (schema-driven)
 *    For each fixture body field that appears in the resolved schema's
 *    `properties`, the JavaScript type of the value must match the
 *    declared OpenAPI type (string/number/integer/boolean/array/object).
 *
 * How to refresh the schema after a backend change:
 *
 *   python artifacts/syrabit-backend/scripts/export_api_schema.py
 *
 * That command re-generates tests/api-schema.json from the live FastAPI
 * route registry.  Commit the updated file alongside any fixture changes.
 */

import { readFileSync } from 'fs';
import { fileURLToPath } from 'url';
import { dirname, resolve } from 'path';

import { FIXTURE_KEYS, FIXTURE_SAMPLES } from './admin-mocks';

// ESM-safe equivalent of __dirname.
const _dir = dirname(fileURLToPath(import.meta.url));

// ─────────────────────────── Types ───────────────────────────────────────────

interface SchemaObject {
  $ref?: string;
  type?: string;
  required?: string[];
  properties?: Record<string, SchemaObject>;
  items?: SchemaObject;
  anyOf?: SchemaObject[];
  allOf?: SchemaObject[];
  oneOf?: SchemaObject[];
  nullable?: boolean;
}

interface OpenApiOperation {
  responses?: Record<string, {
    content?: Record<string, { schema?: SchemaObject }>;
  }>;
}

interface OpenApiSchema {
  paths: Record<string, Record<string, OpenApiOperation>>;
  components?: {
    schemas?: Record<string, SchemaObject>;
  };
}

// ─────────────── Study-flows fixture samples (inline) ────────────────────────

/**
 * Representative bodies for the study-flows.spec.ts mock routes.
 *
 * These fixtures are defined inline in the spec file and not exported,
 * so we maintain representative samples here.  Keep these in sync with
 * the mock route handlers in study-flows.spec.ts.
 */
const STUDY_FIXTURE_SAMPLES: ReadonlyMap<string, unknown> = new Map([
  ['/api/edu/quiz/generate', {
    ok: true, count: 2,
    questions: [{
      id: 'q1', q: 'Question?',
      choices: ['A', 'B', 'C', 'D'],
      answer: 1, explanation: 'Because.',
    }],
  }],
  ['/api/edu/notes', { ok: true, notes: [], count: 0 }],
  ['/api/edu/flashcards/due', { ok: true, cards: [], total: 0 }],
  ['/api/edu/flashcards/streak', { ok: true, current_streak: 0, best_streak: 0, today: 0 }],
  ['/api/edu/flashcards/review', {
    ok: true,
    card: { id: 'c1', ef: 2.5, interval_days: 1, repetitions: 1, last_reviewed: '2026-01-01T00:00:00Z' },
    sm2: { interval_days: 1, repetitions: 1, ef: 2.5 },
    streak: 1,
  }],
  ['/api/edu/flashcards/build', { ok: true, created: 0 }],
  ['/api/edu/study/settings', { ok: true, strict_mode: false, guardian_locked: false, has_pin: false, streak: 0 }],
  ['/api/edu/guardian/pin/set', { ok: true }],
  ['/api/edu/guardian/pin/verify', { ok: true, valid: true, set: false }],
]);

// ─────────────── OpenAPI schema loading and utilities ─────────────────────────

function loadSchema(): OpenApiSchema {
  const schemaPath = resolve(_dir, 'api-schema.json');
  try {
    return JSON.parse(readFileSync(schemaPath, 'utf-8')) as OpenApiSchema;
  } catch (err) {
    throw new Error(
      `[fixture-schema-drift] Cannot read OpenAPI schema at ${schemaPath}.\n` +
      `Run: python artifacts/syrabit-backend/scripts/export_api_schema.py\n` +
      `Original error: ${err}`,
    );
  }
}

/**
 * Resolve a $ref string (e.g. "#/components/schemas/HealthOut") to the
 * referenced SchemaObject within the top-level schema document.
 *
 * Only local JSON Pointer refs (#/…) are supported — OpenAPI 3 always
 * uses these for intra-document component references.
 */
function resolveRef(ref: string, schema: OpenApiSchema): SchemaObject | null {
  if (!ref.startsWith('#/')) return null;
  const parts = ref.slice(2).split('/');
  let node: unknown = schema;
  for (const part of parts) {
    if (node == null || typeof node !== 'object') return null;
    node = (node as Record<string, unknown>)[part];
  }
  return (node as SchemaObject) ?? null;
}

/**
 * Fully resolve a SchemaObject, following $ref and merging allOf chains.
 *
 * Returns the concrete SchemaObject with `required`, `properties`, and
 * `type` populated (where declared), or null if the ref cannot be
 * resolved.
 */
function resolveSchema(s: SchemaObject, root: OpenApiSchema): SchemaObject | null {
  if (s.$ref) {
    const resolved = resolveRef(s.$ref, root);
    return resolved ? resolveSchema(resolved, root) : null;
  }
  if (s.allOf && s.allOf.length > 0) {
    const merged: SchemaObject = { required: [], properties: {} };
    for (const sub of s.allOf) {
      const r = resolveSchema(sub, root);
      if (!r) continue;
      merged.required = [...(merged.required ?? []), ...(r.required ?? [])];
      merged.properties = { ...(merged.properties ?? {}), ...(r.properties ?? {}) };
      if (r.type) merged.type = r.type;
    }
    return merged;
  }
  return s;
}

/**
 * Returns true when a schema path "covers" a fixture key, meaning a real
 * HTTP request to that backend path would be intercepted by a fixture
 * registered with that key via `url.includes(key)`.
 */
function schemaPathCoversKey(schemaPath: string, key: string): boolean {
  return schemaPath === key
    || schemaPath.startsWith(key + '/')
    || schemaPath.startsWith(key + '?');
}

/**
 * Given a fixture URL substring key, find the most appropriate OpenAPI
 * schema path and return the SchemaObject for its 200 JSON response
 * (resolved through $ref).
 *
 * Matching priority:
 *   1. Exact path match (key === schemaPath)
 *   2. Shortest prefix match (avoids selecting a child path's schema
 *      when the key is a broad prefix like /api/admin/alerts)
 *
 * Returns null when no typed 200 response schema exists for the matched
 * path (most admin routes have no response_model and return `{}`).
 */
function resolvedResponseSchema(
  key: string,
  schema: OpenApiSchema,
): SchemaObject | null {
  const schemaPaths = Object.keys(schema.paths);

  // Exact match first, then shortest prefix matches.
  const exact = schemaPaths.filter((p) => p === key);
  const prefixes = schemaPaths
    .filter((p) => p !== key && schemaPathCoversKey(p, key))
    .sort((a, b) => a.length - b.length);
  const ordered = [...exact, ...prefixes];

  for (const schemaPath of ordered) {
    const methods = schema.paths[schemaPath];
    // Prefer GET; fall back to POST, then any other method.
    const orderedMethods = [
      'get', 'post',
      ...Object.keys(methods).filter((m) => m !== 'get' && m !== 'post'),
    ];
    for (const method of orderedMethods) {
      const op = methods[method];
      if (!op) continue;
      const resp200 = op.responses?.['200'];
      if (!resp200) continue;
      for (const ctInfo of Object.values(resp200.content ?? {})) {
        const rawSchema = ctInfo.schema;
        if (!rawSchema) continue;
        const resolved = resolveSchema(rawSchema, schema);
        // Only return if the resolved schema has actual content (not just `{}`)
        if (resolved && (resolved.required?.length || resolved.properties)) {
          return resolved;
        }
      }
    }
  }
  return null;
}

// ─────────────────────────── Validation checks ───────────────────────────────

/** Check 1: every fixture URL key maps to at least one real backend path. */
function checkUrlExistence(
  allKeys: ReadonlyArray<string>,
  schemaPaths: string[],
  errors: string[],
): void {
  for (const key of allKeys) {
    const hasMatch = schemaPaths.some((p) => schemaPathCoversKey(p, key));
    if (!hasMatch) {
      const tail = key.split('/').pop() ?? '';
      const closest = tail.length > 2
        ? schemaPaths.filter((p) => p.includes(tail)).slice(0, 3).join(', ')
        : '(none found)';
      errors.push(
        `No backend path found for fixture key "${key}".\n` +
        `  The endpoint may have been renamed or removed, or the key is wrong.\n` +
        `  Closest schema paths: ${closest || '(none found)'}`,
      );
    }
  }
}

/**
 * Map a JS runtime value to the OpenAPI type string it corresponds to.
 * `integer` is a subset of `number` — both `number` and `integer` match
 * when the JS value is a finite number.
 */
function jsTypeToOpenApi(value: unknown): string {
  if (value === null) return 'null';
  if (Array.isArray(value)) return 'array';
  if (typeof value === 'object') return 'object';
  if (typeof value === 'number') return Number.isInteger(value) ? 'integer' : 'number';
  return typeof value;
}

function typeMatches(declaredType: string, value: unknown): boolean {
  if (declaredType === 'number' || declaredType === 'integer') {
    return typeof value === 'number';
  }
  return jsTypeToOpenApi(value) === declaredType;
}

/**
 * Checks 2 + 3: validate all fixture sample bodies against their
 * corresponding OpenAPI response schemas (required fields + property types).
 */
function checkPayloadShapes(
  allSamples: ReadonlyMap<string, unknown>,
  schema: OpenApiSchema,
  errors: string[],
): void {
  const schemaPaths = Object.keys(schema.paths);

  for (const [key, body] of allSamples) {
    const responseSchema = resolvedResponseSchema(key, schema);
    if (!responseSchema) continue;

    if (!body || typeof body !== 'object' || Array.isArray(body)) continue;
    const bodyObj = body as Record<string, unknown>;

    // Find the schema path this key resolves to (for error messages)
    const schemaPath = schemaPaths.find((p) => schemaPathCoversKey(p, key)) ?? key;

    // 2. Required fields
    for (const field of responseSchema.required ?? []) {
      if (!(field in bodyObj)) {
        errors.push(
          `Fixture "${key}" is missing required field "${field}"` +
          ` (declared on ${schemaPath}).\n` +
          `  Add "${field}" with the correct type to the fixture body.`,
        );
      }
    }

    // 3. Property types (for fields the fixture DOES provide)
    const properties = responseSchema.properties ?? {};
    for (const [field, value] of Object.entries(bodyObj)) {
      const propSchema = properties[field];
      if (!propSchema) continue;

      // Resolve anyOf / nullable — accept any matching type within the union
      const candidates: SchemaObject[] = propSchema.anyOf?.length
        ? propSchema.anyOf
        : [propSchema];

      const resolved = candidates
        .map((c) => resolveSchema(c, schema))
        .filter((r): r is SchemaObject => r !== null);

      const anyTypeMatch = resolved.some((r) => {
        if (!r.type) return true;
        if (value === null && (r.nullable || r.type === 'null')) return true;
        return typeMatches(r.type, value);
      });

      if (!anyTypeMatch && value !== null) {
        const expected = candidates
          .map((c) => resolveSchema(c, schema)?.type ?? '?')
          .join(' | ');
        const got = jsTypeToOpenApi(value);
        errors.push(
          `Fixture "${key}": field "${field}" has type "${got}" but ` +
          `schema for ${schemaPath} declares "${expected}".\n` +
          `  Fix the fixture body or the Pydantic model.`,
        );
      }
    }
  }
}

// ─────────────────────────── Entry point ─────────────────────────────────────

async function validateFixtures(): Promise<void> {
  const schema = loadSchema();
  const schemaPaths = Object.keys(schema.paths ?? {});
  const errors: string[] = [];

  const allKeys: string[] = [...FIXTURE_KEYS, ...STUDY_FIXTURE_SAMPLES.keys()];
  const allSamples: ReadonlyMap<string, unknown> = new Map([
    ...FIXTURE_SAMPLES,
    ...STUDY_FIXTURE_SAMPLES,
  ]);

  checkUrlExistence(allKeys, schemaPaths, errors);
  checkPayloadShapes(allSamples, schema, errors);

  if (errors.length === 0) {
    console.log(
      `\n[fixture-schema-drift] OK — ${allKeys.length} fixture patterns validated ` +
      `against ${schemaPaths.length} paths in api-schema.json.\n`,
    );
    return;
  }

  const header =
    '\n[fixture-schema-drift] Test fixtures are out of sync with the backend OpenAPI schema.\n' +
    'These fixtures pass against stale stubs but the real app shape is already different:\n';

  const body = errors.map((e, i) => `\n  ${i + 1}. ${e}`).join('');

  const footer =
    '\n\nTo refresh the schema snapshot:\n' +
    '  python artifacts/syrabit-backend/scripts/export_api_schema.py\n' +
    'Then update the affected fixture keys/bodies and re-run the suite.\n';

  throw new Error(header + body + footer);
}

export default async function globalSetup(): Promise<void> {
  await validateFixtures();
}
