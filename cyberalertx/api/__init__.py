"""HTTP API layer.

Exposes the existing JsonNewsStore + ContentGenerator over a thin FastAPI
surface for the Next.js frontend (or any other consumer).

Kept deliberately minimal:
  * Three GET endpoints — no auth, no DB beyond the existing JSON store.
  * Re-uses the AI layer's existing on-disk cache so a hot request is
    essentially a JSON file read + dict merge.
  * No background workers. Posts are generated on demand and the result
    cached by NewsItem fingerprint; ordering work happens in-process.
"""
from .app import build_app

__all__ = ["build_app"]
