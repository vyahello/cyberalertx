"""ops/release/o35_units.sh against a fake unit directory and mock systemctl.

Checks the migration installs only the analytics and Telegram units, keeps the
Telegram hold, refuses when the hold is weakened, and reverts from its backup.
"""
from __future__ import annotations

import os
import shutil
import subprocess
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[1]
SCRIPT = REPO / "ops" / "release" / "o35_units.sh"
TEMPLATES = REPO / "server" / "systemd"
CUR = "/home/cax/cyberalertx/current"

pytestmark = pytest.mark.skipif(shutil.which("bash") is None, reason="needs bash")


@pytest.fixture()
def host(tmp_path: Path) -> dict[str, str]:
    units, cur = tmp_path / "units", tmp_path / "current"
    units.mkdir()
    for n in ("analytics", "telegram"):
        old = (TEMPLATES / f"cyberalertx-{n}.service").read_text().replace(CUR + "/venv", "/home/cax/cax/venv") \
            .replace(f"WorkingDirectory={CUR}", "WorkingDirectory=/home/cax/cax")
        (units / f"cyberalertx-{n}.service").write_text(old)
    (units / "cyberalertx-telegram.service.d").mkdir()
    # A marker path under tmp, never the host's: the real one exists once Telegram is activated.
    marker = tmp_path / "STAGE_D_AUTHORIZED"
    hold = (TEMPLATES / "cyberalertx-telegram.service.d" / "stage-c-hold.conf").read_text()
    (units / "cyberalertx-telegram.service.d" / "stage-c-hold.conf").write_text(
        hold.replace("/home/cax/cyberalertx/STAGE_D_AUTHORIZED", str(marker)))
    (cur / "venv" / "bin").mkdir(parents=True)
    (cur / "venv" / "bin" / "python").write_text("#!/bin/sh\n"); (cur / "venv" / "bin" / "python").chmod(0o755)
    (cur / "server" / "analytics").mkdir(parents=True); (cur / "server" / "analytics" / "__main__.py").write_text("")
    (cur / "cyberalertx").mkdir(); (cur / "cyberalertx" / "main.py").write_text("")
    state = tmp_path / "state"; state.mkdir()
    (state / "telegram.timer.enabled").write_text("disabled")
    (state / "analytics.timer.enabled").write_text("enabled")
    sysctl = tmp_path / "systemctl"
    sysctl.write_text(f"""#!/bin/bash
U={units}; S={state}; echo "$*" >> {tmp_path}/calls.log
unit() {{ n=${{1#cyberalertx-}}; echo "${{n%.service}}"; }}
case "$1" in
  show) n=$(unit "${{@: -1}}")
        case "$*" in *WorkingDirectory*) sed -n 's/^WorkingDirectory=//p' $U/cyberalertx-$n.service;;
          *DropInPaths*) ls $U/cyberalertx-$n.service.d/*.conf 2>/dev/null | tr '\\n' ' ';;
          *Result*) cat $S/analytics.result 2>/dev/null || echo success;; esac;;
  cat) n=$(unit "$2"); cat $U/cyberalertx-$n.service $U/cyberalertx-$n.service.d/*.conf 2>/dev/null;;
  is-enabled) n=${{2#cyberalertx-}}; cat $S/$n.enabled 2>/dev/null || echo static;;
  is-active) echo inactive;;
  daemon-reload) ;;
  start) exit $(cat $S/start_rc 2>/dev/null || echo 0);;
esac
""")
    sysctl.chmod(0o755)
    (tmp_path / "backups").mkdir()
    return {"PATH": os.environ.get("PATH", "/usr/bin:/bin"), "TMP": str(tmp_path), "UNITS": str(units),
            "O35_TEST": "1", "O35_SYSTEMCTL": str(sysctl), "O35_UNIT_DIR": str(units), "O35_CURRENT": str(cur),
            "O35_BACKUPS": str(tmp_path / "backups"), "O35_MARKER": str(marker)}


def test_templates_point_at_current_and_telegram_stays_held() -> None:
    for n in ("analytics", "telegram"):
        text = (TEMPLATES / f"cyberalertx-{n}.service").read_text()
        assert f"WorkingDirectory={CUR}\n" in text and f"ExecStart={CUR}/venv/bin/python" in text
        assert "/home/cax/cax/venv" not in text
    hold = (TEMPLATES / "cyberalertx-telegram.service.d" / "stage-c-hold.conf").read_text()
    assert "ConditionPathExists=/home/cax/cyberalertx/STAGE_D_AUTHORIZED" in hold
    assert "EnvironmentFile=/home/cax/cax/.env" in (TEMPLATES / "cyberalertx-telegram.service").read_text()


def _fake_repo(tmp: Path, cur: str) -> Path:
    """The script reads templates relative to itself; give it a copy using the fake `current`."""
    root = tmp / "repo"
    (root / "ops" / "release").mkdir(parents=True, exist_ok=True)
    shutil.copy(SCRIPT, root / "ops" / "release" / "o35_units.sh")
    (root / "server" / "systemd").mkdir(parents=True, exist_ok=True)
    for n in ("analytics", "telegram"):
        (root / "server" / "systemd" / f"cyberalertx-{n}.service").write_text(
            (TEMPLATES / f"cyberalertx-{n}.service").read_text().replace(CUR, cur))
    return root / "ops" / "release" / "o35_units.sh"


def _run_fake(env: dict[str, str], *args: str) -> subprocess.CompletedProcess[str]:
    script = _fake_repo(Path(env["TMP"]), env["O35_CURRENT"])
    return subprocess.run(["bash", str(script), *args], env=env, capture_output=True, text=True, timeout=60)


def test_apply_installs_both_units_keeps_the_hold_and_reverts(host: dict[str, str]) -> None:
    units = Path(host["UNITS"])
    before_hold = (units / "cyberalertx-telegram.service.d" / "stage-c-hold.conf").read_text()
    r = _run_fake(host, "apply")
    assert r.returncode == 0, r.stdout + r.stderr
    assert "O35 APPLY COMPLETED" in r.stdout and "still HELD" in r.stdout
    for n in ("analytics", "telegram"):
        assert f"WorkingDirectory={host['O35_CURRENT']}" in (units / f"cyberalertx-{n}.service").read_text()
    assert (units / "cyberalertx-telegram.service.d" / "stage-c-hold.conf").read_text() == before_hold
    calls = Path(host["TMP"], "calls.log").read_text()
    assert "start cyberalertx-analytics.service" in calls
    assert "telegram" not in "".join(l for l in calls.splitlines() if l.startswith(("start", "enable", "restart")))
    backup = next(Path(host["O35_BACKUPS"]).glob("o35-units-*"))
    assert (backup / "cyberalertx-analytics.service").exists() and oct(backup.stat().st_mode)[-3:] == "700"
    assert _run_fake(host, "check").returncode == 0

    r = _run_fake(host, "revert", str(backup))
    assert r.returncode == 0 and "O35 REVERT COMPLETED" in r.stdout
    assert "WorkingDirectory=/home/cax/cax\n" in (units / "cyberalertx-analytics.service").read_text()


def test_apply_refuses_without_the_hold(host: dict[str, str]) -> None:
    (Path(host["UNITS"]) / "cyberalertx-telegram.service.d" / "stage-c-hold.conf").unlink()
    r = _run_fake(host, "apply")
    assert r.returncode == 1 and "hold drop-in missing" in r.stdout
    assert "WorkingDirectory=/home/cax/cax\n" in (Path(host["UNITS"]) / "cyberalertx-analytics.service").read_text()


def test_apply_refuses_when_the_telegram_timer_is_enabled(host: dict[str, str]) -> None:
    Path(host["TMP"], "state", "telegram.timer.enabled").write_text("enabled")
    r = _run_fake(host, "apply")
    assert r.returncode == 1 and "Telegram timer is not disabled" in r.stdout


def test_apply_refuses_when_the_stage_d_marker_exists(host: dict[str, str], tmp_path: Path) -> None:
    marker = tmp_path / "STAGE_D_AUTHORIZED"
    marker.write_text("")
    env = dict(host, O35_MARKER=str(marker))
    for p in Path(host["UNITS"]).glob("cyberalertx-telegram.service.d/*.conf"):
        p.write_text(p.read_text().replace("/home/cax/cyberalertx/STAGE_D_AUTHORIZED", str(marker)))
    r = _run_fake(env, "apply")
    assert r.returncode == 1 and "Stage D marker" in r.stdout


def test_a_failed_analytics_run_prints_the_revert_command(host: dict[str, str]) -> None:
    Path(host["TMP"], "state", "start_rc").write_text("1")
    r = _run_fake(host, "apply")
    assert r.returncode == 1 and "revert: sudo bash" in r.stdout
