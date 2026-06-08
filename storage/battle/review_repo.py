"""Compatibility wrapper for the canonical review stores."""

from __future__ import annotations

from storage.review_store import CounterfactualStore, DecisionReviewStore

__all__ = ["DecisionReviewStore", "CounterfactualStore"]
