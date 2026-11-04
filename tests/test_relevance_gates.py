"""Relevance gates: what out_of_scope means for generation, the feed and links."""
from __future__ import annotations

from dataclasses import replace
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from cyberalertx.ai.cache import ThreatPostCache
from cyberalertx.api.admin import AdminGuard
from cyberalertx.api.app import build_app
from cyberalertx.pipeline.relevance import hide_out_of_scope_publicly, is_renderable
from tests.test_review import _item, _post, _Svc


def test_is_renderable_honours_override() -> None:
    it = _item("x")
    assert is_renderable(replace(it, relevance_status="out_of_scope")) is False
    assert is_renderable(replace(it, relevance_status="needs_review")) is True
    assert is_renderable(replace(it, relevance_status="out_of_scope", relevance_override="in_scope")) is True


@pytest.mark.parametrize("value, expected", [("", False), ("0", False), ("1", True), ("on", True)])
def test_public_gate_is_off_by_default(monkeypatch: pytest.MonkeyPatch, value: str, expected: bool) -> None:
    monkeypatch.setenv("CYBERALERTX_HIDE_OUT_OF_SCOPE", value)
    assert hide_out_of_scope_publicly() is expected


def test_feed_gate_hides_only_when_enabled_and_links_keep_working(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    cache = ThreatPostCache(tmp_path / "posts.json")
    keep = _item("keep")
    junk = replace(_item("junk"), relevance_status="out_of_scope", relevance_reason="game trailer")
    for it in (keep, junk):
        cache.set(it.fingerprint, "en", _post(it, "en"))
    client = TestClient(build_app(service=_Svc([keep, junk], cache), feedback_path=tmp_path / "f.jsonl",
                                  admin_guard=AdminGuard()))

    def ids() -> set[str]:
        return {p["id"] for p in client.get("/posts?language=en&cached_only=1").json()["items"]}

    monkeypatch.delenv("CYBERALERTX_HIDE_OUT_OF_SCOPE", raising=False)
    assert ids() == {keep.fingerprint, junk.fingerprint}          # default: unchanged behaviour
    monkeypatch.setenv("CYBERALERTX_HIDE_OUT_OF_SCOPE", "1")
    assert ids() == {keep.fingerprint}
    assert client.get(f"/posts/{junk.fingerprint}").status_code == 200   # direct link still works
