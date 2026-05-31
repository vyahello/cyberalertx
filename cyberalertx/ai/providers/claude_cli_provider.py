"""Claude CLI provider — Claude Code headless (`claude -p`) as the content engine.

This is the drop-in replacement for `AnthropicProvider` that does NOT use an
`ANTHROPIC_API_KEY`. Instead of hitting `api.anthropic.com` through the SDK, it
shells out to the locally-installed `claude` CLI in headless print mode and
reuses whatever auth that CLI is logged into (subscription or token). The model
is "you" — the same Claude Code agent — rather than a metered Haiku API call.

How it maps onto the `LLMProvider` contract:

  * **(system, user) → CLI invocation.** The byte-stable journalist system
    prompt goes in via `--system-prompt` (a *full* override, not an append) so
    the persona/rules are exactly what `render_prompts()` produced — no Claude
    Code coding-agent framing leaks in. The per-item user prompt is piped on
    stdin (the "prompt" turn). `--exclude-dynamic-system-prompt-sections`
    strips the env/git/dynamic blocks so the agent is a clean journalist.

  * **Structured output.** The CLI has no Pydantic-schema mode like the SDK's
    `messages.parse()`, so we append the JSON Schema of `ThreatPostResponse`
    to the system prompt and demand a single raw JSON object back. We then
    extract + validate it ourselves into `ThreatPostResponse`. A malformed or
    non-JSON answer raises → the generator falls back to rule-based, exactly
    like a Pydantic validation error on the Anthropic path.

  * **Failure semantics.** Anything wrong — CLI missing, not logged in,
    non-zero exit, timeout, error envelope, unparseable JSON — raises so the
    caller's existing try/except falls through to the deterministic generator.

Switching back to Haiku is a one-liner: set `CYBERALERTX_AI_PROVIDER=anthropic`
(the AnthropicProvider and all its logic are left fully intact).

Operational note: the box that runs the pipeline must have the `claude` CLI
installed AND logged in via the OAuth **subscription** (`claude` once,
interactively, or a token via `claude setup-token`). If it isn't, every render
raises "Not logged in" and the generator quietly falls back to rule-based.

Billing note (important): the CLI bills the metered API — NOT your subscription
— whenever `ANTHROPIC_API_KEY` (or `ANTHROPIC_AUTH_TOKEN`) is present in its
environment. Since `.env` and the systemd `EnvironmentFile` inject that key, we
strip it from the subprocess env (see `_BILLING_ENV_VARS`) so renders go through
the subscription login. Without this the CLI silently charges Opus API rates.
"""
from __future__ import annotations

import json
import logging
import os
import shutil
import subprocess
from typing import Any, List, Optional

from ..models import ThreatPostResponse

logger = logging.getLogger(__name__)

# Env vars that make the `claude` CLI authenticate (and BILL) via the
# pay-per-token API instead of the user's OAuth subscription. We strip these
# from the subprocess environment so headless renders go through the
# subscription login (`claude` / `claude setup-token`) — the whole point of
# using the CLI over AnthropicProvider. `.env` puts ANTHROPIC_API_KEY into the
# process (and systemd injects it via EnvironmentFile), so without this the CLI
# silently charges the API key at Opus rates. If neither is stripped you pay
# twice over: subscription AND metered API.
_BILLING_ENV_VARS = ("ANTHROPIC_API_KEY", "ANTHROPIC_AUTH_TOKEN")


# Appended to the (already schema-aware) system prompt. render_prompts() ends
# with a one-line "respond with a single JSON object" note aimed at the SDK's
# structured-output mode; the CLI has no such mode, so we spell out the exact
# schema and the no-prose / no-fence rules the extractor depends on.
def _build_format_instruction(schema_json: str) -> str:
    return (
        "\n\nRESPONSE FORMAT — STRICT AND NON-NEGOTIABLE:\n"
        "Reply with EXACTLY ONE raw JSON object and nothing else. Do NOT wrap it\n"
        "in markdown code fences, do NOT add explanations, preamble, or trailing\n"
        "commentary, and do NOT use any tools — just emit the JSON. The object\n"
        "MUST conform to this JSON Schema (a `ThreatPostResponse`):\n"
        f"{schema_json}\n"
        "Every required field must be present. Output the JSON object now."
    )


class ClaudeCliProvider:
    """Sync provider backed by the `claude` CLI in headless (`-p`) mode.

    Construction is cheap (just resolves the binary). Reuse the instance —
    each `generate_post()` spawns one short-lived `claude -p` subprocess.
    """

    def __init__(
        self,
        *,
        binary: str = "claude",
        model: Optional[str] = None,
        timeout_seconds: int = 120,
        extra_args: Optional[List[str]] = None,
        use_subscription: bool = True,
    ) -> None:
        resolved = shutil.which(binary)
        if resolved is None:
            # Mirror AnthropicProvider's "missing dep is a clear error, not
            # import death" contract: raise RuntimeError so the factory logs
            # it and stays offline (rule-based) instead of crashing.
            raise RuntimeError(
                f"claude CLI not found on PATH (looked for {binary!r}). "
                "Install Claude Code or set CYBERALERTX_CLAUDE_CLI_BIN to its path."
            )
        self._binary = resolved
        self._model = model
        self._timeout = timeout_seconds
        self._extra_args = list(extra_args or [])
        # When True (default), strip ANTHROPIC_API_KEY/ANTHROPIC_AUTH_TOKEN from
        # the subprocess env so the CLI bills the OAuth subscription, not the
        # metered API. Set False only if you deliberately want API-key billing
        # (then AnthropicProvider is usually the better choice).
        self._use_subscription = use_subscription
        # Cache the schema once — it's identical for every call.
        self._schema_json = json.dumps(
            ThreatPostResponse.model_json_schema(), ensure_ascii=False
        )
        self.name = f"claude-cli:{model or 'default'}"

    def generate_post(self, system: str, user: str) -> ThreatPostResponse:
        """Run `claude -p`, parse its JSON answer into a ThreatPostResponse.

        Raises (→ generator falls back to rule-based) on:
          * CLI not logged in / auth failure
          * non-zero exit or timeout
          * error envelope (`is_error: true`) or a refusal
          * a response that isn't a single valid ThreatPostResponse JSON object
        """
        system_full = system + _build_format_instruction(self._schema_json)

        cmd: List[str] = [
            self._binary,
            "-p",
            "--output-format", "json",
            "--system-prompt", system_full,
            "--exclude-dynamic-system-prompt-sections",
        ]
        if self._model:
            cmd += ["--model", self._model]
        cmd += self._extra_args

        # Force subscription (OAuth) auth by hiding the API-key env vars from
        # the CLI. `.env` / systemd EnvironmentFile inject ANTHROPIC_API_KEY
        # into our process; if the subprocess inherits it, `claude` silently
        # bills the metered API at Opus rates instead of the subscription.
        env = os.environ.copy()
        if self._use_subscription:
            for var in _BILLING_ENV_VARS:
                env.pop(var, None)

        try:
            proc = subprocess.run(
                cmd,
                input=user,
                capture_output=True,
                text=True,
                timeout=self._timeout,
                check=False,
                env=env,
            )
        except subprocess.TimeoutExpired as exc:
            raise RuntimeError(
                f"claude CLI timed out after {self._timeout}s"
            ) from exc

        if proc.returncode != 0:
            raise RuntimeError(
                f"claude CLI exited {proc.returncode}: "
                f"{(proc.stderr or proc.stdout or '').strip()[:500]}"
            )

        envelope = self._parse_envelope(proc.stdout)
        result_text = self._result_text(envelope)
        payload = _extract_json_object(result_text)

        usage = envelope.get("usage")
        if isinstance(usage, dict):
            self._record_usage(usage, envelope.get("total_cost_usd"))

        try:
            return ThreatPostResponse.model_validate_json(payload)
        except Exception as exc:  # pydantic ValidationError / json errors
            raise RuntimeError(
                f"claude CLI returned a non-conforming ThreatPostResponse: {exc}"
            ) from exc

    # ----------------------- internals -------------------------------

    @staticmethod
    def _parse_envelope(stdout: str) -> dict:
        try:
            data = json.loads(stdout)
        except json.JSONDecodeError as exc:
            raise RuntimeError(
                f"claude CLI did not emit a JSON envelope: {stdout.strip()[:300]}"
            ) from exc
        if not isinstance(data, dict):
            raise RuntimeError("claude CLI JSON envelope was not an object")
        return data

    @staticmethod
    def _result_text(envelope: dict) -> str:
        """Pull the assistant text out of the `--output-format json` envelope.

        The envelope carries `is_error` / `subtype` / `result`. A failed run
        (e.g. "Not logged in") still has a 0 exit code but `is_error: true` and
        the human message in `result` — surface it as a raise so we fall back.
        """
        if envelope.get("is_error") or envelope.get("subtype") not in (None, "success"):
            raise RuntimeError(
                f"claude CLI error: {str(envelope.get('result', envelope))[:300]}"
            )
        result = envelope.get("result")
        if not isinstance(result, str) or not result.strip():
            raise RuntimeError("claude CLI envelope had no `result` text")
        return result

    @staticmethod
    def _record_usage(usage: dict, total_cost_usd: Any) -> None:
        """Log token usage + bump observability counters (best-effort).

        Mirrors AnthropicProvider._record_usage so the prompt-cache and spend
        story stays visible regardless of which provider rendered the post.
        Counter names are namespaced `claude_cli_*` so dashboards can tell the
        two engines apart."""
        input_tokens = int(usage.get("input_tokens", 0) or 0)
        cache_read = int(usage.get("cache_read_input_tokens", 0) or 0)
        cache_write = int(usage.get("cache_creation_input_tokens", 0) or 0)
        output_tokens = int(usage.get("output_tokens", 0) or 0)

        logger.info(
            "claude-cli usage: input=%d cache_read=%d cache_write=%d output=%d cost_usd=%s",
            input_tokens, cache_read, cache_write, output_tokens, total_cost_usd,
        )

        try:
            from ...observability.metrics import get_quality_metrics
            m = get_quality_metrics()
            m.bump("claude_cli_calls")
            if input_tokens:
                m.bump("claude_cli_input_tokens", input_tokens)
            if cache_read:
                m.bump("claude_cli_cache_read_tokens", cache_read)
            if cache_write:
                m.bump("claude_cli_cache_write_tokens", cache_write)
            if output_tokens:
                m.bump("claude_cli_output_tokens", output_tokens)
        except Exception as exc:  # pragma: no cover — defensive
            logger.debug("usage counter bump skipped: %s", exc)


def _extract_json_object(text: str) -> str:
    """Return the single top-level JSON object embedded in `text`.

    The prompt demands raw JSON, but models occasionally wrap it in ```json
    fences or add a stray sentence. We strip fences, then scan for the first
    balanced `{...}` (brace-counting, quote/escape aware) and return it. The
    caller validates it against the schema, so we only need to isolate the
    object — not understand it.
    """
    s = text.strip()

    # Strip a leading/trailing markdown code fence if present.
    if s.startswith("```"):
        first_nl = s.find("\n")
        if first_nl != -1:
            s = s[first_nl + 1:]
        if s.rstrip().endswith("```"):
            s = s.rstrip()[:-3]
        s = s.strip()

    start = s.find("{")
    if start == -1:
        raise RuntimeError(f"no JSON object in claude CLI result: {text[:200]!r}")

    depth = 0
    in_str = False
    escaped = False
    for i in range(start, len(s)):
        ch = s[i]
        if in_str:
            if escaped:
                escaped = False
            elif ch == "\\":
                escaped = True
            elif ch == '"':
                in_str = False
            continue
        if ch == '"':
            in_str = True
        elif ch == "{":
            depth += 1
        elif ch == "}":
            depth -= 1
            if depth == 0:
                return s[start:i + 1]

    raise RuntimeError(f"unterminated JSON object in claude CLI result: {text[:200]!r}")


__all__ = ["ClaudeCliProvider"]
