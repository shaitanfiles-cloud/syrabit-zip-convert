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

interface BoardRow { id: string; name: string; slug: string; description?: string }
interface ClassRow { id: string; name: string; slug: string; board_id: string }
interface StreamRow { id: string; name: string; slug: string; class_id: string }
interface SubjectRow {
  id: string; name: string; slug: string; stream_id: string;
  status: string; description: string; icon: string; tags: string;
  thumbnail_url: string; extra_json: string;
}
interface ChapterRow {
  id: string; title: string; slug: string; subject_id: string;
  order_index: number; notes_generated: number; extra_json: string;
}
interface TopicRow { id: string; title: string; slug: string; chapter_id: string; order: number }
interface SeoPageRow {
  id: string; slug: string; topic_id: string; page_type: string;
  status: string; title: string; meta_description: string; html_content: string;
  board_slug: string; class_slug: string; subject_slug: string;
  chapter_slug: string; topic_slug: string; word_count: number;
  created_at: string; updated_at: string; extra_json: string;
}

let _d1Synced: boolean | null = null;
let _d1SyncedCheckAt = 0;
const D1_SYNCED_CHECK_INTERVAL_MS = 60_000;

const _tablePopulatedCache = new Map<string, { populated: boolean; checkedAt: number }>();
const TABLE_POPULATED_CHECK_INTERVAL_MS = 120_000;

export async function isD1Synced(db: D1Database): Promise<boolean> {
  const now = Date.now();
  if (_d1Synced !== null && (now - _d1SyncedCheckAt) < D1_SYNCED_CHECK_INTERVAL_MS) {
    return _d1Synced;
  }
  try {
    const row = await db.prepare("SELECT value FROM sync_meta WHERE key = 'last_sync'").first<{ value: string }>();
    _d1Synced = !!row?.value;
  } catch {
    _d1Synced = false;
  }
  _d1SyncedCheckAt = now;
  return _d1Synced;
}

export function resetD1SyncedCache(): void {
  _d1Synced = null;
  _d1SyncedCheckAt = 0;
  _tablePopulatedCache.clear();
}

export async function isTablePopulated(db: D1Database, table: string): Promise<boolean> {
  const now = Date.now();
  const cached = _tablePopulatedCache.get(table);
  if (cached && (now - cached.checkedAt) < TABLE_POPULATED_CHECK_INTERVAL_MS) {
    return cached.populated;
  }
  try {
    const row = await db.prepare(`SELECT 1 FROM ${table} LIMIT 1`).first();
    const populated = !!row;
    _tablePopulatedCache.set(table, { populated, checkedAt: now });
    return populated;
  } catch {
    return false;
  }
}

export async function getBoards(db: D1Database): Promise<BoardRow[] | null> {
  try {
    const { results } = await db.prepare("SELECT id, name, slug, description FROM boards").all<BoardRow>();
    return results;
  } catch {
    return null;
  }
}

export async function getClasses(db: D1Database, boardId?: string): Promise<ClassRow[] | null> {
  try {
    if (boardId) {
      const { results } = await db.prepare("SELECT id, name, slug, board_id FROM classes WHERE board_id = ?").bind(boardId).all<ClassRow>();
      return results;
    }
    const { results } = await db.prepare("SELECT id, name, slug, board_id FROM classes").all<ClassRow>();
    return results;
  } catch {
    return null;
  }
}

export async function getStreams(db: D1Database, classId?: string): Promise<StreamRow[] | null> {
  try {
    if (classId) {
      const { results } = await db.prepare("SELECT id, name, slug, class_id FROM streams WHERE class_id = ?").bind(classId).all<StreamRow>();
      return results;
    }
    const { results } = await db.prepare("SELECT id, name, slug, class_id FROM streams").all<StreamRow>();
    return results;
  } catch {
    return null;
  }
}

export async function getSubjectsByStream(db: D1Database, streamId: string): Promise<Record<string, unknown>[] | null> {
  try {
    const { results } = await db.prepare(
      "SELECT id, name, slug, stream_id, status, description, icon, tags, thumbnail_url, extra_json FROM subjects WHERE stream_id = ? AND status = 'published'"
    ).bind(streamId).all<SubjectRow>();
    return results.map(normalizeSubject);
  } catch {
    return null;
  }
}

export async function getSubjectsByClassId(db: D1Database, classId: string): Promise<Record<string, unknown>[] | null> {
  try {
    const { results: streams } = await db.prepare("SELECT id FROM streams WHERE class_id = ?").bind(classId).all<{ id: string }>();
    if (!streams.length) return [];
    const placeholders = streams.map(() => "?").join(",");
    const streamIds = streams.map((s) => s.id);
    const { results } = await db.prepare(
      `SELECT id, name, slug, stream_id, status, description, icon, tags, thumbnail_url, extra_json FROM subjects WHERE stream_id IN (${placeholders}) AND status = 'published'`
    ).bind(...streamIds).all<SubjectRow>();
    return results.map(normalizeSubject);
  } catch {
    return null;
  }
}

export async function getAllSubjects(db: D1Database): Promise<Record<string, unknown>[] | null> {
  try {
    const { results } = await db.prepare(
      "SELECT id, name, slug, stream_id, status, description, icon, tags, thumbnail_url, extra_json FROM subjects WHERE status = 'published'"
    ).all<SubjectRow>();
    return results.map(normalizeSubject);
  } catch {
    return null;
  }
}

export async function getSubjectById(db: D1Database, subjectId: string): Promise<Record<string, unknown> | null> {
  try {
    const row = await db.prepare(
      "SELECT id, name, slug, stream_id, status, description, icon, tags, thumbnail_url, extra_json FROM subjects WHERE id = ?"
    ).bind(subjectId).first<SubjectRow>();
    if (!row) return null;
    return normalizeSubject(row);
  } catch {
    return null;
  }
}

export async function getChaptersBySubject(db: D1Database, subjectId: string): Promise<Record<string, unknown>[] | null> {
  try {
    const { results } = await db.prepare(
      "SELECT id, title, slug, subject_id, order_index, notes_generated, extra_json FROM chapters WHERE subject_id = ? ORDER BY order_index ASC"
    ).bind(subjectId).all<ChapterRow>();
    return results.map(normalizeChapter);
  } catch {
    return null;
  }
}

export async function getChapterBySlug(db: D1Database, slug: string): Promise<Record<string, unknown> | null> {
  try {
    const row = await db.prepare(
      "SELECT id, title, slug, subject_id, order_index, notes_generated, extra_json FROM chapters WHERE slug = ? LIMIT 1"
    ).bind(slug).first<ChapterRow>();
    if (!row) return null;
    return normalizeChapter(row);
  } catch {
    return null;
  }
}

export async function getTopicsByChapter(db: D1Database, chapterId: string): Promise<TopicRow[] | null> {
  try {
    const { results } = await db.prepare(
      'SELECT id, title, slug, chapter_id, "order" FROM topics WHERE chapter_id = ? AND status = \'published\' ORDER BY "order" ASC'
    ).bind(chapterId).all<TopicRow>();
    return results;
  } catch {
    return null;
  }
}

export async function getSeoPageBySlug(db: D1Database, slug: string): Promise<Record<string, unknown> | null> {
  try {
    const row = await db.prepare(
      "SELECT id, slug, topic_id, page_type, status, title, meta_description, html_content, board_slug, class_slug, subject_slug, chapter_slug, topic_slug, word_count, created_at, updated_at, extra_json FROM seo_pages WHERE slug = ? AND status = 'published' LIMIT 1"
    ).bind(slug).first<SeoPageRow>();
    if (!row) return null;
    return normalizeSeoPage(row);
  } catch {
    return null;
  }
}

export async function getSeoPageBySlugs(
  db: D1Database,
  boardSlug: string,
  classSlug: string,
  subjectSlug: string,
  topicSlug: string,
  pageType: string = "notes",
): Promise<Record<string, unknown> | null> {
  try {
    const row = await db.prepare(
      "SELECT id, slug, topic_id, page_type, status, title, meta_description, html_content, board_slug, class_slug, subject_slug, chapter_slug, topic_slug, word_count, created_at, updated_at, extra_json FROM seo_pages WHERE board_slug = ? AND class_slug = ? AND subject_slug = ? AND topic_slug = ? AND page_type = ? AND status = 'published' LIMIT 1"
    ).bind(boardSlug, classSlug, subjectSlug, topicSlug, pageType).first<SeoPageRow>();
    if (!row) return null;
    return normalizeSeoPage(row);
  } catch {
    return null;
  }
}

export async function getSeoPageTypes(
  db: D1Database,
  boardSlug: string,
  classSlug: string,
  subjectSlug: string,
  topicSlug: string,
): Promise<Array<{ page_type: string; title: string; word_count: number; id: string }> | null> {
  try {
    const { results } = await db.prepare(
      "SELECT page_type, title, word_count, id FROM seo_pages WHERE board_slug = ? AND class_slug = ? AND subject_slug = ? AND topic_slug = ? AND status = 'published'"
    ).bind(boardSlug, classSlug, subjectSlug, topicSlug).all<{ page_type: string; title: string; word_count: number; id: string }>();
    return results;
  } catch {
    return null;
  }
}

export async function getSeoPageBundle(
  db: D1Database,
  boardSlug: string,
  classSlug: string,
  subjectSlug: string,
  topicSlug: string,
  pageType: string = "notes",
): Promise<{ page: Record<string, unknown>; pageTypes: Array<{ page_type: string; title: string; word_count: number; id: string }>; iqContent: string | null } | null> {
  try {
    const [page, types] = await Promise.all([
      getSeoPageBySlugs(db, boardSlug, classSlug, subjectSlug, topicSlug, pageType),
      getSeoPageTypes(db, boardSlug, classSlug, subjectSlug, topicSlug),
    ]);
    if (types === null) return null;
    if (!page) return null;
    let iqContent: string | null = null;
    if (pageType === "notes" && types.some(t => t.page_type === "important-questions")) {
      const iqPage = await getSeoPageBySlugs(db, boardSlug, classSlug, subjectSlug, topicSlug, "important-questions");
      if (iqPage) {
        iqContent = (iqPage.html_content as string) || null;
      }
    }
    return { page, pageTypes: types, iqContent };
  } catch {
    return null;
  }
}

export async function getSitemapEntries(db: D1Database, pageType?: string): Promise<unknown[] | null> {
  try {
    if (pageType) {
      const { results } = await db.prepare(
        "SELECT board_slug, class_slug, subject_slug, topic_slug, page_type, updated_at FROM seo_pages WHERE status = 'published' AND page_type = ?"
      ).bind(pageType).all<SeoPageRow>();
      return results;
    }
    const { results } = await db.prepare(
      "SELECT board_slug, class_slug, subject_slug, topic_slug, page_type, updated_at FROM seo_pages WHERE status = 'published'"
    ).all<SeoPageRow>();
    return results;
  } catch {
    return null;
  }
}

export async function getSeoPagesByType(
  db: D1Database,
  pageType: string,
): Promise<Array<{ board_slug: string; class_slug: string; subject_slug: string; topic_slug: string; page_type: string; updated_at: string; created_at: string }> | null> {
  try {
    const { results } = await db.prepare(
      "SELECT board_slug, class_slug, subject_slug, topic_slug, page_type, updated_at, created_at FROM seo_pages WHERE status = 'published' AND page_type = ?"
    ).bind(pageType).all();
    return results as Array<{ board_slug: string; class_slug: string; subject_slug: string; topic_slug: string; page_type: string; updated_at: string; created_at: string }>;
  } catch {
    return null;
  }
}

export async function getPublishedPageTypes(db: D1Database): Promise<string[] | null> {
  try {
    const { results } = await db.prepare(
      "SELECT DISTINCT page_type FROM seo_pages WHERE status = 'published'"
    ).all<{ page_type: string }>();
    return results.map(r => r.page_type);
  } catch {
    return null;
  }
}

export async function getSubjectSitemapEntries(db: D1Database): Promise<Array<{ board_slug: string; class_slug: string; subject_slug: string }> | null> {
  try {
    const [boardsRes, classesRes, streamsRes, subjectsRes] = await db.batch([
      db.prepare("SELECT id, slug FROM boards"),
      db.prepare("SELECT id, slug, board_id FROM classes"),
      db.prepare("SELECT id, class_id FROM streams"),
      db.prepare("SELECT slug, stream_id FROM subjects WHERE status = 'published'"),
    ]);

    const boards = (boardsRes.results || []) as Array<{ id: string; slug: string }>;
    const classes = (classesRes.results || []) as Array<{ id: string; slug: string; board_id: string }>;
    const streams = (streamsRes.results || []) as Array<{ id: string; class_id: string }>;
    const subjects = (subjectsRes.results || []) as Array<{ slug: string; stream_id: string }>;

    const boardMap = new Map(boards.map(b => [b.id, b.slug]));
    const classMap = new Map(classes.map(c => [c.id, { slug: c.slug, board_id: c.board_id }]));
    const streamMap = new Map(streams.map(s => [s.id, s.class_id]));

    const seen = new Set<string>();
    const entries: Array<{ board_slug: string; class_slug: string; subject_slug: string }> = [];

    for (const sub of subjects) {
      const classId = streamMap.get(sub.stream_id);
      if (!classId) continue;
      const cls = classMap.get(classId);
      if (!cls) continue;
      const boardSlug = boardMap.get(cls.board_id);
      if (!boardSlug || !cls.slug || !sub.slug) continue;
      const key = `${boardSlug}/${cls.slug}/${sub.slug}`;
      if (!seen.has(key)) {
        seen.add(key);
        entries.push({ board_slug: boardSlug, class_slug: cls.slug, subject_slug: sub.slug });
      }
    }
    return entries;
  } catch {
    return null;
  }
}

export async function getChapterSitemapEntries(db: D1Database): Promise<Array<{ board_slug: string; class_slug: string; subject_slug: string; chapter_slug: string; updated_at: string }> | null> {
  try {
    const [boardsRes, classesRes, streamsRes, subjectsRes, chaptersRes] = await db.batch([
      db.prepare("SELECT id, slug FROM boards"),
      db.prepare("SELECT id, slug, board_id FROM classes"),
      db.prepare("SELECT id, class_id FROM streams"),
      db.prepare("SELECT id, slug, stream_id FROM subjects WHERE status = 'published'"),
      db.prepare("SELECT id, slug, title, subject_id, extra_json FROM chapters"),
    ]);

    const boards = (boardsRes.results || []) as Array<{ id: string; slug: string }>;
    const classes = (classesRes.results || []) as Array<{ id: string; slug: string; board_id: string }>;
    const streams = (streamsRes.results || []) as Array<{ id: string; class_id: string }>;
    const subjects = (subjectsRes.results || []) as Array<{ id: string; slug: string; stream_id: string }>;
    const chapters = (chaptersRes.results || []) as Array<{ id: string; slug: string; title: string; subject_id: string; extra_json: string }>;

    const boardMap = new Map(boards.map(b => [b.id, b.slug]));
    const classMap = new Map(classes.map(c => [c.id, { slug: c.slug, board_id: c.board_id }]));
    const streamMap = new Map(streams.map(s => [s.id, s.class_id]));
    const subjectMap = new Map(subjects.map(s => [s.id, { slug: s.slug, stream_id: s.stream_id }]));

    const entries: Array<{ board_slug: string; class_slug: string; subject_slug: string; chapter_slug: string; updated_at: string }> = [];

    for (const ch of chapters) {
      const sub = subjectMap.get(ch.subject_id);
      if (!sub) continue;
      const classId = streamMap.get(sub.stream_id);
      if (!classId) continue;
      const cls = classMap.get(classId);
      if (!cls) continue;
      const boardSlug = boardMap.get(cls.board_id);
      if (!boardSlug || !cls.slug || !sub.slug) continue;
      const chSlug = ch.slug || ch.title.toLowerCase().replace(/[^a-z0-9]+/g, "-").replace(/^-|-$/g, "");
      if (!chSlug) continue;
      let updatedAt = "";
      if (ch.extra_json) {
        try {
          const extra = JSON.parse(ch.extra_json) as Record<string, string>;
          updatedAt = extra.updated_at || extra.created_at || "";
        } catch { /* ignore */ }
      }
      entries.push({ board_slug: boardSlug, class_slug: cls.slug, subject_slug: sub.slug, chapter_slug: chSlug, updated_at: updatedAt });
    }
    return entries;
  } catch {
    return null;
  }
}

export async function getLibraryBundle(db: D1Database): Promise<Record<string, unknown> | null> {
  try {
    const [boardsRes, classesRes, streamsRes, subjectsRes, chaptersRes] = await db.batch([
      db.prepare("SELECT id, name, slug FROM boards"),
      db.prepare("SELECT id, name, slug, board_id FROM classes"),
      db.prepare("SELECT id, name, slug, class_id FROM streams"),
      db.prepare("SELECT id, name, slug, stream_id, status, description, icon, tags, thumbnail_url, extra_json FROM subjects WHERE status = 'published'"),
      db.prepare("SELECT id, title, slug, subject_id, order_index, notes_generated, extra_json FROM chapters ORDER BY order_index ASC"),
    ]);

    const subjects = ((subjectsRes.results || []) as SubjectRow[]).map(normalizeSubject);
    const chapters = ((chaptersRes.results || []) as ChapterRow[]).map(normalizeChapter);

    const chaptersBySubject: Record<string, number> = {};
    const notesChaptersBySubject: Record<string, number> = {};
    for (const ch of chapters) {
      const sid = ch.subject_id as string;
      if (sid) {
        chaptersBySubject[sid] = (chaptersBySubject[sid] || 0) + 1;
        if (ch.notes_generated) {
          notesChaptersBySubject[sid] = (notesChaptersBySubject[sid] || 0) + 1;
        }
      }
    }

    for (const s of subjects) {
      const sid = s.id as string;
      const total = chaptersBySubject[sid] || 0;
      const notes = notesChaptersBySubject[sid] || 0;
      s.chapter_count = total;
      s.notes_count = notes;
      s.notes_pct = total > 0 ? Math.round((notes / total) * 100) : 0;
    }

    return {
      boards: boardsRes.results || [],
      classes: classesRes.results || [],
      streams: streamsRes.results || [],
      subjects,
      chapters,
    };
  } catch {
    return null;
  }
}

function normalizeSubject(row: SubjectRow): Record<string, unknown> {
  const result: Record<string, unknown> = { ...row };
  if (row.thumbnail_url) {
    result.thumbnailUrl = row.thumbnail_url;
    delete result.thumbnail_url;
  }
  if (typeof row.tags === "string") {
    try { result.tags = JSON.parse(row.tags); } catch { result.tags = []; }
  }
  if (row.extra_json) {
    try {
      const extra = JSON.parse(row.extra_json) as Record<string, unknown>;
      Object.assign(result, extra);
    } catch { /* ignore */ }
    delete result.extra_json;
  }
  return result;
}

function normalizeChapter(row: ChapterRow): Record<string, unknown> {
  const result: Record<string, unknown> = { ...row };
  if (row.extra_json) {
    try {
      const extra = JSON.parse(row.extra_json) as Record<string, unknown>;
      Object.assign(result, extra);
    } catch { /* ignore */ }
    delete result.extra_json;
  }
  return result;
}

function normalizeSeoPage(row: SeoPageRow): Record<string, unknown> {
  const result: Record<string, unknown> = { ...row };
  if (row.extra_json) {
    try {
      const extra = JSON.parse(row.extra_json) as Record<string, unknown>;
      Object.assign(result, extra);
    } catch { /* ignore */ }
    delete result.extra_json;
  }
  return result;
}
