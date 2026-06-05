"""Programmatic deduplication of skill proposals against rejected buffer."""
from __future__ import annotations

import logging
import re
from typing import Any

_log = logging.getLogger(__name__)


def deduplicate_proposals(
    proposals: list[dict[str, Any]],
    rejected: list[dict[str, Any]],
    *,
    similarity_threshold: float = 0.7,
) -> list[dict[str, Any]]:
    """
    Filter proposals that duplicate previously rejected ones.

    Rules:
    1. Same target_file + same action_type = automatic reject
    2. Content similarity (Jaccard on key phrases) > threshold = flag as duplicate

    Returns filtered list of non-duplicate proposals.
    """
    if not rejected:
        return proposals

    filtered = []
    for prop in proposals:
        if _is_duplicate(prop, rejected, similarity_threshold):
            _log.info(
                "Dedup: skipping proposal for %s/%s (matches rejected)",
                prop.get("target_file"), prop.get("action_type"),
            )
            continue
        filtered.append(prop)

    if len(filtered) < len(proposals):
        _log.info(
            "Dedup: %d/%d proposals survived",
            len(filtered), len(proposals),
        )
    return filtered


def _is_duplicate(
    proposal: dict[str, Any],
    rejected: list[dict[str, Any]],
    threshold: float,
) -> bool:
    """Check if a proposal duplicates any rejected entry."""
    prop_file = proposal.get("target_file", "")
    prop_action = proposal.get("action_type", "")
    prop_content = proposal.get("content", "")

    for rej in rejected:
        rej_file = rej.get("target_file", "")
        rej_action = rej.get("action_type", "")
        rej_content = rej.get("content", "")

        # Exact match on file + action type
        if prop_file == rej_file and prop_action == rej_action:
            return True

        # Content similarity check
        if prop_content and rej_content:
            similarity = _jaccard_similarity(prop_content, rej_content)
            if similarity >= threshold:
                return True

    return False


def _jaccard_similarity(text_a: str, text_b: str) -> float:
    """
    Jaccard similarity on key phrases (Chinese-aware).
    Split on whitespace and common punctuation, extract 2-4 char n-grams,
    compute |intersection| / |union|.
    """
    phrases_a = _extract_phrases(text_a)
    phrases_b = _extract_phrases(text_b)
    if not phrases_a or not phrases_b:
        return 0.0
    intersection = phrases_a & phrases_b
    union = phrases_a | phrases_b
    return len(intersection) / len(union) if union else 0.0


def _extract_phrases(text: str) -> set[str]:
    """Extract character n-grams (2-4 chars) from text."""
    text = re.sub(r'\s+', '', text)
    phrases = set()
    for n in (2, 3, 4):
        for i in range(len(text) - n + 1):
            phrases.add(text[i:i+n])
    return phrases
