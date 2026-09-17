"""The dealer group roster for the synthetic workshop dataset.

One definition, because three places need the same answer: the supports
router rejects an unknown group against it, diagnostics checks evidence
coverage, and the UI offers it as a picker. When these drifted apart the UI
simply hardcoded `GROUP-DEMO`.

A dealer group is an ownership boundary, not a franchise brand: one group may
sell several brands, and two groups selling the same brand must never see each
other's data.

Replacing the mock data means replacing this with a lookup against the real
group registry.
"""

from __future__ import annotations

KNOWN_DEALER_GROUPS: tuple[str, ...] = ("GROUP-A", "GROUP-B", "GROUP-DEMO")

# Seeded plans and the guided builder default here.
DEMO_DEALER_GROUP = "GROUP-DEMO"
