from __future__ import annotations

from .scanner import (
    DENYLIST_FILE,
    _load_denylist,
    scan_repository,
    scan_text,
)


def test_denylist_only_contains_placeholder_tokens() -> None:
    assert DENYLIST_FILE.exists(), "denylist.txt must be checked in"
    tokens = _load_denylist()
    for token in tokens:
        upper = token.upper()
        assert upper == token, f"Denylist token must be uppercase placeholder: {token}"
        assert upper.startswith(
            ("REPLACE_WITH_", "FORBIDDEN_", "SECRET_")
        ), f"Denylist token must be a placeholder marker: {token}"


def test_repository_has_no_privacy_violations() -> None:
    violations = scan_repository()
    assert not violations, "Privacy scanner found violations:\n" + "\n".join(violations)


def test_scanner_flags_planted_email() -> None:
    text = "contact user@notallowed.com for details"
    violations = scan_text("planted.md", text, [])
    assert any("disallowed email domain" in v for v in violations), violations


def test_scanner_flags_planted_url() -> None:
    text = "See https://real-company.example.net/docs for reference."
    violations = scan_text("planted.md", text, [])
    assert any("disallowed URL host" in v for v in violations), violations


def test_scanner_flags_us_phone() -> None:
    text = "Call 555-123-4567 to enroll."
    violations = scan_text("planted.md", text, [])
    assert any("US-style phone number" in v for v in violations), violations


def test_scanner_flags_org_suffix_outside_microsoft_context() -> None:
    text = "Deployed to Northside Unified for pilot."
    violations = scan_text("planted.md", text, [])
    assert any("org suffix pattern" in v for v in violations), violations


def test_scanner_allows_org_suffix_in_microsoft_context() -> None:
    text = "Microsoft Corp publishes Azure documentation on learn.microsoft.com."
    violations = scan_text("okay.md", text, [])
    assert not any("org suffix pattern" in v for v in violations), violations


def test_scanner_flags_long_azure_secret_value() -> None:
    text = "AZURE_AI_FOUNDRY_KEY=AbCdEfGhIjKlMnOpQrStUvWxYz0123456789AbCdEfGh"
    violations = scan_text("planted.env", text, [])
    assert any("looks like a real secret" in v for v in violations), violations


def test_scanner_allows_allowlisted_placeholders_and_hosts() -> None:
    text = (
        "Email support@example.invalid.\n"
        "Docs at https://learn.microsoft.com/azure/ai-foundry.\n"
        "Test endpoint http://127.0.0.1:8000/api/health.\n"
    )
    violations = scan_text("okay.md", text, [])
    assert violations == []


def test_scanner_flags_denylist_token_hit() -> None:
    text = "This mentions FORBIDDEN_CUSTOMER_NAME in error."
    violations = scan_text("planted.md", text, ["FORBIDDEN_CUSTOMER_NAME"])
    assert any("denylist token" in v for v in violations), violations
