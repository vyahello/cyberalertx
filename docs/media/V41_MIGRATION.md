# V4.1 migration: default renderer and edition backfill

From this release, V4.1 (`cax-editorial-4`) draws every new illustration.
V3 (`cax-svg-3`) remains available only as an explicit rollback. This page
covers what changes on deploy, the one-time edition backfill, verification
and rollback.

## What changes on deploy

- **Renderer.** `media/renderer.active()` defaults to V4.1. There is no hybrid
  V3 fallback: a story without a supported scene gets the V4.1 editorial cover
  (`dossier`), which shows only the story's own identifiers and status.
  `CYBERALERTX_ILLUSTRATION_RENDERER=svg-3` selects V3 explicitly; nothing
  selects it otherwise. `.env` sets no renderer, so no `.env` change is needed.
- **New images only.** Deploying replaces no existing image. New stories get
  V4.1 on the next hourly run. Existing images stay until a backfill redraws
  them. The one exception is an existing V4.1 image whose inputs changed: like
  any same-renderer image, the hourly run redraws it (this release redraws the
  approved F5 BIG-IP and Optimizely images; see the review gallery).
- **One canonical image per article.** The website (hero, cards, article page)
  and Telegram/Threads all read `engine.illustration_payload`, which uses
  `MediaStore.illustration_for_member`. The rule:
  1. Only a successfully generated illustration that lists the article's
     fingerprint in `members` qualifies. Failed, pending or in-progress
     records never do.
  2. The newest renderer generation wins (V4.1, then V3, V2, V1).
  3. Then the most recent update, then the asset id.

  Each run, the engine removes an article from the image of a story that no
  longer exists, once the article's current story has a validated image. The
  old file and its URL are kept.
- **Failing safely.** If a V4.1 regeneration of an existing image fails, the
  previous validated image stays, with the failure recorded on it
  (`failed_hash`, `last_error`). The run reports the story and its articles.
  There is never a fallback to V3. Failed attempts count towards the retry
  limit (3).
- **Routing and wording fixes:**
  - a `malware_campaign` scene;
  - analysis, guidance and research pieces never get a scene that shows an
    attack;
  - CISA ICS advisories name exactly their product;
  - `patch_to_exploit` needs patch wording;
  - capability wording ("lets attackers abuse") is not exploitation;
  - actor attributions ("China-Linked") are not products;
  - a cover sets an incident status only when the headline reports one.

## Edition backfill (after the deploy, once)

`ops/media/edition_stories.py` is the single source of truth for which
stories the website shows. It asks the API exactly what the homepage asks
(40 posts per language from a pool of 120), then maps each article to the
story the intel engine places it in now.

```bash
cd $APP_ROOT/current
venv/bin/python ops/media/edition_stories.py > $REVIEW_DIR/v41-edition.txt        # read-only
cp -a $APP_HOME/data/media $BACKUPS/media-before-v41-edition                      # restore point
venv/bin/python -m cyberalertx.tools.media backfill --batch 60 --only-file $REVIEW_DIR/v41-edition.txt
```

Guarantees, rehearsed on a copy of the production store:
- only the listed stories are processed, and card records are not touched;
- outside the edition, the only change is a dissolved story's image releasing
  an edition article;
- every replaced image keeps its old URL (`previous_storage_keys`), and every
  file stays on disk;
- the exit code is non-zero on any failure, and each failure is printed with
  its articles and "previous image kept".

`--store DIR` runs the same command against a copy, for a rehearsal.

## Verification

- `ops/media/alt_audit.py`: every eligible story is drawn by V4.1 with 0 alt
  problems.
- `ops/media/edition_stories.py`: every line reads `cax-editorial-4`.
- The homepage, an article page and the next Threads posts show the new
  images.

## Rollback

- **Code:** switch back to the previous release. New stories are then drawn by
  V3 again.
- **Edition images:** restore the media store from
  `$BACKUPS/media-before-v41-edition`. Alternatively, keep this release and set
  `CYBERALERTX_ILLUSTRATION_RENDERER=svg-3`, then run the same backfill command:
  V3 renders are deterministic, so the old files come back byte for byte.

## Not part of this release

**Archive backfill.** About 311 older images (302 V2, 6 V3, 3 V1), mostly for
stories that are no longer visible. At about 0.05 s CPU and about 20 KB each,
a full backfill takes roughly 15 s and 6 MB, at $0. It needs a separate
decision.
