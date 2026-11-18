"""Build the V3 -> V4 illustration review gallery (read-only on production data).

    PYTHONPATH=. venv/bin/python ops/media/build_review_gallery.py OUT_DIR [--stories keys.json]
        [--scores scores.json]

For each story: headline, canonical story id, the structured V4 brief, why the
scene fits, the current (V3) image from the media store, the V4 candidate,
full-size previews, the real feed-size thumbnails (same crop rules as the
site's /media route), source/licence of any library photograph, uncertainty,
and the editorial scores from `scores.json` (filled in by a human reviewer
after looking at the images). Nothing is written to the media store.
Rasterization uses the site's own sharp (frontend/node_modules).
"""
from __future__ import annotations

import argparse
import html
import json
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
CRITERIA = ("relevance", "recognition", "visual_quality", "composition", "distinctiveness", "accuracy", "rights")
MUST_BE_4 = ("relevance", "recognition", "visual_quality", "accuracy")

_RASTER_JS = r"""
const sharp=require(process.argv[1]); const fs=require('fs'); const jobs=JSON.parse(fs.readFileSync(process.argv[2]));
const focusOf=(buf)=>{const t=buf.subarray(Math.max(0,buf.length-400)).toString('utf8');
 const m=/<rect id="cax-focus" x="(\d+)" y="(\d+)" width="(\d+)" height="(\d+)"/.exec(t); return m?m.slice(1).map(Number):null;};
(async()=>{for(const j of jobs){
  const buf=fs.readFileSync(j.src); const t0=Date.now();
  await sharp(buf).resize(1600,900).webp({quality:84}).toFile(j.out+'-full.webp');
  const ms=Date.now()-t0;
  await sharp(buf).resize(800,450).webp({quality:82}).toFile(j.out+'.webp');
  let base=sharp(buf); const head=buf.subarray(0,200).toString('utf8');
  if(head.startsWith('<svg')&&head.includes('id="cax-editorial-4"')){const f=focusOf(buf);
    if(f) base=sharp(await sharp(buf).extract({left:f[0],top:f[1],width:f[2],height:f[3]}).png().toBuffer());}
  else {const m=await sharp(buf).metadata(); const w=m.width,h=m.height; const cw=Math.round(w*0.62),ch=Math.round(cw*9/16);
    const left=Math.round((w-cw)/2),top=Math.max(0,Math.round((h-ch)/2-h*0.04));
    base=sharp(await sharp(buf).extract({left,top,width:cw,height:Math.min(ch,h-top)}).png().toBuffer());}
  await base.resize(352,198,{fit:'cover',position:sharp.strategy.attention}).webp({quality:84}).toFile(j.out+'-feed.webp');
  // Telegram/Threads attach the whole frame; show it at chat-preview size.
  await sharp(buf).resize(320,180).webp({quality:84}).toFile(j.out+'-chat.webp');
  console.log(JSON.stringify({id:j.id,raster_ms:ms}));
}})().catch(e=>{console.error(e);process.exit(1)});
"""


def _story_set(path: Path | None) -> list[str]:
    if path is None:
        return []
    raw = json.loads(path.read_text())
    return [r["story"] if isinstance(r, dict) else r for r in raw]


def build(out: Path, keys: list[str], scores: dict[str, dict]) -> dict:
    import time

    from cyberalertx.api.app import _PostService
    from cyberalertx.intel.engine import run as intel_run
    from cyberalertx.media.assets import MediaStore
    from cyberalertx.media.v4 import library
    from cyberalertx.media.v4.brief import SPECS, alt_text, build as build_brief
    from cyberalertx.media.v4.render import render
    from cyberalertx.media.svg_art import sanitize_svg
    from cyberalertx.tools.media import _stores

    img = out / "img"
    img.mkdir(parents=True, exist_ok=True)
    items = list(_PostService().list_items())
    sheets, posts = _stores()
    stories = {s.key: s for s in intel_run(items, write=False, sheets=sheets, posts=posts).stories}
    store = MediaStore()
    rows, jobs = [], []
    for i, key in enumerate(keys):
        st = stories.get(key)
        if st is None:
            continue
        b = build_brief(st)
        t = time.perf_counter()
        svg = render(b)
        render_ms = (time.perf_counter() - t) * 1000
        sanitize_svg(svg.encode())
        (img / f"{i}-v4.svg").write_text(svg, encoding="utf-8")
        jobs.append({"id": f"{i}-v4", "src": str(img / f"{i}-v4.svg"), "out": str(img / f"{i}-v4")})
        old = store.get(f"illus:{key}")
        old_file = store.files / old.storage_key if old and old.storage_key else None
        if old_file is not None and old_file.is_file():
            jobs.append({"id": f"{i}-v3", "src": str(old_file), "out": str(img / f"{i}-v3")})
        lib = library.get(b.library_id) if b.library_id else None
        rows.append({
            "i": i, "story": key, "title": st.anchor.title, "source": st.anchor.source,
            "lang": st.anchor.language, "category": st.anchor.category,
            "brief": b.to_dict(), "spec_alt": SPECS.get(b.scene, SPECS["dossier"]).alt_en,
            "alt": alt_text(b), "svg_kb": round(len(svg) / 1024), "render_ms": round(render_ms, 1),
            "v3": bool(old_file and old_file.is_file()), "v3_model": old.generation_model if old else "",
            "library": ({**lib.provenance(), "subject": lib.subject} if lib else None),
            "scores": scores.get(key, {}),
        })
    jf = out / "jobs.json"
    jf.write_text(json.dumps(jobs))
    res = subprocess.run(["node", "-e", _RASTER_JS, str(ROOT / "frontend/node_modules/sharp"), str(jf)],
                         capture_output=True, text=True, check=True)
    raster = {j["id"]: j["raster_ms"] for j in map(json.loads, res.stdout.split())}
    for r in rows:
        r["raster_ms"] = raster.get(f"{r['i']}-v4")
    jf.unlink()
    (out / "gallery.json").write_text(json.dumps(rows, ensure_ascii=False, indent=1))
    (out / "index.html").write_text(_html(rows), encoding="utf-8")
    return {"stories": len(rows)}


def _flags(sc: dict) -> list[str]:
    return [c for c in MUST_BE_4 if isinstance(sc.get(c), (int, float)) and sc[c] < 4]


def _html(rows: list[dict]) -> str:
    e = html.escape
    scored = [r for r in rows if r["scores"]]
    flagged = [r for r in scored if _flags(r["scores"])]
    avg = {c: round(sum(r["scores"].get(c, 0) for r in scored) / max(len(scored), 1), 2) for c in CRITERIA}
    cards = []
    for r in rows:
        b, sc = r["brief"], r["scores"]
        fl = _flags(sc)
        facts = ", ".join(f"{k}={v}" for k, v in b["facts"].items() if not k.endswith(("_plus", "_approx"))) or "—"
        lib = r["library"]
        rights = (f'<a href="{e(lib["source_url"])}">{e(lib["author"])}, {e(lib["license"])}</a>'
                  if lib else "Original CyberAlertX illustration (no third-party material)")
        score_cells = "".join(
            f'<td class="{"low" if isinstance(sc.get(c), (int, float)) and sc[c] < 4 else ""}">{sc.get(c, "–")}</td>'
            for c in CRITERIA)
        v3 = (f'<a href="img/{r["i"]}-v3-full.webp"><img src="img/{r["i"]}-v3.webp" alt="V3" loading="lazy"></a>'
              if r["v3"] else '<div class="none">no V3 image</div>')
        v3feed = f'<img class="feed" src="img/{r["i"]}-v3-feed.webp" alt="">' if r["v3"] else ""
        cards.append(f"""
<section class="story{' flagged' if fl else ''}" id="s{r['i']}">
 <h2>{r['i'] + 1}. {e(r['title'])}</h2>
 <p class="meta"><code>{e(r['story'])}</code> · {e(r['source'])} · {e(r['lang'])} · {e(r['category'] or '')}
  · scene <b>{e(b['scene'])}</b> · confidence <b>{e(b['confidence'])}</b>
  {'· <span class="flag">FLAGGED: ' + ', '.join(fl) + ' &lt; 4</span>' if fl else ''}</p>
 <div class="pair">
  <figure><figcaption>V3 (current, {e(r['v3_model'] or '—')})</figcaption>{v3}</figure>
  <figure><figcaption>V4 candidate · <a href="img/{r['i']}-v4-full.webp">full size</a></figcaption>
   <a href="img/{r['i']}-v4-full.webp"><img src="img/{r['i']}-v4.webp" alt="{e(r['alt']['en'])}" loading="lazy"></a></figure>
 </div>
 <div class="thumbs"><span>Feed size (176 px, site crop):</span> V3 {v3feed} V4
  <img class="feed" src="img/{r['i']}-v4-feed.webp" alt=""> <span>Chat preview:</span>
  <img class="chat" src="img/{r['i']}-v4-chat.webp" alt=""></div>
 <table class="brief">
  <tr><th>Primary subject</th><td>{e(b['subject'])}</td></tr>
  <tr><th>Main action</th><td>{e(b['action'])}</td></tr>
  <tr><th>Target</th><td>{e(b['target'])}</td></tr>
  <tr><th>Environment</th><td>{e(b['environment'])}</td></tr>
  <tr><th>Mechanism</th><td>{e(b['mechanism'])}</td></tr>
  <tr><th>Entities</th><td>{e(', '.join(b['entities']) or '—')}</td></tr>
  <tr><th>Impact / facts</th><td>{e(b['impact'] or '—')} · {e(facts)}</td></tr>
  <tr><th>Evidence status</th><td>{e(b['status'])}</td></tr>
  <tr><th>Must not appear</th><td>{e(', '.join(b['exclude']))}</td></tr>
  <tr><th>Why this scene</th><td>{e(b['reason'])}<br><small>runner-up: {e(', '.join(f'{a} ({s})' for a, s in b['alternatives']) or '—')}</small></td></tr>
  <tr><th>Image source / licence</th><td>{rights}</td></tr>
  <tr><th>Alt text (EN)</th><td>{e(r['alt']['en'])}</td></tr>
  <tr><th>Uncertainty</th><td>{e(sc.get('note', '') or ('low-confidence brief: restrained fallback' if b['confidence'] == 'low' else '—'))}</td></tr>
  <tr><th>Cost</th><td>SVG {r['svg_kb']} KB · render {r['render_ms']} ms · rasterize {r['raster_ms']} ms · $0</td></tr>
 </table>
 <table class="scores"><tr>{''.join(f'<th>{c}</th>' for c in CRITERIA)}</tr><tr>{score_cells}</tr></table>
</section>""")
    summary = "".join(f"<li>{c}: {avg[c]}</li>" for c in CRITERIA)
    flagged_list = "".join(f'<li><a href="#s{r["i"]}">{e(r["title"][:90])}</a> — {", ".join(_flags(r["scores"]))}: '
                           f'{e(r["scores"].get("note", ""))}</li>' for r in flagged) or "<li>none</li>"
    return f"""<!doctype html><html lang="en"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1"><title>Illustrations V4 review</title>
<style>
:root{{--bg:#f6f4ef;--fg:#16181d;--mut:#6b6558;--line:#ddd5c6;--bad:#c62f22}}
@media (prefers-color-scheme:dark){{:root{{--bg:#111318;--fg:#e8eaee;--mut:#9aa0ab;--line:#2b303a;--bad:#ff6a5c}}}}
body{{margin:0;background:var(--bg);color:var(--fg);font:15px/1.5 system-ui,sans-serif}}
main{{max-width:1240px;margin:0 auto;padding:24px 16px}}
h1{{font-size:28px;margin:0 0 4px}} h2{{font-size:19px;margin:0 0 4px}}
.meta{{color:var(--mut);margin:0 0 12px;font-size:13px}} code{{font-size:12px}}
.story{{border-top:1px solid var(--line);padding:28px 0}} .flagged h2::before{{content:"⚑ ";color:var(--bad)}}
.flag{{color:var(--bad);font-weight:600}}
.pair{{display:grid;grid-template-columns:1fr 1fr;gap:16px}} figure{{margin:0}}
figcaption{{font-size:12px;color:var(--mut);margin-bottom:4px}}
.pair img{{width:100%;height:auto;display:block;border-radius:4px}}
.none{{aspect-ratio:16/9;display:grid;place-items:center;border:1px dashed var(--line);color:var(--mut)}}
.thumbs{{display:flex;align-items:center;gap:10px;flex-wrap:wrap;margin:10px 0;font-size:12px;color:var(--mut)}}
.thumbs img.feed{{width:176px;height:99px;border-radius:3px}} .thumbs img.chat{{width:320px;height:180px;border-radius:8px}}
table{{border-collapse:collapse;width:100%;font-size:13px;margin-top:8px}}
th,td{{border-bottom:1px solid var(--line);padding:5px 8px;text-align:left;vertical-align:top}}
.brief th{{width:170px;color:var(--mut);font-weight:500}} .scores td{{text-align:center;font-weight:600}}
.scores td.low{{color:var(--bad)}}
@media (max-width:760px){{.pair{{grid-template-columns:1fr}}}}
</style></head><body><main>
<h1>Editorial illustrations: V3 → V4 review</h1>
<p class="meta">{len(rows)} real CyberAlertX stories · renderer cax-editorial-4 · scores 1–5 from visual inspection ·
flag = relevance, recognition, visual quality or accuracy below 4</p>
<h2>Average scores ({len(scored)} scored)</h2><ul>{summary}</ul>
<h2>Needs human review ({len(flagged)})</h2><ul>{flagged_list}</ul>
{''.join(cards)}
</main></body></html>"""


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("out", type=Path)
    ap.add_argument("--stories", type=Path)
    ap.add_argument("--scores", type=Path)
    a = ap.parse_args()
    keys = _story_set(a.stories)
    scores = json.loads(a.scores.read_text()) if a.scores and a.scores.is_file() else {}
    print(build(a.out, keys, scores))


if __name__ == "__main__":
    sys.path.insert(0, str(ROOT))
    main()
