-- 003_threat_posts_denormalized.sql — denormalized columns + indexes for the feed query.
--
-- Why denormalize: the homepage feed wants "freshest 15 AI-rendered posts in
-- locale X, by published_at DESC". The post's freshness lives on news_items;
-- a per-request JOIN works at 100s of rows but scales poorly. We mirror the
-- three fields the API filters/sorts by directly onto threat_posts so the
-- feed becomes a single-table query.
--
-- Sync method: BEFORE INSERT/UPDATE trigger that copies from news_items by
-- fingerprint. Apps don't need to know — they keep calling `set()` with
-- (fingerprint, locale, post). The DB fills the denormalized columns.
--
-- Tradeoff: if news_items is updated AFTER threat_posts (e.g. a re-ingest
-- bumps published_at), threat_posts.published_at lags until the next AI
-- render. Acceptable — feed sort order shifting by a few minutes on a
-- re-ingest is invisible to users.

ALTER TABLE threat_posts
    ADD COLUMN IF NOT EXISTS published_at         TIMESTAMPTZ,
    ADD COLUMN IF NOT EXISTS category             VARCHAR(64),
    ADD COLUMN IF NOT EXISTS actionability_level  VARCHAR(32);

-- Trigger: fill the denormalized columns from news_items on each upsert.
-- Read uses LEFT JOIN semantics — if the news_items row is absent (rare;
-- AI cache shouldn't be ahead of the ingest store), columns stay NULL.
CREATE OR REPLACE FUNCTION sync_threat_posts_denormalized() RETURNS trigger AS $$
BEGIN
    SELECT n.published_at, n.category, n.actionability_level
      INTO NEW.published_at, NEW.category, NEW.actionability_level
      FROM news_items n
     WHERE n.fingerprint = NEW.fingerprint;
    RETURN NEW;
END;
$$ LANGUAGE plpgsql;

DROP TRIGGER IF EXISTS trg_threat_posts_sync_denormalized ON threat_posts;
CREATE TRIGGER trg_threat_posts_sync_denormalized
    BEFORE INSERT OR UPDATE ON threat_posts
    FOR EACH ROW
    EXECUTE FUNCTION sync_threat_posts_denormalized();

-- One-time backfill for any rows already present (PR-1 imported news_items
-- but not threat_posts, so this is a no-op on first run; included for
-- completeness in case a later re-migration is needed).
UPDATE threat_posts tp
   SET published_at = n.published_at,
       category = n.category,
       actionability_level = n.actionability_level
  FROM news_items n
 WHERE tp.fingerprint = n.fingerprint
   AND (tp.published_at IS DISTINCT FROM n.published_at
        OR tp.category IS DISTINCT FROM n.category
        OR tp.actionability_level IS DISTINCT FROM n.actionability_level);

-- Indexes per the spec: locale (exists from 002), published_at DESC,
-- threat_level, category, actionability_level.
CREATE INDEX IF NOT EXISTS ix_threat_posts_published_desc
    ON threat_posts (published_at DESC);

CREATE INDEX IF NOT EXISTS ix_threat_posts_threat_level
    ON threat_posts (threat_level);

CREATE INDEX IF NOT EXISTS ix_threat_posts_category
    ON threat_posts (category);

CREATE INDEX IF NOT EXISTS ix_threat_posts_actionability
    ON threat_posts (actionability_level);

-- Composite index for the homepage feed query — `(locale, published_at DESC)`
-- supports the WHERE locale = ? ORDER BY published_at DESC pattern in one shot.
CREATE INDEX IF NOT EXISTS ix_threat_posts_locale_published
    ON threat_posts (locale, published_at DESC);
