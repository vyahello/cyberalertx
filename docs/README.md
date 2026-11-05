# CyberAlertX documentation

**Current** documents describe how the system works and how to operate it
today. **Reference** documents are stable background. **Historical** records
describe a completed phase or change; they keep their original facts and are
marked as such at the top.

## Current

| Document | What it covers |
|---|---|
| [architecture.md](architecture.md) | Components, data flow, storage model, deployment model |
| [operations/OPERATIONS.md](operations/OPERATIONS.md) | Release layout, build / switch / rollback, backups, consistency model, publishing hold, recovery |
| [media/IMAGE_GENERATION.md](media/IMAGE_GENERATION.md) | Article illustrations: host findings, SVG generator, ComfyUI status, backfill |
| [release/OPEN_ISSUES.md](release/OPEN_ISSUES.md) | Register of open and resolved issues |
| [release/O28_RECONCILIATION_RUNBOOK.md](release/O28_RECONCILIATION_RUNBOOK.md) | JSON → Postgres re-sync procedure |
| [release/ROLLBACK_RUNBOOK.md](release/ROLLBACK_RUNBOOK.md) | Undoing Stage D; migration 005 notes |
| [editorial/EDITORIAL_REVIEW_PROCESS.md](editorial/EDITORIAL_REVIEW_PROCESS.md) | Review modes, the evidence gate, daily routine |
| [editorial/TELEGRAM_FORMAT.md](editorial/TELEGRAM_FORMAT.md) | Telegram post format: structure, emoji, accuracy rules, evaluation |
| [../server/README.md](../server/README.md) | Units, logs, analytics, maintenance tools on the host |
| [threads/THREADS_SETUP.md](threads/THREADS_SETUP.md) | Threads integration setup (publishing is off) |

## Reference

| Document | What it covers |
|---|---|
| [design/DESIGN_SYSTEM.md](design/DESIGN_SYSTEM.md) | Visual identity, tokens, components |
| [editorial/ENGLISH_STYLE_GUIDE.md](editorial/ENGLISH_STYLE_GUIDE.md), [editorial/UKRAINIAN_STYLE_GUIDE.md](editorial/UKRAINIAN_STYLE_GUIDE.md) | House style per language |
| [editorial/UKRAINIAN_CYBERSECURITY_GLOSSARY.md](editorial/UKRAINIAN_CYBERSECURITY_GLOSSARY.md) | Ukrainian terminology |
| [editorial/BENCHMARK_EXAMPLES.md](editorial/BENCHMARK_EXAMPLES.md) | Before/after brief examples |
| [intel/INTELLIGENCE.md](intel/INTELLIGENCE.md), [intel/STORIES_AND_EVIDENCE.md](intel/STORIES_AND_EVIDENCE.md) | Story clustering, scoring, relevance |
| [media/MEDIA_ENGINE.md](media/MEDIA_ENGINE.md) | Share cards, asset store, illustration routes |
| [publish/PUBLICATION_ENGINE.md](publish/PUBLICATION_ENGINE.md) | Telegram publication engine: queue, ledger, message format |
| [admin/ADMIN_DASHBOARD.md](admin/ADMIN_DASHBOARD.md) | `/admin` control room |

## Historical records

| Document | Record of |
|---|---|
| [release/RELEASE_2026-11-05.md](release/RELEASE_2026-11-05.md) | Production release `b509775` (O27/O28 cutover), 5 Nov 2026 |
| [release/O27_API_READ_PATH_REPORT.md](release/O27_API_READ_PATH_REPORT.md) | O27 investigation and benchmark |
| [release/O28_REVIEW_PERSISTENCE_REPORT.md](release/O28_REVIEW_PERSISTENCE_REPORT.md) | O28 investigation |
| [release/SINGLE_REPOSITORY_CONSOLIDATION_REPORT.md](release/SINGLE_REPOSITORY_CONSOLIDATION_REPORT.md) | Checkout consolidation, 4 Nov 2026 |
| [release/STAGE_C_RUNBOOK.md](release/STAGE_C_RUNBOOK.md), [release/STAGE_C_REPORT.md](release/STAGE_C_REPORT.md) | Stage C cutover, 4 Nov 2026 (procedure deprecated) |
| [release/DEPLOYMENT_RUNBOOK.md](release/DEPLOYMENT_RUNBOOK.md), [release/PRODUCTION_READINESS.md](release/PRODUCTION_READINESS.md), [release/SECURITY_REMEDIATION.md](release/SECURITY_REMEDIATION.md) | Phase 7 release preparation |
| [editorial/EDITORIAL_QUALITY_UPGRADE_REPORT.md](editorial/EDITORIAL_QUALITY_UPGRADE_REPORT.md), [editorial/CONTENT_AUDIT.md](editorial/CONTENT_AUDIT.md) | Editorial quality upgrade |
| [audit/BASELINE_AUDIT.md](audit/BASELINE_AUDIT.md), [REDESIGN_REPORT.md](REDESIGN_REPORT.md) | Baseline audit and redesign |
| [intel/PHASE2_REPORT.md](intel/PHASE2_REPORT.md), [media/PHASE3_REPORT.md](media/PHASE3_REPORT.md), [publish/PHASE4_REPORT.md](publish/PHASE4_REPORT.md), [threads/PHASE5_REPORT.md](threads/PHASE5_REPORT.md), [admin/PHASE6_REPORT.md](admin/PHASE6_REPORT.md) | Phases 2–6 |
| [telegram-publisher-discovery.md](telegram-publisher-discovery.md) | Discovery of the legacy Telegram publisher |
