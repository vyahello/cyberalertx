"""Threads (Meta) integration: account connections, OAuth, publishing adapter.

    config.py       settings from the environment (all optional; off by default)
    accounts.py     account slots, encrypted token storage, OAuth state
    client.py       the Threads Graph API calls we use, with error classification
    oauth.py        connect / callback / refresh / verify flows
    format.py       Threads-native EN/UA post text
    destination.py  the Publication Engine adapter (one instance per account)

See docs/threads/THREADS_SETUP.md.
"""
