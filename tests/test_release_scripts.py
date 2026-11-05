"""ops/release/release_switch.sh and switch_when_idle.sh, against a temporary
release tree with mock systemctl / curl / journalctl. Never touches the host."""
from __future__ import annotations

import os
import shutil
import subprocess
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[1]
SWITCH = REPO / "ops" / "release" / "release_switch.sh"
IDLE = REPO / "ops" / "release" / "switch_when_idle.sh"
OLD, NEW = "20261104-1626-4fa7a63", "20261105-0935-b509775"
SHA_OLD, SHA_NEW = "4fa7a63" + "0" * 33, "b509775" + "1" * 33

pytestmark = pytest.mark.skipif(shutil.which("bash") is None or shutil.which("flock") is None,
                                reason="needs bash and flock")


def _exe(path: Path, body: str) -> Path:
    path.write_text("#!/bin/bash\n" + body)
    path.chmod(0o755)
    return path


@pytest.fixture()
def env(tmp_path: Path) -> dict[str, str]:
    root, data = tmp_path / "cyberalertx", tmp_path / "data"
    data.mkdir()
    for rid, sha in ((OLD, SHA_OLD), (NEW, SHA_NEW)):
        r = root / "releases" / rid
        (r / "venv" / "bin").mkdir(parents=True)
        _exe(r / "venv" / "bin" / "python", "exit 0\n")
        (r / "frontend" / ".next").mkdir(parents=True)
        (r / "frontend" / ".next" / "BUILD_ID").write_text("x")
        (r / "RELEASE").write_text(f"release_id={rid}\ncommit={sha}\n")
        (r / "data").symlink_to(data)
    (root / "current").symlink_to(root / "releases" / OLD)
    calls = tmp_path / "calls.log"
    cur = root / "current"
    _exe(tmp_path / "systemctl", f"""echo "$*" >> {calls}
case "$1" in
  show) case "$*" in *frontend*) echo {cur}/frontend;; *MainPID*) echo 4242;; *) echo {cur};; esac;;
  restart) exit $(cat {tmp_path}/restart_rc 2>/dev/null || echo 0);;
  is-active) case "$2" in cyberalertx-generate.service) cat {tmp_path}/generate_state 2>/dev/null || echo inactive;; *) echo active;; esac;;
esac
""")
    _exe(tmp_path / "curl", f"cat {tmp_path}/http_code 2>/dev/null || echo 200\n")
    _exe(tmp_path / "journalctl", f"cat {tmp_path}/journal 2>/dev/null\n")
    (tmp_path / "journal").write_text(
        "x INFO [apscheduler.executors.default] Running job \"Pipeline.run_once\"\n"
        "x INFO [apscheduler.executors.default] Job \"Pipeline.run_once\" executed successfully\n")
    return {
        "PATH": os.environ.get("PATH", "/usr/bin:/bin"), "TMP": str(tmp_path), "ROOT": str(root),
        "RB_TEST": "1", "RB_SYSTEMCTL": str(tmp_path / "systemctl"), "RB_CURL": str(tmp_path / "curl"),
        "RB_ROOT": str(root), "RB_DATA": str(data), "RB_WAIT": "3",
        "SW_TEST": "1", "SW_SYSTEMCTL": str(tmp_path / "systemctl"), "SW_JOURNALCTL": str(tmp_path / "journalctl"),
        "SW_ROOT": str(root), "SW_SWITCH": f"bash {SWITCH}",
    }


def _run(script: Path, env: dict[str, str], *args: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(["bash", str(script), *args], env=env, capture_output=True, text=True, timeout=60)


def _current(env: dict[str, str]) -> str:
    return os.path.basename(os.readlink(Path(env["ROOT"]) / "current"))


def test_forward_switch_reports_neutral_details(env: dict[str, str]) -> None:
    r = _run(SWITCH, env, NEW)
    assert r.returncode == 0, r.stdout + r.stderr
    assert "RELEASE SWITCH COMPLETED (forward to a newer release)" in r.stdout
    assert "ROLLBACK" not in r.stdout
    assert f"previous release: {OLD} (commit {SHA_OLD})" in r.stdout
    assert f"active release:   {NEW} (commit {SHA_NEW})" in r.stdout
    assert "health:           api /healthz 200, site /en 200" in r.stdout
    assert _current(env) == NEW
    assert "restart cyberalertx-api cyberalertx-frontend cyberalertx-run" in Path(env["TMP"], "calls.log").read_text()


def test_rollback_switch(env: dict[str, str]) -> None:
    assert _run(SWITCH, env, NEW).returncode == 0
    r = _run(SWITCH, env, OLD)
    assert r.returncode == 0 and "rollback to an earlier release" in r.stdout
    assert _current(env) == OLD


def test_already_active_is_a_no_op(env: dict[str, str]) -> None:
    r = _run(SWITCH, env, OLD)
    assert r.returncode == 0 and "ACTIVE RELEASE UNCHANGED" in r.stdout


@pytest.mark.parametrize("target", ["does-not-exist", "../escape", ".hidden", ""])
def test_invalid_target_is_refused_and_current_is_unchanged(env: dict[str, str], target: str) -> None:
    r = _run(SWITCH, env, target)
    assert r.returncode != 0
    assert _current(env) == OLD


def test_incomplete_release_is_refused(env: dict[str, str]) -> None:
    (Path(env["ROOT"]) / "releases" / NEW / "frontend" / ".next" / "BUILD_ID").unlink()
    r = _run(SWITCH, env, NEW)
    assert r.returncode == 1 and "frontend build missing" in r.stdout and _current(env) == OLD


def test_wrong_data_link_is_refused(env: dict[str, str], tmp_path: Path) -> None:
    link = Path(env["ROOT"]) / "releases" / NEW / "data"
    link.unlink()
    link.symlink_to(tmp_path)
    r = _run(SWITCH, env, NEW)
    assert r.returncode == 1 and "data link" in r.stdout and _current(env) == OLD


def test_failed_health_check_reports_the_way_back(env: dict[str, str]) -> None:
    Path(env["TMP"], "http_code").write_text("502\n")
    r = _run(SWITCH, env, NEW)
    assert r.returncode == 1 and "not healthy after the switch (api=502 site=502)" in r.stdout
    assert f"to go back: sudo bash {SWITCH} {OLD}" in r.stdout


def test_restart_failure_reports_the_way_back(env: dict[str, str]) -> None:
    Path(env["TMP"], "restart_rc").write_text("1\n")
    r = _run(SWITCH, env, NEW)
    assert r.returncode == 1 and "restart failed after the switch" in r.stdout and OLD in r.stdout


def test_switch_is_atomic_and_leaves_no_temp_link(env: dict[str, str]) -> None:
    assert _run(SWITCH, env, NEW).returncode == 0
    root = Path(env["ROOT"])
    assert (root / "current").is_symlink() and not (root / "current.switch-tmp").exists()


def test_concurrent_switch_is_refused(env: dict[str, str]) -> None:
    lock = Path(env["ROOT"]) / ".release-switch.lock"
    holder = subprocess.Popen(["flock", str(lock), "sleep", "5"])
    try:
        import time
        time.sleep(0.3)
        r = _run(SWITCH, env, NEW)
        assert r.returncode == 1 and "another release switch is running" in r.stdout and _current(env) == OLD
    finally:
        holder.kill()


# ----- switch_when_idle.sh -----------------------------------------------------------
def test_idle_writers_hand_over_to_the_switch(env: dict[str, str]) -> None:
    r = _run(IDLE, env, NEW, "5")
    assert r.returncode == 0, r.stdout + r.stderr
    assert "writers idle" in r.stdout and "RELEASE SWITCH COMPLETED" in r.stdout and _current(env) == NEW


def test_busy_generate_times_out_without_switching(env: dict[str, str]) -> None:
    Path(env["TMP"], "generate_state").write_text("active\n")
    r = _run(IDLE, env, NEW, "0")
    assert r.returncode == 3 and "writers still busy" in r.stdout and "generate running" in r.stdout
    assert _current(env) == OLD


def test_running_ingest_cycle_times_out_without_switching(env: dict[str, str]) -> None:
    Path(env["TMP"], "journal").write_text("x INFO [apscheduler.executors.default] Running job \"Pipeline.run_once\"\n")
    r = _run(IDLE, env, NEW, "0")
    assert r.returncode == 3 and "ingest cycle running" in r.stdout and _current(env) == OLD


def test_unknown_writer_state_fails_closed(env: dict[str, str]) -> None:
    Path(env["TMP"], "journal").write_text("")
    r = _run(IDLE, env, NEW, "60")
    assert r.returncode == 3 and "cannot determine writer state" in r.stdout and _current(env) == OLD


def test_invalid_target_is_refused_before_waiting(env: dict[str, str]) -> None:
    r = _run(IDLE, env, "nope")
    assert r.returncode == 3 and "no release" in r.stdout and _current(env) == OLD


def test_the_wait_is_bounded_and_numeric(env: dict[str, str]) -> None:
    r = _run(IDLE, env, NEW, "forever")
    assert r.returncode == 3 and _current(env) == OLD


# ----- api_json_reads.sh (recovery switch) -------------------------------------------
def test_api_json_reads_apply_and_revert(tmp_path: Path) -> None:
    script = REPO / "ops" / "release" / "api_json_reads.sh"
    units = tmp_path / "units"; units.mkdir()
    envf = tmp_path / "api-json-backend.env"; envf.write_text("CYBERALERTX_STORAGE_BACKEND=json")
    _exe(tmp_path / "systemctl", f"""case "$1" in
  show) case "$*" in *WorkingDirectory*) echo /home/cax/cyberalertx/current;;
        *DropInPaths*) ls {units}/cyberalertx-api.service.d/*.conf 2>/dev/null | tr '\\n' ' ';; esac;;
esac
""")
    _exe(tmp_path / "curl", 'case "$*" in *time_total*) echo 0.05;; *) echo 200;; esac\n')
    env = {"PATH": os.environ.get("PATH", "/usr/bin:/bin"), "C8_TEST": "1", "C8_SYSTEMCTL": str(tmp_path / "systemctl"),
           "C8_CURL": str(tmp_path / "curl"), "C8_UNIT_DIR": str(units), "C8_ENVF": str(envf), "C8_WAIT": "2"}
    r = subprocess.run(["bash", str(script), "apply"], env=env, capture_output=True, text=True, timeout=30)
    assert r.returncode == 0 and "apply COMPLETED" in r.stdout, r.stdout + r.stderr
    dropin = units / "cyberalertx-api.service.d" / "stage-c-json-reads.conf"
    assert f"EnvironmentFile={envf}" in dropin.read_text()
    r = subprocess.run(["bash", str(script), "revert"], env=env, capture_output=True, text=True, timeout=30)
    assert r.returncode == 0 and not dropin.exists()
    envf.write_text("CYBERALERTX_STORAGE_BACKEND=dual")      # refuses anything but exactly json
    r = subprocess.run(["bash", str(script), "apply"], env=env, capture_output=True, text=True, timeout=30)
    assert r.returncode == 1 and not dropin.exists()
