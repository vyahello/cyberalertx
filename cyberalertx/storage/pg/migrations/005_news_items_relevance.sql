-- 005_news_items_relevance.sql — mirror the relevance classification.
--
-- Why: since Phase 1 every NewsItem carries `relevance_status`
-- (in_scope | needs_review | out_of_scope), `relevance_reason` and an
-- editor's `relevance_override`. JSON (authoritative) stores them; the
-- Postgres mirror did not, so a database read-path or a restore from
-- Postgres would silently lose every relevance decision and override.
--
-- Safe on a live database with no coordinated deploy:
--   * ADD COLUMN IF NOT EXISTS with constant defaults — no rewrite of
--     existing rows on PG 11+, repeatable.
--   * Code before this migration never names these columns; code after it
--     checks that they exist before writing them (PgNewsStore), so either
--     order of "migrate" and "deploy" works.
--   * Empty string = "not classified yet", exactly how the JSON store reads
--     items written before the field existed.
-- Forward-only (see README): to undo, a new migration drops the columns;
-- nothing reads them from Postgres today.

ALTER TABLE news_items
    ADD COLUMN IF NOT EXISTS relevance_status   VARCHAR(16) NOT NULL DEFAULT '',
    ADD COLUMN IF NOT EXISTS relevance_reason   TEXT        NOT NULL DEFAULT '',
    ADD COLUMN IF NOT EXISTS relevance_override VARCHAR(16) NOT NULL DEFAULT '';
