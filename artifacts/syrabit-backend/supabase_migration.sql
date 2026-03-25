-- ============================================================
-- SYRABIT.AI — Supabase Migration
-- Run this in your Supabase Dashboard → SQL Editor
-- URL: https://supabase.com/dashboard/project/czeznmqogtwecidhpysa/sql
-- ============================================================

-- ── Users (Supabase layer — auth, credits, plans) ──────────
CREATE TABLE IF NOT EXISTS public.users (
    id TEXT PRIMARY KEY,
    name TEXT NOT NULL DEFAULT '',
    email TEXT UNIQUE NOT NULL,
    password_hash TEXT NOT NULL DEFAULT '',
    plan TEXT NOT NULL DEFAULT 'free',         -- free | starter | pro
    credits_used INTEGER NOT NULL DEFAULT 0,
    credits_limit INTEGER NOT NULL DEFAULT 30,
    document_access TEXT NOT NULL DEFAULT 'zero',
    onboarding_done BOOLEAN NOT NULL DEFAULT FALSE,
    is_admin BOOLEAN NOT NULL DEFAULT FALSE,
    status TEXT NOT NULL DEFAULT 'active',     -- active | banned
    bio TEXT NOT NULL DEFAULT '',
    phone TEXT NOT NULL DEFAULT '',
    avatar_url TEXT NOT NULL DEFAULT '',
    saved_subjects JSONB NOT NULL DEFAULT '[]',
    has_free_credits_issued BOOLEAN NOT NULL DEFAULT TRUE,
    board_id TEXT,
    board_name TEXT,
    class_id TEXT,
    class_name TEXT,
    stream_id TEXT,
    stream_name TEXT,
    created_at TEXT NOT NULL DEFAULT ''
);

-- ── Conversations metadata (Supabase layer) ─────────────────
-- Full message content is stored in MongoDB (AI layer)
CREATE TABLE IF NOT EXISTS public.conversations (
    id TEXT PRIMARY KEY,
    user_id TEXT NOT NULL REFERENCES public.users(id) ON DELETE CASCADE,
    title TEXT NOT NULL DEFAULT 'New Chat',
    preview TEXT NOT NULL DEFAULT '',
    subject_id TEXT,
    subject_name TEXT,
    starred BOOLEAN NOT NULL DEFAULT FALSE,
    archived BOOLEAN NOT NULL DEFAULT FALSE,
    messages TEXT NOT NULL DEFAULT '[]',       -- JSON array of messages
    tokens INTEGER NOT NULL DEFAULT 0,
    created_at TEXT NOT NULL DEFAULT '',
    updated_at TEXT NOT NULL DEFAULT ''
);
CREATE INDEX IF NOT EXISTS conversations_user_id_idx ON public.conversations(user_id);
CREATE INDEX IF NOT EXISTS conversations_updated_at_idx ON public.conversations(updated_at DESC);

-- ── App settings (admin config) ─────────────────────────────
CREATE TABLE IF NOT EXISTS public.app_settings (
    id INTEGER PRIMARY KEY DEFAULT 1,
    registrations_open BOOLEAN NOT NULL DEFAULT TRUE,
    maintenance_mode BOOLEAN NOT NULL DEFAULT FALSE,
    app_name TEXT NOT NULL DEFAULT 'Syrabit.ai',
    tagline TEXT NOT NULL DEFAULT 'AI-Powered Exam Prep'
);
INSERT INTO public.app_settings(id) VALUES(1) ON CONFLICT(id) DO NOTHING;

-- ── Password resets ─────────────────────────────────────────
CREATE TABLE IF NOT EXISTS public.password_resets (
    token TEXT PRIMARY KEY,
    email TEXT NOT NULL,
    expires TEXT NOT NULL
);

-- ── Admin activity log ──────────────────────────────────────
CREATE TABLE IF NOT EXISTS public.activity_log (
    id TEXT PRIMARY KEY,
    action TEXT NOT NULL DEFAULT '',
    details TEXT NOT NULL DEFAULT '',
    level TEXT NOT NULL DEFAULT 'info',
    admin_name TEXT NOT NULL DEFAULT '',
    admin_email TEXT NOT NULL DEFAULT '',
    created_at TEXT NOT NULL DEFAULT ''
);

-- ── Admin notifications ─────────────────────────────────────
CREATE TABLE IF NOT EXISTS public.notifications (
    id TEXT PRIMARY KEY,
    title TEXT NOT NULL DEFAULT '',
    message TEXT NOT NULL DEFAULT '',
    type TEXT NOT NULL DEFAULT 'info',
    audience TEXT NOT NULL DEFAULT 'all',
    status TEXT NOT NULL DEFAULT 'sent',
    sent_at TEXT,
    created_at TEXT NOT NULL DEFAULT ''
);

-- ── Row Level Security (enable for production) ──────────────
ALTER TABLE public.users ENABLE ROW LEVEL SECURITY;
ALTER TABLE public.conversations ENABLE ROW LEVEL SECURITY;
ALTER TABLE public.app_settings ENABLE ROW LEVEL SECURITY;
ALTER TABLE public.password_resets ENABLE ROW LEVEL SECURITY;
ALTER TABLE public.activity_log ENABLE ROW LEVEL SECURITY;
ALTER TABLE public.notifications ENABLE ROW LEVEL SECURITY;

-- Service role bypasses RLS (used by backend)
-- Your backend uses SUPABASE_SERVICE_KEY which bypasses all RLS policies
-- No additional policies needed for the backend service role
