-- 002_threat_posts.sql — AI-generated post cache, keyed by (fingerprint, locale).
--
-- Schema ready, NOT YET WRITTEN TO in this PR. The threat-post Python
-- store is on the JSON path; this table sits empty until a follow-up
-- introduces PgThreatPostStore + dual-write for the AI cache.

CREATE TABLE IF NOT EXISTS threat_posts (
    fingerprint     VARCHAR(64) NOT NULL,
    locale          VARCHAR(8)  NOT NULL,
    title           TEXT        NOT NULL,
    threat_level    VARCHAR(16) NOT NULL DEFAULT 'Low',
    generated_by    VARCHAR(64) NOT NULL DEFAULT 'rule_based',
    language        VARCHAR(8)  NOT NULL,
    -- Full ThreatPost as JSONB. We don't index inside it; it's read by id.
    -- JSONB chosen over TEXT so future fields (references, signals
    -- extensions) don't require migrations.
    payload         JSONB       NOT NULL,
    created_at      TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at      TIMESTAMPTZ NOT NULL DEFAULT now(),
    PRIMARY KEY (fingerprint, locale)
);

CREATE INDEX IF NOT EXISTS ix_threat_posts_locale
    ON threat_posts (locale);

CREATE INDEX IF NOT EXISTS ix_threat_posts_updated_desc
    ON threat_posts (updated_at DESC);

-- Re-use the touch_updated_at() function from 001_init.sql.
DROP TRIGGER IF EXISTS trg_threat_posts_touch ON threat_posts;
CREATE TRIGGER trg_threat_posts_touch
    BEFORE UPDATE ON threat_posts
    FOR EACH ROW
    EXECUTE FUNCTION touch_updated_at();
