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
