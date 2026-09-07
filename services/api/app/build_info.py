"""Identify which build is actually serving.

A successful `az webapp deploy` does not guarantee the new code is live:
Oryx can skip the rebuild and the previous worker can keep serving. Without
a stamp, a stale deployment is indistinguishable from a good one.

`deploy-app.ps1` writes `build_id.txt` next to `contracts/` in the zip and
then polls `/api/health` until the served build_id matches what it shipped.
"""

from __future__ import annotations

import os
from pathlib import Path

_REPO_ROOT = Path(__file__).resolve().parents[3]
_BUILD_ID_FILE = _REPO_ROOT / "build_id.txt"

UNKNOWN_BUILD = "unknown"


def current_build_id() -> str:
    """Build stamp written at package time, or BUILD_ID, or 'unknown'."""
    env_value = os.environ.get("BUILD_ID", "").strip()
    if env_value:
        return env_value
    try:
        return _BUILD_ID_FILE.read_text(encoding="utf-8").strip() or UNKNOWN_BUILD
    except OSError:
        return UNKNOWN_BUILD
