"""O27: the dual-write post cache must not query Postgres per item.

Before the fix every JSON miss in `DualWriteThreatPostCache.get` cost one
Postgres round-trip, and a feed render calls `get` several times per item,
so a 40-post feed in dual mode spent seconds on sequential misses. These
tests pin the new contract with an in-memory PG fake that counts calls:

  * JSON hit                      -> no PG call
  * miss for a key PG lacks       -> no PG call after the one index load
  * key only PG has               -> served from one batch query
  * own writes / deletes          -> visible at once, no resurrection
  * peer rows written only to PG  -> visible after the next index refresh
  * unreadable JSON               -> fail closed (O28), no PG call
  * index load failure            -> miss, backoff, no hammering
"""
from __future__ import annotations

import threading
from dataclasses import dataclass, field
from pathlib import Path
from typing import Iterable, Optional

from cyberalertx.ai.cache import ThreatPostCache
from cyberalertx.ai.models import ThreatPost
from cyberalertx.storage.dual_write import DualWriteThreatPostCache


def _post(title: str = "t") -> ThreatPost:
    return ThreatPost(
        title=title, short_summary="s", threat_level="Low",
        why_it_matters="w", affected_users=["a"], what_to_do=["b"],
        generated_by="anthropic", language="en",
    )


@dataclass
class _CountingPg:
    posts: dict[tuple[str, str], ThreatPost] = field(default_factory=dict)
    calls: list[str] = field(default_factory=list)
    fail_keys: bool = False

    def keys(self) -> set[tuple[str, str]]:
        self.calls.append("keys")
        if self.fail_keys:
            raise RuntimeError("simulated PG outage")
        return set(self.posts)

    def get_many(self, keys: Iterable[tuple[str, str]]) -> dict[tuple[str, str], ThreatPost]:
        wanted = list(keys)
        self.calls.append(f"get_many:{len(wanted)}")
        return {k: self.posts[k] for k in wanted if k in self.posts}

    def get(self, fingerprint: str, locale: str = "en") -> Optional[ThreatPost]:
        self.calls.append(f"get:{fingerprint}/{locale}")
        return self.posts.get((fingerprint, locale))

    def set(self, fingerprint: str, locale: str, post: ThreatPost) -> None:
        self.calls.append(f"set:{fingerprint}/{locale}")
        self.posts[(fingerprint, locale)] = post

    def delete(self, fingerprint: str, locale: str) -> bool:
        self.calls.append(f"delete:{fingerprint}/{locale}")
        return self.posts.pop((fingerprint, locale), None) is not None

    def all(self) -> Iterable[ThreatPost]:
        return iter(self.posts.values())

    def __len__(self) -> int:
        return len(self.posts)

    def reads(self) -> list[str]:
        return [c for c in self.calls if not c.startswith(("set:", "delete:"))]


def _dual(tmp_path: Path, pg: _CountingPg, ttl: float = 3600.0) -> tuple[ThreatPostCache, DualWriteThreatPostCache]:
    json_cache = ThreatPostCache(tmp_path / "threat_posts.json")
    return json_cache, DualWriteThreatPostCache(json_cache, pg, index_ttl=ttl)


def test_json_hit_never_touches_pg(tmp_path: Path) -> None:
    pg = _CountingPg()
    json_cache, dual = _dual(tmp_path, pg)
    json_cache.set("fp", "en", _post("json"))
    for _ in range(50):
        assert dual.get("fp", "en").title == "json"  # type: ignore[union-attr]
    assert pg.calls == []


def test_misses_cost_one_index_load_not_one_query_each(tmp_path: Path) -> None:
    pg = _CountingPg(posts={("other", "en"): _post()})
    json_cache, dual = _dual(tmp_path, pg)
    json_cache.set("other", "en", _post("json"))
    for i in range(200):                       # 200 misses, both locales
        assert dual.get(f"missing{i}", "ua" if i % 2 else "en") is None
    assert pg.reads() == ["keys"]              # PG-only set is empty: no batch query either


def test_pg_only_keys_come_from_one_batch_query(tmp_path: Path) -> None:
    pg = _CountingPg(posts={(f"fp{i}", "ua"): _post(f"pg{i}") for i in range(40)})
    _, dual = _dual(tmp_path, pg)
    for _ in range(3):                         # a feed asks several times per item
        for i in range(40):
            assert dual.get(f"fp{i}", "ua").title == f"pg{i}"  # type: ignore[union-attr]
    assert pg.reads() == ["keys", "get_many:40"]


def test_json_wins_over_pg_for_the_same_key(tmp_path: Path) -> None:
    pg = _CountingPg(posts={("fp", "en"): _post("stale-pg")})
    json_cache, dual = _dual(tmp_path, pg)
    json_cache.set("fp", "en", _post("json"))
    assert dual.get("fp", "en").title == "json"  # type: ignore[union-attr]
    assert pg.reads() == []


def test_write_then_read_and_delete_without_resurrection(tmp_path: Path) -> None:
    pg = _CountingPg()
    _, dual = _dual(tmp_path, pg)
    assert dual.get("new", "en") is None       # loads the (empty) index
    dual.set("new", "en", _post("fresh"))
    assert dual.get("new", "en").title == "fresh"  # type: ignore[union-attr]
    dual.set_strict("new", "en", _post("decided"))
    assert dual.get("new", "en").title == "decided"  # type: ignore[union-attr]
    assert dual.delete("new", "en") is True
    assert dual.get("new", "en") is None       # gone from both, not resurrected
    assert ("new", "en") not in pg.posts
    assert pg.reads() == ["keys"]


def test_deleted_pg_only_key_is_not_served_from_the_batch(tmp_path: Path) -> None:
    pg = _CountingPg(posts={("fp", "ua"): _post("pg")})
    _, dual = _dual(tmp_path, pg)
    assert dual.get("fp", "ua").title == "pg"  # type: ignore[union-attr]
    dual.delete("fp", "ua")
    assert dual.get("fp", "ua") is None


def test_peer_pg_rows_appear_after_refresh(tmp_path: Path) -> None:
    pg = _CountingPg()
    _, dual = _dual(tmp_path, pg)
    assert dual.get("peer", "en") is None
    pg.posts[("peer", "en")] = _post("peer")   # another process wrote only PG
    assert dual.get("peer", "en") is None      # within the TTL: not yet indexed
    assert dual.refresh_index()                # what a TTL expiry does, synchronously
    assert dual.get("peer", "en").title == "peer"  # type: ignore[union-attr]
    assert pg.reads() == ["keys", "keys", "get_many:1"]


def test_expired_index_reloads_in_the_background(tmp_path: Path) -> None:
    pg = _CountingPg()
    _, dual = _dual(tmp_path, pg, ttl=0.0)
    assert dual.get("a", "en") is None         # first load (the read waits for it)
    pg.posts[("a", "en")] = _post("peer")
    dual.get("a", "en")                        # expired: starts a reload, answers from the old index
    assert dual._load_done.wait(5)
    assert dual.get("a", "en").title == "peer"  # type: ignore[union-attr]


def test_unreadable_json_fails_closed_without_pg(tmp_path: Path) -> None:
    path = tmp_path / "threat_posts.json"
    path.write_text("{not json", encoding="utf-8")
    pg = _CountingPg(posts={("fp", "en"): _post("old-decision")})
    dual = DualWriteThreatPostCache(ThreatPostCache(path), pg, index_ttl=3600)
    assert dual.get("fp", "en") is None
    assert pg.calls == []


def test_index_failure_is_a_miss_with_backoff(tmp_path: Path) -> None:
    pg = _CountingPg(posts={("fp", "en"): _post()}, fail_keys=True)
    _, dual = _dual(tmp_path, pg)
    for _ in range(20):
        assert dual.get("fp", "en") is None
    assert pg.reads() == ["keys"]              # retried after the backoff, not per read
    assert dual.index_stats["failures"] == 1
    pg.fail_keys = False
    assert dual.refresh_index()
    assert dual.get("fp", "en") is not None


def test_failed_refresh_keeps_the_previous_index(tmp_path: Path) -> None:
    pg = _CountingPg(posts={("fp", "en"): _post("pg")})
    _, dual = _dual(tmp_path, pg)
    assert dual.get("fp", "en") is not None
    pg.fail_keys = True
    assert dual.refresh_index() is False
    assert dual.get("fp", "en").title == "pg"  # type: ignore[union-attr]


def test_concurrent_readers_load_the_index_once(tmp_path: Path) -> None:
    pg = _CountingPg(posts={(f"fp{i}", "en"): _post(f"pg{i}") for i in range(10)})
    _, dual = _dual(tmp_path, pg)
    errors: list[str] = []

    def reader() -> None:
        for i in range(100):
            got = dual.get(f"fp{i % 20}", "en")
            want = f"pg{i % 20}" if i % 20 < 10 else None
            if (got.title if got else None) != want:
                errors.append(f"{i}: {got}")

    threads = [threading.Thread(target=reader) for _ in range(8)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    assert errors == []
    assert pg.reads() == ["keys", "get_many:10"]


def test_restart_rebuilds_the_index(tmp_path: Path) -> None:
    pg = _CountingPg(posts={("fp", "ua"): _post("pg")})
    _, first = _dual(tmp_path, pg)
    first.set("own", "ua", _post("own"))
    _, second = _dual(tmp_path, pg)            # new process, same files and PG
    assert second.get("own", "ua").title == "own"  # type: ignore[union-attr]
    assert second.get("fp", "ua").title == "pg"  # type: ignore[union-attr]
    assert second.get("nope", "ua") is None


def test_json_cache_keys_round_trip(tmp_path: Path) -> None:
    cache = ThreatPostCache(tmp_path / "threat_posts.json")
    cache.set("ab12", "en", _post())
    cache.set("ab12", "ua", _post())
    assert ThreatPostCache(tmp_path / "threat_posts.json").keys() == {("ab12", "en"), ("ab12", "ua")}


def test_warm_up_loads_the_index_before_the_first_request(tmp_path: Path) -> None:
    pg = _CountingPg(posts={("fp", "en"): _post("pg")})
    _, dual = _dual(tmp_path, pg)
    dual.warm_index_async()
    assert dual._load_done.wait(5)
    assert pg.reads() == ["keys", "get_many:1"]
    assert dual.get("fp", "en").title == "pg"  # type: ignore[union-attr]
    assert dual.get("nope", "en") is None
    assert pg.reads() == ["keys", "get_many:1"]   # the request paid nothing


class _SlowPg(_CountingPg):
    """keys() blocks until released: a slow or hanging database."""
    def __init__(self, **kw: object) -> None:
        super().__init__(**kw)  # type: ignore[arg-type]
        self.release = threading.Event()

    def keys(self) -> set[tuple[str, str]]:
        snapshot = set(self.posts)
        self.release.wait(10)
        self.calls.append("keys")
        return snapshot


def test_a_hanging_database_never_stalls_reads_or_writes(tmp_path: Path) -> None:
    import time
    pg = _SlowPg()
    _, dual = _dual(tmp_path, pg)
    dual._first_load_wait = 0.2
    t0 = time.monotonic()
    assert dual.get("x", "en") is None          # waits at most the first-load bound
    dual.set("new", "en", _post("w"))           # writers never wait for the load
    assert dual.get("new", "en").title == "w"   # type: ignore[union-attr]
    assert time.monotonic() - t0 < 2.0
    pg.release.set()
    assert dual._load_done.wait(5)


def test_a_delete_during_a_load_is_not_undone_by_the_snapshot(tmp_path: Path) -> None:
    pg = _SlowPg(posts={("old", "ua"): _post("stale")})
    _, dual = _dual(tmp_path, pg)
    dual._first_load_wait = 0.1
    dual.get("x", "ua")                          # load starts; snapshot already holds ("old","ua")
    dual.delete("old", "ua")                     # deleted from both stores meanwhile
    pg.release.set()
    assert dual._load_done.wait(5)
    assert dual.get("old", "ua") is None         # not resurrected from the stale snapshot
