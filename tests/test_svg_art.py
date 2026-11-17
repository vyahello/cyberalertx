"""Server-side SVG illustrations (media/svg_art.py) and their sanitizer."""
from __future__ import annotations

import pytest

from cyberalertx.media.assets import MediaStore, MediaValidationError, validate_image
from cyberalertx.media.svg_art import OVERLAYS, SCENES, UnsafeSvg, VisualBrief, render_svg, sanitize_svg


@pytest.mark.parametrize("event", sorted(OVERLAYS))
@pytest.mark.parametrize("scene", sorted(SCENES))
def test_every_scene_and_event_renders_a_safe_1600x900_svg(event: str, scene: str) -> None:
    svg = render_svg(VisualBrief(event, (scene,), f"{event}:{scene}"))
    assert sanitize_svg(svg.encode()) == (1600, 900)
    for banned in ("<script", "<text", "<image", "foreignObject", "href", "http"):
        assert banned not in svg.replace('xmlns="http://www.w3.org/2000/svg"', "")


def test_deterministic_per_story_and_different_between_stories() -> None:
    a = render_svg(VisualBrief("exploited", ("rack",), "s:one"))
    assert a == render_svg(VisualBrief("exploited", ("rack",), "s:one"))
    assert a != render_svg(VisualBrief("exploited", ("rack",), "s:two"))


def test_event_changes_the_picture() -> None:
    seed = "s:same"
    assert render_svg(VisualBrief("exposed", ("rack",), seed)) != render_svg(VisualBrief("exploited", ("rack",), seed))


@pytest.mark.parametrize("bad", [
    '<svg xmlns="http://www.w3.org/2000/svg" width="1600" height="900"><script>alert(1)</script></svg>',
    '<svg xmlns="http://www.w3.org/2000/svg" width="1600" height="900"><foreignObject/></svg>',
    '<svg xmlns="http://www.w3.org/2000/svg" width="1600" height="900"><image href="https://x.test/a.png"/></svg>',
    '<svg xmlns="http://www.w3.org/2000/svg" width="1600" height="900"><rect onload="x()"/></svg>',
    '<svg xmlns="http://www.w3.org/2000/svg" width="1600" height="900"><rect fill="url(https://x.test/p)"/></svg>',
    '<!DOCTYPE svg [<!ENTITY a "b">]><svg xmlns="http://www.w3.org/2000/svg" width="1600" height="900"/>',
    '<svg xmlns="http://www.w3.org/2000/svg" width="1600" height="900"><text>hi</text></svg>',
    '<svg xmlns="http://www.w3.org/2000/svg" width="10" height="10"/>',
    "<svg not even xml",
])
def test_sanitizer_rejects_unsafe_svg(bad: str) -> None:
    with pytest.raises(UnsafeSvg):
        sanitize_svg(bad.encode())


def test_store_accepts_rendered_svg_and_refuses_unsafe(tmp_path: object) -> None:
    from pathlib import Path
    store = MediaStore(Path(str(tmp_path)))
    good = render_svg(VisualBrief("analysis", ("ai",), "s:x")).encode()
    assert validate_image(good) == ("image/svg+xml", 1600, 900)
    sha, mime, w, h = store.save_bytes(good, declared_mime="image/svg+xml")
    assert mime == "image/svg+xml" and (w, h) == (1600, 900) and (store.files / f"{sha}.svg").exists()
    with pytest.raises(MediaValidationError):
        validate_image(b'<svg xmlns="http://www.w3.org/2000/svg" width="1600" height="900"><script/></svg>')


# ---------------------------------------------------------------- v2 composition

def test_renderer_version_is_v3() -> None:
    from cyberalertx.media.svg_art import RENDERER_VERSION
    assert RENDERER_VERSION == "cax-svg-3"


@pytest.mark.parametrize("scene", sorted(SCENES))
def test_the_subject_is_fitted_to_fill_about_half_the_frame(scene: str) -> None:
    import random
    from cyberalertx.media.svg_art import W, H, _fit, _scene_layer
    layer, _ = _scene_layer(random.Random(1), scene)
    tw, th = W * 0.55, H * 0.6
    _, to_screen, _ = _fit(layer.bbox, tw, th, W / 2, H / 2, False)
    x0, y0 = to_screen((layer.bbox[0], layer.bbox[1]))
    x1, y1 = to_screen((layer.bbox[2], layer.bbox[3]))
    w, h = x1 - x0, y1 - y0
    assert w <= tw + 1 and h <= th + 1
    assert w >= tw - 1 or h >= th - 1          # one dimension touches the target: no tiny subject
    assert 0 <= x0 and x1 <= W and 0 <= y0 and y1 <= H


def test_stories_of_the_same_kind_get_different_compositions() -> None:
    import re
    seen = set()
    for i in range(12):
        svg = render_svg(VisualBrief("exposed", ("rack",), f"s:{i:04d}"))
        m = re.search(r'<g transform="(translate\([^)]*\) scale\([^)]*\))">', svg)
        assert m
        seen.add(m.group(1))
    assert len(seen) == 12


def test_no_perspective_grid_and_restrained_glow() -> None:
    svg = render_svg(VisualBrief("exploited", ("phone", "browser"), "s:x"))
    assert svg.count('stroke="#1B212A"') == 0            # the v1 floor grid is gone
    glows = [float(x) for x in __import__("re").findall(r'opacity="([\d.]+)" filter="url\(#blur\)"', svg)]
    assert all(g <= 0.3 for g in glows)


# ---------------------------------------------------------------- v3: primary subject and new scene families

@pytest.mark.parametrize("title, first", [
    ("N-able Patches 17 N-central Flaws as Attackers Exploit Earlier Bugs to Deploy Crypto Miners", "rmm"),
    ("Hackers drain $40 million from a crypto platform after a wallet key leak", "wallet"),
    ("Google warns that fully-automated AI attacks will find and exploit vulnerabilities", "ai_discovery"),
    ("OpenAI's AI model turned up 948 ways to take over Linux machines via flaws", "ai_discovery"),
    ("Siemens PLC flaw exploited while attackers also target cloud logins", "industrial"),
    ("Phishing kit steals Microsoft 365 logins after hijacking cloud sessions", "mail"),
])
def test_the_main_clause_decides_the_subject(title: str, first: str) -> None:
    from cyberalertx.media.illustrations import _title_scenes
    assert _title_scenes(title)[0] == first


def test_an_incidental_consequence_never_becomes_the_subject() -> None:
    from cyberalertx.media.illustrations import _title_scenes
    scenes = _title_scenes("Widget VPN gateways patched after attackers stole crypto wallets")
    assert scenes[0] == "network_edge" and "wallet" in scenes[1:]


def test_new_scene_families_render_safe_and_distinct() -> None:
    a = render_svg(VisualBrief("exploited", ("rmm",), "s:same"))
    b = render_svg(VisualBrief("exploited", ("ai_discovery",), "s:same"))
    c = render_svg(VisualBrief("exploited", ("rack",), "s:same"))
    for svg in (a, b, c):
        assert sanitize_svg(svg.encode()) == (1600, 900)
    assert len({a, b, c}) == 3


def test_a_replaced_image_keeps_its_old_url_working(tmp_path: object) -> None:
    from pathlib import Path
    from cyberalertx.media.assets import MediaAsset
    store = MediaStore(Path(str(tmp_path)))
    old = render_svg(VisualBrief("analysis", ("ai",), "s:old")).encode()
    new = render_svg(VisualBrief("exploited", ("rmm",), "s:new")).encode()
    sha_old, *_ = store.save_bytes(old, declared_mime="image/svg+xml")
    sha_new, *_ = store.save_bytes(new, declared_mime="image/svg+xml")
    store.put(MediaAsset(asset_id="illus:s:x", story_key="s:x", asset_type="editorial_illustration",
                         storage_key=f"{sha_new}.svg", previous_storage_keys=[f"{sha_old}.svg"], status="validated"))
    assert store.open_file(sha_new[:16])[0] == new                      # the new image
    assert store.open_file(sha_old[:16])[0] == old                      # a cached page's old URL still works
    assert store.open_file("0" * 16) is None


def test_a_new_renderer_never_replaces_existing_images_by_itself(monkeypatch: pytest.MonkeyPatch,
                                                                 tmp_path: object) -> None:
    """Deploying cax-svg-3 must not start regenerating the archive hourly; only the
    explicit backfill (upgrade_renderer=True) replaces images of an older renderer."""
    from pathlib import Path
    from cyberalertx.media import engine
    from tests.test_media import NOW, critical_story, fake_intel
    stories = [critical_story("s:one"), critical_story("s:two", products=("Gadget Hub",))]
    fake_intel(monkeypatch, stories)
    store = MediaStore(Path(str(tmp_path)) / "media")
    anchors = [s.anchor for s in stories]
    assert len(engine.run(anchors, store=store, now=NOW).generated) == 2
    first = {a.asset_id: a.storage_key for a in store.all() if a.asset_type == "editorial_illustration"}
    for a in store.all():
        if a.asset_type == "editorial_illustration":
            a.generation_model, a.content_hash = "cax-svg-2", "old-renderer-hash"
            store.put(a)
    assert engine.run(anchors, store=store, now=NOW).generated == []      # the hourly pass
    assert {a.asset_id: a.storage_key for a in store.all() if a.asset_type == "editorial_illustration"} == first
    assert len(engine.run(anchors, store=store, now=NOW, upgrade_renderer=True).generated) == 2   # explicit backfill
