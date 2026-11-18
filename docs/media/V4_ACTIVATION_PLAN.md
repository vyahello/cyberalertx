# V4 illustration renderer: controlled activation plan

**Status: prepared, not executed.** Production renders with V3 (`cax-svg-3`).
Nothing below runs without the owner's explicit approval. Each phase is
approved separately.

Paths use the placeholders of the other runbooks: `$APP_HOME` (the app
checkout, with `.env` and `data/`), `$APP_ROOT/current` (the active release),
`$OPS_TOOLS` (release tooling) and `$BACKUPS` (the protected backup root).
Set them in the shell before running a block.

Out of scope here: the archive backfill (152 eligible stories, 313
illustrations in the index). That is a later, separate decision taken after
the canary.

## What was verified (18 Nov 2026)

| Check | Method | Result |
|---|---|---|
| The flag changes nothing for existing images | `engine.run(dry_run=True)` on production data, flag unset vs `editorial-4` | Both: 152 eligible, **152 kept, 0 to generate**, identical sets (144 `cax-svg-2`, 8 `cax-svg-3`). `assets.json` checksum unchanged |
| Under V4, existing images are frozen | Code path `media/engine.py` (gate on `generation_model != plan.renderer`) + test `test_switching_renderers_never_replaces_images_by_itself` | A validated image from any other renderer is kept, and only its member list is updated, as today. Alt text and file are untouched. Under V4, existing images are never refreshed even when their story changes |
| Deploying the release with the flag unset changes no image | V3 render of all 252 scene/overlay combinations in the live release vs `9b4adb0` | Byte-identical (digest `9f124bcc880c706c`). Only the sanitizer allowlist changed |
| Only one process renders illustrations | `systemctl cat` of all units; code search | Only the `cyberalertx-generate.service` `ExecStartPost` (`tools.media run --max-calls 25`, hourly). API, Telegram and Threads only read existing images |
| The flag is not already set | `.env` key count | `CYBERALERTX_ILLUSTRATION_RENDERER` absent |
| Rollback re-renders only V4 images | Test `test_canary_rollback_rerenders_only_the_v4_images` | Flag back to V3 keeps V4 images; `regenerate` + one run returns the story to V3; an older `cax-svg-2` image is untouched; the V4 file stays served as a previous key |
| Canary volume | Validated illustrations created per day, last 7 days | 12–32 per day, so 5–10 V4 images arrive within about 4–10 h |

**Correction:** earlier drafts described rollback as "unset the flag and run
the backfill". That would convert the 302 `cax-svg-2` images to V3. Rollback
is per story (below).

## The six flagged images: are code changes needed?

| # | Story / scene | Finding | Change needed? | Before canary? |
|---|---|---|---|---|
| 28 | Fireworks key → Cursor → Claude Code extension (`dev_supply_chain`) | The chain is supported by the source: Cursor's statement "an access key we had issued to Fireworks", and a malicious extension pushed through its marketplace. The editor panel shows invented loader code (`exec('curl … \| sh')`) and a spawned `sh -c curl` process as if they were facts | **Yes, small:** replace the code and process panes with the extension update and an explicitly redacted "contents not described" block. This applies to every story routed to this scene | **Recommended (accuracy)** |
| 29 | UnrealIRCd (`irc_injection`) | Source: "delimiter-handling command injection", exploited (CISA KEV). The `;` "shell delimiter" label and the `sh -c` chain are plausible but not stated | **Yes, small:** label the boxed character "delimiter not neutralised" and show "command executed as ircd" instead of a specific `sh -c` chain | **Recommended (accuracy)** |
| 31 | Deepfake video calls (`deepfake_call`) | The idea and the facts are right; the face rendering is flat, close to clip-art | Yes, a redraw of the face (medium effort) | No: quality only; rare scene |
| 34 | Telegram RCE claims (`vuln_advisory`, terminal variant) | Accurate after the review fix (proof of concept); visually sparse | Yes: richer product drawing for mobile apps, or route mobile-app advisories to the sheet variant | **Recommended**: `vuln_advisory` is the most frequent scene (about 23% of stories) |
| 35 | Trigram campaign (`dossier`) | Fallback by design; accurate, not story-specific | No code fix; new scenes would reduce fallbacks | No |
| 36 | Fandango checkout skimming (`dossier`) | Same; a "payment skimmer" scene would serve it | Optional new scene | No |

None of these touches the archive. They affect only the images new stories
would get. The three "recommended" items are small and can ship in the same
release as the canary if approved; otherwise the canary will measure them.

## Phase 0: release (needs approval; no image change)

The release is built from `main` with the standard procedure: `git archive`,
`verify_release.py`, venv, staging tests, read-only data link. The flag is
**not** set. The owner switches:

```bash
sudo bash $OPS_TOOLS/switch_when_idle.sh <RELEASE_ID>
```

**Expected:** no illustration changes; V3 stays the renderer. Telegram and
Threads schedules, the ledger and the Threads disabled state are untouched.
Article pages gain a credit line only for library photographs (none in the
archive). The feed thumbnail of V3 images keeps its 62% crop.

**Rollback:**

```bash
sudo bash $OPS_TOOLS/release_switch.sh 20261117-1852-9821880
```

## Phase 1: pre-flight (as `cax`; read-only apart from a protected backup)

Run right after an hourly generate run has finished (the timer fires at about
:01; see `systemctl list-timers cyberalertx-generate.timer`):

```bash
cd $APP_ROOT/current
B=$BACKUPS/pre-v4-canary-$(date +%Y%m%d-%H%M)
install -d -m 700 "$B"
cp -a $APP_HOME/data/media/assets.json "$B"/assets.json            # the image index
venv/bin/python ops/media/illustration_inventory.py snapshot "$B"/inventory.json
wc -l < $APP_HOME/data/telegram_published.jsonl > "$B"/telegram_ledger_lines.txt
sha256sum $APP_HOME/.env > "$B"/env.sha256                        # proves .env is not edited
grep -c '^THREADS_ENABLED=0' $APP_HOME/.env                       # expect 1
systemctl list-timers 'cyberalertx-*' --all > "$B"/timers.txt
echo "$B"
```

Image files are content-addressed and never deleted, so the index
(`assets.json`) is the only state the canary can change. The backup covers it.

## Phase 2: activate the canary (root; needs approval)

A systemd drop-in on the one unit that renders. `.env` is not edited.

```bash
sudo install -d -m 755 /etc/systemd/system/cyberalertx-generate.service.d
printf '[Service]\nEnvironment=CYBERALERTX_ILLUSTRATION_RENDERER=editorial-4\n' \
  | sudo tee /etc/systemd/system/cyberalertx-generate.service.d/v4-renderer.conf >/dev/null
sudo systemctl daemon-reload
systemctl show cyberalertx-generate.service -p Environment     # must list CYBERALERTX_ILLUSTRATION_RENDERER=editorial-4
```

Do not restart the service: the timer starts the next run. A run that is
already in progress keeps V3.

**Expected effects:**

* From the next hourly media pass, a story that has no validated
  illustration gets a V4 image. All 313 existing illustrations keep their
  file, renderer, status and alt text.
* New stories' Telegram posts attach the V4 image, as they attach any
  canonical illustration today. The schedule, ledger and channels are
  unchanged. Threads stays disabled.
* About 0.3 s more CPU per rasterized variant on first request (cached for a
  day). The hourly pass gains under 1 s for V4 rendering.
* Other processes and manual `tools.media` commands still use V3 (the
  variable is only in this unit). Run any manual media command during the
  canary with the variable set explicitly, or not at all.

## Phase 3: canary verification

### After the first media pass (about :01–:10 after activation)

```bash
cd $APP_ROOT/current
journalctl -u cyberalertx-generate.service --since "-30 min" --no-pager -o cat \
  | awk '/"generated"|"failed"|Traceback/{p=1} p{print} /\]/{p=0}'          # generated + failed lists
venv/bin/python ops/media/illustration_inventory.py compare "$B"/inventory.json     # exit 0 required
venv/bin/python ops/media/illustration_inventory.py v4-stories
sha256sum -c "$B"/env.sha256
grep -c '^THREADS_ENABLED=0' $APP_HOME/.env                                    # still 1
```

**Pass criteria:**

* `compare` shows **0 changed, 0 missing**. The only `NEW` entries are new
  stories, all `cax-editorial-4 validated`.
* No `failed` entries and no tracebacks in the journal.
* `.env` checksum unchanged; Threads still disabled.
* The Telegram ledger only grows by normal scheduled posts: at most one per
  channel per run, no replays.

### The first 5–10 V4 images (human review, within about 4–10 h)

For each story listed by `v4-stories`:

```bash
venv/bin/python -m cyberalertx.tools.media brief <STORY> --svg /tmp/<STORY>.svg   # brief + evidence; read-only
```

Open the article page and the Telegram post. Score each image 1–5, using the
same rubric as VISUAL_REVIEW_V4.md:

| Criterion | Per image | Across the canary |
|---|---|---|
| Relevance | ≥ 4 | average ≥ 4.5 |
| Recognition (without the headline) | ≥ 4, except the `dossier` fallback | average ≥ 4.0 |
| Visual quality | ≥ 4 | average ≥ 4.0 |
| Composition | ≥ 3 | average ≥ 3.8 |
| Technical accuracy | **≥ 4, no exceptions**: no figure absent from `brief.facts`, no exploitation, theft or encryption the evidence does not state, no real logo or interface | **every image** |
| Fallback frequency | — | `dossier` ≤ 30% of canary images (archive baseline 18%) |
| Engineering | sanitizer OK, SVG ≤ 400 KB, page and Telegram image load, feed thumbnail legible at 176 px, alt text matches the image (EN and UA) | every image |

**Go/no-go:**

* **Go** (keep V4 on for new stories; propose the archive backfill
  separately) when every image passes the accuracy and engineering criteria,
  at least 80% pass all per-image criteria, and the averages are met.
* **Pause** (soft rollback) on any accuracy failure, any engineering failure,
  or more than 30% fallbacks. V4 images already published stay; fix, then
  re-run the canary.
* **Full rollback** if an image is misleading in public.

To bound the canary at 5–10 images, apply the soft rollback once that many
exist and keep it in place during the review. Re-enable with the Phase 2
commands.

## Rollback

**Soft** (stop V4 for new stories; canary images stay):

```bash
sudo rm /etc/systemd/system/cyberalertx-generate.service.d/v4-renderer.conf
sudo rmdir /etc/systemd/system/cyberalertx-generate.service.d
sudo systemctl daemon-reload
systemctl show cyberalertx-generate.service -p Environment   # variable gone
```

**Full** (also re-render the canary images with V3; as `cax`, after the soft
rollback):

```bash
cd $APP_ROOT/current
for s in $(venv/bin/python ops/media/illustration_inventory.py v4-stories); do
  venv/bin/python -m cyberalertx.tools.media regenerate "$s"
done
# The next hourly pass re-renders them with V3. Until then those few stories
# show the branded "pending" visual. Their V4 file URLs keep working
# (previous keys).
```

**Never** use `tools.media backfill --batch` for a rollback. It replaces
every image not made by the active renderer, including the 302 `cax-svg-2`
images.

**Last resort** (restore the index exactly as it was before the canary;
stops writes while copying):

```bash
sudo systemctl stop cyberalertx-generate.timer
cp -a "$B"/assets.json $APP_HOME/data/media/assets.json
sudo systemctl start cyberalertx-generate.timer
```

## What stays unchanged throughout

* The current release (until Phase 0 is approved) and every older release.
* The image index entries and files of all existing illustrations, and
  `/media` URLs and cache headers (asset IDs are content hashes).
* Generate, Telegram, analytics and Threads-token timers.
* The Telegram ledger and job store (only normal scheduled activity), and
  Threads disabled (`THREADS_ENABLED=0`).
* `.env`: never edited; the variable lives in a systemd drop-in.
