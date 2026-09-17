"""The web knowledge source encodes a service constraint that is easy to miss.

Azure AI Search rejects `include_subpages=True` on an address more than two
path segments deep. Module 6 hands learners a four-segment census.gov URL, so
hardcoding the flag made the documented command fail outright.
"""

from __future__ import annotations

import importlib.util
import sys
from pathlib import Path
from typing import Any

import pytest

REPO_ROOT = Path(__file__).resolve().parents[3]


def _load() -> Any:
    path = REPO_ROOT / "scripts" / "provision_foundry_iq.py"
    spec = importlib.util.spec_from_file_location("provision_foundry_iq", path)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    sys.modules["provision_foundry_iq"] = module
    spec.loader.exec_module(module)
    return module


@pytest.mark.parametrize(
    ("address", "depth"),
    [
        ("https://www.census.gov", 0),
        ("https://www.census.gov/econ", 1),
        ("https://www.census.gov/econ/indviz", 2),
        ("https://www.census.gov/econ/indviz/auto/main.html", 4),
        ("https://www.census.gov/econ/", 1),
    ],
)
def test_path_depth_counts_segments(address: str, depth: int) -> None:
    assert _load()._path_depth(address) == depth


def test_the_documented_census_url_is_too_deep_for_subpages() -> None:
    """The URL in Module 6 must resolve to include_subpages=False."""

    module = _load()
    documented = "https://www.census.gov/econ/indviz/auto/main.html"
    assert module._path_depth(documented) > 2
