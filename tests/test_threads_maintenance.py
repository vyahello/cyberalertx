"""Threads maintenance fixes: no repeated paragraphs, token maintenance that is
independent of publishing, and the N-central image brief. Mocked API only."""
from __future__ import annotations

import argparse
import os
import shutil
import subprocess
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

import httpx
import pytest

from cyberalertx.threads.credentials import check_token, maintain, maintenance_lock, register
from cyberalertx.threads.envfile import read_env
from cyberalertx.threads.format import render_post
from tests.test_threads_accounts import EN_TOK, UA_TOK, Graph, settings, store

REPO = Path(__file__).resolve().parents[1]
NOW = datetime.now(timezone.utc).replace(microsecond=0)
URL = "https://cyberalertx.com/{loc}/threat/7d8a94de5f64d8dd"


# ------------------------------------------------------------------ A. repeated paragraphs

def post(loc: str, title: str, plain: str, short: str, **extra: Any) -> str:
    p = {"id": "7d8a94de5f64d8dd", "source": "The Hacker News", "threat_level": "High",
         "evidence": {"exploitation": "confirmed"}, "actionability_level": "recommended_action",
         "translations": {loc: {"title": title, "plain_summary": plain, "short_summary": short, **extra}}}
    return render_post(p, locale=loc, url=URL.format(loc=loc)).text


NCENTRAL = dict(
    title="N-able ships urgent N-central fix as attackers mine crypto on older bugs",
    plain="N-able, whose N-central tool lets IT firms manage company computers remotely, fixed 17 flaws while "
          "attackers use older ones to plant crypto miners.",
    short="N-able released N-central 2026.4 Hotfix 3, patching 17 flaws in its RMM platform, while attackers "
          "exploit earlier bugs to deploy crypto miners.")


def test_an_exact_duplicate_paragraph_appears_once() -> None:
    s = "Attackers are taking over Widget servers that have not installed the latest fix."
    text = post("en", "Widget servers taken over", s, s)
    assert text.count(s) == 1


def test_a_reworded_retelling_is_dropped_en() -> None:
    text = post("en", **NCENTRAL)
    assert NCENTRAL["plain"] in text and "Hotfix 3, patching 17 flaws" not in text
    assert text.count("17 flaws") == 1


def test_a_reworded_retelling_is_dropped_ua() -> None:
    text = post("ua", "Суперкомп'ютер Fugaku зазнав атаки, викрадено понад 4000 облікових записів",
                "Японський суперкомп'ютер Fugaku, найпотужніший у країні, зламали, і зловмисники заволоділи понад "
                "4000 облікових записів його користувачів.",
                "За даними Japan Times, зловмисники атакували Fugaku, найпотужніший суперкомп'ютер Японії, і "
                "викрали понад 4000 облікових записів.")
    assert text.count("4000") == 2                                        # headline + one paragraph, not three


@pytest.mark.parametrize("loc, title, plain, short, kept", [
    ("en", "Retadup worm is back",
     "Retadup, a worm that spreads through infected USB sticks, is active again on Windows computers.",
     "Its infrastructure was seized by French police in 2019 after it infected 850,000 machines.",
     "850,000"),
    ("ua", "Хробак Retadup повернувся",
     "Хробак Retadup, який передається через флешки, знову активний на комп'ютерах з Windows.",
     "У 2019 році французька поліція вилучила його інфраструктуру після зараження 850 000 машин.",
     "850 000"),
])
def test_similar_paragraphs_with_distinct_facts_both_remain(loc: str, title: str, plain: str, short: str,
                                                           kept: str) -> None:
    text = post(loc, title, plain, short)
    assert plain in text and kept in text


@pytest.mark.parametrize("loc, plain, short, cve", [
    ("en", "PostgreSQL released updates fixing 52 security holes, one of which lets a database user run their own "
           "programs on the server itself.",
     "PostgreSQL updates fixing 52 security flaws, including CVE-2026-6460 (CVSS 8.8), a type confusion bug "
     "letting users with object-creation rights execute code on the server.", "CVE-2026-6460"),
    ("ua", "PostgreSQL випустив оновлення, яке виправляє 52 помилки, зокрема ту, через яку користувач бази даних "
           "може запустити власну програму на сервері.",
     "PostgreSQL випустив оновлення, що виправляє 52 помилки, зокрема CVE-2026-6460: користувач бази даних може "
     "запустити код на сервері.", "CVE-2026-6460"),
])
def test_a_retelling_that_adds_a_cve_replaces_the_general_paragraph(loc: str, plain: str, short: str,
                                                                   cve: str) -> None:
    text = post(loc, "PostgreSQL update fixes 52 flaws, one letting database users run code on the server", plain, short)
    assert cve in text and plain not in text and text.count("52") == 2   # headline + one paragraph


def test_telegram_formatting_is_unchanged_by_the_threads_rule() -> None:
    from cyberalertx.publish.format import render_caption
    p = {"id": "7d8a94de5f64d8dd", "source": "The Hacker News", "threat_level": "High", "category": "exploit",
         "evidence": {"exploitation": "confirmed"},
         "translations": {"en": {"title": NCENTRAL["title"], "plain_summary": NCENTRAL["plain"],
                                 "short_summary": NCENTRAL["short"]}}}
    assert "Hotfix 3" in render_caption(p, locale="en", base_url="https://cyberalertx.com")


# ------------------------------------------------------------------ B. token maintenance

def _ready(tmp_path: Path, g: Graph) -> tuple[Any, Path]:
    s = store(tmp_path)
    register(s, check_token("en", EN_TOK, "cyberalertx", g.client()), EN_TOK, NOW)
    register(s, check_token("ua", UA_TOK, "cyberalertx_ua", g.client()), UA_TOK, NOW)
    env = tmp_path / ".env"
    env.write_text(f"THREADS_ENABLED=0\nCYBERALERTX_TELEGRAM_BOT_TOKEN=keep\nTHREADS_EN_ACCESS_TOKEN={EN_TOK}\n"
                   f"THREADS_UA_ACCESS_TOKEN={UA_TOK}\n")
    env.chmod(0o600)
    return s, env


def _maintain(tmp_path: Path, s: Any, env: Path, g: Graph) -> Any:
    return maintain(settings(publish_enabled=False), s, g.client(), NOW, env_path=env,
                    backup_dir=tmp_path / "bk", lock_path=tmp_path / "lock")


def test_refresh_runs_with_publishing_disabled_and_never_publishes(tmp_path: Path) -> None:
    g = Graph()                                     # tokens 40 days old, 20 days left: due
    s, env = _ready(tmp_path, g)
    res = {r.slot: r.outcome for r in _maintain(tmp_path, s, env, g) if r.outcome != "ok"}
    assert res == {"en": "refreshed", "ua": "refreshed"}
    vals = read_env(env)
    assert vals["THREADS_ENABLED"] == "0" and vals["CYBERALERTX_TELEGRAM_BOT_TOKEN"] == "keep"
    assert vals["THREADS_EN_ACCESS_TOKEN"] == g.refreshed[EN_TOK]
    assert not any(p.endswith(("/threads", "/threads_publish")) for p in g.calls)     # no container, no publish
    assert not (tmp_path / "publish_jobs.json").exists()


def test_accounts_refresh_independently_and_a_bad_replacement_is_not_saved(tmp_path: Path) -> None:
    g = Graph()
    s, env = _ready(tmp_path, g)
    real = g.handler

    def ua_bad(req: httpx.Request) -> httpx.Response:
        resp = real(req)
        if req.url.path == "/refresh_access_token" and req.url.params.get("access_token") == UA_TOK:
            g.users[g.refreshed[UA_TOK]] = ("17841400000000099", "intruder")       # new token, wrong account
        return resp
    g.handler = ua_bad                                                           # type: ignore[method-assign]
    res = {r.slot: r.outcome for r in _maintain(tmp_path, s, env, g) if r.outcome != "ok"}
    assert res == {"en": "refreshed", "ua": "failed"}
    vals = read_env(env)
    assert vals["THREADS_EN_ACCESS_TOKEN"] == g.refreshed[EN_TOK] and vals["THREADS_UA_ACCESS_TOKEN"] == UA_TOK
    assert s.get("ua").threads_user_id == "17841400000000002"                     # registry unchanged


def test_a_failed_refresh_keeps_the_previous_token(tmp_path: Path) -> None:
    g = Graph()
    s, env = _ready(tmp_path, g)
    g.fail["/refresh_access_token"] = httpx.Response(400, json={"error": {"message": "refresh refused", "code": 190}})
    _maintain(tmp_path, s, env, g)
    assert read_env(env)["THREADS_EN_ACCESS_TOKEN"] == EN_TOK and s.token("en") == EN_TOK


def test_repeated_runs_do_not_refresh_again(tmp_path: Path) -> None:
    g = Graph()
    s, env = _ready(tmp_path, g)
    _maintain(tmp_path, s, env, g)
    g.calls.clear()
    out = {r.slot: r.outcome for r in _maintain(tmp_path, s, env, g)}
    assert "/refresh_access_token" not in g.calls and "refreshed" not in out.values()


def test_only_one_maintenance_run_at_a_time(tmp_path: Path) -> None:
    g = Graph()
    s, env = _ready(tmp_path, g)
    with maintenance_lock(tmp_path / "lock") as held:
        assert held and _maintain(tmp_path, s, env, g) is None
    assert "/refresh_access_token" not in g.calls


def test_maintain_command_ignores_the_switch_and_leaves_telegram_alone(tmp_path: Path,
                                                                     monkeypatch: pytest.MonkeyPatch,
                                                                     capsys: pytest.CaptureFixture[str]) -> None:
    import cyberalertx.threads.accounts as acc_mod
    from cyberalertx.tools import threads as tool
    g = Graph()
    s, env = _ready(tmp_path, g)
    ledger = tmp_path / "telegram_published.jsonl"
    ledger.write_text('{"fingerprint": "x"}\n')
    before = ledger.read_bytes()
    monkeypatch.setattr(acc_mod, "ACCOUNTS_PATH", tmp_path / "threads_accounts.json")
    monkeypatch.setattr(tool, "_env_file", lambda: env)
    monkeypatch.setattr(tool, "_backups", lambda: tmp_path / "bk")
    monkeypatch.setattr(tool, "_lock_path", lambda: tmp_path / "lock")
    for k, v in {"THREADS_ENABLED": "0", "THREADS_EN_ACCESS_TOKEN": EN_TOK, "THREADS_UA_ACCESS_TOKEN": UA_TOK,
                 "THREADS_EN_USERNAME": "cyberalertx", "THREADS_UA_USERNAME": "cyberalertx_ua"}.items():
        monkeypatch.setenv(k, v)
    assert tool.cmd_maintain(argparse.Namespace(), client=g.client()) == 0
    out = capsys.readouterr()
    assert "en: refreshed" in out.out and EN_TOK not in out.out + out.err
    assert ledger.read_bytes() == before and read_env(env)["THREADS_ENABLED"] == "0"


def test_units_run_as_cax_from_current_and_never_publish() -> None:
    svc = (REPO / "server/systemd/cyberalertx-threads-tokens.service").read_text()
    assert "User=cax" in svc and "EnvironmentFile=/home/cax/cax/.env" in svc
    assert "ExecStart=/home/cax/cyberalertx/current/venv/bin/python -m cyberalertx.tools.threads maintain" in svc
    assert "tools.publish" not in svc and "threads_publish" not in svc
    timer = (REPO / "server/systemd/cyberalertx-threads-tokens.timer").read_text()
    assert "Persistent=true" in timer and "Unit=cyberalertx-threads-tokens.service" in timer


@pytest.mark.skipif(shutil.which("bash") is None, reason="needs bash")
def test_installer_backs_up_installs_and_uninstalls(tmp_path: Path) -> None:
    units, cur, bk = tmp_path / "units", tmp_path / "current", tmp_path / "backups"
    for d in (units, cur / "server" / "systemd", cur / "cyberalertx" / "tools", bk):
        d.mkdir(parents=True)
    for u in ("cyberalertx-threads-tokens.service", "cyberalertx-threads-tokens.timer"):
        shutil.copy(REPO / "server/systemd" / u, cur / "server/systemd" / u)
    shutil.copy(REPO / "cyberalertx/tools/threads.py", cur / "cyberalertx/tools/threads.py")
    log = tmp_path / "calls.log"
    sysctl = tmp_path / "systemctl"
    sysctl.write_text(f"#!/bin/bash\necho \"$*\" >> {log}\nexit 0\n")
    sysctl.chmod(0o755)
    env = {"PATH": os.environ.get("PATH", "/usr/bin:/bin"), "TT_TEST": "1", "TT_SYSTEMCTL": str(sysctl),
           "TT_UNIT_DIR": str(units), "TT_CURRENT": str(cur), "TT_BACKUPS": str(bk)}
    script = REPO / "ops/release/threads_tokens_timer.sh"
    r = subprocess.run(["bash", str(script), "install"], env=env, capture_output=True, text=True, timeout=60)
    assert r.returncode == 0, r.stdout + r.stderr
    assert (units / "cyberalertx-threads-tokens.timer").exists()
    calls = log.read_text()
    assert "enable --now cyberalertx-threads-tokens.timer" in calls and "start cyberalertx-threads-tokens.service" in calls
    assert "telegram" not in calls
    r = subprocess.run(["bash", str(script), "uninstall"], env=env, capture_output=True, text=True, timeout=60)
    assert r.returncode == 0 and not (units / "cyberalertx-threads-tokens.timer").exists()


# ------------------------------------------------------------------ C. N-central image brief

def _brief(title: str, excerpt: str, category: str = "exploit") -> Any:
    from types import SimpleNamespace
    from cyberalertx.media.illustrations import visual_brief
    from cyberalertx.models import NewsItem
    item = NewsItem(title=title, source="The Hacker News", url="https://e.test/n", published_at=NOW,
                    raw_content=excerpt, category=category)
    story = SimpleNamespace(key="s:ncentral", anchor=item, members=[item])
    return visual_brief(story)


def test_the_ncentral_story_shows_remote_management_not_a_wallet() -> None:
    brief, alt, _ = _brief(
        "N-able Patches 17 N-central Flaws as Attackers Exploit Earlier Bugs to Deploy Crypto Miners",
        "N-able has released a new security update to address additional critical security flaws impacting "
        "N-central, its Remote Monitoring and Management (RMM) platform.")
    assert brief.scene == "corporate" and "wallet" not in brief.scenes
    assert "cryptocurrency" not in alt["en"]


@pytest.mark.parametrize("title", ["Hackers drain $40 million from a crypto platform", "Crypto wallet app leaks keys"])
def test_real_crypto_stories_keep_the_wallet(title: str) -> None:
    brief, _, _ = _brief(title, title, category="breach")
    assert brief.scene == "wallet"
