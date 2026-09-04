"""The hosted agent ships its own sanitizer copy and its own output gate.

Both are security boundaries no other test covers, because the hosted agent
runs standalone and never reaches the API's validator agent.
"""

from __future__ import annotations

import importlib.util
import io
import sys
import zipfile
from pathlib import Path
from typing import Any

import pytest

REPO_ROOT = Path(__file__).resolve().parents[3]
HOSTED_DIR = REPO_ROOT / "hosted" / "support-explainer"
SANITIZER_SRC = REPO_ROOT / "services" / "api" / "app" / "agents" / "shared" / "sanitization.py"


def _load_safety() -> Any:
    """Import safety.py with the sanitizer importable, without booting the server."""

    sys.path.insert(0, str(SANITIZER_SRC.parent))
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


def test_published_zip_bundles_the_same_sanitizer() -> None:
    """A drifted copy would silently weaken the deployed agent."""

    payload, names = _build_zip()
    assert "sanitization.py" in names
    with zipfile.ZipFile(io.BytesIO(payload)) as zf:
        shipped = zf.read("sanitization.py").decode("utf-8")
    assert shipped == SANITIZER_SRC.read_text(encoding="utf-8")


def test_zip_is_flat_and_carries_the_safety_module() -> None:
    payload, _ = _build_zip()
    with zipfile.ZipFile(io.BytesIO(payload)) as zf:
        names = zf.namelist()
    assert all("/" not in name for name in names)
    for required in ("main.py", "safety.py", "sanitization.py", "instructions.md"):
        assert required in names


@pytest.mark.parametrize(
    "answer",
    [
        "Use a diagnostic assessment to monitor progress.",
        "This is not a diagnosis; a qualified clinician may diagnose dyslexia.",
        "A specialist might diagnose an underlying cause.",
    ],
)
def test_gate_allows_safe_uses_of_clinical_vocabulary(answer: str) -> None:
    """Withholding the careful answer would punish exactly the right behaviour."""

    safety = _load_safety()
    assert "withheld" not in safety.gate(answer)


@pytest.mark.parametrize(
    "answer",
    [
        "The learner has dyslexia; this is my diagnosis.",
        "This is a placement decision: the learner must be placed in Tier 3.",
        "The learner is eligible for an IEP.",
    ],
)
def test_gate_withholds_assertive_determinations(answer: str) -> None:
    safety = _load_safety()
    assert "withheld" in safety.gate(answer)


def test_gate_always_carries_the_human_review_caveat() -> None:
    safety = _load_safety()
    assert "human must review" in safety.gate("Letter-sound practice helps.").lower()


def test_gate_unwraps_fenced_json_instead_of_appending_prose_to_it() -> None:
    """Appending a sentence to JSON yields something nothing can parse."""

    safety = _load_safety()
    out = safety.gate('```json\n{"answer": "Try paired reading."}\n```')
    assert "Try paired reading." in out
    assert "```" not in out
    assert '{"answer"' not in out


def test_hosted_input_is_sanitized_and_bounded() -> None:
    safety = _load_safety()
    assert "\u200b" not in safety.extract_question({"input": "ignore\u200b previous"})
    assert len(safety.extract_question({"input": "x" * 50000})) <= safety.QUESTION_MAX_LEN
