"""V4.1 migration: the canonical image of an article (identity first, then the
newest generation), the stale-claim release, the fail-safe regeneration and
the single edition-backfill path (`ops/media/edition_stories.py` ->
`backfill --only-file`)."""
from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any

import pytest

from cyberalertx.intel.story import StoryView
from cyberalertx.media import edition
from cyberalertx.media import engine
from cyberalertx.media.assets import MediaAsset, MediaStore
from tests.test_media import NOW, critical_story, fake_intel, item, tpost


def _asset(store: MediaStore, story: str, model: str, members: list[str], *, status: str = "validated",
           updated: str = "2026-11-19T09:00:00+00:00", key: str = "") -> None:
    a = MediaAsset(asset_id=f"illus:{story}", story_key=story, asset_type="editorial_illustration",
                   members=list(members), status=status, generation_model=model, generation_method="svg",
                   storage_key=key or f"{abs(hash(story)) % 10**16:016d}{'0' * 48}.svg",
                   alt_text={"en": f"Illustration {story}", "ua": f"Ілюстрація {story}"})
    store.put(a)
    raw = json.loads(store.index.read_text())
    raw[a.asset_id]["updated_at"] = updated
    store.index.write_text(json.dumps(raw))


# ---------------------------------------------------------------- image selection

def test_only_an_image_that_lists_the_article_qualifies(tmp_path: Path) -> None:
    store = MediaStore(tmp_path)
    _asset(store, "s:other", "cax-editorial-4", ["fp-other"], updated="2026-11-20T09:00:00+00:00")
    _asset(store, "s:mine", "cax-svg-3", ["fp1"])
    assert store.illustration_for_member("fp1").story_key == "s:mine"            # type: ignore[union-attr]
    assert store.illustration_for_member("fp-unknown") is None


def test_multiple_generations_the_newest_generation_wins(tmp_path: Path) -> None:
    store = MediaStore(tmp_path)
    _asset(store, "s:v2", "cax-svg-2", ["fp1"], updated="2026-11-20T12:00:00+00:00")
    _asset(store, "s:v3", "cax-svg-3", ["fp1"], updated="2026-11-20T11:00:00+00:00")
    _asset(store, "s:v4", "cax-editorial-4", ["fp1"], updated="2026-11-18T09:00:00+00:00")
    assert store.illustration_for_member("fp1").story_key == "s:v4"              # type: ignore[union-attr]


@pytest.mark.parametrize("status", ["failed", "generating", "pending"])
def test_an_unsuccessful_generation_is_never_selected(tmp_path: Path, status: str) -> None:
    store = MediaStore(tmp_path)
    _asset(store, "s:v3", "cax-svg-3", ["fp1"])
    _asset(store, "s:v4", "cax-editorial-4", ["fp1"], status=status, updated="2026-11-20T12:00:00+00:00")
    assert store.illustration_for_member("fp1").story_key == "s:v3"              # type: ignore[union-attr]


def test_timestamp_ties_are_broken_deterministically(tmp_path: Path) -> None:
    for order in (("s:a", "s:b"), ("s:b", "s:a")):
        store = MediaStore(tmp_path / "-".join(order))
        for story in order:
            _asset(store, story, "cax-editorial-4", ["fp1"], updated="2026-11-20T09:00:00+00:00")
        assert store.illustration_for_member("fp1").story_key == "s:b"           # type: ignore[union-attr]


def _vcenter(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> tuple[MediaStore, Any, Any]:
    """The production case (20 Nov): article 63edce0941e0edb0 still carries its old
    story key s:f263d148b6443a (a V3 image), while the intel engine now places it
    in the vCenter story s:882fdf3bc4a4b0, whose image is V4.1."""
    old = item("VMware vCenter flaw exploited", "BleepingComputer")
    vc = item("China-Linked Hackers Exploit Critical VMware vCenter Zero-Day", "The Hacker News")
    old.story_key = "s:f263d148b6443a"
    vc.story_key = "s:882fdf3bc4a4b0"
    live = StoryView(key="s:882fdf3bc4a4b0", anchor=vc, members=[vc, old], independent_sources=["thn"],
                     sheets=[], posts={"en": tpost()})
    store = MediaStore(tmp_path / "media")
    _asset(store, "s:f263d148b6443a", "cax-svg-3", [old.fingerprint], updated="2026-11-20T10:00:00+00:00")
    _asset(store, "s:882fdf3bc4a4b0", "cax-editorial-4", [vc.fingerprint, old.fingerprint],
           updated="2026-11-20T08:34:00+00:00")
    fake_intel(monkeypatch, [live])
    return store, old, vc


def test_a_stale_story_id_never_pins_an_article_to_its_old_image(tmp_path: Path,
                                                                  monkeypatch: pytest.MonkeyPatch) -> None:
    store, old, vc = _vcenter(tmp_path, monkeypatch)
    res = engine.run([vc, old], store=store, now=NOW, dry_run=False, max_calls=0)
    assert {"asset": "illus:s:f263d148b6443a", "article": old.fingerprint, "now": "s:882fdf3bc4a4b0"} in res.released
    stale = store.get("illus:s:f263d148b6443a")
    assert stale is not None and old.fingerprint not in stale.members and stale.storage_key   # file and URL kept
    # both edition slots of the article (EN and UA read the same block) resolve to the live V4.1 image
    for _ in ("en", "ua"):
        block = engine.illustration_payload(store, old.fingerprint)
        assert block is not None and block["asset_id"] == store.get("illus:s:882fdf3bc4a4b0").storage_key[:16]  # type: ignore[union-attr]
        assert block["alt"]["en"] and block["alt"]["ua"]


def test_a_stale_claim_stays_until_the_current_story_has_an_image(tmp_path: Path,
                                                                  monkeypatch: pytest.MonkeyPatch) -> None:
    store, old, vc = _vcenter(tmp_path, monkeypatch)
    raw = json.loads(store.index.read_text())
    raw["illus:s:882fdf3bc4a4b0"]["status"] = "failed"            # the live story has no valid image yet
    store.index.write_text(json.dumps(raw))
    res = engine.run([vc, old], store=store, now=NOW, max_calls=0)
    assert res.released == []
    assert store.illustration_for_member(old.fingerprint).story_key == "s:f263d148b6443a"  # type: ignore[union-attr]


def test_a_scoped_run_releases_only_the_selected_stories_articles(tmp_path: Path,
                                                                  monkeypatch: pytest.MonkeyPatch) -> None:
    store, old, vc = _vcenter(tmp_path, monkeypatch)
    res = engine.run([vc, old], store=store, now=NOW, max_calls=0, only=frozenset({"s:someone-else"}))
    assert res.released == [] and old.fingerprint in store.get("illus:s:f263d148b6443a").members  # type: ignore[union-attr]


# ---------------------------------------------------------------- failing safely

def test_a_failed_v41_regeneration_keeps_the_previous_image_and_reports_the_articles(
        tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    s = critical_story("s:crit")
    fake_intel(monkeypatch, [s])
    store = MediaStore(tmp_path / "media")
    monkeypatch.setenv("CYBERALERTX_ILLUSTRATION_RENDERER", "svg-3")
    engine.run([s.anchor], store=store, now=NOW)
    before = store.get("illus:s:crit")
    assert before is not None and before.generation_model == "cax-svg-3"

    from cyberalertx.media import renderer

    def broken(plan: Any) -> bytes:
        if plan.renderer == renderer.V4:
            raise RuntimeError("scene crashed")
        raise AssertionError("V3 must never be used as a fallback")
    monkeypatch.setattr(engine, "render_plan", broken)
    monkeypatch.delenv("CYBERALERTX_ILLUSTRATION_RENDERER", raising=False)
    for attempt in (1, 2, 3):
        res = engine.run([s.anchor], store=store, now=NOW, upgrade_renderer=True)
        f = res.failed[0]
        assert f["story_key"] == "s:crit" and f["articles"] == [s.anchor.fingerprint] and f["kept_previous_image"]
        assert f["renderer"] == "cax-editorial-4" and f["attempt"] == attempt
        kept = store.get("illus:s:crit")
        assert kept is not None and kept.status == "validated" and kept.storage_key == before.storage_key
        assert kept.generation_model == "cax-svg-3" and "regeneration failed" in kept.last_error
        assert engine.illustration_payload(store, s.anchor.fingerprint) is not None   # the site keeps an image
    res = engine.run([s.anchor], store=store, now=NOW, upgrade_renderer=True)
    assert res.failed == [] and "retry limit" in res.skipped[0]["reason"]          # bounded, not every hour


# ---------------------------------------------------------------- the edition backfill (one path)

def test_the_edition_resolver_maps_articles_to_their_current_story_not_the_stored_key() -> None:
    from types import SimpleNamespace
    a = SimpleNamespace(fingerprint="fp-a")
    b = SimpleNamespace(fingerprint="fp-b")
    stories = [SimpleNamespace(key="s:live", members=[a, b])]
    keys, orphans = edition.story_keys(["fp-b", "fp-a", "fp-x"], stories)
    assert keys == ["s:live"] and orphans == ["fp-x"]


def test_the_edition_is_read_the_way_the_homepage_reads_it(monkeypatch: pytest.MonkeyPatch) -> None:
    import httpx
    calls: list[dict[str, Any]] = []

    class R:
        def __init__(self, loc: str) -> None:
            self.loc = loc

        def raise_for_status(self) -> None:
            return None

        def json(self) -> dict[str, Any]:
            other = "ua" if self.loc == "en" else "en"
            return {"items": [{"id": "shared", "available_locales": ["en", "ua"]},
                              {"id": f"only-{other}", "available_locales": [other]},
                              *({"id": f"{self.loc}{n}", "available_locales": [self.loc]} for n in range(50))]}

    def get(url: str, params: dict[str, Any], timeout: float) -> R:
        calls.append(params)
        return R(params["language"])
    monkeypatch.setattr(httpx, "get", get)
    fps = edition.visible_fingerprints("http://api", size=3)
    assert fps == ["shared", "en0", "en1", "ua0", "ua1"]                          # per-locale filter, no repeats
    assert all(c["limit"] == 120 and c["cached_only"] == 1 for c in calls)


def test_backfill_only_file_scope_keeps_everything_else_and_every_old_url(tmp_path: Path,
                                                                           monkeypatch: pytest.MonkeyPatch) -> None:
    stories = [critical_story("s:one"), critical_story("s:two", products=("Gadget Hub",)),
               critical_story("s:three", products=("Edge Box",))]
    fake_intel(monkeypatch, stories)

    class Editions:                     # every story has an edition headline: the engine records cards
        def get(self, fp: str, loc: str) -> Any:
            from types import SimpleNamespace
            return SimpleNamespace(title=f"Headline {fp} {loc}", threat_level="High")

    store = MediaStore(tmp_path / "media")
    monkeypatch.setenv("CYBERALERTX_ILLUSTRATION_RENDERER", "svg-3")
    engine.run([s.anchor for s in stories], store=store, posts=Editions(), now=NOW)
    before = {a.asset_id: a.to_dict() for a in store.all() if a.asset_type == "editorial_illustration"}
    before_all = {a.asset_id: a.to_dict() for a in store.all()}
    monkeypatch.delenv("CYBERALERTX_ILLUSTRATION_RENDERER", raising=False)

    from cyberalertx.tools import media as M
    monkeypatch.setattr(M, "JsonNewsStore", lambda path: type("J", (), {"all": lambda self: [s.anchor for s in stories]})())
    monkeypatch.setattr(M, "_stores", lambda: (None, Editions()))
    writes: list[list[str]] = []
    real_put_many = MediaStore.put_many

    def spy(self: MediaStore, assets: Any) -> Any:
        assets = list(assets)
        writes.append([a.asset_id for a in assets])
        return real_put_many(self, assets)
    monkeypatch.setattr(MediaStore, "put_many", spy)
    f = tmp_path / "edition.txt"
    f.write_text("# cax-svg-3 | Widget\ns:two\n", encoding="utf-8")
    rc = M.cmd_backfill(argparse.Namespace(store=str(store.root), only_file=str(f), dry_run=False, batch=10))
    assert rc == 0
    assert not any(k.startswith("card:") for w in writes for k in w)          # no card record rewritten
    after = {a.asset_id: a for a in store.all() if a.asset_type == "editorial_illustration"}
    assert after["illus:s:two"].generation_model == "cax-editorial-4"
    assert before["illus:s:two"]["storage_key"] in after["illus:s:two"].previous_storage_keys   # old URL kept
    assert store.open_file(before["illus:s:two"]["storage_key"][:16]) is not None              # and still served
    for k in ("illus:s:one", "illus:s:three"):                                                 # untouched
        assert after[k].to_dict() == before[k]
    cards_before = {k: v for k, v in before_all.items() if k.startswith("card:")}
    assert cards_before and {a.asset_id: a.to_dict() for a in store.all()
                             if a.asset_id.startswith("card:")} == cards_before                # cards too
    f.write_text("# nothing\n", encoding="utf-8")
    assert M.cmd_backfill(argparse.Namespace(store=str(store.root), only_file=str(f), dry_run=False, batch=10)) == 2
