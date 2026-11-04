"""Operations read models for the admin control room.

    audit.py      append-only admin audit log (who did what, to what, result)
    usage.py      per-call AI usage ledger + aggregation (measured / estimated / unavailable)
    readmodel.py  cached, read-only views over the existing stores: overview,
                  pipeline, destinations, activity, stories, search
    health.py     system health checks (healthy / warning / critical / unknown /
                  not_configured)

Nothing here calls an AI provider, sends a message or writes to a content
store; the audit and usage ledgers are the only files it appends to.
"""
