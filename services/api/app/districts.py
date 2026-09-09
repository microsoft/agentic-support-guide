"""The district roster for the synthetic workshop dataset.

One definition, because three places need the same answer: `/api/me` resolves
a facilitator's usable districts against it, diagnostics checks evidence
coverage, and the UI offers it as a picker. When these drifted apart the UI
simply hardcoded `DIST-DEMO`.

Replacing the mock data means replacing this with a lookup against the real
district registry.
"""

from __future__ import annotations

KNOWN_DISTRICTS: tuple[str, ...] = ("DIST-A", "DIST-B", "DIST-DEMO")

# Seeded plans and the guided builder default here.
DEMO_DISTRICT = "DIST-DEMO"
