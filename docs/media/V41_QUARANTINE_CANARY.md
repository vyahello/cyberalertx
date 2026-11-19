# V4.1 canary in quarantine

Canary 4 published five faulty V4.1 images before anyone reviewed them
(O57). From canary 5 on, a canary never publishes. Production keeps V3, and
**no systemd override is used**. V4.1 images are produced as
**candidates** in a review directory, outside the image index. Only
candidates the owner explicitly approves are promoted into production.

Code: `cyberalertx/media/candidates.py`, CLI `tools.media candidates`.
Paths use the runbook placeholders `$APP_HOME`, `$APP_ROOT/current` and
`$REVIEW_DIR`.

## Guarantees

| Requirement | How |
|---|---|
| Production rendering unchanged | The generate service keeps V3; no drop-in, no `.env` change |
| Candidates outside the image index | Files live under `$REVIEW_DIR/v41-candidates/<session>/` (mode 700). `collect` checks the index sha256 before and after and aborts on any change |
| No public URL for a candidate | `/media` serves only files the index references; nginx exposes neither `$REVIEW_DIR` nor `data/` |
| Nothing sent to Telegram or Threads | Both send only the index's canonical illustration |
| Hybrid routing kept | `collect` uses `renderer.plan_for(…, V4)`; low-confidence and unrecognisable drawings are listed as "routed to V3" and not drawn |
| Only approved images reach production | `promote` refuses a story without an `approved` verdict in `review.json`, recorded against the exact SVG checksum. The candidate must re-render byte for byte with the deployed code, and only the approved stories may change in the index |
| Old URLs keep working | Promotion keeps the previous file in `previous_storage_keys` |
| Secondary guard | Every session has an expiry (6 h by default, at most 12 h). After it, `collect` refuses |

## Run

```bash
cd $APP_ROOT/current
c() { bash -c ". ops/release/loadenv.sh && loadenv $APP_HOME/.env && venv/bin/python -m cyberalertx.tools.media candidates $*"; }

c start --root $REVIEW_DIR/v41-candidates --hours 6      # prints the session directory
SESSION=$REVIEW_DIR/v41-candidates/<timestamp>

# Collect after each hourly generate run (new stories only). Optional cron
# entry as the app user; it no-ops (exit 2) once the session has expired:
#   20 * * * * bash -c 'cd $APP_ROOT/current && . ops/release/loadenv.sh && loadenv $APP_HOME/.env && venv/bin/python -m cyberalertx.tools.media candidates collect --session SESSION' >> SESSION/collect.log 2>&1
c collect --session $SESSION
c collect --session $SESSION --recent 5    # optional: also 5 newest existing stories without a V4.1 image

# Review: $SESSION/index.html has, per candidate, the source and excerpt,
# the full image (website, article and Telegram use the full frame), the
# 176 px feed crop, the 1200x630 card crop, EN/UA alt text, the drawn labels
# and the alt check. Record each decision:
c review --session $SESSION --story s:… --verdict approved --reviewer owner \
  --score relevance=5 --score recognition=4 --score visual=4 --score composition=4 \
  --score accuracy=5 --score integrity=5 --score thumbnail=5
c review --session $SESSION --story s:… --verdict rejected --reviewer owner --score … --notes "why"
```

The gates are relevance, recognition, visual quality, accuracy and
thumbnail readability at 4 or more, composition at 3 or more, and evidence
integrity at 5. The alt check must be clean. `review` refuses to approve
below a gate.

## Promote (only after the owner's explicit approval)

```bash
B=$BACKUPS/pre-v41-promote-$(date +%Y%m%d-%H%M); install -d -m 700 "$B"
cp -a $APP_HOME/data/media/assets.json "$B"/ && sha256sum $APP_HOME/data/media/assets.json > "$B"/assets.sha256
c promote --session $SESSION --story s:A --story s:B    # approved stories only
venv/bin/python ops/media/illustration_inventory.py compare "$B"/…   # exactly these stories changed
venv/bin/python ops/media/alt_audit.py | head -1
```

## Rollback and cleanup

* **Exact restore** of the index to its pre-promotion state:
  `cp -a "$B"/assets.json $APP_HOME/data/media/assets.json && sha256sum -c "$B"/assets.sha256`.
  Files are never deleted, so every old URL works again.
* **One story back to V3:** run `tools.media regenerate s:…` with V3
  active, then one V3 `tools.media run`.
* **End of a session:** remove the cron line
  (`crontab -l | grep -v v41-candidates | crontab -`), then
  `c cleanup --session $SESSION`. That deletes the candidate files and
  verifies the index is unchanged. Keep the session instead if it is review
  evidence.
