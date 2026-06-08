"""Compatibility import for evolution experience candidates.

Experience candidates are evolution-only data and must be written through
``storage.evolution.experience_repo`` so run-type eligibility is enforced.
"""

from __future__ import annotations

from storage.evolution.experience_repo import ExperienceCandidateStore

__all__ = ["ExperienceCandidateStore"]
