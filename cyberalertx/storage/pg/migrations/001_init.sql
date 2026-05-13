-- 001_init.sql — bootstrap schema (news_items + bookkeeping).
--
-- Idempotent: every CREATE uses IF NOT EXISTS so re-running the migration
-- runner is safe. The runner records applied versions in schema_migrations
-- separately; this is belt-and-suspenders for manual re-application.

CREATE TABLE IF NOT EXISTS schema_migrations (
    version     VARCHAR(64) PRIMARY KEY,
    applied_at  TIMESTAMPTZ NOT NULL DEFAULT now()
);

-- ----------------------------------------------------------------------
-- news_items
--
-- The unit-of-work for the ingest pipeline. One row per article (keyed
-- by fingerprint — SHA256(url)[0:16] from cyberalertx.models.NewsItem).
--
-- Why columnized (not JSONB): every field on this row is queried by the
-- pipeline (filter / rank / serve) and must be efficiently indexable.
-- ----------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS news_items (
    fingerprint                 VARCHAR(64) PRIMARY KEY,
    title                       TEXT        NOT NULL,
    source                      VARCHAR(128) NOT NULL,
    url                         TEXT        NOT NULL,
    published_at                TIMESTAMPTZ NOT NULL,
    raw_content                 TEXT        NOT NULL DEFAULT '',
    threat_score                DOUBLE PRECISION NOT NULL DEFAULT 0.0,
    tags                        TEXT[]      NOT NULL DEFAULT '{}',
    fetched_at                  TIMESTAMPTZ NOT NULL DEFAULT now(),
    language                    VARCHAR(16) NOT NULL DEFAULT 'unknown',
    original_language           VARCHAR(16) NOT NULL DEFAULT 'unknown',
    category                    VARCHAR(64) NOT NULL DEFAULT 'other',
    category_confidence         DOUBLE PRECISION NOT NULL DEFAULT 0.0,
    affected_platforms          TEXT[]      NOT NULL DEFAULT '{}',
    audience_targets            TEXT[]      NOT NULL DEFAULT '{}',
    audience_relevance_score    DOUBLE PRECISION NOT NULL DEFAULT 0.0,
    actionability_level         VARCHAR(32) NOT NULL DEFAULT 'informational',
    actionability_score         DOUBLE PRECISION NOT NULL DEFAULT 0.0,
    source_tier                 VARCHAR(32) NOT NULL DEFAULT 'unverified',
    source_credibility_score    DOUBLE PRECISION NOT NULL DEFAULT 0.0,
    corroborating_sources       TEXT[]      NOT NULL DEFAULT '{}',
    created_at                  TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at                  TIMESTAMPTZ NOT NULL DEFAULT now()
);

-- Chronological feed (the homepage sort).
CREATE INDEX IF NOT EXISTS ix_news_items_published_desc
    ON news_items (published_at DESC);

-- Per-locale filter on the homepage / trending endpoints.
CREATE INDEX IF NOT EXISTS ix_news_items_language
    ON news_items (language);

-- Category facet (filters / analytics).
CREATE INDEX IF NOT EXISTS ix_news_items_category
    ON news_items (category);

-- ----------------------------------------------------------------------
-- FTS-ready full-text index — `simple` config so it works for both EN
-- and UA content without language detection. Title weighted 'A',
-- raw_content 'B'. Generated column keeps the tsvector in sync without
-- app-side maintenance.
-- ----------------------------------------------------------------------
ALTER TABLE news_items
    ADD COLUMN IF NOT EXISTS search_vector tsvector
    GENERATED ALWAYS AS (
        setweight(to_tsvector('simple', coalesce(title, '')), 'A') ||
        setweight(to_tsvector('simple', coalesce(raw_content, '')), 'B')
    ) STORED;

CREATE INDEX IF NOT EXISTS ix_news_items_search
    ON news_items USING GIN (search_vector);

-- updated_at touch trigger.
CREATE OR REPLACE FUNCTION touch_updated_at() RETURNS trigger AS $$
BEGIN
    NEW.updated_at = now();
    RETURN NEW;
END;
$$ LANGUAGE plpgsql;

DROP TRIGGER IF EXISTS trg_news_items_touch ON news_items;
CREATE TRIGGER trg_news_items_touch
    BEFORE UPDATE ON news_items
    FOR EACH ROW
    EXECUTE FUNCTION touch_updated_at();
