"""Build the illustration review gallery (read-only on production data).

    PYTHONPATH=. venv/bin/python ops/media/build_review_gallery.py OUT_DIR --stories keys.json
        [--prev PREV_DIR] [--scores scores.json] [--title "..."]

For each story: headline, canonical story id, the structured brief, the
previous image (an SVG named `*-<key>.svg` in PREV_DIR, e.g. renders of the
previous release), the candidate image, every alternative composition a scene
module exposes (`ALTERNATIVES`), the real feed thumbnail (176 px, same crop
rules as the site's /media route) for each, a chat-preview-size copy, notes
("what changed and why", uncertainties) and the reviewer's scores with the
hard gates. Nothing is written to the media store. Rasterization uses the
site's own sharp (frontend/node_modules).
"""
from __future__ import annotations

import argparse
import html
import importlib
import json
import subprocess
import sys
import time
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[2]
CRITERIA = ("relevance", "recognition", "visual_quality", "composition", "distinctiveness", "accuracy",
            "thumbnail", "integrity")
#: Hard gates: (criterion, minimum). Recognition is waived for the honest generic fallback.
GATES = (("relevance", 4), ("recognition", 4), ("visual_quality", 4), ("accuracy", 4), ("thumbnail", 4),
         ("integrity", 5))

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
  await base.resize(352,198,{fit:'cover',position:sharp.strategy.attention}).webp({quality:86}).toFile(j.out+'-feed.webp');
  await sharp(buf).resize(320,180).webp({quality:84}).toFile(j.out+'-chat.webp');
  console.log(JSON.stringify({id:j.id,raster_ms:ms}));
}})().catch(e=>{console.error(e);process.exit(1)});
"""


def _render_alt(brief: Any, fn: Any) -> str:
    from cyberalertx.media.v4.kit import PALETTES, Doc, signature
    from cyberalertx.media.v4.render import rng_for
    doc = Doc(PALETTES.get(brief.palette, PALETTES["midnight"]))
    fn(doc, brief, rng_for(brief))
    doc.grain(0.06 if doc.pal.dark else 0.05)
    signature(doc)
    return doc.svg()


def build(out: Path, keys: list[str], scores: dict[str, dict[str, Any]], prev: Path | None,
          title: str) -> dict[str, int]:
    from cyberalertx.api.app import _PostService
    from cyberalertx.intel.engine import run as intel_run
    from cyberalertx.media.svg_art import sanitize_svg
    from cyberalertx.media.v4 import library
    from cyberalertx.media.v4.brief import SPECS, alt_text
    from cyberalertx.media.v4.brief import build as build_brief
    from cyberalertx.media.v4.render import render
    from cyberalertx.tools.media import _stores

    img = out / "img"
    img.mkdir(parents=True, exist_ok=True)
    items = list(_PostService().list_items())
    sheets, posts = _stores()
    stories = {s.key: s for s in intel_run(items, write=False, sheets=sheets, posts=posts).stories}
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
        (img / f"{i}-new.svg").write_text(svg, encoding="utf-8")
        jobs.append({"id": f"{i}-new", "src": str(img / f"{i}-new.svg"), "out": str(img / f"{i}-new")})
        alts: list[str] = []
        mod = importlib.import_module(f"cyberalertx.media.v4.scenes.{b.scene}")
        for name, fn in sorted(getattr(mod, "ALTERNATIVES", {}).items()):
            try:
                a_svg = _render_alt(b, fn)
                sanitize_svg(a_svg.encode())
            except Exception as exc:                          # an alternative for another variant
                print(f"skip alternative {b.scene}@{name} for {key}: {type(exc).__name__}", file=sys.stderr)
                continue
            if a_svg == svg:
                alts.append(f"{name}*")                       # the selected one
                continue
            (img / f"{i}-alt-{name}.svg").write_text(a_svg, encoding="utf-8")
            jobs.append({"id": f"{i}-alt-{name}", "src": str(img / f"{i}-alt-{name}.svg"),
                         "out": str(img / f"{i}-alt-{name}")})
            alts.append(name)
        has_prev = False
        if prev is not None:
            cand = sorted(prev.glob(f"*-{key[2:]}.svg"))
            cand = [c for c in cand if "@" not in c.name]
            if cand:
                jobs.append({"id": f"{i}-prev", "src": str(cand[0]), "out": str(img / f"{i}-prev")})
                has_prev = True
        lib = library.get(b.library_id) if b.library_id else None
        rows.append({
            "i": i, "story": key, "title": st.anchor.title, "source": st.anchor.source,
            "lang": st.anchor.language, "category": st.anchor.category, "brief": b.to_dict(),
            "alt": alt_text(b), "svg_kb": round(len(svg) / 1024), "render_ms": round(render_ms, 1),
            "prev": has_prev, "alts": alts, "spec_mechanism": SPECS.get(b.scene, SPECS["dossier"]).mechanism,
            "library": ({**lib.provenance(), "subject": lib.subject} if lib else None),
            "scores": scores.get(key, {}),
        })
    jf = out / "jobs.json"
    jf.write_text(json.dumps(jobs))
    res = subprocess.run(["node", "-e", _RASTER_JS, str(ROOT / "frontend/node_modules/sharp"), str(jf)],
                         capture_output=True, text=True, check=True)
    raster = {j["id"]: j["raster_ms"] for j in map(json.loads, res.stdout.split())}
    for r in rows:
        r["raster_ms"] = raster.get(f"{r['i']}-new")
    jf.unlink()
    (out / "gallery.json").write_text(json.dumps(rows, ensure_ascii=False, indent=1))
    (out / "index.html").write_text(_html(rows, title), encoding="utf-8")
    return {"stories": len(rows)}


def gate_failures(sc: dict[str, Any], scene: str) -> list[str]:
    out = []
    for c, need in GATES:
        if c == "recognition" and scene == "dossier":
            continue
        v = sc.get(c)
        if isinstance(v, (int, float)) and v < need:
            out.append(f"{c} {v} < {need}")
    return out


def _html(rows: list[dict[str, Any]], title: str) -> str:
    e = html.escape
    scored = [r for r in rows if r["scores"]]
    fails = [(r, gate_failures(r["scores"], r["brief"]["scene"])) for r in scored]
    fails = [(r, f) for r, f in fails if f]
    avg = {c: round(sum(r["scores"].get(c, 0) for r in scored) / max(len(scored), 1), 2) for c in CRITERIA}
    cards = []
    for r in rows:
        b, sc, i = r["brief"], r["scores"], r["i"]
        fl = gate_failures(sc, b["scene"])
        facts = ", ".join(f"{k}={v}" for k, v in b["facts"].items() if not k.endswith(("_plus", "_approx"))) or "none"
        lib = r["library"]
        rights = (f'<a href="{e(lib["source_url"])}">{e(lib["author"])}, {e(lib["license"])}</a>'
                  if lib else "Original CyberAlertX illustration")

        def fig(tag: str, label: str) -> str:
            return (f'<figure><figcaption>{e(label)}</figcaption><a href="img/{i}-{tag}-full.webp">'
                    f'<img src="img/{i}-{tag}.webp" alt="" loading="lazy"></a>'
                    f'<div class="th"><img class="feed" src="img/{i}-{tag}-feed.webp" alt="" loading="lazy">'
                    f'<span>176 px</span></div></figure>')
        figs = []
        if r["prev"]:
            figs.append(fig("prev", "Previous V4"))
        sel = next((a[:-1] for a in r["alts"] if a.endswith("*")), "")
        figs.append(fig("new", "V4.1" + (f" (selected: {sel})" if sel else "")))
        for a in r["alts"]:
            if not a.endswith("*"):
                figs.append(fig(f"alt-{a}", f"Alternative {a}"))
        cells = "".join(
            f'<td class="{"low" if any(x.startswith(c + " ") for x in fl) else ""}">{sc.get(c, "–")}</td>'
            for c in CRITERIA)
        cards.append(f"""
<section class="story{' flagged' if fl else ''}" id="s{i}">
 <h2>{i + 1}. {e(r['title'])}</h2>
 <p class="meta"><code>{e(r['story'])}</code> · {e(r['source'])} · {e(r['lang'])} · scene <b>{e(b['scene'])}</b>
  · confidence {e(b['confidence'])}{' · <span class="flag">HARD GATE: ' + e('; '.join(fl)) + '</span>' if fl else ''}</p>
 <div class="figs">{''.join(figs)}</div>
 <div class="chat"><span>Chat preview (whole frame, 320 px):</span><img src="img/{i}-new-chat.webp" alt=""></div>
 <table class="brief">
  <tr><th>Subject / action</th><td>{e(b['subject'])}: {e(b['action'])}</td></tr>
  <tr><th>Mechanism shown</th><td>{e(b['mechanism'])}</td></tr>
  <tr><th>Stated facts used</th><td>{e(facts)} · entities: {e(', '.join(b['entities']) or 'none')} · evidence status: {e(b['status'])}</td></tr>
  <tr><th>Why this scene</th><td>{e(b['reason'])}</td></tr>
  <tr><th>What changed, why</th><td>{e(sc.get('changed', '') or '–')}</td></tr>
  <tr><th>Known uncertainties</th><td>{e(sc.get('uncertain', '') or '–')}</td></tr>
  <tr><th>Image source</th><td>{rights}</td></tr>
  <tr><th>Alt text (EN)</th><td>{e(r['alt']['en'])}</td></tr>
  <tr><th>Cost</th><td>SVG {r['svg_kb']} KB · render {r['render_ms']} ms · rasterize {r['raster_ms']} ms · $0</td></tr>
 </table>
 <table class="scores"><tr>{''.join(f'<th>{c}</th>' for c in CRITERIA)}</tr><tr>{cells}</tr></table>
</section>""")
    summary = "".join(f"<li>{c}: {avg[c]}</li>" for c in CRITERIA)
    fail_list = "".join(f'<li><a href="#s{r["i"]}">{e(r["title"][:90])}</a>: {e("; ".join(f))}</li>'
                        for r, f in fails) or "<li>none</li>"
    comp_ok = avg["composition"] >= 3.8
    return f"""<!doctype html><html lang="en"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1"><title>{e(title)}</title>
<style>
:root{{--bg:#f4f5f2;--fg:#15181e;--mut:#5c6470;--line:#d9dcd5;--bad:#c53a2e;--card:#fff}}
@media (prefers-color-scheme:dark){{:root{{--bg:#111418;--fg:#e7eaee;--mut:#9aa3ae;--line:#2a3038;--bad:#ff7b6e;--card:#181c22}}}}
body{{margin:0;background:var(--bg);color:var(--fg);font:15px/1.5 system-ui,sans-serif}}
main{{max-width:1320px;margin:0 auto;padding:24px 16px}}
h1{{font-size:28px;margin:0 0 4px}} h2{{font-size:19px;margin:0 0 4px}}
.meta{{color:var(--mut);margin:0 0 12px;font-size:13px}} code{{font-size:12px}}
.story{{border-top:1px solid var(--line);padding:28px 0}} .flagged h2::before{{content:"⚑ ";color:var(--bad)}}
.flag{{color:var(--bad);font-weight:600}}
.figs{{display:grid;grid-template-columns:repeat(auto-fit,minmax(300px,1fr));gap:14px}} figure{{margin:0}}
figcaption{{font-size:12px;color:var(--mut);margin-bottom:4px}}
.figs img{{width:100%;height:auto;display:block;border-radius:4px}}
.th{{display:flex;align-items:center;gap:8px;margin-top:6px;font-size:11px;color:var(--mut)}}
.figs img.feed{{width:176px;height:99px;border-radius:3px}}
.chat{{display:flex;gap:10px;align-items:center;margin:10px 0;font-size:12px;color:var(--mut)}} .chat img{{width:320px;height:180px;border-radius:8px}}
table{{border-collapse:collapse;width:100%;font-size:13px;margin-top:8px}}
th,td{{border-bottom:1px solid var(--line);padding:5px 8px;text-align:left;vertical-align:top}}
.brief th{{width:170px;color:var(--mut);font-weight:500}} .scores td{{text-align:center;font-weight:600}}
.scores td.low{{color:var(--bad)}}
</style></head><body><main>
<h1>{e(title)}</h1>
<p class="meta">{len(rows)} real stories · scores 1–5 from visual inspection at full size and 176 px ·
hard gates: relevance, recognition (except the honest fallback), visual quality, accuracy, thumbnail ≥ 4; evidence integrity = 5; composition average ≥ 3.8 (now {avg['composition']}, {'met' if comp_ok else 'NOT met'})</p>
<h2>Averages ({len(scored)} scored)</h2><ul>{summary}</ul>
<h2>Hard-gate failures ({len(fails)})</h2><ul>{fail_list}</ul>
{''.join(cards)}
</main></body></html>"""


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("out", type=Path)
    ap.add_argument("--stories", type=Path, required=True)
    ap.add_argument("--prev", type=Path)
    ap.add_argument("--scores", type=Path)
    ap.add_argument("--title", default="Illustration review")
    a = ap.parse_args()
    raw = json.loads(a.stories.read_text())
    keys = [x["story"] if isinstance(x, dict) else x for x in raw]
    scores = json.loads(a.scores.read_text()) if a.scores and a.scores.is_file() else {}
    print(build(a.out, keys, scores, a.prev, a.title))


if __name__ == "__main__":
    sys.path.insert(0, str(ROOT))
    main()
