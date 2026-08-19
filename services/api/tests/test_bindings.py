from __future__ import annotations

import json
from pathlib import Path

import pytest

from app.foundry_agents import bindings as bindings_mod
from app.foundry_agents.bindings import (
    AgentBinding,
    BindingFileError,
    hash_endpoint,
    hash_instructions,
    load_bindings,
    save_bindings,
)


@pytest.fixture()
def isolated_bindings(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    """Redirect bindings_path() to a tmp file so tests don't touch the real one."""
    fake_dir = tmp_path / ".foundry"
    fake_dir.mkdir()
    fake_path = fake_dir / "agent-bindings.local.json"

    def fake_bindings_path() -> Path:
        return fake_path

    monkeypatch.setattr(bindings_mod, "bindings_path", fake_bindings_path)
    return fake_path


def _binding(role: str, *, endpoint_hash: str = "abc") -> AgentBinding:
    return AgentBinding(
        role=role,
        assistant_id=f"asst_{role}",
        agent_name=f"asg-{role}",
        model="fake-model",
        instructions_hash="0" * 64,
        manifest_version="1.0.0",
        response_format_mode="json_object",
        project_endpoint_hash=endpoint_hash,
        updated_at="2026-01-01T00:00:00Z",
    )


def test_load_bindings_returns_empty_when_file_missing(isolated_bindings: Path) -> None:
    assert not isolated_bindings.exists()
    assert load_bindings() == {}


def test_save_and_load_bindings_round_trip(isolated_bindings: Path) -> None:
    original = {"data-analyst-agent": _binding("data-analyst-agent")}
    save_bindings(original)
    assert isolated_bindings.exists()
    loaded = load_bindings()
    assert set(loaded.keys()) == {"data-analyst-agent"}
    b = loaded["data-analyst-agent"]
    assert b.assistant_id == "asst_data-analyst-agent"
    assert b.agent_name == "asg-data-analyst-agent"
    assert b.project_endpoint_hash == "abc"


def test_save_bindings_writes_deterministic_json(isolated_bindings: Path) -> None:
    save_bindings(
        {
            "b": _binding("b"),
            "a": _binding("a"),
        }
    )
    data = json.loads(isolated_bindings.read_text(encoding="utf-8"))
    # keys sorted alphabetically
    assert list(data.keys()) == ["a", "b"]


def test_load_bindings_rejects_non_object(isolated_bindings: Path) -> None:
    isolated_bindings.write_text("[]", encoding="utf-8")
    with pytest.raises(BindingFileError):
        load_bindings()


def test_load_bindings_rejects_invalid_json(isolated_bindings: Path) -> None:
    isolated_bindings.write_text("{not json", encoding="utf-8")
    with pytest.raises(BindingFileError):
        load_bindings()


def test_hash_endpoint_is_deterministic() -> None:
    a = hash_endpoint("https://foo.example.invalid/api/projects/p")
    b = hash_endpoint("https://foo.example.invalid/api/projects/p")
    assert a == b
    assert len(a) == 64  # sha256 hex


def test_hash_endpoint_differs_by_endpoint() -> None:
    a = hash_endpoint("https://foo.example.invalid/")
    b = hash_endpoint("https://bar.example.invalid/")
    assert a != b


def test_hash_instructions_stable_across_line_endings() -> None:
    lf = "line 1\nline 2\n"
    crlf = "line 1\r\nline 2\r\n"
    assert hash_instructions(lf) == hash_instructions(crlf)


def test_hash_instructions_stable_across_trailing_whitespace() -> None:
    a = "line 1  \nline 2   \n"
    b = "line 1\nline 2\n"
    assert hash_instructions(a) == hash_instructions(b)
