"""The editor's dashboard at /admin: authentication and pages."""
from .guard import AdminGuard, GuardStats, same_origin
from .pages import (
    REVIEW_TABS,
    FeedStatus,
    ReviewEntry,
    classify_sources,
    render_feedback,
    render_not_found,
    render_overview,
    render_quality,
    render_review,
    render_sources,
)
from .intel_page import render_intel
from .ui import CSP, CSP_FORMS

__all__ = [
    "CSP", "CSP_FORMS", "REVIEW_TABS", "AdminGuard", "FeedStatus", "GuardStats", "ReviewEntry",
    "classify_sources", "render_feedback", "render_not_found", "render_overview",
    "render_intel", "render_quality", "render_review", "render_sources", "same_origin",
]
