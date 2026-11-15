-- ============================================================
-- Supabase Schema for Calendar AI (Multi-User + Hashes + Chat)
-- Paste and run this in Supabase Dashboard -> SQL Editor
-- ============================================================

-- 1. Ensure user_id and date_time columns exist on calendar_events, and make start_time/end_time optional
ALTER TABLE IF EXISTS public.calendar_events 
ADD COLUMN IF NOT EXISTS user_id TEXT DEFAULT 'guest';

ALTER TABLE IF EXISTS public.calendar_events 
ADD COLUMN IF NOT EXISTS date_time TIMESTAMPTZ;

ALTER TABLE IF EXISTS public.calendar_events 
ALTER COLUMN start_time DROP NOT NULL;

ALTER TABLE IF EXISTS public.calendar_events 
ALTER COLUMN end_time DROP NOT NULL;

-- Backfill date_time from start_time if already existing
UPDATE public.calendar_events 
SET date_time = start_time 
WHERE date_time IS NULL AND start_time IS NOT NULL;

-- 2. Ensure user_id column exists on hashed_vectors
ALTER TABLE IF EXISTS public.hashed_vectors 
ADD COLUMN IF NOT EXISTS user_id TEXT DEFAULT 'guest';

-- 3. Create hashed_vectors table if it doesn't exist yet
CREATE TABLE IF NOT EXISTS public.hashed_vectors (
    id TEXT PRIMARY KEY,
    user_id TEXT DEFAULT 'guest',
    raw_text TEXT NOT NULL,
    dimension INT NOT NULL DEFAULT 128,
    semantic_hash TEXT NOT NULL,
    vector_preview JSONB,
    updated_at TIMESTAMPTZ DEFAULT NOW()
);

-- 4. Create chat_messages table (Separate isolated chat history for every user)
CREATE TABLE IF NOT EXISTS public.chat_messages (
    id TEXT PRIMARY KEY,
    user_id TEXT NOT NULL DEFAULT 'guest',
    sender TEXT NOT NULL, -- 'user' or 'ai'
    message TEXT NOT NULL,
    metadata JSONB DEFAULT '{}'::jsonb,
    created_at TIMESTAMPTZ DEFAULT NOW()
);

-- 5. Create fast lookup indexes
CREATE INDEX IF NOT EXISTS idx_calendar_events_user ON public.calendar_events(user_id);
CREATE INDEX IF NOT EXISTS idx_calendar_events_datetime ON public.calendar_events(date_time);
CREATE INDEX IF NOT EXISTS idx_hashed_vectors_user ON public.hashed_vectors(user_id);
CREATE INDEX IF NOT EXISTS idx_chat_messages_user_time ON public.chat_messages(user_id, created_at ASC);

-- 6. Enable Row Level Security (RLS) with open access for authenticated & anon requests
ALTER TABLE public.calendar_events ENABLE ROW LEVEL SECURITY;
ALTER TABLE public.hashed_vectors ENABLE ROW LEVEL SECURITY;
ALTER TABLE public.chat_messages ENABLE ROW LEVEL SECURITY;

DROP POLICY IF EXISTS "Allow all calendar_events" ON public.calendar_events;
CREATE POLICY "Allow all calendar_events" ON public.calendar_events FOR ALL USING (true);

DROP POLICY IF EXISTS "Allow all hashed_vectors" ON public.hashed_vectors;
CREATE POLICY "Allow all hashed_vectors" ON public.hashed_vectors FOR ALL USING (true);

DROP POLICY IF EXISTS "Allow all chat_messages" ON public.chat_messages;
CREATE POLICY "Allow all chat_messages" ON public.chat_messages FOR ALL USING (true);
