# V4.1 archive backfill: controlled plan

**Status: prepared, not executed.** Running it needs the owner's explicit
approval, given after canary 4 (V4.1 with the O54 and O55 fixes and the
hybrid policy) has passed.

Paths use the runbook placeholders: `$APP_HOME` (checkout with `.env` and
`data/`), `$APP_ROOT/current` (active release) and `$BACKUPS`.

## Scope (read-only plan, reconciled 19 Nov 2026, 09:30 EET, V4.1.4)

The archive follows the **hybrid policy** (`renderer.v4_applies`, see
VISUAL_SYSTEM_V4.md). With `CYBERALERTX_ILLUSTRATION_RENDERER=editorial-4`, a
story whose V4 brief found an evidence-backed scene is drawn by V4.1. A
low-confidence story, the generic `dossier` fallback, is drawn by V3. The
backfill therefore converts the archive to **V4.1 where the evidence
supports a scene, and V3 elsewhere**. It never produces a generic V4 card.

`CYBERALERTX_ILLUSTRATION_RENDERER=editorial-4 python -m cyberalertx.tools.media backfill`
(without `--batch`, read-only) and a per-story reconciliation against the
image index report:

| Route | Current image | Stories | Backfill action |
|---|---|---|---|
| **V4.1** (evidence-backed scene that names the story), 103 | `cax-svg-2` | 86 | redraw with V4.1 |
| | `cax-svg-3` | 11 | redraw with V4.1 |
| | `cax-editorial-4` | 6 | keep: Optimizely, 3 corrected redraws, F5 advisory, Apache Roller |
| **V3** (low confidence, or a drawing that names nothing of the story), 49 | `cax-svg-2` | 39 | redraw with V3 |
| | `cax-svg-3` | 10 | keep (incl. the 6 canary-4 rollbacks) |
| **Total eligible** | | **152** | **136 redraws, 16 kept** |

| Images shared between stories | none |
| Render cost | about 7 s CPU in total, $0 |
| New files | about 3.1 MB (disk: 22 GB free) |

Illustrations of stories outside
the window are not touched.

### Why the count moves (152 → 153 → 145 → 146 → 145 → 146)

The eligible set is computed at run time from the rolling store of the newest
200 articles. A story leaves it when all its articles have aged out, and
enters it when it gets its first published AI brief.

| When | Eligible | Change |
|---|---|---|
| 18 Nov, 08:30 dry run | 152 | |
| 09:01 hourly run | 153 | +1: `s:c28488d1995440` |
| 15:40 backfill plan | 145 | −10 aged out, +2 new (below) |
| 16:00 hourly run | 146 | +1: `s:04b949e06cb43f` (the V4.1 canary image) |
| 18 Nov, 22:3x O54 audit | 145 | |
| 19 Nov, 09:30 V4.1.4 reconciliation | 152 | +6 new stories during canary 4; the V4.1.4 routing (O56, O57) moves 22 more stories to V3 |
| 19 Nov, 00:40 hybrid reconciliation | 146 | −1 aged out: `s:c14c9dbe7a909e` (low-confidence, V2, which is why the V3 group is 15, not 16); +2 new: `s:244fe89270c50c` (F5, canary 3), `s:7c7e65f63ae32c` (23:02 V3 run) |

* **Aged out (all their articles left the window):** `s:4afcb47f404ff0`,
  `s:b315ff6301a22e`, `s:49b25506e347f5`, `s:98a1d904a20248`,
  `s:9f9ebdee0aa795`, `s:38dcb287c0e010`, `s:3ab224d3322fc9`,
  `s:0a5ac73f29712c`, `s:9a9d16c53ee54f`, `s:b5153bea9b0092`. Their
  illustrations stay in the index and on disk, and their URLs keep working.
  They are just no longer backfill candidates.
* **New between 09:01 and 15:40:** `s:29ea3d56ef9122`, `s:dd8c35efb8a8bd`.

The backfill therefore covers whatever is eligible when it runs. Each batch
reports its own list, and `illustration_inventory.py compare` shows exactly
which stories changed.

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
* `venv/bin/python ops/media/alt_audit.py` exits 0. Every alt text must
  match its image (O54);
* `compare` lists only stories of this batch as changed (now
  `cax-editorial-4`), with nothing missing;
* five of the new images are spot-checked on their article pages and at
  feed size;
* the Telegram ledger shows only scheduled growth.

Then run the next batch. The command always takes the newest stories that
still need it, so batches never overlap. Six batches of 25 cover all 136.
In each batch, `compare` shows the high-confidence stories as
`cax-editorial-4` and the low-confidence ones as `cax-svg-3`. A
low-confidence story turning up as `cax-editorial-4` is a defect: stop.

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
