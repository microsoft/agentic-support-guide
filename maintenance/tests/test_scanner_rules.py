"""The privacy scanner's new rules must fire on secrets and stay quiet on prose.

The previous rules were narrow enough that a storage key, a SAS token or a
PEM block passed cleanly, while a naive `sk-\\w+` rule would have flagged the
word "Task-local".
"""

from __future__ import annotations

import pytest

from .scanner import SECRET_PATTERNS


def _labels(text: str) -> set[str]:
    return {label for label, pattern in SECRET_PATTERNS if pattern.search(text)}


@pytest.mark.parametrize(
    ("text", "expected"),
    [
        (
            "DefaultEndpointsProtocol=https;AccountKey=" + "A" * 60 + "==;",
            "storage account key",
        ),
        ("https://x.blob.core.windows.net/c?sv=2024&sig=" + "b" * 40, "shared access signature"),
        ("-----BEGIN RSA PRIVATE KEY-----", "private key block"),
        ("token = 'sk-" + "c" * 40 + "'", "openai-style token"),
        ("Authorization: Bearer eyJhbGciOiJIUzI1NiIsInR5cCI6.abc", "bearer token literal"),
    ],
)
def test_secret_shapes_are_detected(text: str, expected: str) -> None:
    assert expected in _labels(text)


@pytest.mark.parametrize(
    "text",
    [
        # The exact false positive an unbounded sk- rule would produce.
        "# Task-local, so concurrent requests sharing one runtime never interleave",
        "See docs/security-and-privacy.md for the key rotation policy.",
        "AccountKey is never stored in this repository.",
        "sk-short",
        "Use a private key stored in Key Vault.",
    ],
)
def test_ordinary_prose_is_not_flagged(text: str) -> None:
    assert _labels(text) == set()
