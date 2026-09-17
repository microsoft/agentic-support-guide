"""The screenshot redaction checker must actually detect what it claims to.

Three separate redaction passes in this repo reported "clean" while a real
identifier was sitting in the output: an allowlist that missed a tenant admin
UPN, a residual check reading `innerText` (which omits `<input>` values), and
a top-frame-only scan of a portal that renders blades in iframes. Each looked
green. The pattern is always the same - the check ran, found nothing, and
nothing was there to find because it was looking in the wrong place.

So this asserts the detector can still fail. It exercises the matching logic
directly rather than the OCR engine, because the matching logic is what silently
stops matching when someone edits the config.
"""

from __future__ import annotations

import importlib.util
import json
import sys
from pathlib import Path
from types import ModuleType

import pytest

REPO_ROOT = Path(__file__).resolve().parents[3]
CHECKER = REPO_ROOT / "scripts" / "check_screenshot_redaction.py"
CONFIG_EXAMPLE = REPO_ROOT / "scripts" / "portal_redact.config.example.json"


def _load_checker() -> ModuleType:
    spec = importlib.util.spec_from_file_location("check_screenshot_redaction", CHECKER)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


CONFIG = {
    "literals": [["zz9xq2", "abc123"], ["ContosoTenantName", "Contoso"]],
    "allowedEmailDomains": ["example.invalid"],
    "allowedGuids": ["00000000-0000-0000-0000-000000000000"],
}

# The repo's own privacy scanner only permits `example.invalid` addresses, so an
# address that must be DETECTED cannot use a different domain. Allowing no
# domains at all makes the same address a positive case.
STRICT_CONFIG = {**CONFIG, "allowedEmailDomains": []}


@pytest.fixture(scope="module")
def checker() -> ModuleType:
    return _load_checker()


@pytest.mark.parametrize(
    "text",
    [
        "Resource group: rg-agentic-support-guide-zz9xq2",
        "Directory: ContosoTenantName.onmicrosoft.com",
        "12345678-1234-1234-1234-123456789abc",
    ],
)
def test_detects_identifiers(checker: ModuleType, text: str) -> None:
    assert checker._findings(text, CONFIG), f"detector missed: {text!r}"


def test_detects_email_outside_allowed_domains(checker: ModuleType) -> None:
    assert checker._findings("Created by: admin@example.invalid", STRICT_CONFIG)


@pytest.mark.parametrize(
    "text",
    [
        "Resource group: rg-agentic-support-guide-abc123",
        "Created by: learner@example.invalid",
        "00000000-0000-0000-0000-000000000000",
        "Status Running  Runtime status Healthy",
    ],
)
def test_passes_redacted_text(checker: ModuleType, text: str) -> None:
    assert not checker._findings(text, CONFIG), f"false positive on: {text!r}"


def test_ocr_confusions_do_not_defeat_literal_matching(checker: ModuleType) -> None:
    # OCR routinely reads 0 as o and 1 as l. A leak must not slip through on a
    # misread character, so both sides are normalised before comparison.
    config = {**CONFIG, "literals": [["st0rage1d", "placeholder"]]}
    misread = "Account name: storageld"
    assert misread != "Account name: st0rage1d"
    assert checker._findings(misread, config), "confusion normalisation is not working"


def test_example_config_ships_placeholders_not_real_values() -> None:
    config = json.loads(CONFIG_EXAMPLE.read_text(encoding="utf-8"))
    for needle, _replacement in config["literals"]:
        assert needle.startswith("<") and needle.endswith(">"), (
            f"{CONFIG_EXAMPLE.name} must contain placeholders, not real identifiers: {needle!r}"
        )
