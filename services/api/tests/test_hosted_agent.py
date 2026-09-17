"""The hosted agent ships its own copy of the shared modules and its own output gate.

Both are security boundaries no other test covers, because the hosted agent
runs standalone and never reaches the API's validator agent.
"""

from __future__ import annotations

import hashlib
import importlib.util
import io
import sys
import zipfile
from pathlib import Path
from typing import Any

import pytest

REPO_ROOT = Path(__file__).resolve().parents[3]
HOSTED_DIR = REPO_ROOT / "hosted" / "support-explainer"
SHARED_DIR = REPO_ROOT / "services" / "api" / "app" / "agents" / "shared"
SHARED_MODULES = ("prompt_blocks.py", "determinations.py")


def _load_safety() -> Any:
    """Import safety.py with its shared deps importable, without booting the server."""

    sys.path.insert(0, str(SHARED_DIR))
    spec = importlib.util.spec_from_file_location("hosted_safety", HOSTED_DIR / "safety.py")
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _build_zip() -> tuple[bytes, list[str]]:
    sys.path.insert(0, str(REPO_ROOT / "scripts"))
    import publish_hosted_agent  # type: ignore[import-not-found]

    payload, names = publish_hosted_agent._build_zip()
    return bytes(payload), list(names)


@pytest.mark.parametrize("module", SHARED_MODULES)
def test_published_zip_bundles_the_same_shared_modules(module: str) -> None:
    """A drifted copy would silently weaken the deployed agent."""

    payload, names = _build_zip()
    assert module in names
    with zipfile.ZipFile(io.BytesIO(payload)) as zf:
        shipped = zf.read(module).decode("utf-8")
    assert shipped == (SHARED_DIR / module).read_text(encoding="utf-8")


def test_zip_is_flat_and_carries_the_safety_module() -> None:
    payload, _ = _build_zip()
    with zipfile.ZipFile(io.BytesIO(payload)) as zf:
        names = zf.namelist()
    assert all("/" not in name for name in names)
    for required in ("main.py", "safety.py", "instructions.md", *SHARED_MODULES):
        assert required in names


def test_zip_is_byte_identical_across_builds() -> None:
    """Module 5 has learners compare the sha256 across runs.

    `writestr` defaults each entry's timestamp to now, which made the hash
    change on every build and the exercise fail at random.
    """

    first, _ = _build_zip()
    second, _ = _build_zip()
    assert hashlib.sha256(first).hexdigest() == hashlib.sha256(second).hexdigest()


@pytest.mark.parametrize(
    "answer",
    [
        "Use a diagnostic checklist to monitor the enquiry process.",
        "This is not a credit decision; a qualified lender may approve financing.",
        "A specialist might inspect the vehicle before it is listed.",
    ],
)
def test_gate_allows_safe_uses_of_restricted_vocabulary(answer: str) -> None:
    """Withholding the careful answer would punish exactly the right behaviour."""

    safety = _load_safety()
    assert "withheld" not in safety.gate(answer)


@pytest.mark.parametrize(
    "answer",
    [
        "Your trade-in is worth $8,500.",
        "This vehicle has no open recalls and is safe to drive.",
        "You are approved for financing at 4.9% APR.",
        # Cue in the previous sentence: the old window let this through.
        "A qualified inspector agrees. This is our credit decision.",
    ],
)
def test_gate_withholds_assertive_determinations(answer: str) -> None:
    safety = _load_safety()
    assert "withheld" in safety.gate(answer)


@pytest.mark.parametrize(
    "answer",
    [
        "No human review is needed.",
        "Human review is not required for this change.",
    ],
)
def test_gate_refuses_to_pass_on_a_claim_that_review_can_be_skipped(answer: str) -> None:
    """This previously matched the "human review" check and returned unchanged."""

    safety = _load_safety()
    out = safety.gate(answer)
    assert "withheld" in out
    assert "human must review" in out.lower()


def test_gate_always_carries_the_human_review_caveat() -> None:
    safety = _load_safety()
    assert "human must review" in safety.gate("Faster first replies help.").lower()


def test_gate_unwraps_fenced_json_instead_of_appending_prose_to_it() -> None:
    """Appending a sentence to JSON yields something nothing can parse."""

    safety = _load_safety()
    out = safety.gate('```json\n{"answer": "Try a same-day follow-up."}\n```')
    assert "Try a same-day follow-up." in out
    assert "```" not in out


def test_question_extraction_is_bounded_before_normalising() -> None:
    """The endpoint is internet-facing; breadth was unbounded, only depth was."""

    safety = _load_safety()
    blocks = [{"type": "text", "text": "x" * 200} for _ in range(20_000)]
    assert len(safety.extract_question({"input": blocks})) <= safety.QUESTION_MAX_LEN


def test_hosted_input_is_bounded() -> None:
    safety = _load_safety()
    assert len(safety.extract_question({"input": "x" * 50000})) <= safety.QUESTION_MAX_LEN
