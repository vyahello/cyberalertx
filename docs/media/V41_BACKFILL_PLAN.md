# V4.1 archive backfill: controlled plan

**Status: prepared, not executed.** Running it needs the owner's explicit
approval, given after the V4.1 canary has been reviewed.

Paths use the runbook placeholders: `$APP_HOME` (checkout with `.env` and
`data/`), `$APP_ROOT/current` (active release) and `$BACKUPS`.

## Scope (read-only plan, 18 Nov 2026)

`CYBERALERTX_ILLUSTRATION_RENDERER=editorial-4 python -m cyberalertx.tools.media backfill`
(without `--batch`) reports:

| | |
|---|---|
| Eligible public stories in the current article window | 145 (the window rolls; it was 152 on 17 Nov) |
| To regenerate | 145: 134 `cax-svg-2` and 11 `cax-svg-3` |
| Images shared between stories | none |
| Render cost | about 7 s CPU in total, $0 |
| New files | about 3.3 MB (disk: 26 GB free) |

Illustrations of stories outside the window (about 160 in the index) are not
touched.

## What is preserved

* **Every old file.** The store is content-addressed and nothing is deleted.
  A replaced image's file stays on disk and its key moves into
  `previous_storage_keys`. Old `/media/<id>/...` URLs keep resolving, so
  cached pages, feeds and shared links do not break.
* **The image index.** A full copy is taken before the run (below).
* **Telegram and Threads posts already published.** They keep the image they
  were sent with: those platforms store the photo, and nothing is re-posted.
  The Telegram schedule and ledger are untouched.
* **Story IDs, canonical URLs and alt text history.** Alt text is replaced
  together with each image, so it always describes the image shown.

## Procedure (as `cax`, right after an hourly generate run has finished)

```bash
cd $APP_ROOT/current
B=$BACKUPS/pre-v41-backfill-$(date +%Y%m%d-%H%M); install -d -m 700 "$B"
cp -a $APP_HOME/data/media/assets.json "$B"/assets.json
sha256sum $APP_HOME/data/media/assets.json > "$B"/assets.sha256
venv/bin/python ops/media/illustration_inventory.py snapshot "$B"/inventory.json
wc -l < $APP_HOME/data/telegram_published.jsonl > "$B"/telegram_ledger_lines.txt

# batch 1 of 6: the 25 newest stories
CYBERALERTX_ILLUSTRATION_RENDERER=editorial-4 venv/bin/python -m cyberalertx.tools.media backfill --batch 25
venv/bin/python ops/media/illustration_inventory.py compare "$B"/inventory.json   # CHANGED = this batch only
```

**After each batch:**
* the `batch` summary shows `failed: []`;
* `compare` lists only stories of this batch as changed (now
  `cax-editorial-4`), with nothing missing;
* five of the new images are spot-checked on their article pages and at
  feed size;
* the Telegram ledger shows only scheduled growth.

Then run the next batch. The command always takes the newest stories that
still need it, so batches never overlap. Six batches cover all 145.

## Rollback

* **Stop between batches:** simply do not run the next batch. Images already
  converted stay V4.1.
* **Per story:** set `CYBERALERTX_ILLUSTRATION_RENDERER=svg-3` and run
  `tools.media regenerate <story>`, then the next hourly run. This yields a
  V3 image, not the old V2 one: V2 is no longer in the code.
* **Exact restore** of the whole archive to its pre-backfill state:

  ```bash
  sudo systemctl stop cyberalertx-generate.timer
  cp -a "$B"/assets.json $APP_HOME/data/media/assets.json
  sha256sum -c "$B"/assets.sha256
  sudo systemctl start cyberalertx-generate.timer
  ```

  The old files never left the disk, so every old image and URL comes back as
  it was.

**Never** run `backfill --batch` with the V3 setting as a "rollback": it
would convert the V2 archive to V3.
