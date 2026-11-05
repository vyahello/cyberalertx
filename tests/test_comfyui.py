"""Local ComfyUI adapter (media/comfyui.py): disabled unless explicitly and safely enabled."""
from __future__ import annotations

import json
from pathlib import Path

import httpx
import pytest

from cyberalertx.media.comfyui import ComfyUIProvider
from cyberalertx.media.illustrations import ProviderError, ProviderUnavailable
from tests.test_media import png

WORKFLOW = {"3": {"class_type": "KSampler", "inputs": {"seed": "{{SEED}}", "text": "{{PROMPT}}",
                                                      "negative": "{{NEGATIVE}}"}},
            "5": {"class_type": "EmptyLatentImage", "inputs": {"width": "{{WIDTH}}", "height": "{{HEIGHT}}"}}}


def _wf(tmp_path: Path) -> str:
    p = tmp_path / "wf.json"
    p.write_text(json.dumps(WORKFLOW).replace('"{{SEED}}"', '"{{SEED}}"'))
    return str(p)


def test_disabled_without_a_url(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("CYBERALERTX_COMFYUI_URL", raising=False)
    with pytest.raises(ProviderUnavailable, match="not set"):
        ComfyUIProvider()


def test_refuses_a_non_loopback_worker(tmp_path: Path) -> None:
    with pytest.raises(ProviderUnavailable, match="loopback"):
        ComfyUIProvider(url="http://10.0.0.5:8188", workflow=_wf(tmp_path))


def test_refuses_a_workflow_without_the_prompt_placeholder(tmp_path: Path) -> None:
    p = tmp_path / "wf.json"
    p.write_text("{}")
    with pytest.raises(ProviderUnavailable, match="PROMPT"):
        ComfyUIProvider(url="http://127.0.0.1:8188", workflow=str(p))


def test_low_memory_means_unavailable_and_no_request(tmp_path: Path) -> None:
    calls: list[str] = []

    def handler(req: httpx.Request) -> httpx.Response:
        calls.append(req.url.path)
        return httpx.Response(200, json={})
    prov = ComfyUIProvider(url="http://127.0.0.1:8188", workflow=_wf(tmp_path), min_free_mb=2048,
                           mem_available=lambda: 900, transport=httpx.MockTransport(handler))
    with pytest.raises(ProviderUnavailable, match="900 MiB"):
        prov.generate("p", width=1536, height=864, timeout_s=60)
    assert calls == []


def test_full_job_flow_returns_the_png(tmp_path: Path) -> None:
    seen: dict[str, object] = {}
    image = png(1536, 864)

    def handler(req: httpx.Request) -> httpx.Response:
        if req.url.path == "/system_stats":
            return httpx.Response(200, json={"system": {}})
        if req.url.path == "/prompt":
            seen["workflow"] = json.loads(req.content)["prompt"]
            return httpx.Response(200, json={"prompt_id": "abc"})
        if req.url.path == "/history/abc":
            return httpx.Response(200, json={"abc": {"outputs": {"9": {"images": [
                {"filename": "o.png", "subfolder": "", "type": "output"}]}}}})
        if req.url.path == "/view":
            return httpx.Response(200, content=image)
        return httpx.Response(404)
    prov = ComfyUIProvider(url="http://127.0.0.1:8188", workflow=_wf(tmp_path), min_free_mb=0,
                           mem_available=lambda: 4000, transport=httpx.MockTransport(handler), sleep=lambda s: None)
    img = prov.generate('a "quoted" brief', width=1536, height=864, timeout_s=60)
    assert img.data == image and img.method == "comfyui" and img.cost_usd == 0.0
    wf = seen["workflow"]
    assert isinstance(wf, dict) and wf["5"]["inputs"] == {"width": 1536, "height": 864}
    assert wf["3"]["inputs"]["text"] == 'a "quoted" brief' and isinstance(wf["3"]["inputs"]["seed"], int)


def test_a_job_that_never_finishes_times_out(tmp_path: Path) -> None:
    def handler(req: httpx.Request) -> httpx.Response:
        if req.url.path == "/system_stats":
            return httpx.Response(200, json={})
        if req.url.path == "/prompt":
            return httpx.Response(200, json={"prompt_id": "abc"})
        return httpx.Response(200, json={})
    prov = ComfyUIProvider(url="http://127.0.0.1:8188", workflow=_wf(tmp_path), min_free_mb=0,
                           mem_available=lambda: 4000, transport=httpx.MockTransport(handler), sleep=lambda s: None)
    with pytest.raises(ProviderError, match="timeout"):
        prov.generate("p", width=1536, height=864, timeout_s=0)
