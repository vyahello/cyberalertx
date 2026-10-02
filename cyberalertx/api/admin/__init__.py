"""The editor's dashboard at /admin: authentication and pages."""
from .guard import AdminGuard, GuardStats
from .pages import (
    FeedStatus,
    classify_sources,
    render_feedback,
    render_not_found,
    render_overview,
    render_quality,
    render_sources,
)
from .ui import CSP

__all__ = [
    "CSP", "AdminGuard", "FeedStatus", "GuardStats", "classify_sources", "render_feedback",
    "render_not_found", "render_overview", "render_quality", "render_sources",
]
