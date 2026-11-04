"""Story-level intelligence layer (SHADOW / EVALUATION ONLY).

Computes, per story (a cluster of NewsItems from `pipeline.dedup`):

  * an importance score 0-100 (`scoring.py`) — transparent, deterministic,
    reproducible, weights in `config.py`;
  * three dimensions kept apart from that score (`dimensions.py`):
    confidence, verification_status, exploitation_status;
  * a daily Top 10 (`selection.py`), a Trending classification
    (`trending.py`) and a Breaking classification with per-story alert
    state (`breaking.py`).

Nothing in this package changes the public feed, the public API, the
existing `threat_score`, Telegram, or anything that is published. Results
are written under `data/intel/` by `python -m cyberalertx.tools.intel
evaluate` and shown on the token-locked `/admin/intel` page. See
`docs/intel/INTELLIGENCE.md`.
"""
from .config import CALCULATION_VERSION, IntelConfig, load_config

__all__ = ["CALCULATION_VERSION", "IntelConfig", "load_config"]
