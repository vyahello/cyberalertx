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

def test_renderer_version_is_v2() -> None:
    from cyberalertx.media.svg_art import RENDERER_VERSION
    assert RENDERER_VERSION == "cax-svg-2"


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
