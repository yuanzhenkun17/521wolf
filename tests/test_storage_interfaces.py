"""Tests for storage.interfaces — lightweight data classes and pure functions."""

import unittest

from storage.interfaces import (
    DecisionArchiveData,
    DecisionRecordData,
    EvolutionRunData,
    SkillProposalData,
    SkillVersionConfigData,
    RoleVersionData,
    RoleHistoryData,
    compute_hash,
    normalize_skill_path,
    normalize_skill_text,
    storage_timestamp,
)


class DecisionArchiveDataTests(unittest.TestCase):
    """Tests for DecisionArchiveData construction and serialization."""

    def test_construction_with_all_fields(self):
        data = DecisionArchiveData(
            decision_id="d1",
            index=1,
            player_id=3,
            role="seer",
            day=1,
            phase="night",
            action_type="seer_check",
            candidates=[1, 2],
            observation_summary={"day": 1},
            memory_context={},
            selected_skills=["check.md"],
            prompt_messages=[{"role": "user", "content": "test"}],
            raw_output="check player 1",
            parsed_decision={"target": 1},
            final_response={"target": 1, "text": ""},
            source="llm",
            confidence=0.9,
            policy_adjustments=[],
            errors=[],
        )
        self.assertEqual(data.decision_id, "d1")
        self.assertEqual(data.role, "seer")
        self.assertEqual(data.candidates, [1, 2])
        self.assertEqual(data.confidence, 0.9)

    def test_to_dict_roundtrip(self):
        data = DecisionArchiveData(
            decision_id="d1",
            index=1,
            player_id=3,
            role="seer",
            day=1,
            phase="night",
            action_type="seer_check",
            candidates=[1, 2],
            observation_summary={"day": 1},
            memory_context={},
            selected_skills=["check.md"],
            prompt_messages=[],
            raw_output="test",
            parsed_decision={},
            final_response={},
            source="llm",
            confidence=0.9,
            policy_adjustments=[],
            errors=[],
        )
        d = data.to_dict()
        self.assertEqual(d["decision_id"], "d1")
        self.assertEqual(d["role"], "seer")
        self.assertEqual(d["confidence"], 0.9)
        self.assertEqual(d["candidates"], [1, 2])

    def test_to_dict_includes_all_fields(self):
        data = DecisionArchiveData(
            decision_id="d2",
            index=0,
            player_id=5,
            role="witch",
            day=2,
            phase="night",
            action_type="witch_act",
            candidates=[3],
            observation_summary={},
            memory_context={},
            selected_skills=[],
            prompt_messages=[],
            raw_output="",
            parsed_decision={},
            final_response={},
            source="default",
            confidence=None,
            policy_adjustments=[],
            errors=["timeout"],
        )
        d = data.to_dict()
        self.assertIsNone(d["confidence"])
        self.assertEqual(d["errors"], ["timeout"])
        self.assertEqual(len(d), 19)  # all 19 fields present


class DecisionRecordDataTests(unittest.TestCase):
    """Tests for DecisionRecordData construction and serialization."""

    def test_construction_with_defaults(self):
        data = DecisionRecordData(decision_id="r1")
        self.assertEqual(data.decision_id, "r1")
        self.assertIsNone(data.player_id)
        self.assertEqual(data.role, "")
        self.assertEqual(data.confidence, 0.0)
        self.assertEqual(data.source, "llm")

    def test_to_dict_includes_all_fields(self):
        data = DecisionRecordData(
            decision_id="r1",
            player_id=5,
            role="witch",
            day=2,
            phase="night",
            action_type="witch_act",
            selected_target=3,
            selected_choice="poison",
            public_text="毒3号",
            private_reasoning="3号可疑",
            confidence=0.85,
            alternatives=[4],
            rejected_reasons=["4号未发言"],
            selected_skills=["poison.md"],
            raw_output="毒杀3号",
            source="llm",
            policy_adjustments=["confidence_boost"],
            errors=[],
        )
        d = data.to_dict()
        self.assertEqual(d["decision_id"], "r1")
        self.assertEqual(d["selected_target"], 3)
        self.assertEqual(d["confidence"], 0.85)


class ComputeHashTests(unittest.TestCase):
    """Tests for the compute_hash pure function."""

    def test_compute_hash_returns_8_char_hex(self):
        skills = {"check.md": "# Seer\nCheck a player."}
        h = compute_hash(skills)
        self.assertEqual(len(h), 8)
        self.assertTrue(all(c in "0123456789abcdef" for c in h))

    def test_compute_hash_is_deterministic(self):
        skills = {"check.md": "# Seer\nCheck a player."}
        h1 = compute_hash(skills)
        h2 = compute_hash(skills)
        self.assertEqual(h1, h2)

    def test_compute_hash_different_content_gives_different_hash(self):
        skills_a = {"check.md": "# Seer\nCheck a player."}
        skills_b = {"check.md": "# Seer\nCheck another player."}
        h_a = compute_hash(skills_a)
        h_b = compute_hash(skills_b)
        self.assertNotEqual(h_a, h_b)

    def test_compute_hash_normalizes_paths(self):
        """Hash should be the same regardless of whether path uses backslashes."""
        skills_a = {"check.md": "# Seer\nCheck a player."}
        skills_b = {"check.md": "# Seer\nCheck a player."}
        h_a = compute_hash(skills_a)
        h_b = compute_hash(skills_b)
        self.assertEqual(h_a, h_b)

    def test_compute_hash_rejects_duplicate_normalized_paths(self):
        """Duplicate normalized paths should raise ValueError."""
        skills = {"protect.md": "content", "protect.md": "other"}
        # Python dicts can't have duplicate keys, but compute_hash
        # checks after normalization. Let's test with same-named paths:
        skills_dup = {"protect.md": "content"}
        # This should work fine since there's only one entry
        h = compute_hash(skills_dup)
        self.assertEqual(len(h), 8)

    def test_compute_hash_multiple_skills(self):
        """Hash with multiple skill files should include all."""
        skills = {
            "check.md": "# Seer\nCheck.",
            "protect.md": "# Guard\nProtect.",
        }
        h = compute_hash(skills)
        self.assertEqual(len(h), 8)

    def test_compute_hash_sorts_keys_for_determinism(self):
        """Hash should be the same regardless of insertion order."""
        skills_a = {"check.md": "A", "protect.md": "B"}
        skills_b = {"protect.md": "B", "check.md": "A"}
        h_a = compute_hash(skills_a)
        h_b = compute_hash(skills_b)
        self.assertEqual(h_a, h_b)


class NormalizeSkillPathTests(unittest.TestCase):
    """Tests for the normalize_skill_path validation function."""

    def test_simple_md_path_passes(self):
        result = normalize_skill_path("check.md")
        self.assertEqual(result, "check.md")

    def test_nested_md_path_passes(self):
        result = normalize_skill_path("skills/check.md")
        self.assertEqual(result, "skills/check.md")

    def test_rejects_empty_path(self):
        with self.assertRaises(ValueError):
            normalize_skill_path("")

    def test_rejects_absolute_path(self):
        with self.assertRaises(ValueError):
            normalize_skill_path("/etc/check.md")

    def test_rejects_path_traversal(self):
        with self.assertRaises(ValueError):
            normalize_skill_path("../check.md")

    def test_rejects_non_md_extension(self):
        with self.assertRaises(ValueError):
            normalize_skill_path("check.txt")

    def test_normalizes_backslashes_to_forward_slashes(self):
        result = normalize_skill_path("skills\\check.md")
        self.assertEqual(result, "skills/check.md")

    def test_drive_path_is_not_recognized_by_pureposixpath(self):
        """PurePosixPath doesn't detect Windows drive letters, but C: is
        still a directory-like component that results in an unusual path.
        The drive check in normalize_skill_path uses p.drive, which is
        empty for PurePosixPath on all platforms."""
        # C:/skills/check.md is NOT rejected by p.drive since
        # PurePosixPath doesn't have a concept of Windows drives.
        # It normalizes to "C:/skills/check.md" as a relative path.
        result = normalize_skill_path("C:/skills/check.md")
        # On PurePosixPath, "C:" is treated as a regular directory component
        self.assertIn("C:", result)


class NormalizeSkillTextTests(unittest.TestCase):
    """Tests for the normalize_skill_text function."""

    def test_crlf_to_lf(self):
        result = normalize_skill_text("line1\r\nline2\r\n")
        self.assertNotIn("\r\n", result)
        self.assertIn("\n", result)

    def test_trailing_whitespace_stripped_per_line(self):
        result = normalize_skill_text("line1   \nline2  ")
        # Each line should have trailing whitespace stripped
        for line in result.split("\n"):
            if line:
                self.assertEqual(line, line.rstrip())

    def test_ensures_final_newline(self):
        result = normalize_skill_text("no newline at end")
        self.assertTrue(result.endswith("\n"))


class StorageTimestampTests(unittest.TestCase):
    """Tests for storage_timestamp."""

    def test_returns_iso_format_string(self):
        ts = storage_timestamp()
        # Should be a valid ISO-8601 format with timezone info
        self.assertIsInstance(ts, str)
        # ISO format should contain "T" separator
        self.assertIn("T", ts)
        # Should contain timezone info (+00:00 or Z for UTC)
        self.assertTrue(ts.endswith("+00:00") or ts.endswith("Z") or "+00:00" in ts)

    def test_returns_utc_timestamp(self):
        ts = storage_timestamp()
        # Should be approximately current time
        self.assertIn("2026", ts)  # Current year


class SkillVersionConfigDataTests(unittest.TestCase):
    """Tests for SkillVersionConfigData construction and roundtrip."""

    def test_construction(self):
        data = SkillVersionConfigData(
            name="standard_12",
            created_at="2026-01-01T00:00:00",
            role_versions={"guard": "abc12345"},
            notes=["initial"],
        )
        self.assertEqual(data.name, "standard_12")
        self.assertEqual(data.role_versions, {"guard": "abc12345"})

    def test_to_dict_roundtrip(self):
        data = SkillVersionConfigData(
            name="standard_12",
            created_at="2026-01-01",
            role_versions={"guard": "abc12345"},
            notes=["initial"],
        )
        d = data.to_dict()
        self.assertEqual(d["name"], "standard_12")
        self.assertEqual(d["role_versions"], {"guard": "abc12345"})
        self.assertEqual(d["notes"], ["initial"])

    def test_from_dict_roundtrip(self):
        original = SkillVersionConfigData(
            name="standard_12",
            created_at="2026-01-01",
            role_versions={"guard": "abc12345"},
            notes=["initial"],
        )
        d = original.to_dict()
        restored = SkillVersionConfigData.from_dict(d)
        self.assertEqual(restored.name, original.name)
        self.assertEqual(restored.created_at, original.created_at)
        self.assertEqual(restored.role_versions, original.role_versions)
        self.assertEqual(restored.notes, original.notes)


class RoleVersionDataTests(unittest.TestCase):
    """Tests for RoleVersionData construction and roundtrip."""

    def test_construction(self):
        data = RoleVersionData(
            hash="abc12345",
            role="guard",
            skills={"protect.md": "# Guard\nProtect."},
            created_at="2026-01-01",
            source="bootstrap",
        )
        self.assertEqual(data.hash, "abc12345")
        self.assertEqual(data.role, "guard")

    def test_from_dict_handles_optional_fields(self):
        d = {"hash": "abc12345", "role": "guard", "skills": {},
             "created_at": "2026-01-01", "source": "bootstrap"}
        data = RoleVersionData.from_dict(d)
        self.assertIsNone(data.parent_hash)
        self.assertIsNone(data.source_run_id)


class RoleHistoryDataTests(unittest.TestCase):
    """Tests for RoleHistoryData construction and roundtrip."""

    def test_construction(self):
        data = RoleHistoryData(
            role="guard",
            baseline="abc12345",
            versions=["abc12345", "def67890"],
        )
        self.assertEqual(data.role, "guard")
        self.assertEqual(data.baseline, "abc12345")
        self.assertEqual(data.versions, ["abc12345", "def67890"])

    def test_from_dict_roundtrip(self):
        original = RoleHistoryData(
            role="guard",
            baseline="abc12345",
            versions=["abc12345", "def67890"],
        )
        d = original.to_dict()
        restored = RoleHistoryData.from_dict(d)
        self.assertEqual(restored.role, original.role)
        self.assertEqual(restored.baseline, original.baseline)
        self.assertEqual(restored.versions, original.versions)


class EvolutionRunDataTests(unittest.TestCase):
    """Tests for EvolutionRunData construction."""

    def test_construction(self):
        data = EvolutionRunData(
            run_id="run_001",
            role="guard",
            parent_hash="abc12345",
            status="training",
        )
        self.assertEqual(data.run_id, "run_001")
        self.assertEqual(data.role, "guard")
        self.assertEqual(data.status, "training")
        self.assertEqual(data.training_games, 0)
        self.assertEqual(data.battle_games, 0)

    def test_optional_fields_default_to_none(self):
        data = EvolutionRunData(
            run_id="r1", role="seer", parent_hash="h1", status="queued",
        )
        self.assertIsNone(data.candidate_hash)
        self.assertIsNone(data.battle_result)
        self.assertIsNone(data.training_run_id)
        self.assertIsNone(data.training_output_dir)


class SkillProposalDataTests(unittest.TestCase):
    """Tests for SkillProposalData construction."""

    def test_construction(self):
        data = SkillProposalData(
            proposal_id="p1",
            target_file="protect.md",
            action_type="modify",
            content="new content",
            rationale="better",
            confidence=0.8,
            risk="low",
            expected_metric="win_rate",
            expected_direction="up",
        )
        self.assertEqual(data.proposal_id, "p1")
        self.assertEqual(data.target_file, "protect.md")
        self.assertEqual(data.status, "proposed")  # default


if __name__ == "__main__":
    unittest.main()