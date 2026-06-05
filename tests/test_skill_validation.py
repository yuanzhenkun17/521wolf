"""Tests for skill validation: forbidden-content scanner and length limits."""
import pytest
from agent.knowledge.skills.loader import (
    MarkdownSkill,
    validate_runtime_body,
    check_skill_limits,
    _RUNTIME_BODY_SOFT_LIMIT,
    _RUNTIME_BODY_HARD_LIMIT,
    _SKILL_FILE_TOTAL_SOFT_LIMIT,
)


# ── validate_runtime_body ────────────────────────────────────────────────────

class TestValidateRuntimeBody:
    def test_empty_body_is_clean(self):
        assert validate_runtime_body("") == []

    def test_plain_strategy_text_is_clean(self):
        body = "Bluff aggressively when low on cards. Deflect suspicion."
        assert validate_runtime_body(body) == []

    def test_detects_player_number_p(self):
        violations = validate_runtime_body("Target P2 for elimination.")
        assert any("player number" in v and "P1" in v for v in violations)

    def test_detects_player_number_chinese(self):
        violations = validate_runtime_body("怀疑7号玩家是狼人")
        assert any("player number" in v and "N号" in v for v in violations)

    def test_detects_game_id(self):
        violations = validate_runtime_body("See game_id for details.")
        assert "game_id" in violations

    def test_detects_run_id(self):
        violations = validate_runtime_body("The run_id was logged.")
        assert "run_id" in violations

    def test_detects_seed(self):
        violations = validate_runtime_body("Random seed affects outcome.")
        assert "seed" in violations

    def test_detects_source_game_id(self):
        violations = validate_runtime_body("Use source_game_id lookup.")
        assert "source_game_id" in violations

    def test_detects_model_id(self):
        violations = validate_runtime_body("The model_id determines behavior.")
        assert "model_id" in violations

    def test_detects_provider(self):
        violations = validate_runtime_body("Switch provider if needed.")
        assert "provider" in violations

    def test_detects_gpt_model_name(self):
        violations = validate_runtime_body("Based on GPT-4 output.")
        assert any("GPT" in v for v in violations)

    def test_detects_claude_model_name(self):
        violations = validate_runtime_body("Using Claude-3 Opus here.")
        assert any("Claude" in v for v in violations)

    def test_detects_win_rate(self):
        violations = validate_runtime_body("The win_rate was 0.65.")
        assert any("win_rate" in v for v in violations)

    def test_detects_victory_count(self):
        violations = validate_runtime_body("victory_count = 42")
        assert any("victory_count" in v for v in violations)

    def test_detects_result_detail(self):
        violations = validate_runtime_body("result: good")
        assert any("result" in v for v in violations)

    def test_multiple_violations_returned(self):
        body = "P1 had game_id=xyz and win_rate was 50%"
        violations = validate_runtime_body(body)
        assert len(violations) >= 3

    def test_case_insensitive_p_number(self):
        violations = validate_runtime_body("target p3 now")
        assert any("player number" in v for v in violations)


# ── check_skill_limits ───────────────────────────────────────────────────────

class TestCheckSkillLimits:
    def _skill(self, runtime_len: int, body_len: int | None = None) -> MarkdownSkill:
        """Build a skill with controlled lengths."""
        return MarkdownSkill(
            name="test_skill",
            runtime_body="x" * runtime_len,
            body="y" * (body_len if body_len is not None else runtime_len),
        )

    def test_within_all_limits(self):
        assert check_skill_limits(self._skill(500, 1000)) == []

    def test_soft_runtime_body_warning(self):
        s = self._skill(_RUNTIME_BODY_SOFT_LIMIT + 100, 100)
        issues = check_skill_limits(s)
        assert len(issues) == 1
        assert "[soft]" in issues[0]
        assert "runtime_body" in issues[0]

    def test_hard_runtime_body_error(self):
        s = self._skill(_RUNTIME_BODY_HARD_LIMIT + 10, 100)
        issues = check_skill_limits(s)
        assert len(issues) == 1
        assert "[hard]" in issues[0]
        assert "runtime_body" in issues[0]

    def test_hard_takes_priority_over_soft(self):
        """When hard limit is exceeded, only hard message appears."""
        s = self._skill(_RUNTIME_BODY_HARD_LIMIT + 10, 100)
        issues = check_skill_limits(s)
        assert not any("[soft]" in i for i in issues)
        assert any("[hard]" in i for i in issues)

    def test_soft_total_body_warning(self):
        s = self._skill(500, _SKILL_FILE_TOTAL_SOFT_LIMIT + 100)
        issues = check_skill_limits(s)
        assert any("[soft]" in i and "body length" in i for i in issues)

    def test_both_runtime_and_total_issues(self):
        s = self._skill(_RUNTIME_BODY_SOFT_LIMIT + 10, _SKILL_FILE_TOTAL_SOFT_LIMIT + 10)
        issues = check_skill_limits(s)
        assert len(issues) == 2

    def test_exact_soft_limit_is_ok(self):
        s = self._skill(_RUNTIME_BODY_SOFT_LIMIT, _SKILL_FILE_TOTAL_SOFT_LIMIT)
        assert check_skill_limits(s) == []

    def test_exact_hard_limit_is_ok(self):
        """Exact hard limit should produce only a soft warning, not a hard error."""
        s = self._skill(_RUNTIME_BODY_HARD_LIMIT, _SKILL_FILE_TOTAL_SOFT_LIMIT)
        issues = check_skill_limits(s)
        assert not any("[hard]" in i for i in issues)
        assert any("[soft]" in i and "runtime_body" in i for i in issues)
