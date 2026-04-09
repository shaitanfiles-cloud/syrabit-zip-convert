-- D1 Edge Content Database Schema
-- Mirrors MongoDB content catalog for edge-first serving

CREATE TABLE IF NOT EXISTS boards (
    id TEXT PRIMARY KEY,
    name TEXT NOT NULL,
    slug TEXT NOT NULL,
    description TEXT NOT NULL DEFAULT '',
    created_at TEXT NOT NULL DEFAULT ''
);
CREATE INDEX IF NOT EXISTS idx_boards_slug ON boards(slug);

CREATE TABLE IF NOT EXISTS classes (
    id TEXT PRIMARY KEY,
    name TEXT NOT NULL,
    slug TEXT NOT NULL,
    board_id TEXT NOT NULL,
    created_at TEXT NOT NULL DEFAULT ''
);
CREATE INDEX IF NOT EXISTS idx_classes_board ON classes(board_id);
CREATE INDEX IF NOT EXISTS idx_classes_slug ON classes(slug);

CREATE TABLE IF NOT EXISTS streams (
    id TEXT PRIMARY KEY,
    name TEXT NOT NULL,
    slug TEXT NOT NULL,
    class_id TEXT NOT NULL,
    created_at TEXT NOT NULL DEFAULT ''
);
CREATE INDEX IF NOT EXISTS idx_streams_class ON streams(class_id);
CREATE INDEX IF NOT EXISTS idx_streams_slug ON streams(slug);

CREATE TABLE IF NOT EXISTS subjects (
    id TEXT PRIMARY KEY,
    name TEXT NOT NULL,
    slug TEXT NOT NULL,
    stream_id TEXT NOT NULL,
    status TEXT NOT NULL DEFAULT 'published',
    description TEXT NOT NULL DEFAULT '',
    icon TEXT NOT NULL DEFAULT '',
    tags TEXT NOT NULL DEFAULT '[]',
    thumbnail_url TEXT NOT NULL DEFAULT '',
    created_at TEXT NOT NULL DEFAULT '',
    extra_json TEXT NOT NULL DEFAULT '{}'
);
CREATE INDEX IF NOT EXISTS idx_subjects_stream ON subjects(stream_id);
CREATE INDEX IF NOT EXISTS idx_subjects_slug ON subjects(slug);
CREATE INDEX IF NOT EXISTS idx_subjects_status ON subjects(status);

CREATE TABLE IF NOT EXISTS chapters (
    id TEXT PRIMARY KEY,
    title TEXT NOT NULL,
    slug TEXT NOT NULL,
    subject_id TEXT NOT NULL,
    order_index INTEGER NOT NULL DEFAULT 0,
    notes_generated INTEGER NOT NULL DEFAULT 0,
    status TEXT NOT NULL DEFAULT 'published',
    created_at TEXT NOT NULL DEFAULT '',
    extra_json TEXT NOT NULL DEFAULT '{}'
);
CREATE INDEX IF NOT EXISTS idx_chapters_subject ON chapters(subject_id);
CREATE INDEX IF NOT EXISTS idx_chapters_slug ON chapters(slug);
CREATE INDEX IF NOT EXISTS idx_chapters_order ON chapters(subject_id, order_index);

CREATE TABLE IF NOT EXISTS topics (
    id TEXT PRIMARY KEY,
    title TEXT NOT NULL,
    slug TEXT NOT NULL,
    chapter_id TEXT NOT NULL,
    "order" INTEGER NOT NULL DEFAULT 0,
    status TEXT NOT NULL DEFAULT 'published',
    created_at TEXT NOT NULL DEFAULT '',
    extra_json TEXT NOT NULL DEFAULT '{}'
);
CREATE INDEX IF NOT EXISTS idx_topics_chapter ON topics(chapter_id);
CREATE INDEX IF NOT EXISTS idx_topics_slug ON topics(slug);
CREATE INDEX IF NOT EXISTS idx_topics_order ON topics(chapter_id, "order");

CREATE TABLE IF NOT EXISTS seo_pages (
    id TEXT PRIMARY KEY,
    slug TEXT NOT NULL DEFAULT '',
    topic_id TEXT NOT NULL DEFAULT '',
    page_type TEXT NOT NULL DEFAULT '',
    status TEXT NOT NULL DEFAULT 'published',
    title TEXT NOT NULL DEFAULT '',
    meta_description TEXT NOT NULL DEFAULT '',
    html_content TEXT NOT NULL DEFAULT '',
    board_slug TEXT NOT NULL DEFAULT '',
    class_slug TEXT NOT NULL DEFAULT '',
    subject_slug TEXT NOT NULL DEFAULT '',
    chapter_slug TEXT NOT NULL DEFAULT '',
    topic_slug TEXT NOT NULL DEFAULT '',
    word_count INTEGER NOT NULL DEFAULT 0,
    created_at TEXT NOT NULL DEFAULT '',
    updated_at TEXT NOT NULL DEFAULT '',
    extra_json TEXT NOT NULL DEFAULT '{}'
);
CREATE INDEX IF NOT EXISTS idx_seo_slug ON seo_pages(slug);
CREATE INDEX IF NOT EXISTS idx_seo_topic ON seo_pages(topic_id);
CREATE INDEX IF NOT EXISTS idx_seo_type ON seo_pages(page_type);
CREATE INDEX IF NOT EXISTS idx_seo_status ON seo_pages(status);
CREATE INDEX IF NOT EXISTS idx_seo_slug_status ON seo_pages(slug, status);
CREATE INDEX IF NOT EXISTS idx_seo_status_type ON seo_pages(status, page_type);
CREATE INDEX IF NOT EXISTS idx_seo_page_lookup ON seo_pages(board_slug, class_slug, subject_slug, topic_slug, page_type, status);
CREATE INDEX IF NOT EXISTS idx_subjects_stream_status ON subjects(stream_id, status);
CREATE INDEX IF NOT EXISTS idx_topics_chapter_status ON topics(chapter_id, status, "order");

CREATE TABLE IF NOT EXISTS sync_meta (
    key TEXT PRIMARY KEY,
    value TEXT NOT NULL DEFAULT '',
    updated_at TEXT NOT NULL DEFAULT ''
);
