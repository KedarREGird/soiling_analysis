"""Environment helpers for database-backed soiling analysis tools."""
from __future__ import annotations

import os
from pathlib import Path


TIGERDATA_ENV_VARS = (
    "TIGERDATA_HOST",
    "TIGERDATA_PORT",
    "TIGERDATA_DB",
    "TIGERDATA_USER",
    "TIGERDATA_PASSWORD",
)


def load_env_file(path: str | Path = ".env") -> None:
    """Load simple KEY=VALUE lines from an env file without overwriting exports."""
    env_path = Path(path)
    if not env_path.exists():
        return

    for line in env_path.read_text().splitlines():
        stripped = line.strip()
        if not stripped or stripped.startswith("#") or "=" not in stripped:
            continue
        key, _, value = stripped.partition("=")
        os.environ.setdefault(key.strip(), value.strip().strip("\"'"))


def tigerdata_connect_kwargs() -> dict[str, object]:
    """Return psycopg2 connection kwargs from TIGERDATA_* environment variables."""
    missing = [name for name in TIGERDATA_ENV_VARS if not os.environ.get(name)]
    if missing:
        joined = ", ".join(missing)
        raise RuntimeError(f"Missing required environment variable(s): {joined}")

    return {
        "host": os.environ["TIGERDATA_HOST"],
        "port": int(os.environ["TIGERDATA_PORT"]),
        "dbname": os.environ["TIGERDATA_DB"],
        "user": os.environ["TIGERDATA_USER"],
        "password": os.environ["TIGERDATA_PASSWORD"],
        "sslmode": os.environ.get("TIGERDATA_SSLMODE", "require"),
        "connect_timeout": int(os.environ.get("TIGERDATA_CONNECT_TIMEOUT", "10")),
    }
