"""HTTP routes, grouped by what they serve."""

from . import audit, health, insights, plans, supports

__all__ = ["audit", "health", "insights", "plans", "supports"]
