"""SQLAlchemy Core 2.0 Table definitions.

Mirror the DDL in `migrations/001_init.sql` / `002_threat_posts.sql`.
The migrations are authoritative — these declarations exist so the
Python layer can build typed `INSERT` / `SELECT` / `UPDATE` statements
without raw-SQL string interpolation.

Schema drift detection: when adding a column, edit both the migration
and this file. The live tests (`tests/test_pg_live.py`) catch the
divergence by trying actual round-trips.
"""
from __future__ import annotations

from sqlalchemy import (
    Column, DateTime, Float, MetaData, String, Table, Text, text,
)
from sqlalchemy.dialects.postgresql import ARRAY, JSONB

metadata = MetaData()

news_items = Table(
    "news_items",
    metadata,
    Column("fingerprint", String(64), primary_key=True),
    Column("title", Text, nullable=False),
    Column("source", String(128), nullable=False),
    Column("url", Text, nullable=False),
    Column("published_at", DateTime(timezone=True), nullable=False),
    Column("raw_content", Text, nullable=False, server_default=""),
    Column("threat_score", Float, nullable=False, server_default=text("0.0")),
    Column("tags", ARRAY(Text), nullable=False, server_default=text("'{}'::text[]")),
    Column("fetched_at", DateTime(timezone=True), nullable=False, server_default=text("now()")),
    Column("language", String(16), nullable=False, server_default="unknown"),
    Column("original_language", String(16), nullable=False, server_default="unknown"),
    Column("category", String(64), nullable=False, server_default="other"),
    Column("category_confidence", Float, nullable=False, server_default=text("0.0")),
    Column("affected_platforms", ARRAY(Text), nullable=False, server_default=text("'{}'::text[]")),
    Column("audience_targets", ARRAY(Text), nullable=False, server_default=text("'{}'::text[]")),
    Column("audience_relevance_score", Float, nullable=False, server_default=text("0.0")),
    Column("actionability_level", String(32), nullable=False, server_default="informational"),
    Column("actionability_score", Float, nullable=False, server_default=text("0.0")),
    Column("source_tier", String(32), nullable=False, server_default="unverified"),
    Column("source_credibility_score", Float, nullable=False, server_default=text("0.0")),
    Column("corroborating_sources", ARRAY(Text), nullable=False, server_default=text("'{}'::text[]")),
    Column("created_at", DateTime(timezone=True), nullable=False, server_default=text("now()")),
    Column("updated_at", DateTime(timezone=True), nullable=False, server_default=text("now()")),
)


# Threat posts table. Composite PK (fingerprint, locale) — one row per
# locale render of a NewsItem. `payload` is the full ThreatPost JSON; the
# top-level columns (threat_level, generated_by, language, ...) are mirrored
# from `payload` for index-friendly WHERE filters. The denormalized
# published_at / category / actionability_level columns are populated by
# the `sync_threat_posts_denormalized` trigger from news_items at INSERT /
# UPDATE time — see migration 003.
threat_posts = Table(
    "threat_posts",
    metadata,
    Column("fingerprint", String(64), primary_key=True),
    Column("locale", String(8), primary_key=True),
    Column("title", Text, nullable=False),
    Column("threat_level", String(16), nullable=False, server_default="Low"),
    Column("generated_by", String(64), nullable=False, server_default="rule_based"),
    Column("language", String(8), nullable=False),
    Column("payload", JSONB, nullable=False),
    # Denormalized from news_items by the migration-003 trigger.
    Column("published_at", DateTime(timezone=True)),
    Column("category", String(64)),
    Column("actionability_level", String(32)),
    Column("created_at", DateTime(timezone=True), nullable=False, server_default=text("now()")),
    Column("updated_at", DateTime(timezone=True), nullable=False, server_default=text("now()")),
)


__all__ = ["metadata", "news_items", "threat_posts"]
