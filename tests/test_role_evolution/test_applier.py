"""Tests for agent.role_evolution.applier — proposal application with safety checks."""

from __future__ import annotations

import json
import unittest
from typing import Any

from agent.role_evolution.applier import apply_proposals
from agent.role_evolution.models import (
    SkillConsolidation,
    SkillProposal,
)


# ---------------------------------------------------------------------------
# Valid skill file templates
# ---------------------------------------------------------------------------

_VALID_SKILL_FRONT_MATTER = (
    "---\n"
    "name: {name}\n"
    "role: {role}\n"
    "scope: role\n"
    "applicable_actions:\n"
    "  - speak\n"
    "  - vote\n"
    "output_constraints:\n"
    "  format: text\n"
    "category: strategy\n"
    "evolvable: false\n"
    "---\n"
    "\n"
    "Base body content.\n"
)

_VALID_SKILL_BODY = "Base body content.\n"


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_skill_content(
    name: str = "test_skill",
    role: str = "werewolf",
    scope: str = "role",
    applicable_actions: list[str] | None = None,
    output_constraints: str = "format: text",
    evolvable: bool = False,
    body: str = "Base body content.",
) -> str:
    """Build a valid skill markdown file with YAML front matter."""
    if applicable_actions is None:
        applicable_actions = ["speak", "vote"]
    action_lines = "\n".join(f"  - {a}" for a in applicable_actions)
    return (
        f"---\n"
        f"name: {name}\n"
        f"role: {role}\n"
        f"scope: {scope}\n"
        f"applicable_actions:\n"
        f"{action_lines}\n"
        f"output_constraints:\n"
        f"  {output_constraints}\n"
        f"category: strategy\n"
        f"evolvable: {str(evolvable).lower()}\n"
        f"---\n"
        f"\n"
        f"{body}\n"
    )


def _make_proposal(
    proposal_id: str,
    target_file: str,
    confidence: float = 0.8,
    risk: str = "low",
    status: str = "proposed",
    action_type: str = "append_rule",
    content: str = "",
    rationale: str = "test rationale",
    conflicts_with: list[str] | None = None,
) -> SkillProposal:
    """Create a SkillProposal with sensible defaults."""
    return SkillProposal(
        proposal_id=proposal_id,
        target_file=target_file,
        action_type=action_type,
        content=content or f"Proposed content for {proposal_id}",
        rationale=rationale,
        confidence=confidence,
        risk=risk,
        expected_metric="score",
        expected_direction="up",
        conflicts_with=conflicts_with or [],
        status=status,
    )


def _make_consolidation(
    role: str,
    proposals: list[SkillProposal],
) -> SkillConsolidation:
    """Create a SkillConsolidation wrapping the given proposals."""
    return SkillConsolidation(
        role=role,
        run_id="test_run",
        parent_hash="abc123",
        generated_at="2026-01-01T00:00:00",
        source_window=10,
        prompt_version="v1",
        proposals=proposals,
    )


def _make_fake_model_adapter(response_json: dict[str, Any]):
    """Return a mock ModelAdapter that returns the given JSON as a string.

    The adapter's ``complete`` method is a coroutine that always returns
    ``json.dumps(response_json)``.
    """

    class _FakeAdapter:
        def __init__(self, resp: str) -> None:
            self._resp = resp
            self.calls: list[list[dict[str, str]]] = []

        async def complete(self, messages: list[dict[str, str]], *, name: str = "") -> str:
            self.calls.append(messages)
            return self._resp

    return _FakeAdapter(json.dumps(response_json))


def _make_llm_response(files: dict[str, str], changes: list[dict[str, str]] | None = None) -> dict[str, Any]:
    """Build a valid LLM JSON response shape."""
    resp: dict[str, Any] = {"files": files}
    if changes is not None:
        resp["changes"] = changes
    return resp


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


class ApplierFilteringTests(unittest.IsolatedAsyncioTestCase):
    """Tests that proposals are correctly filtered by confidence, risk, conflict."""

    async def test_skips_low_confidence_proposals(self):
        """Proposals with confidence < CONFIDENCE_THRESHOLD are not applied."""
        skill_content = _make_skill_content()
        current = {"werewolf/strategy.md": skill_content}

        low_conf = _make_proposal("p1", "werewolf/strategy.md", confidence=0.3)
        consol = _make_consolidation("werewolf", [low_conf])

        # If the LLM were called, it would return changed content.
        # Since the proposal is filtered out, LLM should NOT be called and
        # original skills should be returned unchanged.
        changed = _make_skill_content(body="CHANGED body")
        adapter = _make_fake_model_adapter(_make_llm_response({"werewolf/strategy.md": changed}))

        new_skills, diffs = await apply_proposals(current, consol, adapter)

        self.assertEqual(new_skills, current)
        self.assertEqual(diffs, [])
        self.assertEqual(adapter.calls, [], "LLM should not be called for filtered proposals")

    async def test_skips_high_risk_proposals(self):
        """Proposals with risk='high' are not applied."""
        skill_content = _make_skill_content()
        current = {"werewolf/strategy.md": skill_content}

        high_risk = _make_proposal("p1", "werewolf/strategy.md", risk="high", confidence=0.9)
        consol = _make_consolidation("werewolf", [high_risk])

        changed = _make_skill_content(body="CHANGED body")
        adapter = _make_fake_model_adapter(_make_llm_response({"werewolf/strategy.md": changed}))

        new_skills, diffs = await apply_proposals(current, consol, adapter)

        self.assertEqual(new_skills, current)
        self.assertEqual(diffs, [])
        self.assertEqual(adapter.calls, [])

    async def test_skips_conflicting_proposals(self):
        """If A conflicts_with B, both are skipped."""
        skill_content = _make_skill_content()
        current = {"werewolf/strategy.md": skill_content}

        p1 = _make_proposal("p1", "werewolf/strategy.md", conflicts_with=["p2"])
        p2 = _make_proposal("p2", "werewolf/strategy.md", conflicts_with=["p1"])
        consol = _make_consolidation("werewolf", [p1, p2])

        changed = _make_skill_content(body="CHANGED body")
        adapter = _make_fake_model_adapter(_make_llm_response({"werewolf/strategy.md": changed}))

        new_skills, diffs = await apply_proposals(current, consol, adapter)

        self.assertEqual(new_skills, current)
        self.assertEqual(diffs, [])


class ApplierValidationTests(unittest.IsolatedAsyncioTestCase):
    """Tests that LLM output is validated and rejected on safety violations."""

    async def _run_with_llm_output(self, current: dict[str, str], llm_files: dict[str, str], proposals: list[SkillProposal], role: str = "werewolf"):
        """Helper: run apply_proposals with a mock adapter returning llm_files."""
        consol = _make_consolidation(role, proposals)
        # Build changes list to match files
        changes = [{"filename": f, "action": "modified", "description": "test"} for f in llm_files]
        adapter = _make_fake_model_adapter(_make_llm_response(llm_files, changes))
        return await apply_proposals(current, consol, adapter)

    async def test_rejects_role_change(self):
        """If LLM output changes the role field, reject all."""
        original = _make_skill_content(role="werewolf")
        current = {"werewolf/strategy.md": original}
        # LLM changes role to seer
        tampered = _make_skill_content(role="seer", body="Updated content")
        proposal = _make_proposal("p1", "werewolf/strategy.md")

        new_skills, diffs = await self._run_with_llm_output(current, {"werewolf/strategy.md": tampered}, [proposal])

        self.assertEqual(new_skills, current)
        self.assertEqual(diffs, [])

    async def test_rejects_scope_change_to_common(self):
        """If LLM output changes scope to common, reject all."""
        original = _make_skill_content(scope="role")
        current = {"werewolf/strategy.md": original}
        tampered = _make_skill_content(scope="common", body="Updated content")
        proposal = _make_proposal("p1", "werewolf/strategy.md")

        new_skills, diffs = await self._run_with_llm_output(current, {"werewolf/strategy.md": tampered}, [proposal])

        self.assertEqual(new_skills, current)
        self.assertEqual(diffs, [])

    async def test_rejects_name_change(self):
        """If LLM output changes the name field, reject all."""
        original = _make_skill_content(name="strategy")
        current = {"werewolf/strategy.md": original}
        tampered = _make_skill_content(name="renamed_strategy", body="Updated content")
        proposal = _make_proposal("p1", "werewolf/strategy.md")

        new_skills, diffs = await self._run_with_llm_output(current, {"werewolf/strategy.md": tampered}, [proposal])

        self.assertEqual(new_skills, current)
        self.assertEqual(diffs, [])

    async def test_rejects_action_expansion(self):
        """If applicable_actions expands, reject all."""
        original = _make_skill_content(applicable_actions=["speak", "vote"])
        current = {"werewolf/strategy.md": original}
        # LLM adds a new action "kill"
        tampered = _make_skill_content(applicable_actions=["speak", "vote", "kill"], body="Updated content")
        proposal = _make_proposal("p1", "werewolf/strategy.md")

        new_skills, diffs = await self._run_with_llm_output(current, {"werewolf/strategy.md": tampered}, [proposal])

        self.assertEqual(new_skills, current)
        self.assertEqual(diffs, [])

    async def test_rejects_unsafe_path(self):
        """Paths with '..', absolute paths, non-.md are rejected."""
        skill_content = _make_skill_content()
        test_cases = [
            ("../escape.md", "path traversal with .."),
            ("/etc/passwd.md", "absolute path"),
            ("werewolf/strategy.txt", "non-.md suffix"),
        ]

        for bad_path, desc in test_cases:
            with self.subTest(path=bad_path, reason=desc):
                # For path-based rejections, the current skills map uses the bad path
                # as a key (simulating LLM outputting a file at that path).
                # The proposal targets the bad path, so LLM returns it.
                current = {bad_path: skill_content}
                proposal = _make_proposal("p1", bad_path)
                tampered = _make_skill_content(body="Updated content")
                consol = _make_consolidation("werewolf", [proposal])
                changes = [{"filename": bad_path, "action": "modified", "description": "test"}]
                adapter = _make_fake_model_adapter(_make_llm_response({bad_path: tampered}, changes))

                new_skills, diffs = await apply_proposals(current, consol, adapter)

                self.assertEqual(new_skills, current, f"Should reject: {desc}")
                self.assertEqual(diffs, [], f"Should have no diffs: {desc}")

    async def test_rejects_file_deletion(self):
        """If LLM removes a file that existed, reject all."""
        original = _make_skill_content(name="strategy")
        current = {
            "werewolf/strategy.md": original,
            "werewolf/backup.md": _make_skill_content(name="backup"),
        }
        # LLM only returns strategy.md, omitting backup.md -> treated as deletion
        proposal = _make_proposal("p1", "werewolf/strategy.md")
        # The LLM returns both files to avoid path errors, but removes content
        # from backup — wait, actually deletion is when a current file is NOT in
        # proposed_files. So the LLM response must omit backup.md entirely.
        consol = _make_consolidation("werewolf", [proposal])
        adapter = _make_fake_model_adapter(
            _make_llm_response(
                {"werewolf/strategy.md": _make_skill_content(name="strategy", body="Updated")},
                [{"filename": "werewolf/strategy.md", "action": "modified", "description": "test"}],
            )
        )

        new_skills, diffs = await apply_proposals(current, consol, adapter)

        self.assertEqual(new_skills, current)
        self.assertEqual(diffs, [])


class ApplierSmokeTest(unittest.IsolatedAsyncioTestCase):
    """Tests the end-to-end smoke test path."""

    async def test_smoke_test_loads_skills(self):
        """After validation, skills are loadable via load_markdown_skills."""
        original = _make_skill_content(name="strategy", body="Old body.")
        current = {"werewolf/strategy.md": original}

        proposal = _make_proposal("p1", "werewolf/strategy.md", confidence=0.9)
        consol = _make_consolidation("werewolf", [proposal])

        # LLM returns a valid modified file that should pass all checks
        updated = _make_skill_content(name="strategy", body="New improved body with more detail.")
        adapter = _make_fake_model_adapter(
            _make_llm_response(
                {"werewolf/strategy.md": updated},
                [{"filename": "werewolf/strategy.md", "action": "modified", "description": "improved strategy"}],
            )
        )

        new_skills, diffs = await apply_proposals(current, consol, adapter)

        # Should succeed: the returned skills should be the updated version
        self.assertIn("werewolf/strategy.md", new_skills)
        self.assertEqual(new_skills["werewolf/strategy.md"], updated)
        self.assertGreater(len(diffs), 0)
        self.assertEqual(diffs[0].filename, "werewolf/strategy.md")
        self.assertEqual(diffs[0].action, "modified")


if __name__ == "__main__":
    unittest.main()
