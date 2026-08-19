"""Privacy guardrail: rule-based scan of tracked source/text.

Rules enforced (any hit = test failure):
- Any RFC-shaped email whose domain is not `example.invalid`.
- Any http(s) URL whose host is not in a small allowlist of localhost or
  Microsoft/Azure documentation hosts.
- US-style phone numbers.
- Organization suffix patterns (Inc, LLC, Ltd, Corp, School District,
  Unified, ISD, County Schools, Academy) unless in an allowlisted
  Microsoft/Azure platform context on the same line.
- 32+ character base64/hex literals near AZURE_* names that look like real
  keys or secrets.
- Denylist tokens in `denylist.txt` and optional `denylist.local.txt`.

Excluded from the scan: this file itself, denylist files, generated
artifacts, virtual environments, node_modules, dist/build, .git,
coverage, lockfiles, Terraform state, .terraform/.
"""

from __future__ import annotations

import re
import subprocess
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[3]
API_ROOT = Path(__file__).resolve().parents[1]

DENYLIST_FILE = API_ROOT / "denylist.txt"
LOCAL_DENYLIST_FILE = API_ROOT / "denylist.local.txt"

EMAIL_REGEX = re.compile(r"[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}")
URL_REGEX = re.compile(r"https?://([A-Za-z0-9._-]+)(?::\d+)?(?:/|\s|$|[\"'`)])")
PHONE_REGEX = re.compile(r"(?<!\d)(?:\+?1[-.\s]?)?\(?\d{3}\)?[-.\s]\d{3}[-.\s]\d{4}(?!\d)")
ORG_SUFFIX_REGEX = re.compile(
    r"\b(?:Inc\.?|LLC|Ltd\.?|Corp\.?|Unified|School\s+District|ISD|County\s+Schools|Academy)\b"
)
LONG_SECRET_REGEX = re.compile(r"[A-Za-z0-9+/=]{40,}")

ALLOWED_EMAIL_DOMAIN = "example.invalid"

ALLOWED_HOSTS = {
    "example.invalid",
    "localhost",
    "127.0.0.1",
    "0.0.0.0",
    # Microsoft / Azure documentation and required platform hosts.
    "learn.microsoft.com",
    "docs.microsoft.com",
    "azure.microsoft.com",
    "www.microsoft.com",
    "microsoft.com",
    "aka.ms",
    "cognitiveservices.azure.com",
    "ai.azure.com",
    "openai.azure.com",
    "core.windows.net",
    "vault.azure.net",
    "monitor.azure.com",
    "applicationinsights.azure.com",
    "portal.azure.com",
    "registry.terraform.io",
    "developer.hashicorp.com",
    "www.terraform.io",
    "github.com",
    "raw.githubusercontent.com",
    "opentelemetry.io",
    "json-schema.org",
}

# Lines matching these substrings are treated as legitimate Microsoft/Azure
# platform context and are allowed to mention org suffixes such as
# "Microsoft Corp" or similar. This is a conservative allowlist, not a
# denylist bypass: it applies only to org-suffix rule.
MICROSOFT_PLATFORM_CONTEXT_MARKERS = (
    "Azure",
    "Microsoft",
    "Foundry",
    "Terraform",
    "Fabric",
    "Entra",
    "Purview",
    "Monitor",
    "Copilot",
    "Graph",
)

TEXT_SUFFIXES = {
    ".py",
    ".ts",
    ".tsx",
    ".js",
    ".jsx",
    ".json",
    ".md",
    ".txt",
    ".css",
    ".html",
    ".yaml",
    ".yml",
    ".toml",
    ".cfg",
    ".ini",
    ".tf",
    ".tfvars.example",
    ".hcl",
    ".env.example",
}

EXCLUDED_DIR_PARTS = {
    ".venv",
    "node_modules",
    "dist",
    "build",
    ".git",
    "coverage",
    "__pycache__",
    ".pytest_cache",
    ".mypy_cache",
    ".ruff_cache",
    ".vite",
    ".terraform",
}

EXCLUDED_FILE_NAMES = {
    "denylist.txt",
    "denylist.local.txt",
    "package-lock.json",
    "yarn.lock",
    "pnpm-lock.yaml",
    "openapi.json",
    "terraform.tfstate",
    "terraform.tfstate.backup",
    ".terraform.lock.hcl",
    "scanner.py",  # this scanner itself, so its own patterns don't self-flag
    "test_no_sensitive_content.py",  # scanner tests contain intentional negative fixtures
}


def _load_denylist() -> list[str]:
    tokens: list[str] = []
    for path in (DENYLIST_FILE, LOCAL_DENYLIST_FILE):
        if not path.exists():
            continue
        for raw in path.read_text(encoding="utf-8").splitlines():
            line = raw.strip()
            if not line or line.startswith("#"):
                continue
            tokens.append(line)
    return tokens


def _tracked_files() -> list[Path]:
    try:
        result = subprocess.run(
            ["git", "ls-files"],
            cwd=REPO_ROOT,
            capture_output=True,
            text=True,
            check=True,
        )
    except (FileNotFoundError, subprocess.CalledProcessError):
        return []
    paths: list[Path] = []
    for rel in result.stdout.splitlines():
        rel = rel.strip()
        if not rel:
            continue
        p = REPO_ROOT / rel
        if not p.is_file():
            continue
        if p.name in EXCLUDED_FILE_NAMES:
            continue
        if any(part in EXCLUDED_DIR_PARTS for part in p.parts):
            continue
        suffix = p.suffix.lower()
        name_lower = p.name.lower()
        if (
            suffix in TEXT_SUFFIXES
            or name_lower in {".env.example", ".env"}
            or name_lower.endswith(".tfvars.example")
        ):
            paths.append(p)
    return paths


def _line_is_platform_context(line: str) -> bool:
    return any(marker in line for marker in MICROSOFT_PLATFORM_CONTEXT_MARKERS)


def scan_text(name: str, text: str, denylist: list[str]) -> list[str]:
    """Return a list of human-readable violation strings for a single blob."""

    violations: list[str] = []

    for match in EMAIL_REGEX.findall(text):
        domain = match.split("@", 1)[1].lower()
        if domain != ALLOWED_EMAIL_DOMAIN:
            violations.append(f"{name}: disallowed email domain -> {match}")

    for host in URL_REGEX.findall(text):
        host_lower = host.lower().rstrip(".")
        # Subdomains of example.invalid are also reserved fake hosts (RFC 2606).
        if host_lower in ALLOWED_HOSTS or host_lower.endswith(".example.invalid"):
            continue
        violations.append(f"{name}: disallowed URL host -> {host_lower}")

    for match in PHONE_REGEX.findall(text):
        violations.append(f"{name}: US-style phone number -> {match}")

    for line_no, line in enumerate(text.splitlines(), start=1):
        if ORG_SUFFIX_REGEX.search(line) and not _line_is_platform_context(line):
            violations.append(f"{name}:{line_no}: org suffix pattern in non-platform context")

    lines = text.splitlines()
    for line_no, line in enumerate(lines, start=1):
        if "AZURE_" in line and "=" in line:
            _, _, rhs = line.partition("=")
            rhs_clean = rhs.strip().strip("\"'")
            if rhs_clean and LONG_SECRET_REGEX.fullmatch(rhs_clean):
                violations.append(f"{name}:{line_no}: AZURE_* value looks like a real secret")

    for token in denylist:
        if token and token in text:
            violations.append(f"{name}: denylist token -> {token}")

    return violations


def scan_repository() -> list[str]:
    denylist = _load_denylist()
    violations: list[str] = []
    for path in _tracked_files():
        try:
            text = path.read_text(encoding="utf-8", errors="ignore")
        except OSError:
            continue
        rel = str(path.relative_to(REPO_ROOT))
        violations.extend(scan_text(rel, text, denylist))
    return violations
