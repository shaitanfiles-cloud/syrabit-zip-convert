-- Syrabit.ai Supabase Schema
-- Run this in the Supabase SQL Editor

-- ─────────────────────────────────────────────
-- USERS
-- ─────────────────────────────────────────────
CREATE TABLE IF NOT EXISTS public.users (
    id TEXT PRIMARY KEY DEFAULT gen_random_uuid()::text,
    email TEXT UNIQUE NOT NULL,
    name TEXT NOT NULL DEFAULT '',
    password_hash TEXT NOT NULL DEFAULT '',
    avatar_url TEXT DEFAULT '',
    plan TEXT NOT NULL DEFAULT 'free',
    credits_used INTEGER NOT NULL DEFAULT 0,
    board_id TEXT DEFAULT '',
    board_name TEXT DEFAULT '',
    class_id TEXT DEFAULT '',
    class_name TEXT DEFAULT '',
    stream_id TEXT DEFAULT '',
    stream_name TEXT DEFAULT '',
    status TEXT NOT NULL DEFAULT 'active',
    is_admin BOOLEAN NOT NULL DEFAULT false,
    onboarding_completed BOOLEAN NOT NULL DEFAULT false,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE INDEX IF NOT EXISTS idx_users_email ON public.users(email);
CREATE INDEX IF NOT EXISTS idx_users_plan ON public.users(plan);
CREATE INDEX IF NOT EXISTS idx_users_status ON public.users(status);

-- ─────────────────────────────────────────────
-- CONVERSATIONS
-- ─────────────────────────────────────────────
CREATE TABLE IF NOT EXISTS public.conversations (
    id TEXT PRIMARY KEY,
    user_id TEXT NOT NULL REFERENCES public.users(id) ON DELETE CASCADE,
    title TEXT NOT NULL DEFAULT 'New Chat',
    subject_id TEXT DEFAULT '',
    subject_name TEXT DEFAULT '',
    messages JSONB NOT NULL DEFAULT '[]'::jsonb,
    message_count INTEGER NOT NULL DEFAULT 0,
    user_email TEXT DEFAULT '',
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE INDEX IF NOT EXISTS idx_conversations_user_id ON public.conversations(user_id);
CREATE INDEX IF NOT EXISTS idx_conversations_updated_at ON public.conversations(updated_at DESC);

-- ─────────────────────────────────────────────
-- SETTINGS (single-row table)
-- ─────────────────────────────────────────────
CREATE TABLE IF NOT EXISTS public.settings (
    id INTEGER PRIMARY KEY DEFAULT 1,
    registrations_open BOOLEAN NOT NULL DEFAULT true,
    maintenance_mode BOOLEAN NOT NULL DEFAULT false,
    app_name TEXT NOT NULL DEFAULT 'Syrabit.ai',
    tagline TEXT NOT NULL DEFAULT 'AI-Powered AHSEC Exam Prep',
    updated_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

-- Insert default settings
INSERT INTO public.settings (id, registrations_open, maintenance_mode, app_name, tagline)
VALUES (1, true, false, 'Syrabit.ai', 'AI-Powered AHSEC Exam Prep')
ON CONFLICT (id) DO NOTHING;

-- ─────────────────────────────────────────────
-- PASSWORD RESETS
-- ─────────────────────────────────────────────
CREATE TABLE IF NOT EXISTS public.password_resets (
    token TEXT PRIMARY KEY,
    email TEXT NOT NULL,
    expires_at TIMESTAMPTZ NOT NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE INDEX IF NOT EXISTS idx_password_resets_email ON public.password_resets(email);

-- ─────────────────────────────────────────────
-- ACTIVITY LOG
-- ─────────────────────────────────────────────
CREATE TABLE IF NOT EXISTS public.activity_log (
    id TEXT PRIMARY KEY DEFAULT gen_random_uuid()::text,
    action TEXT NOT NULL,
    details TEXT DEFAULT '',
    level TEXT NOT NULL DEFAULT 'info',
    admin_name TEXT DEFAULT 'Admin',
    admin_email TEXT DEFAULT '',
    created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE INDEX IF NOT EXISTS idx_activity_log_created_at ON public.activity_log(created_at DESC);

-- ─────────────────────────────────────────────
-- NOTIFICATIONS
-- ─────────────────────────────────────────────
CREATE TABLE IF NOT EXISTS public.notifications (
    id TEXT PRIMARY KEY DEFAULT gen_random_uuid()::text,
    title TEXT NOT NULL DEFAULT '',
    message TEXT NOT NULL DEFAULT '',
    type TEXT NOT NULL DEFAULT 'info',
    audience TEXT NOT NULL DEFAULT 'all',
    status TEXT NOT NULL DEFAULT 'draft',
    sent_at TIMESTAMPTZ,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE INDEX IF NOT EXISTS idx_notifications_created_at ON public.notifications(created_at DESC);

-- ─────────────────────────────────────────────
-- CONTENT TABLES (for chapters/documents added by admin)
-- ─────────────────────────────────────────────
CREATE TABLE IF NOT EXISTS public.chapters (
    id TEXT PRIMARY KEY DEFAULT gen_random_uuid()::text,
    subject_id TEXT NOT NULL,
    title TEXT NOT NULL,
    description TEXT DEFAULT '',
    content TEXT DEFAULT '',
    chapter_number INTEGER DEFAULT 1,
    "order" INTEGER NOT NULL DEFAULT 1,
    status TEXT NOT NULL DEFAULT 'published',
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at TIMESTAMPTZ DEFAULT now()
);

CREATE INDEX IF NOT EXISTS idx_chapters_subject_id ON public.chapters(subject_id);
CREATE INDEX IF NOT EXISTS idx_chapters_order ON public.chapters("order");

-- ─────────────────────────────────────────────
-- CONTENT CHUNKS (RAG)
-- ─────────────────────────────────────────────
CREATE TABLE IF NOT EXISTS public.chunks (
    id TEXT PRIMARY KEY DEFAULT gen_random_uuid()::text,
    chapter_id TEXT NOT NULL REFERENCES public.chapters(id) ON DELETE CASCADE,
    subject_id TEXT NOT NULL,
    content TEXT NOT NULL,
    content_type TEXT NOT NULL DEFAULT 'notes',
    chunk_index INTEGER NOT NULL DEFAULT 0,
    tags JSONB DEFAULT '[]'::jsonb,
    char_count INTEGER DEFAULT 0,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE INDEX IF NOT EXISTS idx_chunks_chapter_id ON public.chunks(chapter_id);
CREATE INDEX IF NOT EXISTS idx_chunks_subject_id ON public.chunks(subject_id);

-- ─────────────────────────────────────────────
-- CONTENT UPLOADS (PDFs, documents)
-- ─────────────────────────────────────────────
CREATE TABLE IF NOT EXISTS public.content_uploads (
    id TEXT PRIMARY KEY DEFAULT gen_random_uuid()::text,
    subject_id TEXT NOT NULL,
    content_type TEXT NOT NULL DEFAULT 'document',
    title TEXT NOT NULL DEFAULT '',
    description TEXT DEFAULT '',
    tags TEXT DEFAULT '',
    year TEXT DEFAULT '',
    file_name TEXT DEFAULT '',
    file_ext TEXT DEFAULT '',
    file_size INTEGER DEFAULT 0,
    file_url TEXT DEFAULT '',
    content TEXT DEFAULT '',
    pdf_url TEXT DEFAULT '',
    storage_path TEXT DEFAULT '',
    extracted_text TEXT DEFAULT '',
    is_scanned BOOLEAN DEFAULT false,
    page_count INTEGER DEFAULT 0,
    uploaded_by TEXT DEFAULT '',
    uploaded_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    status TEXT NOT NULL DEFAULT 'published',
    updated_at TIMESTAMPTZ DEFAULT now()
);

CREATE INDEX IF NOT EXISTS idx_content_uploads_subject_id ON public.content_uploads(subject_id);

-- ─────────────────────────────────────────────
-- SUBJECTS OVERRIDES (for admin customizations on top of seed data)
-- ─────────────────────────────────────────────
CREATE TABLE IF NOT EXISTS public.subject_overrides (
    id TEXT PRIMARY KEY,
    has_document BOOLEAN DEFAULT false,
    document_type TEXT DEFAULT '',
    chapter_count INTEGER DEFAULT 0,
    thumbnail_url TEXT DEFAULT '',
    updated_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

-- ─────────────────────────────────────────────
-- ANALYTICS
-- ─────────────────────────────────────────────
CREATE TABLE IF NOT EXISTS public.analytics (
    id TEXT PRIMARY KEY DEFAULT gen_random_uuid()::text,
    event_type TEXT NOT NULL,
    subject_id TEXT DEFAULT '',
    chapter_id TEXT DEFAULT '',
    user_id TEXT DEFAULT '',
    search_query TEXT DEFAULT '',
    metadata JSONB DEFAULT '{}'::jsonb,
    timestamp TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE INDEX IF NOT EXISTS idx_analytics_event_type ON public.analytics(event_type);
CREATE INDEX IF NOT EXISTS idx_analytics_subject_id ON public.analytics(subject_id);
CREATE INDEX IF NOT EXISTS idx_analytics_timestamp ON public.analytics(timestamp DESC);

-- ─────────────────────────────────────────────
-- CMS DOCUMENTS (SEO content)
-- ─────────────────────────────────────────────
CREATE TABLE IF NOT EXISTS public.cms_documents (
    id TEXT PRIMARY KEY DEFAULT gen_random_uuid()::text,
    title TEXT NOT NULL,
    content TEXT NOT NULL DEFAULT '',
    meta_description TEXT DEFAULT '',
    description TEXT DEFAULT '',
    seo_tags TEXT DEFAULT '',
    primary_keyword TEXT DEFAULT '',
    seo_slug TEXT DEFAULT '',
    thumbnail_url TEXT DEFAULT '',
    alt_text TEXT DEFAULT '',
    category TEXT DEFAULT '',
    headings TEXT DEFAULT '',
    status TEXT NOT NULL DEFAULT 'draft',
    word_count INTEGER DEFAULT 0,
    rag_processed BOOLEAN DEFAULT false,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    created_by TEXT DEFAULT ''
);

CREATE INDEX IF NOT EXISTS idx_cms_documents_status ON public.cms_documents(status);
CREATE INDEX IF NOT EXISTS idx_cms_documents_seo_slug ON public.cms_documents(seo_slug);

-- ─────────────────────────────────────────────
-- DISABLE RLS (service key bypasses anyway, but let's be explicit)
-- ─────────────────────────────────────────────
ALTER TABLE public.users DISABLE ROW LEVEL SECURITY;
ALTER TABLE public.conversations DISABLE ROW LEVEL SECURITY;
ALTER TABLE public.settings DISABLE ROW LEVEL SECURITY;
ALTER TABLE public.password_resets DISABLE ROW LEVEL SECURITY;
ALTER TABLE public.activity_log DISABLE ROW LEVEL SECURITY;
ALTER TABLE public.notifications DISABLE ROW LEVEL SECURITY;
ALTER TABLE public.chapters DISABLE ROW LEVEL SECURITY;
ALTER TABLE public.chunks DISABLE ROW LEVEL SECURITY;
ALTER TABLE public.content_uploads DISABLE ROW LEVEL SECURITY;
ALTER TABLE public.subject_overrides DISABLE ROW LEVEL SECURITY;
ALTER TABLE public.analytics DISABLE ROW LEVEL SECURITY;
ALTER TABLE public.cms_documents DISABLE ROW LEVEL SECURITY;
