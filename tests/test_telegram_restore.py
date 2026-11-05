"""Telegram restoration tooling: read-only Bot API check, activation baseline,
and ops/release/telegram_activate.sh (mocked; never touches the host)."""
from __future__ import annotations

import argparse
import json
import os
import shutil
import subprocess
from datetime import timedelta
from pathlib import Path

import httpx
import pytest

from cyberalertx.publish.config import TelegramSettings
from cyberalertx.publish.jobs import JobStore
from cyberalertx.tools import publish as tool
from tests.test_publication import NOW, dests, item, settings, source_for

REPO = Path(__file__).resolve().parents[1]
TOKEN = "123456:SECRET-TOKEN"


def _bot(member_status: str = "administrator", can_post: bool = True) -> httpx.Client:
    def handler(req: httpx.Request) -> httpx.Response:
        m = req.url.path.rsplit("/", 1)[-1]
        if m == "getMe":
            return httpx.Response(200, json={"ok": True, "result": {"id": 42, "is_bot": True, "username": "cax_bot"}})
        if m == "getChat":
            return httpx.Response(200, json={"ok": True, "result": {"type": "channel", "title": "CyberAlertX"}})
        if m == "getChatMember":
            return httpx.Response(200, json={"ok": True, "result": {"status": member_status,
                                                                   "can_post_messages": can_post}})
        return httpx.Response(404, json={"ok": False, "description": "Not Found"})
    return httpx.Client(transport=httpx.MockTransport(handler))


def _settings() -> TelegramSettings:
    return TelegramSettings(bot_token=TOKEN, channels={"en": "@c_en", "ua": "@c_ua"})


def test_check_passes_for_an_admin_bot_and_sends_nothing() -> None:
    res = tool.check_telegram(_settings(), client=_bot())
    assert res["ok"] and res["bot"]["username"] == "cax_bot"
    assert all(c["ok"] and c["can_post_messages"] for c in res["channels"].values())
    assert TOKEN not in json.dumps(res) and "@c_en" not in json.dumps(res)


def test_check_fails_when_the_bot_cannot_post() -> None:
    res = tool.check_telegram(_settings(), client=_bot(member_status="member", can_post=False))
    assert not res["ok"] and not res["channels"]["en"]["ok"]


def test_check_never_leaks_the_token_in_errors() -> None:
    def handler(req: httpx.Request) -> httpx.Response:
        return httpx.Response(401, json={"ok": False, "description": f"Unauthorized {TOKEN}"})
    res = tool.check_telegram(_settings(), client=httpx.Client(transport=httpx.MockTransport(handler)))
    assert not res["ok"] and TOKEN not in json.dumps(res)


def test_baseline_cancels_the_backlog_and_keeps_new_stories(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    old, new = item(1, hours_ago=20), item(2, hours_ago=0.2)
    src = source_for(old, new)
    s = settings()
    from tests.test_publication import Bot
    destinations = dests(tmp_path, Bot(), s)
    monkeypatch.setattr(tool, "_now", lambda: NOW)
    monkeypatch.setattr(tool, "_source", lambda: src)
    monkeypatch.setattr(tool, "_destinations", lambda _s: destinations)
    monkeypatch.setattr(tool, "_ledger_has", lambda: (lambda fp, loc: False))
    monkeypatch.setattr(tool, "build_telegram_settings", lambda: s)
    import cyberalertx.publish.orchestrator as orch
    from tests.test_publication import view
    real_plan = orch.plan
    monkeypatch.setattr(orch, "plan", lambda *a, **k: real_plan(*a, **{**k, "view": view(old, new)}))
    jobs = tmp_path / "jobs.json"
    cutoff = (NOW - timedelta(hours=1)).isoformat()
    args = argparse.Namespace(before=cutoff, dry_run=False, jobs=str(jobs), show=10)
    assert tool.cmd_baseline(args) == 0
    by_id = {j.job_id: j for j in JobStore(jobs).all()}
    tg = {k: v for k, v in by_id.items() if ":telegram:" in k}
    assert tg and all(j.status == "cancelled" for k, j in tg.items() if k.startswith("s:0001"))
    assert all(j.status == "scheduled" for k, j in tg.items() if k.startswith("s:0002"))
    assert all(j.status == "scheduled" for k, j in by_id.items() if ":website:" in k)     # website untouched
    assert tool.cmd_baseline(args) == 0                                                    # idempotent
    assert {j.job_id: j.status for j in JobStore(jobs).all()} == {k: j.status for k, j in by_id.items()}


# ----------------------------------------------------------------- activation script

pytestmark_bash = pytest.mark.skipif(shutil.which("bash") is None, reason="needs bash")


def _host(tmp_path: Path, check_ok: bool = True) -> dict[str, str]:
    units, cur, data, bk = tmp_path / "units", tmp_path / "current", tmp_path / "data", tmp_path / "backups"
    for d in (units / "cyberalertx-telegram.service.d", cur / "ops" / "release", cur / "server" / "systemd" / "cyberalertx-telegram.service.d",
              cur / "cyberalertx" / "tools", data, bk):
        d.mkdir(parents=True, exist_ok=True)
    for f in ("cyberalertx-telegram.service", "cyberalertx-generate.service"):
        shutil.copy(REPO / "server" / "systemd" / f, cur / "server" / "systemd" / f)
        (units / f).write_text("[Service]\nExecStart=/old/python -m cyberalertx.main publish-telegram --limit 1\n")
    (units / "cyberalertx-telegram.timer").write_text("[Timer]\n")
    hold = REPO / "server" / "systemd" / "cyberalertx-telegram.service.d" / "stage-c-hold.conf"
    shutil.copy(hold, cur / "server" / "systemd" / "cyberalertx-telegram.service.d" / "stage-c-hold.conf")
    shutil.copy(hold, units / "cyberalertx-telegram.service.d" / "stage-c-hold.conf")
    shutil.copy(REPO / "ops" / "release" / "loadenv.sh", cur / "ops" / "release" / "loadenv.sh")
    shutil.copy(REPO / "cyberalertx" / "tools" / "publish.py", cur / "cyberalertx" / "tools" / "publish.py")
    (data / "telegram_published.jsonl").write_text('{"fingerprint": "x"}\n')
    log = tmp_path / "calls.log"
    sysctl = tmp_path / "systemctl"
    sysctl.write_text(f"""#!/bin/bash
echo "systemctl $*" >> {log}
case "$1" in
  show) case "$*" in *WorkingDirectory*) echo {cur};; *DropInPaths*) ls {units}/cyberalertx-telegram.service.d/*.conf | tr '\\n' ' ';; esac;;
  cat) cat {units}/cyberalertx-telegram.service {units}/cyberalertx-telegram.service.d/*.conf;;
  is-active) [ -f {tmp_path}/timer_on ] && echo active || echo inactive;;
  is-enabled) [ -f {tmp_path}/timer_on ] && echo enabled || echo disabled;;
  enable) touch {tmp_path}/timer_on;;
  disable) rm -f {tmp_path}/timer_on;;
esac
""")
    sysctl.chmod(0o755)
    runner = tmp_path / "runas"
    runner.write_text(f"""#!/bin/bash
echo "app $*" >> {log}
case "$*" in *check-telegram*) exit {0 if check_ok else 1};; esac
exit 0
""")
    runner.chmod(0o755)
    return {"PATH": os.environ.get("PATH", "/usr/bin:/bin"), "TA_TEST": "1", "TA_SYSTEMCTL": str(sysctl),
            "TA_UNIT_DIR": str(units), "TA_CURRENT": str(cur), "TA_BACKUPS": str(bk),
            "TA_MARKER": str(tmp_path / "STAGE_D_AUTHORIZED"), "TA_DATA": str(data), "TA_RUN_AS": str(runner),
            "LOG": str(log), "TMP": str(tmp_path)}


def _ta(env: dict[str, str], mode: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(["bash", str(REPO / "ops" / "release" / "telegram_activate.sh"), mode], env=env,
                          capture_output=True, text=True, timeout=60)


@pytestmark_bash
def test_activate_installs_baselines_marks_and_enables(tmp_path: Path) -> None:
    env = _host(tmp_path)
    r = _ta(env, "activate")
    assert r.returncode == 0, r.stdout + r.stderr
    assert "TELEGRAM ACTIVATED" in r.stdout and Path(env["TA_MARKER"]).exists()
    unit = (Path(env["TA_UNIT_DIR"]) / "cyberalertx-telegram.service").read_text()
    assert "tools.publish cycle --send --limit 1" in unit and "/home/cax/cyberalertx/current" in unit
    assert (Path(env["TA_UNIT_DIR"]) / "cyberalertx-telegram.service.d" / "stage-c-hold.conf").exists()   # hold kept
    calls = Path(env["LOG"]).read_text()
    order = [line for line in calls.splitlines() if line.startswith("app")]
    assert "check-telegram" in order[0] and "media run" in order[1] and "baseline --before" in order[2]
    assert "systemctl enable --now cyberalertx-telegram.timer" in calls
    backup = next(Path(env["TA_BACKUPS"]).glob("telegram-activation-*"))
    assert (backup / "telegram_published.jsonl").exists() and (backup / "SHA256SUMS").exists()
    assert oct(backup.stat().st_mode)[-3:] == "700"


@pytestmark_bash
def test_a_failed_bot_check_changes_nothing(tmp_path: Path) -> None:
    env = _host(tmp_path, check_ok=False)
    r = _ta(env, "activate")
    assert r.returncode == 1 and "nothing changed" in r.stdout
    assert not Path(env["TA_MARKER"]).exists() and not (tmp_path / "timer_on").exists()
    assert "publish-telegram" in (Path(env["TA_UNIT_DIR"]) / "cyberalertx-telegram.service").read_text()


@pytestmark_bash
def test_deactivate_restores_the_hold(tmp_path: Path) -> None:
    env = _host(tmp_path)
    assert _ta(env, "activate").returncode == 0
    r = _ta(env, "deactivate")
    assert r.returncode == 0 and "DEACTIVATED" in r.stdout
    assert not Path(env["TA_MARKER"]).exists() and not (tmp_path / "timer_on").exists()
