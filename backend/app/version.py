"""Build version for /api/health: GIT_SHA env -> git rev-parse -> "dev"."""

from __future__ import annotations

import os
import subprocess
from functools import lru_cache
from pathlib import Path


@lru_cache(maxsize=1)
def app_version() -> str:
    env_sha = os.environ.get("GIT_SHA", "").strip()
    if env_sha:
        return env_sha
    try:
        out = subprocess.run(
            ["git", "rev-parse", "--short", "HEAD"],
            cwd=Path(__file__).resolve().parent,
            capture_output=True,
            text=True,
            timeout=2,
            check=False,
        )
        sha = out.stdout.strip()
        if out.returncode == 0 and sha:
            return sha
    except (OSError, subprocess.SubprocessError):
        pass
    return "dev"
