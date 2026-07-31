-- 004_story_clusters.sql — cross-source story clustering columns.
--
-- Why: `fingerprint` identifies an ARTICLE (it is a hash of the URL), not a
-- STORY. When BleepingComputer, The Hacker News and CISA all report the same
-- zero-day we store three rows, and the reader sees the same news three
-- times in the feed and three times in the Telegram channel.
--
-- `story_key` is shared by every article covering one story; `duplicate_of`
-- names the canonical article's fingerprint, or is empty when the row IS the
-- canonical one. The matching rules live in cyberalertx/pipeline/dedup.py.
--
-- Both columns default to empty, which every reader interprets as "this row
-- is its own story". That means rows written before this migration keep
-- behaving exactly as they do today until `cyberalertx dedup --apply`
-- backfills them — the migration is safe to apply to a live database with no
-- coordinated deploy.

ALTER TABLE news_items
    ADD COLUMN IF NOT EXISTS story_key    VARCHAR(32) NOT NULL DEFAULT '',
    ADD COLUMN IF NOT EXISTS duplicate_of VARCHAR(64) NOT NULL DEFAULT '';

-- The feed's hot query is "give me the canonical article of each story,
-- newest first". A partial index over non-duplicates keeps that scan tight
-- as the duplicate share of the table grows.
CREATE INDEX IF NOT EXISTS news_items_canonical_published_idx
    ON news_items (published_at DESC)
    WHERE duplicate_of = '';

-- Detail pages ask "what else covered this story?", which is a lookup by key.
CREATE INDEX IF NOT EXISTS news_items_story_key_idx
    ON news_items (story_key)
    WHERE story_key <> '';
