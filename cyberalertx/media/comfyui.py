"""Local ComfyUI worker adapter (optional, disabled by default).

Used only when ALL of these hold; otherwise the engine renders SVG:
  * CYBERALERTX_COMFYUI_URL points at a loopback address (http://127.0.0.1:PORT);
  * CYBERALERTX_COMFYUI_WORKFLOW is an API-format workflow JSON file with the
    placeholders "{{PROMPT}}", "{{NEGATIVE}}", "{{SEED}}", "{{WIDTH}}", "{{HEIGHT}}";
  * the worker answers GET /system_stats;
  * MemAvailable is at least CYBERALERTX_COMFYUI_MIN_FREE_MB (default 2048).

Endpoints used (ComfyUI's local HTTP API): POST /prompt, GET /history/{id},
GET /view. One job at a time; a hard timeout per job. No remote or paid API.

On the production host (Nov 2026: 2 vCPU, 3.7 GiB RAM, no GPU) this stays
disabled: see docs/media/IMAGE_GENERATION.md.
"""
from __future__ import annotations

import json
import os
import random
import time
from pathlib import Path
from typing import Any, Callable
from urllib.parse import urlparse

import httpx

from .illustrations import GeneratedImage, ProviderError, ProviderUnavailable

NEGATIVE = ("text, letters, watermark, logo, brand, face, person, hooded hacker, padlock, shield, "
            "binary digits, matrix rain, terminal screen, user interface, screenshot")


def _mem_available_mb(meminfo: Path = Path("/proc/meminfo")) -> int:
    try:
        for line in meminfo.read_text().splitlines():
            if line.startswith("MemAvailable:"):
                return int(line.split()[1]) // 1024
    except (OSError, ValueError, IndexError):
        pass
    return 0


class ComfyUIProvider:
    name = "comfyui"

    def __init__(self, *, url: str | None = None, workflow: str | None = None,
                 min_free_mb: int | None = None, transport: httpx.BaseTransport | None = None,
                 mem_available: Callable[[], int] = _mem_available_mb,
                 sleep: Callable[[float], None] = time.sleep) -> None:
        self.url = (url if url is not None else os.getenv("CYBERALERTX_COMFYUI_URL", "")).rstrip("/")
        if not self.url:
            raise ProviderUnavailable("CYBERALERTX_COMFYUI_URL not set (ComfyUI disabled)")
        host = urlparse(self.url).hostname or ""
        if host not in ("127.0.0.1", "localhost", "::1"):
            raise ProviderUnavailable("ComfyUI must listen on loopback only")
        path = workflow if workflow is not None else os.getenv("CYBERALERTX_COMFYUI_WORKFLOW", "")
        try:
            self.template = Path(path).read_text(encoding="utf-8") if path else ""
            json.loads(self.template.replace('"{{SEED}}"', "0").replace('"{{WIDTH}}"', "0")
                       .replace('"{{HEIGHT}}"', "0") or "{}")
        except (OSError, ValueError) as exc:
            raise ProviderUnavailable(f"ComfyUI workflow unreadable: {type(exc).__name__}") from exc
        if "{{PROMPT}}" not in self.template:
            raise ProviderUnavailable("ComfyUI workflow lacks the {{PROMPT}} placeholder")
        self.min_free_mb = min_free_mb if min_free_mb is not None else int(
            os.getenv("CYBERALERTX_COMFYUI_MIN_FREE_MB", "2048") or 2048)
        self._transport = transport
        self._mem = mem_available
        self._sleep = sleep
        self.model = os.getenv("CYBERALERTX_COMFYUI_MODEL_LABEL", "comfyui-local")

    def _client(self, timeout: float) -> httpx.Client:
        return httpx.Client(base_url=self.url, timeout=timeout, transport=self._transport)

    def healthy(self) -> tuple[bool, str]:
        free = self._mem()
        if free < self.min_free_mb:
            return False, f"only {free} MiB available (< {self.min_free_mb})"
        try:
            with self._client(5.0) as c:
                r = c.get("/system_stats")
            return (r.status_code == 200, f"system_stats HTTP {r.status_code}")
        except httpx.HTTPError as exc:
            return False, f"unreachable: {type(exc).__name__}"

    def _workflow(self, prompt: str, width: int, height: int, seed: int) -> dict[str, Any]:
        text = (self.template.replace("{{PROMPT}}", json.dumps(prompt)[1:-1])
                .replace("{{NEGATIVE}}", json.dumps(NEGATIVE)[1:-1])
                .replace('"{{SEED}}"', str(seed)).replace('"{{WIDTH}}"', str(width))
                .replace('"{{HEIGHT}}"', str(height)))
        return dict(json.loads(text))

    def generate(self, prompt: str, *, width: int, height: int, timeout_s: float) -> GeneratedImage:
        ok, why = self.healthy()
        if not ok:
            raise ProviderUnavailable(f"ComfyUI not available: {why}")
        seed = random.Random(prompt).randrange(2**31)
        deadline = time.monotonic() + timeout_s
        try:
            with self._client(30.0) as c:
                r = c.post("/prompt", json={"prompt": self._workflow(prompt, width, height, seed)})
                if r.status_code != 200:
                    raise ProviderError(f"/prompt HTTP {r.status_code}")
                pid = str(r.json().get("prompt_id") or "")
                if not pid:
                    raise ProviderError("/prompt returned no prompt_id")
                while True:
                    h = c.get(f"/history/{pid}")
                    entry = (h.json() or {}).get(pid) if h.status_code == 200 else None
                    if entry and entry.get("outputs"):
                        break
                    if time.monotonic() > deadline:
                        raise ProviderError(f"timeout after {timeout_s:.0f}s")
                    self._sleep(2.0)
                image = next((img for out in entry["outputs"].values() for img in out.get("images", [])), None)
                if not image:
                    raise ProviderError("workflow produced no image")
                v = c.get("/view", params={"filename": image["filename"], "subfolder": image.get("subfolder", ""),
                                           "type": image.get("type", "output")})
                if v.status_code != 200 or not v.content:
                    raise ProviderError(f"/view HTTP {v.status_code}")
        except httpx.HTTPError as exc:
            raise ProviderError(f"ComfyUI request failed: {type(exc).__name__}") from exc
        except (ValueError, KeyError, TypeError) as exc:
            raise ProviderError(f"unexpected ComfyUI response: {type(exc).__name__}") from exc
        return GeneratedImage(data=v.content, mime="image/png", model=self.model, cost_usd=0.0, method="comfyui")


__all__ = ["ComfyUIProvider", "NEGATIVE"]
