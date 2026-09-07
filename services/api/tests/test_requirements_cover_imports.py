"""Guard against shipping an import that requirements.txt does not declare.

`azure-search-documents` was importable locally but missing from
requirements.txt, so the deployed app returned 500 on every grounded request
while /api/health still reported ok.

Neither top-level module names nor `packages_distributions()` catch this:
azure-identity, azure-ai-projects and azure-search-documents all live under
the shared `azure` namespace. This resolves each import to the file that
provides it, then maps that file back to the distribution that installed it.
"""

from __future__ import annotations

import ast
import sys
from importlib.metadata import distributions
from importlib.util import find_spec
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[3]
APP_DIR = REPO_ROOT / "services" / "api" / "app"
REQUIREMENTS = REPO_ROOT / "services" / "api" / "requirements.txt"


def _normalise(name: str) -> str:
    return name.split("[")[0].strip().lower().replace("_", "-")


def _declared_distributions() -> set[str]:
    declared: set[str] = set()
    for line in REQUIREMENTS.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith(("#", "-")):
            continue
        declared.add(_normalise(line.split("==")[0].split(">=")[0]))
    return declared


def _imported_paths() -> set[tuple[str, ...]]:
    paths: set[tuple[str, ...]] = set()
    for path in APP_DIR.rglob("*.py"):
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                for alias in node.names:
                    paths.add(tuple(alias.name.split(".")))
            elif isinstance(node, ast.ImportFrom) and node.level == 0 and node.module:
                paths.add(tuple(node.module.split(".")))
    return paths


def _file_owners() -> dict[Path, str]:
    """Map every installed file to the distribution that shipped it."""
    owners: dict[Path, str] = {}
    for dist in distributions():
        name = _normalise(dist.metadata["Name"] or "")
        base = dist.locate_file("")
        for rel in dist.files or ():
            try:
                owners[Path(str(base), str(rel)).resolve()] = name
            except (OSError, ValueError):
                continue
    return owners


def _owning_distribution(parts: tuple[str, ...], owners: dict[Path, str]) -> str | None:
    """Distribution providing the most specific importable prefix."""
    for end in range(len(parts), 0, -1):
        module = ".".join(parts[:end])
        try:
            spec = find_spec(module)
        except (ImportError, ValueError):
            continue
        if spec is None or not spec.origin or spec.origin == "built-in":
            continue
        owner = owners.get(Path(spec.origin).resolve())
        if owner:
            return owner
    return None


def test_every_third_party_import_is_declared() -> None:
    stdlib = set(sys.stdlib_module_names)
    declared = _declared_distributions()
    owners = _file_owners()

    missing: dict[str, str] = {}
    for parts in _imported_paths():
        if parts[0] in stdlib or parts[0] == "app" or parts[0].startswith("_"):
            continue
        owner = _owning_distribution(parts, owners)
        if owner and owner not in declared:
            missing[".".join(parts)] = owner

    detail = ", ".join(f"{mod} -> {dist}" for mod, dist in sorted(missing.items()))
    assert not missing, (
        f"imports whose distribution is not in requirements.txt: {detail}. "
        "The deployed app will fail at import time."
    )
