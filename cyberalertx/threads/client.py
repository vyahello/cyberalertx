"""The Threads Graph API calls CyberAlertX uses — nothing more.

Endpoints follow Meta's official documentation (developers.facebook.com/docs/
threads, checked Nov 2026): host `graph.threads.com`, version `v1.0` for
Graph calls; `oauth/access_token`, `access_token` and `refresh_access_token`
unversioned at the host root, exactly as documented.

Secrets: tokens and the app secret travel in POST bodies where the API
accepts them, and in query strings only for the documented GET calls. Every
error message that leaves this module passes through `scrub()`, so a token,
secret or authorization code can never reach a log or the job store.

Errors are `ThreadsError(category)` with the Publication Engine's categories:
network · rate_limit · temporary · auth · permission · invalid_content ·
missing_media · unknown_outcome. Graph error codes are classified by Meta's
general Graph API conventions (190 invalid/expired token; 10 and 200–299
permission; 4, 17, 32, 613 rate limiting); the Threads docs do not publish a
separate code table.
"""
from __future__ import annotations

import re
from typing import Any
from urllib.parse import urlencode

import httpx

from .config import GRAPH_ROOT, GRAPH_VERSION

from ..logsafe import install as _install_log_redaction

_install_log_redaction()   # httpx logs request URLs; ours carry credentials

_SECRET_RE = re.compile(r"(access_token|client_secret|code|fb_exchange_token)=[^&\s\"']+", re.I)
_BEARER_RE = re.compile(r"(TH|EAA)[A-Za-z0-9_\-]{20,}")
_NOT_SENT = (httpx.ConnectError, httpx.ConnectTimeout, httpx.PoolTimeout, httpx.UnsupportedProtocol,
             httpx.InvalidURL)
_RATE_CODES = {4, 17, 32, 613}


def scrub(text: str) -> str:
    return _BEARER_RE.sub("[token]", _SECRET_RE.sub(r"\1=[redacted]", str(text)))[:500]


class ThreadsError(RuntimeError):
    def __init__(self, message: str, *, category: str, status_code: int | None = None,
                 code: int | None = None, retry_after: float = 0.0) -> None:
        super().__init__(scrub(message))
        self.category = category
        self.status_code = status_code
        self.code = code
        self.retry_after = retry_after


def _classify(status: int, err: dict[str, Any]) -> str:
    code = err.get("code")
    msg = str(err.get("message", "")).lower()
    if status == 429 or code in _RATE_CODES or "rate limit" in msg or "request limit" in msg:
        return "rate_limit"
    if status == 401 or code == 190:
        return "auth"
    if status == 403 or code == 10 or (isinstance(code, int) and 200 <= code < 300):
        return "permission"
    if status >= 500:
        return "temporary"
    if any(k in msg for k in ("image", "media", "download", "aspect", "url")):
        return "missing_media"
    return "invalid_content"


class ThreadsClient:
    def __init__(self, *, client: httpx.Client | None = None, graph_root: str = GRAPH_ROOT,
                 timeout_s: float = 20.0) -> None:
        self._owns = client is None
        self._http = client or httpx.Client(timeout=timeout_s)
        self.root = graph_root.rstrip("/")
        self.api = f"{self.root}/{GRAPH_VERSION}"

    def close(self) -> None:
        if self._owns:
            self._http.close()

    # -- transport ---------------------------------------------------------------

    def _call(self, method: str, url: str, *, params: dict[str, Any] | None = None,
              data: dict[str, Any] | None = None) -> dict[str, Any]:
        try:
            resp = self._http.request(method, url, params=params, data=data)
        except httpx.HTTPError as exc:
            cat = "network" if isinstance(exc, _NOT_SENT) else "unknown_outcome"
            raise ThreadsError(f"{method} {url.split('?')[0]}: {type(exc).__name__}: {exc}", category=cat) from exc
        try:
            body = resp.json()
        except ValueError:
            body = None
        if resp.status_code >= 400 or not isinstance(body, dict) or "error" in body:
            err = (body or {}).get("error") if isinstance(body, dict) else None
            if resp.status_code < 400 and not err:
                raise ThreadsError(f"{url.split('?')[0]} returned an unreadable {resp.status_code}",
                                   category="unknown_outcome", status_code=resp.status_code)
            err = err if isinstance(err, dict) else {"message": resp.text[:200]}
            retry_after = 0.0
            try:
                retry_after = float(resp.headers.get("retry-after", "0") or 0)
            except ValueError:
                pass
            raise ThreadsError(
                f"HTTP {resp.status_code} {err.get('type', '')} code={err.get('code')}: {err.get('message', '')}",
                category=_classify(resp.status_code, err), status_code=resp.status_code,
                code=err.get("code") if isinstance(err.get("code"), int) else None, retry_after=retry_after)
        return body

    # -- OAuth (docs: get-access-tokens-and-permissions, long-lived-tokens) -------

    @staticmethod
    def authorize_url(authorize_base: str, *, app_id: str, redirect_uri: str, state: str,
                      scopes: tuple[str, ...]) -> str:
        return authorize_base + "?" + urlencode({
            "client_id": app_id, "redirect_uri": redirect_uri, "scope": ",".join(scopes),
            "response_type": "code", "state": state})

    def exchange_code(self, *, app_id: str, app_secret: str, redirect_uri: str, code: str) -> tuple[str, str]:
        """→ (short-lived token, threads user id)."""
        body = self._call("POST", f"{self.root}/oauth/access_token", data={
            "client_id": app_id, "client_secret": app_secret, "code": code,
            "grant_type": "authorization_code", "redirect_uri": redirect_uri})
        token, user_id = body.get("access_token"), body.get("user_id")
        if not token or not user_id:
            raise ThreadsError("token exchange returned no token/user_id", category="auth")
        return str(token), str(user_id)

    def long_lived(self, *, app_secret: str, short_token: str) -> tuple[str, int]:
        body = self._call("GET", f"{self.root}/access_token", params={
            "grant_type": "th_exchange_token", "client_secret": app_secret, "access_token": short_token})
        return self._token_pair(body)

    def refresh(self, token: str) -> tuple[str, int]:
        body = self._call("GET", f"{self.root}/refresh_access_token", params={
            "grant_type": "th_refresh_token", "access_token": token})
        return self._token_pair(body)

    @staticmethod
    def _token_pair(body: dict[str, Any]) -> tuple[str, int]:
        token, expires = body.get("access_token"), body.get("expires_in")
        if not token or not isinstance(expires, (int, float)):
            raise ThreadsError("token response without access_token/expires_in", category="auth")
        return str(token), int(expires)

    def me(self, token: str) -> dict[str, Any]:
        return self._call("GET", f"{self.api}/me", params={"fields": "id,username,name", "access_token": token})

    # -- publishing (docs: posts, reference/publishing, troubleshooting) ----------

    def create_container(self, user_id: str, token: str, *, text: str, image_url: str = "",
                         alt_text: str = "", topic_tag: str = "") -> str:
        data: dict[str, Any] = {"access_token": token, "text": text,
                                "media_type": "IMAGE" if image_url else "TEXT"}
        if image_url:
            data["image_url"] = image_url
            if alt_text:
                data["alt_text"] = alt_text[:1000]
        if topic_tag:
            data["topic_tag"] = topic_tag
        body = self._call("POST", f"{self.api}/{user_id}/threads", data=data)
        if not body.get("id"):
            raise ThreadsError("container creation returned no id", category="unknown_outcome")
        return str(body["id"])

    def container_status(self, container_id: str, token: str) -> tuple[str, str]:
        body = self._call("GET", f"{self.api}/{container_id}",
                          params={"fields": "status,error_message", "access_token": token})
        return str(body.get("status", "")), str(body.get("error_message", "") or "")

    def publish(self, user_id: str, token: str, creation_id: str) -> str:
        body = self._call("POST", f"{self.api}/{user_id}/threads_publish",
                          data={"creation_id": creation_id, "access_token": token})
        if not body.get("id"):
            raise ThreadsError("publish returned no media id", category="unknown_outcome")
        return str(body["id"])

    def permalink(self, media_id: str, token: str) -> str:
        body = self._call("GET", f"{self.api}/{media_id}", params={"fields": "id,permalink", "access_token": token})
        return str(body.get("permalink", "") or "")

    def recent_posts(self, user_id: str, token: str, *, since_unix: int, limit: int = 25) -> list[dict[str, Any]]:
        body = self._call("GET", f"{self.api}/{user_id}/threads", params={
            "fields": "id,permalink,text,timestamp", "since": since_unix, "limit": limit, "access_token": token})
        data = body.get("data")
        return [d for d in data if isinstance(d, dict)] if isinstance(data, list) else []

    def publishing_limit(self, user_id: str, token: str) -> tuple[int, int, int]:
        """(quota_usage, quota_total, quota_duration_s)."""
        body = self._call("GET", f"{self.api}/{user_id}/threads_publishing_limit",
                          params={"fields": "quota_usage,config", "access_token": token})
        row = (body.get("data") or [{}])[0]
        cfg = row.get("config") or {}
        return int(row.get("quota_usage", 0) or 0), int(cfg.get("quota_total", 0) or 0), \
            int(cfg.get("quota_duration", 0) or 0)


__all__ = ["ThreadsClient", "ThreadsError", "scrub"]
