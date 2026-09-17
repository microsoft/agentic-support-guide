"""Privacy guardrail: rule-based scan of tracked source/text.

Rules enforced (any hit = test failure):
- Any RFC-shaped email whose domain is not `example.invalid`, apart from a
  short allowlist of published Microsoft contact addresses.
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
# Trade suffixes only count when a proper name precedes them: "Northside Auto
# Group" identifies a customer, while "dealership" is this domain's ordinary
# type noun and appears in almost every file. Bare "Dealerships" is excluded
# for the same reason - it matched the "Active Dealerships" KPI label.
ORG_SUFFIX_REGEX = re.compile(
    r"\b(?:Inc\.?|LLC|Ltd\.?|Corp\.?|GmbH|PLC)\b"
    r"|\b[A-Z][A-Za-z]{2,}\s+(?:Auto\s+Group|Motor\s+Group|Dealer\s+Group|"
    r"Automotive\s+Group|Motors)\b"
)
LONG_SECRET_REGEX = re.compile(r"[A-Za-z0-9+/=]{40,}")

# UUID/GUID pattern used to detect real subscription/tenant/resource IDs
# when they appear next to identifying keywords on the same line.
GUID_REGEX = re.compile(
    r"\b[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12}\b"
)
# Azure Resource Manager IDs start with `/subscriptions/<guid>/`.
ARM_ID_REGEX = re.compile(r"/subscriptions/[0-9a-fA-F-]{16,}", re.IGNORECASE)
# Local absolute paths that point to real user home directories.
# `/home/site` and `/home/LogFiles` are App Service system paths, not a user's
# home, and appear in any Linux App Service startup command.
LOCAL_HOME_PATH_REGEX = re.compile(
    r"(?:[A-Z]:\\Users\\[^\\/\s]+|/Users/[^/\s]+|/home/(?!site\b|LogFiles\b)[^/\s]+)"
)

# Keyword markers that make a same-line GUID suspicious.
_SENSITIVE_ID_KEYWORDS = (
    "subscription_id",
    "subscription id",
    "tenant_id",
    "tenant id",
    "resource_id",
    "resource id",
    "arm_id",
    "principal_id",
    "principal id",
    "object_id",
    "object id",
    "client_id",
    "client id",
)

ALLOWED_EMAIL_DOMAIN = "example.invalid"

# Microsoft's public Code of Conduct contact. Fixed, published, and required
# verbatim by the standard open-source README boilerplate - not a person.
ALLOWED_EMAILS = {"opencode@microsoft.com"}

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
    # Microsoft open-source governance: Code of Conduct and the CLA bot. Both
    # are required verbatim by the standard README boilerplate.
    "opensource.microsoft.com",
    "cla.opensource.microsoft.com",
    # GitHub's OIDC issuer. Module 1's optional CI section must quote it
    # verbatim: it is the `issuer` of the federated credential, not a link.
    "token.actions.githubusercontent.com",
    "opentelemetry.io",
    "json-schema.org",
    # Public reference sites used as the Module 6 Web IQ allow-list. A web
    # knowledge source needs real, stable public domains to be worth
    # demonstrating. These are US government statistics and the franchised
    # new-car dealer trade body; none carries customer or personal data.
    "www.census.gov",
    "census.gov",
    "www.nada.org",
    "nada.org",
    "www.fueleconomy.gov",
    "fueleconomy.gov",
    # Rendering service called by scripts/render-architecture-diagram.ps1.
    "plantuml.com",
    "www.plantuml.com",
}

# Secret shapes that the AZURE_-prefixed heuristic below does not catch.
# Anchored and length-bounded so ordinary prose cannot trip them: an
# unbounded `sk-\w+` matches "Task-local" in a comment.
SECRET_PATTERNS: tuple[tuple[str, re.Pattern[str]], ...] = (
    ("storage account key", re.compile(r"AccountKey\s*=\s*[A-Za-z0-9+/]{40,}={0,2}")),
    ("shared access signature", re.compile(r"[?&]sig=[A-Za-z0-9%+/]{20,}")),
    ("private key block", re.compile(r"-----BEGIN (?:[A-Z ]+ )?PRIVATE KEY-----")),
    ("openai-style token", re.compile(r"\bsk-[A-Za-z0-9]{32,}\b")),
    ("bearer token literal", re.compile(r"\bBearer\s+ey[A-Za-z0-9_-]{20,}\.")),
)

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
    ".jsonl",
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
    ".hcl",
    # Scripts were unscanned, and they are the files most likely to carry a
    # subscription ID, an endpoint, or a pasted key.
    ".ps1",
    ".sh",
    ".bat",
    ".cmd",
    ".dsl",
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
    # Holds deliberately secret-shaped fixtures that prove the rules fire.
    "test_scanner_rules.py",
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
            # `--others --exclude-standard` adds new, not-yet-committed files.
            # Without them a new file is unscanned until it is already
            # committed, which is exactly when a leak is hardest to undo.
            ["git", "ls-files", "--cached", "--others", "--exclude-standard"],
            cwd=REPO_ROOT,
            capture_output=True,
            text=True,
            check=True,
        )
    except (FileNotFoundError, subprocess.CalledProcessError) as exc:
        # Returning [] here made the whole privacy test pass vacuously on any
        # machine or container without git. A guard that silently disables
        # itself is worse than no guard.
        raise RuntimeError(
            "privacy scanner needs git to enumerate files; refusing to pass vacuously"
        ) from exc
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
        if match.lower() not in ALLOWED_EMAILS and domain != ALLOWED_EMAIL_DOMAIN:
            violations.append(f"{name}: disallowed email domain -> {match}")

    for host in URL_REGEX.findall(text):
        host_lower = host.lower().rstrip(".")
        # Subdomains of example.invalid are also reserved fake hosts (RFC 2606).
        if host_lower in ALLOWED_HOSTS or host_lower.endswith(".example.invalid"):
            continue
        # `example.<anything>` is the placeholder convention used in tests and
        # docs, e.g. example.search.windows.net. Reserved by RFC 2606.
        if host_lower.startswith("example."):
            continue
        violations.append(f"{name}: disallowed URL host -> {host_lower}")

    for match in PHONE_REGEX.findall(text):
        violations.append(f"{name}: US-style phone number -> {match}")

    for label, pattern in SECRET_PATTERNS:
        if pattern.search(text):
            violations.append(f"{name}: possible {label}")

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

        # A GUID sitting next to sensitive-ID keywords on the same line is
        # very likely a real subscription/tenant/resource ID.
        lower = line.lower()
        if any(k in lower for k in _SENSITIVE_ID_KEYWORDS) and GUID_REGEX.search(line):
            # Allow all-zero placeholder GUIDs commonly used in examples.
            for hit in GUID_REGEX.findall(line):
                if hit.replace("-", "").strip("0") != "":
                    violations.append(
                        f"{name}:{line_no}: GUID next to sensitive ID keyword -> {hit}"
                    )

        # Azure Resource Manager IDs.
        for match in ARM_ID_REGEX.findall(line):
            violations.append(
                f"{name}:{line_no}: Azure Resource Manager ID pattern -> {match[:32]}..."
            )

        # Local absolute paths pointing to real user home directories.
        for match in LOCAL_HOME_PATH_REGEX.findall(line):
            violations.append(f"{name}:{line_no}: local user home path -> {match}")

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
