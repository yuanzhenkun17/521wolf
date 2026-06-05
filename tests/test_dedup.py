"""Tests for agent.evolution.dedup — proposal deduplication against rejected buffer."""
from __future__ import annotations

from agent.learning.dedup import (
    _extract_phrases,
    _jaccard_similarity,
    deduplicate_proposals,
)


# ---------------------------------------------------------------------------
# deduplicate_proposals — exact match (same file + action type)
# ---------------------------------------------------------------------------


def test_dedup_exact_match_same_file_and_action():
    proposals = [
        {"target_file": "seer/strategy.md", "action_type": "modify", "content": "new content"},
    ]
    rejected = [
        {"target_file": "seer/strategy.md", "action_type": "modify", "content": "old content"},
    ]

    result = deduplicate_proposals(proposals, rejected)
    assert len(result) == 0


def test_dedup_exact_match_different_action_survives():
    proposals = [
        {"target_file": "seer/strategy.md", "action_type": "create", "content": "new file"},
    ]
    rejected = [
        {"target_file": "seer/strategy.md", "action_type": "modify", "content": "old content"},
    ]

    result = deduplicate_proposals(proposals, rejected)
    assert len(result) == 1


def test_dedup_exact_match_different_file_survives():
    proposals = [
        {"target_file": "witch/tips.md", "action_type": "modify", "content": "new"},
    ]
    rejected = [
        {"target_file": "seer/strategy.md", "action_type": "modify", "content": "old"},
    ]

    result = deduplicate_proposals(proposals, rejected)
    assert len(result) == 1


# ---------------------------------------------------------------------------
# deduplicate_proposals — content similarity above threshold
# ---------------------------------------------------------------------------


def test_dedup_content_similarity_above_threshold():
    # Almost identical content should trigger similarity dedup
    proposals = [
        {
            "target_file": "new_file.md",
            "action_type": "create",
            "content": "预言家应该在第一天查验最可疑的玩家，因为这样可以尽早获取信息",
        },
    ]
    rejected = [
        {
            "target_file": "other_file.md",
            "action_type": "create",
            "content": "预言家应该在第一天查验最可疑的玩家，因为这样可以尽早获取信息",
        },
    ]

    result = deduplicate_proposals(proposals, rejected, similarity_threshold=0.7)
    assert len(result) == 0


def test_dedup_content_similarity_below_threshold():
    proposals = [
        {
            "target_file": "new_file.md",
            "action_type": "create",
            "content": "狼人应该在夜晚优先击杀预言家",
        },
    ]
    rejected = [
        {
            "target_file": "other_file.md",
            "action_type": "create",
            "content": "村民应该在白天积极发言分析投票方向完全不同内容",
        },
    ]

    result = deduplicate_proposals(proposals, rejected, similarity_threshold=0.7)
    assert len(result) == 1


# ---------------------------------------------------------------------------
# deduplicate_proposals — no rejected (returns all)
# ---------------------------------------------------------------------------


def test_dedup_no_rejected_returns_all():
    proposals = [
        {"target_file": "a.md", "action_type": "create", "content": "aaa"},
        {"target_file": "b.md", "action_type": "modify", "content": "bbb"},
        {"target_file": "c.md", "action_type": "create", "content": "ccc"},
    ]

    result = deduplicate_proposals(proposals, [])
    assert len(result) == 3
    assert result == proposals


def test_dedup_empty_proposals():
    result = deduplicate_proposals([], [{"target_file": "a.md", "action_type": "create"}])
    assert result == []


# ---------------------------------------------------------------------------
# deduplicate_proposals — mixed scenarios
# ---------------------------------------------------------------------------


def test_dedup_mixed_some_survive():
    proposals = [
        {"target_file": "seer/strategy.md", "action_type": "modify", "content": "unique A"},
        {"target_file": "witch/tips.md", "action_type": "create", "content": "unique B"},
        {"target_file": "hunter/guide.md", "action_type": "create", "content": "unique C"},
    ]
    rejected = [
        {"target_file": "seer/strategy.md", "action_type": "modify", "content": "different"},
    ]

    result = deduplicate_proposals(proposals, rejected)
    assert len(result) == 2
    assert result[0]["target_file"] == "witch/tips.md"
    assert result[1]["target_file"] == "hunter/guide.md"


# ---------------------------------------------------------------------------
# _jaccard_similarity
# ---------------------------------------------------------------------------


def test_jaccard_identical_texts():
    text = "预言家查验狼人的身份是好人的关键策略"
    assert _jaccard_similarity(text, text) == 1.0


def test_jaccard_completely_different_texts():
    text_a = "abcdef"
    text_b = "xyzwvu"
    assert _jaccard_similarity(text_a, text_b) == 0.0


def test_jaccard_chinese_text_partial_overlap():
    text_a = "预言家应该在第一天查验狼人"
    text_b = "预言家应该在第二天保护好人"
    sim = _jaccard_similarity(text_a, text_b)
    # Some shared n-grams but not identical
    assert 0.0 < sim < 1.0


def test_jaccard_empty_texts():
    assert _jaccard_similarity("", "") == 0.0
    assert _jaccard_similarity("hello", "") == 0.0
    assert _jaccard_similarity("", "world") == 0.0


def test_jaccard_english_text():
    text_a = "the quick brown fox jumps over the lazy dog"
    text_b = "the quick brown fox jumps over the lazy dog"
    assert _jaccard_similarity(text_a, text_b) == 1.0


def test_jaccard_whitespace_normalization():
    # Whitespace is stripped before comparison
    text_a = "hello  world"
    text_b = "helloworld"
    assert _jaccard_similarity(text_a, text_b) == 1.0


# ---------------------------------------------------------------------------
# _extract_phrases
# ---------------------------------------------------------------------------


def test_extract_phrases_generates_ngrams():
    phrases = _extract_phrases("abcd")
    # 2-grams: ab, bc, cd
    # 3-grams: abc, bcd
    # 4-grams: abcd
    assert "ab" in phrases
    assert "bc" in phrases
    assert "cd" in phrases
    assert "abc" in phrases
    assert "bcd" in phrases
    assert "abcd" in phrases


def test_extract_phrases_short_text():
    # Text shorter than 2 chars produces no phrases
    phrases = _extract_phrases("a")
    assert len(phrases) == 0


def test_extract_phrases_chinese():
    phrases = _extract_phrases("预言家查验")
    assert "预言" in phrases
    assert "言家" in phrases
    assert "查验" in phrases
    assert "预言家" in phrases
    assert "言家查" in phrases
    assert "预言家查" in phrases
