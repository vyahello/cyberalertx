# Prints the settings the release code actually resolves from the environment. No secrets.
import os
from cyberalertx.ai.config import AISettings
from cyberalertx.ai.review import review_mode
from cyberalertx.media.illustrations import provider_from_env
from cyberalertx.pipeline.relevance import hide_out_of_scope_publicly
from cyberalertx.publish.config import build_telegram_settings
from cyberalertx.publish.orchestrator import PublishPolicy
from cyberalertx.threads.config import ThreadsSettings
p = PublishPolicy.from_env(None)
rows = {
    "fact_sheet_enabled": AISettings().fact_sheet_enabled,
    "threads_publish_enabled": ThreadsSettings.from_env().publish_enabled,
    "telegram_attach_images": build_telegram_settings().attach_images,
    "hide_out_of_scope_publicly": hide_out_of_scope_publicly(),
    "review_mode": review_mode() + ("  (CYBERALERTX_REVIEW_MODE unset)" if "CYBERALERTX_REVIEW_MODE" not in os.environ else ""),
    "top10_slot": p.top10_at or "(off)",
    "breaking_updates": p.breaking_updates,
    "image_provider": provider_from_env().name,
}
for k, v in rows.items(): print(f"{k:28} {v}")
