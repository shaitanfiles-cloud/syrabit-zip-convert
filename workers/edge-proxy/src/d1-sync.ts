interface D1Database {
  prepare(query: string): D1PreparedStatement;
  batch<T = unknown>(statements: D1PreparedStatement[]): Promise<D1Result<T>[]>;
  exec(query: string): Promise<D1ExecResult>;
}
interface D1PreparedStatement {
  bind(...values: unknown[]): D1PreparedStatement;
  first<T = unknown>(colName?: string): Promise<T | null>;
  run<T = unknown>(): Promise<D1Result<T>>;
  all<T = unknown>(): Promise<D1Result<T>>;
  raw<T = unknown[]>(options?: { columnNames?: boolean }): Promise<T[]>;
}
interface D1Result<T = unknown> { results: T[]; success: boolean; meta: object }
interface D1ExecResult { count: number; duration: number }

interface SyncPayload {
  boards?: Array<Record<string, unknown>>;
  classes?: Array<Record<string, unknown>>;
  streams?: Array<Record<string, unknown>>;
  subjects?: Array<Record<string, unknown>>;
  chapters?: Array<Record<string, unknown>>;
  topics?: Array<Record<string, unknown>>;
  seo_pages?: Array<Record<string, unknown>>;
}

function str(val: unknown): string {
  if (val === null || val === undefined) return "";
  return String(val);
}

function num(val: unknown, fallback = 0): number {
  if (val === null || val === undefined) return fallback;
  const n = Number(val);
  return isNaN(n) ? fallback : n;
}

export async function syncFromPayload(db: D1Database, payload: SyncPayload): Promise<{ success: boolean; synced: Record<string, number>; errors: string[] }> {
  const synced: Record<string, number> = {};
  const errors: string[] = [];

  if (payload.boards !== undefined) {
    try {
      await replaceTable(db, "boards", payload.boards || [], ["id", "name", "slug", "description", "created_at"]);
      synced.boards = (payload.boards || []).length;
    } catch (e: unknown) { errors.push(`boards: ${e instanceof Error ? e.message : String(e)}`); }
  }

  if (payload.classes !== undefined) {
    try {
      await replaceTable(db, "classes", payload.classes || [], ["id", "name", "slug", "board_id", "created_at"]);
      synced.classes = (payload.classes || []).length;
    } catch (e: unknown) { errors.push(`classes: ${e instanceof Error ? e.message : String(e)}`); }
  }

  if (payload.streams !== undefined) {
    try {
      await replaceTable(db, "streams", payload.streams || [], ["id", "name", "slug", "class_id", "created_at"]);
      synced.streams = (payload.streams || []).length;
    } catch (e: unknown) { errors.push(`streams: ${e instanceof Error ? e.message : String(e)}`); }
  }

  if (payload.subjects !== undefined) {
    try {
      const rows = (payload.subjects || []).map((s) => {
        const { id, name, slug, stream_id, status, description, icon, tags, thumbnail_url, thumbnailUrl, created_at, ...rest } = s;
        return {
          id: str(id),
          name: str(name),
          slug: str(slug),
          stream_id: str(stream_id),
          status: str(status) || "published",
          description: str(description),
          icon: str(icon),
          tags: JSON.stringify(tags || []),
          thumbnail_url: str(thumbnailUrl || thumbnail_url),
          created_at: str(created_at),
          extra_json: JSON.stringify(rest),
        };
      });
      await replaceTable(db, "subjects", rows, ["id", "name", "slug", "stream_id", "status", "description", "icon", "tags", "thumbnail_url", "created_at", "extra_json"]);
      synced.subjects = rows.length;
    } catch (e: unknown) { errors.push(`subjects: ${e instanceof Error ? e.message : String(e)}`); }
  }

  if (payload.chapters !== undefined) {
    try {
      const rows = (payload.chapters || []).map((c) => {
        const { id, title, slug, subject_id, order_index, notes_generated, status, created_at, ...rest } = c;
        return {
          id: str(id),
          title: str(title),
          slug: str(slug),
          subject_id: str(subject_id),
          order_index: num(order_index),
          notes_generated: notes_generated ? 1 : 0,
          status: str(status) || "published",
          created_at: str(created_at),
          extra_json: JSON.stringify(rest),
        };
      });
      await replaceTable(db, "chapters", rows, ["id", "title", "slug", "subject_id", "order_index", "notes_generated", "status", "created_at", "extra_json"]);
      synced.chapters = rows.length;
    } catch (e: unknown) { errors.push(`chapters: ${e instanceof Error ? e.message : String(e)}`); }
  }

  if (payload.topics !== undefined) {
    try {
      const rows = (payload.topics || []).map((t) => {
        const { id, title, slug, chapter_id, order, status, created_at, ...rest } = t;
        return {
          id: str(id),
          title: str(title),
          slug: str(slug),
          chapter_id: str(chapter_id),
          order: num(order),
          status: str(status) || "published",
          created_at: str(created_at),
          extra_json: JSON.stringify(rest),
        };
      });
      await replaceTable(db, "topics", rows, ["id", "title", "slug", "chapter_id", "order", "status", "created_at", "extra_json"]);
      synced.topics = rows.length;
    } catch (e: unknown) { errors.push(`topics: ${e instanceof Error ? e.message : String(e)}`); }
  }

  if (payload.seo_pages !== undefined) {
    try {
      const rows = (payload.seo_pages || []).map((p) => {
        const { id, slug, topic_id, page_type, status, title, meta_description, html_content, content,
                board_slug, class_slug, subject_slug, chapter_slug, topic_slug, word_count,
                created_at, updated_at, ...rest } = p;
        return {
          id: str(id),
          slug: str(slug),
          topic_id: str(topic_id),
          page_type: str(page_type),
          status: str(status) || "published",
          title: str(title),
          meta_description: str(meta_description),
          html_content: str(html_content || content),
          board_slug: str(board_slug),
          class_slug: str(class_slug),
          subject_slug: str(subject_slug),
          chapter_slug: str(chapter_slug),
          topic_slug: str(topic_slug),
          word_count: num(word_count),
          created_at: str(created_at),
          updated_at: str(updated_at),
          extra_json: JSON.stringify(rest),
        };
      });
      await replaceTable(db, "seo_pages", rows, ["id", "slug", "topic_id", "page_type", "status", "title", "meta_description", "html_content", "board_slug", "class_slug", "subject_slug", "chapter_slug", "topic_slug", "word_count", "created_at", "updated_at", "extra_json"]);
      synced.seo_pages = rows.length;
    } catch (e: unknown) { errors.push(`seo_pages: ${e instanceof Error ? e.message : String(e)}`); }
  }

  if (errors.length === 0) {
    const now = new Date().toISOString();
    try {
      await db.prepare(
        "INSERT INTO sync_meta (key, value, updated_at) VALUES ('last_sync', ?, ?) ON CONFLICT(key) DO UPDATE SET value = excluded.value, updated_at = excluded.updated_at"
      ).bind(now, now).run();
    } catch { /* ignore */ }
  }

  return { success: errors.length === 0, synced, errors };
}

async function replaceTable(db: D1Database, table: string, rows: Array<Record<string, unknown>>, columns: string[]): Promise<void> {
  const deleteStmt = db.prepare(`DELETE FROM ${table}`);

  if (!rows.length) {
    await db.batch([deleteStmt]);
    return;
  }

  const quotedCols = columns.map((c) => c === "order" ? `"order"` : c);
  const placeholders = columns.map(() => "?").join(", ");
  const sql = `INSERT INTO ${table} (${quotedCols.join(", ")}) VALUES (${placeholders})`;

  const batchSize = 50;
  const firstBatchRows = rows.slice(0, batchSize);
  const firstBatchStatements: D1PreparedStatement[] = [deleteStmt];
  for (const row of firstBatchRows) {
    const values = columns.map((col) => row[col] ?? "");
    firstBatchStatements.push(db.prepare(sql).bind(...values));
  }
  await db.batch(firstBatchStatements);

  for (let i = batchSize; i < rows.length; i += batchSize) {
    const batch = rows.slice(i, i + batchSize);
    const statements = batch.map((row) => {
      const values = columns.map((col) => row[col] ?? "");
      return db.prepare(sql).bind(...values);
    });
    await db.batch(statements);
  }
}

interface CountResult { count: number }
interface SyncMetaResult { value: string; updated_at: string }

export async function getSyncStatus(db: D1Database): Promise<Record<string, unknown>> {
  try {
    const [boardsRes, classesRes, streamsRes, subjectsRes, chaptersRes, topicsRes, seoRes, metaRes] = await db.batch([
      db.prepare("SELECT COUNT(*) as count FROM boards"),
      db.prepare("SELECT COUNT(*) as count FROM classes"),
      db.prepare("SELECT COUNT(*) as count FROM streams"),
      db.prepare("SELECT COUNT(*) as count FROM subjects"),
      db.prepare("SELECT COUNT(*) as count FROM chapters"),
      db.prepare("SELECT COUNT(*) as count FROM topics"),
      db.prepare("SELECT COUNT(*) as count FROM seo_pages"),
      db.prepare("SELECT value, updated_at FROM sync_meta WHERE key = 'last_sync'"),
    ]);

    const lastSync = (metaRes.results as SyncMetaResult[])?.[0] || null;

    return {
      counts: {
        boards: (boardsRes.results as CountResult[])?.[0]?.count ?? 0,
        classes: (classesRes.results as CountResult[])?.[0]?.count ?? 0,
        streams: (streamsRes.results as CountResult[])?.[0]?.count ?? 0,
        subjects: (subjectsRes.results as CountResult[])?.[0]?.count ?? 0,
        chapters: (chaptersRes.results as CountResult[])?.[0]?.count ?? 0,
        topics: (topicsRes.results as CountResult[])?.[0]?.count ?? 0,
        seo_pages: (seoRes.results as CountResult[])?.[0]?.count ?? 0,
      },
      last_sync: lastSync?.value || null,
      last_sync_at: lastSync?.updated_at || null,
    };
  } catch (e: unknown) {
    return { error: e instanceof Error ? e.message : String(e) };
  }
}
