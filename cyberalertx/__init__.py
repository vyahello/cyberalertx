"""CyberAlertX package init.

The .env loader fires here, BEFORE any submodule is imported, so that
dataclass-field defaults like
    fetch_interval_minutes: int = int(os.getenv("CYBERALERTX_INTERVAL_MIN", "15"))
see the values from .env when the dataclass is evaluated.

Loader contract:
  * Soft fail when python-dotenv is not installed (no hard dependency).
  * `override=False` — values already in the real environment (shell,
    CI, docker-compose, pytest monkeypatch) WIN over .env.
  * Loaded once per process. No-op when .env is absent.
"""
__version__ = "0.1.0"


def _load_dotenv_if_available() -> None:
    try:
        from dotenv import find_dotenv, load_dotenv
    except ImportError:
        # python-dotenv not installed — that's fine for ops paths that
        # set env vars directly (Docker, systemd, CI). The package
        # works without it.
        return
    # find_dotenv walks up from the caller's directory and returns ""
    # if nothing's found. load_dotenv("") is a no-op.
    load_dotenv(find_dotenv(usecwd=True), override=False)


_load_dotenv_if_available()
