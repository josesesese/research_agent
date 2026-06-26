"""Runtime configuration helpers for the Research Agent."""

from __future__ import annotations

import os
from pathlib import Path


def project_root() -> Path:
    """Return the repository root that contains the local .env file."""
    return Path(__file__).resolve().parents[2]


def load_environment(env_path: Path | None = None) -> Path:
    """Load environment variables from the project .env file.

    The normal path uses python-dotenv. A small fallback parser keeps local
    runs usable if the optional package is missing, while never overriding
    variables that are already set in the shell.
    """
    path = env_path or project_root() / ".env"
    if not path.exists():
        return path

    try:
        from dotenv import load_dotenv
    except ImportError:
        _load_env_fallback(path)
        return path

    load_dotenv(dotenv_path=path, override=False)
    return path


def _load_env_fallback(path: Path) -> None:
    for raw_line in path.read_text(encoding="utf-8").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        key = key.strip()
        value = value.strip().strip('"').strip("'")
        if key and key not in os.environ:
            os.environ[key] = value
