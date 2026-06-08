"""Tests for evolve consolidate_node / apply_node wired to LLM chains.

Uses a fake model (no network) and an on-disk skill dir to exercise the full
consolidate -> apply path: prompt building, JSON parsing, applier validation,
smoke test, candidate skill-file writing, and graceful degradation.
"""

from __future__ import annotations

import asyncio

import pytest

from app.graphs.subgraphs.evolve.nodes import (
    apply_node,
    battle_node,
    consolidate_node,
    decide_node,
    init_evolve_node,
    training_node,
)


SEER_SKILL = """---
name: seer_vote
role: seer
status: active
applicable_actions:
  - vote
evolution:
  enabled: true
  allowed_actions:
    - append_rule
---

# Seer voting

## Strategy

Vote the most suspicious player.
"""


class FakeModel:
    """Async LLM stand-in: returns canned text per call in order."""

    def __init__(self, responses: list[str]):
        self._responses = list(responses)
        self.calls: list[list[dict]] = []

    async def ainvoke(self, messages):
        self.calls.append(messages)
        return self._responses.pop(0) if self._responses else ""


def _write_seer_skills(tmp_path):
    skill_dir = tmp_path / "skills"
    (skill_dir / "seer").mkdir(parents=True)
    (skill_dir / "seer" / "vote.md").write_text(SEER_SKILL, encoding="utf-8")
    return skill_dir


def _training_games():
    return [
        {
            "game_id": "g1",
            "winner": "villagers",
            "days": 4,
            "player_roles": {"1": "seer"},
            "decisions": [
                {"player_id": 1, "action_type": "vote", "action": "vote:3", "reasoning": "P3 lied"},
            ],
        },
        {
            "game_id": "g2",
            "winner": "werewolves",
            "days": 3,
            "player_roles": {"2": "seer"},
            "decisions": [
                {"player_id": 2, "action_type": "vote", "action": "vote:5", "reasoning": "guess"},
            ],
        },
    ]


class TrainingEvidenceGameSubgraph:
    """One-game subgraph fixture with a seer key decision for training_node."""

    def __init__(self):
        self.invocations: list[dict] = []

    async def ainvoke(self, game_state: dict):
        self.invocations.append(dict(game_state))
        return {
            "winner": "villagers",
            "roles": {"1": "seer", "2": "werewolf"},
            "game_events": [
                {"event_type": "game_init", "payload": {"roles": {"1": "seer", "2": "werewolf"}}},
                {"event_type": "night_end", "day": 1, "phase": "night", "target": 2},
            ],
            "decisions": [
                {
                    "decision_id": "d_check",
                    "player_id": 1,
                    "role": "seer",
                    "day": 1,
                    "phase": "night",
                    "action_type": "seer_check",
                    "selected_target": 2,
                    "private_reasoning": "2号发言前后矛盾，查验收益高。",
                    "confidence": 0.82,
                }
            ],
        }


def test_init_evolve_node_rejects_unsafe_run_id():
    with pytest.raises(ValueError, match="Unsafe run_id"):
        asyncio.run(init_evolve_node({"role": "seer", "run_id": "../escape"}))


def test_init_evolve_node_freezes_registry_baseline(tmp_path):
    from app.lib.version import VersionRegistry

    paths = _PathsStub(tmp_path)
    registry = VersionRegistry(paths.registry_dir)
    baseline = registry.publish_skills(
        "seer",
        {"seer/vote.md": SEER_SKILL},
        set_as_baseline=True,
    )

    out = asyncio.run(init_evolve_node({"role": "seer", "run_id": "r_baseline", "paths": paths}))

    assert out["parent_hash"] == baseline
    assert out["baseline_config"]["role_versions"] == {"seer": baseline}


def test_init_evolve_node_materializes_registry_baseline_skill_dir(tmp_path):
    from pathlib import Path

    from app.lib.version import VersionRegistry

    paths = _PathsStub(tmp_path)
    registry = VersionRegistry(paths.registry_dir)
    baseline = registry.publish_skills(
        "seer",
        {"seer/vote.md": SEER_SKILL},
        set_as_baseline=True,
    )
    legacy_dir = tmp_path / "legacy_skills"

    out = asyncio.run(
        init_evolve_node(
            {
                "role": "seer",
                "run_id": "r_baseline_skill_dir",
                "paths": paths,
                "config": {"skill_dir": str(legacy_dir)},
            }
        )
    )

    baseline_dir = Path(out["baseline_skill_dir"])
    assert out["parent_hash"] == baseline
    assert baseline_dir != legacy_dir
    assert (baseline_dir / "seer" / "vote.md").read_text(encoding="utf-8") == SEER_SKILL
    assert not (baseline_dir / "seer" / "seer" / "vote.md").exists()


def test_init_evolve_node_warns_when_registry_baseline_unavailable(tmp_path, monkeypatch):
    import app.graphs.subgraphs.evolve.nodes as nodes

    def _boom(state):
        raise RuntimeError("registry down")

    monkeypatch.setattr(nodes, "_registry", _boom)
    out = asyncio.run(init_evolve_node({"role": "seer", "run_id": "r_no_registry", "paths": _PathsStub(tmp_path)}))

    assert out["parent_hash"] == "baseline_seer"
    assert out["baseline_config"]["role_versions"] == {"seer": "baseline_seer"}
    assert any("baseline freeze failed" in warning and "registry down" in warning for warning in out["warnings"])


def test_training_node_attaches_compact_evidence(tmp_path):
    game = TrainingEvidenceGameSubgraph()
    baseline_dir = str(tmp_path / "frozen_baseline")
    legacy_dir = str(tmp_path / "legacy_skills")
    state = {
        "role": "seer",
        "run_id": "evolve_evidence",
        "config": {"training_games": 1, "seed_start": 7, "max_days": 2, "game_concurrency": 1},
        "baseline_skill_dir": baseline_dir,
        "skill_dir": legacy_dir,
        "paths": _PathsStub(tmp_path),
        "game_subgraph": game,
    }

    out = asyncio.run(training_node(state))

    assert len(game.invocations) == 1
    assert game.invocations[0]["skill_dir"] == baseline_dir
    training_game = out["training_games"][0]
    evidence = training_game["evidence"]
    assert evidence["counts"]["decisions"] == 1
    assert evidence["counts"]["role_key_decisions"] == 1
    key = evidence["role_key_decisions"][0]
    assert key["decision_id"] == "d_check"
    assert key["action_type"] == "seer_check"
    assert key["role"] == "seer"
    assert key["target"] == 2
    assert "查验收益高" in key["reason"]


def test_training_node_records_evidence_extraction_warning(tmp_path, monkeypatch):
    import app.graphs.subgraphs.evolve.nodes as nodes

    def _boom(game, *, role):
        raise RuntimeError("evidence boom")

    monkeypatch.setattr(nodes, "_build_training_evidence_summary", _boom)
    game = TrainingEvidenceGameSubgraph()
    state = {
        "role": "seer",
        "run_id": "evolve_evidence_warning",
        "config": {"training_games": 1, "seed_start": 7, "max_days": 2, "game_concurrency": 1},
        "paths": _PathsStub(tmp_path),
        "game_subgraph": game,
    }

    out = asyncio.run(training_node(state))

    assert "warnings" in out
    assert "evidence extraction failed" in out["warnings"][0]
    assert "evidence boom" in out["warnings"][0]
    training_game = out["training_games"][0]
    assert training_game["evidence"]["error"] == "evidence boom"
    assert training_game["warnings"] == out["warnings"]


def test_training_node_records_unexpected_failure(tmp_path, monkeypatch):
    import app.graphs.subgraphs.evolve.nodes as nodes

    async def _boom(*args, **kwargs):
        raise RuntimeError("scheduler down")

    monkeypatch.setattr(nodes, "_run_games", _boom)
    state = {
        "role": "seer",
        "run_id": "r_training_fail",
        "config": {"training_games": 1, "seed_start": 7, "max_days": 2, "game_concurrency": 1},
        "paths": _PathsStub(tmp_path),
        "game_subgraph": TrainingEvidenceGameSubgraph(),
    }

    out = asyncio.run(training_node(state))

    assert out["training_games"] == []
    assert out["status"] == "failed"
    assert out["errors"] == ["training: scheduler down"]
    assert out["current_stage"] == "training"
    assert out["progress"]["stage"] == "training"
    assert out["progress"]["completed_games"] == 0
    assert out["last_heartbeat_at"]
    assert out["diagnostics"][0]["kind"] == "training_error"
    assert out["diagnostics"][0]["stage"] == "training.run_games"
    assert out["diagnostics"][0]["exception_type"] == "RuntimeError"


def test_consolidate_node_parses_llm_proposals(tmp_path):
    skill_dir = _write_seer_skills(tmp_path)
    raw = (
        '{"trends": ["seer votes too early"], "proposals": [{'
        '"proposal_id": "p1", "target_file": "seer/vote.md", "action_type": "append_rule", '
        '"content": "Wait one round before voting.", "rationale": "two losses from early votes", '
        '"confidence": 0.8, "risk": "low", "expected_metric": "role_score", '
        '"expected_direction": "improve", "evidence": [{"game_id": "g1"}, {"game_id": "g2"}]}]}'
    )
    model = FakeModel([raw])
    state = {
        "role": "seer",
        "run_id": "evolve_test",
        "parent_hash": "baseline_seer",
        "config": {"max_proposals": 3, "skill_dir": str(skill_dir)},
        "model": model,
        "training_games": _training_games(),
    }
    out = asyncio.run(consolidate_node(state))

    assert len(model.calls) == 1
    assert out["status"] == "consolidating"
    assert len(out["proposals"]) == 1
    prop = out["proposals"][0]
    assert prop["target_file"] == "seer/vote.md"
    assert prop["status"] == "proposed"
    assert out["consolidation"]["trends"] == ["seer votes too early"]


def test_consolidate_node_records_skill_load_warnings(tmp_path):
    skill_dir = _write_seer_skills(tmp_path)
    (skill_dir / "seer" / "broken.md").write_text("# missing front matter\n", encoding="utf-8")
    raw = '{"trends": [], "proposals": []}'
    model = FakeModel([raw])
    state = {
        "role": "seer",
        "run_id": "evolve_test",
        "parent_hash": "baseline_seer",
        "config": {"max_proposals": 3, "skill_dir": str(skill_dir)},
        "model": model,
        "training_games": _training_games(),
    }

    out = asyncio.run(consolidate_node(state))

    assert len(model.calls) == 1
    assert out["proposals"] == []
    assert any(
        "consolidate: skill load error: seer/broken.md: missing YAML front matter" in warning
        for warning in out["warnings"]
    )


def test_consolidate_node_surfaces_parse_errors_and_filters_bad_proposals(tmp_path):
    skill_dir = _write_seer_skills(tmp_path)
    raw = (
        '{"trends": ["x"], "proposals": [{'
        '"proposal_id": "p_bad", "target_file": "seer/vote.md", "action_type": "append_rule", '
        '"content": "Wait for two checks.", "rationale": "only one supporting game", '
        '"confidence": 0.8, "risk": "low", "evidence": [{"game_id": "g1"}]'
        '}]}'
    )
    model = FakeModel([raw])
    state = {
        "role": "seer",
        "run_id": "evolve_test",
        "parent_hash": "baseline_seer",
        "config": {"max_proposals": 3, "skill_dir": str(skill_dir)},
        "model": model,
        "training_games": _training_games(),
    }

    out = asyncio.run(consolidate_node(state))

    assert len(model.calls) == 1
    assert out["proposals"] == []
    assert out["consolidation"]["proposals"] == []
    assert out["consolidation"]["warnings"] == out["warnings"]
    assert any("at least 2 distinct game_id" in warning for warning in out["warnings"])


def test_consolidate_prompt_includes_training_key_decisions(tmp_path):
    skill_dir = _write_seer_skills(tmp_path)
    raw = '{"trends": [], "proposals": []}'
    model = FakeModel([raw])
    game = _training_games()[0]
    game["evidence"] = {
        "role_key_decisions": [
            {
                "decision_id": "d_check",
                "day": 1,
                "phase": "night",
                "action_type": "seer_check",
                "player_id": 1,
                "role": "seer",
                "target": 3,
                "impact_level": "high",
                "key_reason": "rule_natural_key_action",
                "reason": "查验 3 号能验证白天冲突。",
                "notes": ["规则上直接改变信息。"],
            }
        ],
        "counts": {"decisions": 1, "key_decisions": 1, "role_key_decisions": 1},
    }
    state = {
        "role": "seer",
        "run_id": "r",
        "parent_hash": "baseline_seer",
        "config": {"max_proposals": 3, "skill_dir": str(skill_dir)},
        "model": model,
        "training_games": [game],
    }

    asyncio.run(consolidate_node(state))

    user_content = model.calls[0][1]["content"]
    assert "key_decisions" in user_content
    assert "decision_id" in user_content
    assert "d_check" in user_content
    assert "seer_check" in user_content


def test_consolidate_node_no_games_yields_no_proposals(tmp_path):
    skill_dir = _write_seer_skills(tmp_path)
    model = FakeModel(["{}"])
    state = {
        "role": "seer",
        "run_id": "r",
        "config": {"max_proposals": 3, "skill_dir": str(skill_dir)},
        "model": model,
        "training_games": [],
    }
    out = asyncio.run(consolidate_node(state))
    assert out["proposals"] == []
    assert out["consolidation"] is None
    assert model.calls == []  # no LLM call when there is nothing to consolidate


def test_consolidate_node_dedups_rejected_proposals(tmp_path):
    """A proposal repeating a rejected direction is dropped after parsing."""
    from app.config import PathConfig
    from app.lib.version import VersionRegistry

    paths = PathConfig(root=tmp_path)
    skill_dir = _write_seer_skills(tmp_path)
    # Seed the rejected buffer with a proposal targeting seer/vote.md.
    reg = VersionRegistry(paths.registry_dir)
    reg.save_rejected("seer", [{"target_file": "seer/vote.md", "rationale": "wait one round"}])

    # LLM returns a proposal on the same file with the same rationale → dup.
    raw = (
        '{"trends": ["x"], "proposals": [{'
        '"proposal_id": "p1", "target_file": "seer/vote.md", "action_type": "append_rule", '
        '"content": "c", "rationale": "wait one round", "confidence": 0.8, "risk": "low", '
        '"evidence": [{"game_id": "g1"}, {"game_id": "g2"}]}]}'
    )
    model = FakeModel([raw])
    state = {
        "role": "seer",
        "run_id": "r",
        "parent_hash": "baseline_seer",
        "config": {"max_proposals": 3, "skill_dir": str(skill_dir)},
        "paths": paths,
        "model": model,
        "training_games": _training_games(),
    }
    out = asyncio.run(consolidate_node(state))
    assert len(model.calls) == 1  # LLM was consulted
    assert out["proposals"] == []  # but the duplicate proposal was dropped


def test_consolidate_node_records_rejected_buffer_warning(tmp_path, monkeypatch):
    import app.graphs.subgraphs.evolve.nodes as nodes

    skill_dir = _write_seer_skills(tmp_path)
    raw = '{"trends": [], "proposals": []}'
    model = FakeModel([raw])

    def _boom(state):
        raise RuntimeError("registry unavailable")

    monkeypatch.setattr(nodes, "_registry", _boom)
    state = {
        "role": "seer",
        "run_id": "r",
        "parent_hash": "baseline_seer",
        "config": {"max_proposals": 3, "skill_dir": str(skill_dir)},
        "model": model,
        "training_games": _training_games(),
    }

    out = asyncio.run(consolidate_node(state))

    assert len(model.calls) == 1
    assert out["proposals"] == []
    assert "warnings" in out
    assert "failed to load rejected buffer" in out["warnings"][0]
    assert "registry unavailable" in out["warnings"][0]


def test_apply_node_writes_candidate_skills(tmp_path):
    skill_dir = _write_seer_skills(tmp_path)
    # Consolidation with one eligible proposal.
    consolidation = {
        "role": "seer",
        "run_id": "evolve_test",
        "proposals": [{
            "proposal_id": "p1",
            "target_file": "seer/vote.md",
            "action_type": "append_rule",
            "content": "Wait one round before voting.",
            "rationale": "two losses",
            "confidence": 0.8,
            "risk": "low",
            "status": "proposed",
        }],
    }
    # Applier LLM returns the full (modified) file set.
    new_file = SEER_SKILL + "\n- Wait one round before voting.\n"
    apply_raw = '{"files": {"seer/vote.md": %s}, "changes": [{"filename": "seer/vote.md", "action": "modified"}]}' % _json_str(new_file)
    model = FakeModel([apply_raw])
    state = {
        "role": "seer",
        "run_id": "evolve_test",
        "parent_hash": "baseline_seer",
        "config": {"skill_dir": str(skill_dir)},
        "paths": _PathsStub(tmp_path),
        "model": model,
        "consolidation": consolidation,
        "proposals": consolidation["proposals"],
    }
    out = asyncio.run(apply_node(state))

    assert len(model.calls) == 1
    assert out["status"] == "applying"
    assert out["candidate_hash"] == "candidate_evolve_test"
    assert len(out["diff"]) == 1
    assert out["diff"][0]["filename"] == "seer/vote.md"
    # Candidate file written to disk with the new content.
    candidate = out["candidate_skill_dir"]
    assert candidate is not None
    from pathlib import Path
    written = (Path(candidate) / "seer" / "vote.md").read_text(encoding="utf-8")
    assert "Wait one round before voting." in written


@pytest.mark.parametrize(
    "raw_template",
    [
        "```json\n{payload}\n```",
        "Here is the patch:\n\n{payload}\n\nDone.",
    ],
)
def test_parse_apply_output_extracts_json_object(raw_template):
    from app.lib.evolve import _parse_apply_output

    new_file = SEER_SKILL + "\n- Wait one round before voting.\n"
    payload = (
        '{"files": {"seer/vote.md": %s}, '
        '"changes": [{"filename": "seer/vote.md", "action": "modified"}]}'
    ) % _json_str(new_file)

    parsed = _parse_apply_output(raw_template.format(payload=payload))

    assert parsed["files"]["seer/vote.md"] == new_file
    assert parsed["changes"][0]["filename"] == "seer/vote.md"


@pytest.mark.parametrize(
    ("raw", "message"),
    [
        ('["not", "an", "object"]', "LLM output is not a JSON object"),
        ('{"changes": []}', "LLM output missing 'files' object"),
        ('{"files": []}', "LLM output missing 'files' object"),
    ],
)
def test_parse_apply_output_requires_files_object(raw, message):
    from app.lib.evolve import _parse_apply_output

    with pytest.raises(ValueError, match=message):
        _parse_apply_output(raw)


def test_apply_node_records_candidate_write_failure(tmp_path, monkeypatch):
    import app.graphs.subgraphs.evolve.nodes as nodes

    skill_dir = _write_seer_skills(tmp_path)
    consolidation = {
        "role": "seer",
        "run_id": "evolve_write_fail",
        "proposals": [{
            "proposal_id": "p1",
            "target_file": "seer/vote.md",
            "action_type": "append_rule",
            "content": "Wait one round before voting.",
            "rationale": "two losses",
            "confidence": 0.8,
            "risk": "low",
            "status": "proposed",
        }],
    }
    new_file = SEER_SKILL + "\n- Wait one round before voting.\n"
    apply_raw = '{"files": {"seer/vote.md": %s}, "changes": [{"filename": "seer/vote.md", "action": "modified"}]}' % _json_str(new_file)
    model = FakeModel([apply_raw])

    def _boom(state, skills):
        raise RuntimeError("candidate disk unavailable")

    monkeypatch.setattr(nodes, "_write_candidate_skills", _boom)
    state = {
        "role": "seer",
        "run_id": "evolve_write_fail",
        "parent_hash": "baseline_seer",
        "config": {"skill_dir": str(skill_dir)},
        "paths": _PathsStub(tmp_path),
        "model": model,
        "consolidation": consolidation,
        "proposals": consolidation["proposals"],
    }

    out = asyncio.run(apply_node(state))

    assert out["candidate_hash"] == "baseline_seer"
    assert out["candidate_skill_dir"] is None
    assert out["diff"] == []
    assert "apply: failed to write candidate skills: candidate disk unavailable" in out["errors"]
    assert out["warnings"] == out["errors"]


def test_apply_node_records_current_skill_read_failure(tmp_path, monkeypatch):
    import app.graphs.subgraphs.evolve.nodes as nodes

    skill_dir = _write_seer_skills(tmp_path)
    consolidation = {
        "role": "seer",
        "run_id": "evolve_read_fail",
        "proposals": [{
            "proposal_id": "p1",
            "target_file": "seer/vote.md",
            "action_type": "append_rule",
            "content": "Wait one round before voting.",
            "rationale": "two losses",
            "confidence": 0.8,
            "risk": "low",
            "status": "proposed",
        }],
    }
    model = FakeModel([])

    def _boom(skill_dir):
        raise RuntimeError("baseline skills unreadable")

    monkeypatch.setattr(nodes, "_read_skill_contents", _boom)
    state = {
        "role": "seer",
        "run_id": "evolve_read_fail",
        "parent_hash": "baseline_seer",
        "config": {"skill_dir": str(skill_dir)},
        "paths": _PathsStub(tmp_path),
        "model": model,
        "consolidation": consolidation,
        "proposals": consolidation["proposals"],
    }

    out = asyncio.run(apply_node(state))

    assert out["candidate_hash"] == "baseline_seer"
    assert out["candidate_skill_dir"] is None
    assert out["diff"] == []
    assert model.calls == []
    assert "apply: failed to read current skills: baseline skills unreadable" in out["errors"]
    assert out["warnings"] == out["errors"]


def test_apply_node_no_proposals_falls_back_to_baseline(tmp_path):
    skill_dir = _write_seer_skills(tmp_path)
    model = FakeModel([])  # must not be called
    state = {
        "role": "seer",
        "run_id": "r",
        "parent_hash": "baseline_seer",
        "config": {"skill_dir": str(skill_dir)},
        "paths": _PathsStub(tmp_path),
        "model": model,
        "consolidation": {"role": "seer", "proposals": []},
        "proposals": [],
    }
    out = asyncio.run(apply_node(state))
    assert out["candidate_hash"] == "baseline_seer"
    assert out["candidate_skill_dir"] is None
    assert out["diff"] == []
    assert model.calls == []


def test_apply_node_rejects_unsafe_edit(tmp_path):
    """Applier validation rejects edits to files without an eligible proposal."""
    skill_dir = _write_seer_skills(tmp_path)
    consolidation = {
        "role": "seer",
        "run_id": "r",
        "proposals": [{
            "proposal_id": "p1",
            "target_file": "seer/vote.md",
            "action_type": "append_rule",
            "content": "x",
            "confidence": 0.8,
            "risk": "low",
            "status": "proposed",
        }],
    }
    # LLM tries to change the role front-matter (illegal) -> validation fails -> fallback.
    bad = SEER_SKILL.replace("role: seer", "role: witch")
    raw = '{"files": {"seer/vote.md": %s}, "changes": []}' % _json_str(bad)
    model = FakeModel([raw])
    state = {
        "role": "seer",
        "run_id": "r",
        "parent_hash": "baseline_seer",
        "config": {"skill_dir": str(skill_dir)},
        "paths": _PathsStub(tmp_path),
        "model": model,
        "consolidation": consolidation,
        "proposals": consolidation["proposals"],
    }
    out = asyncio.run(apply_node(state))
    assert out["candidate_hash"] == "baseline_seer"
    assert out["diff"] == []
    assert "warnings" in out
    assert any("validation failed" in item for item in out["warnings"])
    assert out["consolidation"]["errors"] == out["warnings"]


def test_apply_smoke_test_reports_skill_loader_diagnostics():
    from app.lib.evolve import _smoke_test

    ok, message = _smoke_test({"broken.md": "# missing front matter\n"})

    assert ok is False
    assert "load_markdown_skills returned empty list" in message
    assert "broken.md: missing YAML front matter" in message


def _json_str(value: str) -> str:
    import json

    return json.dumps(value)


class _PathsStub:
    def __init__(self, root):
        from pathlib import Path

        self.evolution_dir = Path(root) / "evolution"
        self.registry_dir = Path(root) / "registry"


# ---------------------------------------------------------------------------
# battle_node — fixed-seed baseline vs candidate A/B
# ---------------------------------------------------------------------------

class FakeGameSubgraph:
    """Returns a winner per effective skill source for one role.

    The 'effective' skill dir for the evolving role is role_skill_dirs[role]
    if present, else skill_dir — mirroring create_agents_node. Keying off that
    lets a test distinguish baseline vs candidate sides.
    """

    def __init__(self, win_by_dir: dict, role: str = "seer"):
        self._win_by_dir = win_by_dir
        self._role = role
        self.invocations: list[dict] = []

    async def ainvoke(self, game_state: dict):
        self.invocations.append(dict(game_state))
        role_dirs = game_state.get("role_skill_dirs") or {}
        effective = role_dirs.get(self._role, game_state.get("skill_dir"))
        winner = self._win_by_dir.get(str(effective), "werewolves")
        return {
            "winner": winner,
            "roles": {"1": self._role},
            "game_events": [{"day": 2}],
            "decisions": [],
        }


def test_battle_node_runs_ab_and_flags_significant(tmp_path):
    baseline_dir = str(tmp_path / "baseline_skills")
    legacy_dir = str(tmp_path / "legacy_skills")
    candidate_dir = str(tmp_path / "candidate_skills")
    # Candidate (seer = villagers team) wins every game; baseline loses every game.
    game = FakeGameSubgraph({baseline_dir: "werewolves", candidate_dir: "villagers"})
    state = {
        "role": "seer",
        "run_id": "r",
        "parent_hash": "baseline_seer",
        "candidate_hash": "candidate_r",
        "candidate_skill_dir": candidate_dir,
        "baseline_skill_dir": baseline_dir,
        "skill_dir": legacy_dir,
        "config": {"battle_games": 4, "skill_dir": legacy_dir},
        "game_subgraph": game,
    }
    out = asyncio.run(battle_node(state))
    res = out["battle_result"]

    assert res["target_team"] == "villagers"
    assert res["candidate_win_rate"] == 1.0
    assert res["baseline_win_rate"] == 0.0
    assert res["win_rate_delta"] == 1.0
    assert res["significant"] is True
    # Same seed range used for both sides.
    seeds = [inv["seed"] for inv in game.invocations]
    assert sorted(seeds[:4]) == sorted(seeds[4:])
    # Candidate side overrides only the evolving role; baseline side does not.
    baseline_invs = game.invocations[:4]
    candidate_invs = game.invocations[4:]
    assert all(not inv.get("role_skill_dirs") for inv in baseline_invs)
    assert all(inv["role_skill_dirs"] == {"seer": candidate_dir} for inv in candidate_invs)
    assert all(inv["skill_dir"] == baseline_dir for inv in candidate_invs)
    # battle_games carries both sides, each tagged for the UI split.
    sides = {g["side"] for g in out["battle_games"]}
    assert sides == {"baseline", "candidate"}
    assert len(out["battle_games"]) == 8


def test_battle_node_skips_when_no_candidate(tmp_path):
    game = FakeGameSubgraph({})
    state = {
        "role": "seer",
        "run_id": "r",
        "parent_hash": "baseline_seer",
        "candidate_hash": "baseline_seer",  # equals parent → nothing changed
        "candidate_skill_dir": None,
        "skill_dir": str(tmp_path / "skills"),
        "config": {"battle_games": 4},
        "game_subgraph": game,
    }
    out = asyncio.run(battle_node(state))
    assert out["battle_result"]["skipped"] is True
    assert game.invocations == []  # no games run


def test_battle_node_records_unexpected_failure(tmp_path, monkeypatch):
    import app.graphs.subgraphs.evolve.nodes as nodes

    async def _boom(*args, **kwargs):
        raise RuntimeError("batch runner down")

    monkeypatch.setattr(nodes, "_run_games", _boom)
    state = {
        "role": "seer",
        "run_id": "r_battle_fail",
        "parent_hash": "baseline_seer",
        "candidate_hash": "candidate_r",
        "candidate_skill_dir": str(tmp_path / "candidate"),
        "skill_dir": str(tmp_path / "baseline"),
        "config": {"battle_games": 2},
        "game_subgraph": FakeGameSubgraph({}),
    }

    out = asyncio.run(battle_node(state))

    assert out["battle_games"] == []
    assert out["status"] == "failed"
    assert out["battle_result"]["skipped"] is True
    assert out["battle_result"]["reason"] == "battle_failed"
    assert out["battle_result"]["error"] == "batch runner down"
    assert out["errors"] == ["battle: batch runner down"]


def test_create_agents_node_applies_per_role_skill_dir(tmp_path):
    """create_agents_node routes the evolving role to its override dir only."""
    from app.graphs.subgraphs.agent.builder import build_agent_subgraph
    from app.graphs.subgraphs.game.nodes import create_agents_node

    baseline = tmp_path / "baseline"
    candidate = tmp_path / "candidate"
    baseline.mkdir()
    candidate.mkdir()

    class _Model:
        async def ainvoke(self, messages):
            return type("R", (), {"content": "{}"})()

    state = {
        "roles": {1: "seer", 2: "villager", 3: "werewolf"},
        "model": _Model(),
        "game_id": "g",
        "skill_dir": str(baseline),
        "role_skill_dirs": {"seer": str(candidate)},
        "agent_subgraph": build_agent_subgraph(),
    }
    out = asyncio.run(create_agents_node(state))
    agents = out["agents"]
    # Seer (evolving role) uses the candidate dir; everyone else uses baseline.
    assert str(agents[1].skill_dir) == str(candidate)
    assert str(agents[2].skill_dir) == str(baseline)
    assert str(agents[3].skill_dir) == str(baseline)


# ---------------------------------------------------------------------------
# decide_node — recommendation + registry side effects
# ---------------------------------------------------------------------------

def _seer_candidate_dir(tmp_path):
    d = tmp_path / "cand" / "seer"
    d.mkdir(parents=True)
    (d.parent / "seer" / "vote.md").write_text(SEER_SKILL, encoding="utf-8")
    return str(tmp_path / "cand")


def test_decide_promotes_to_registry_on_auto_promote(tmp_path):
    candidate_dir = _seer_candidate_dir(tmp_path)
    paths = _PathsStub(tmp_path)
    state = {
        "role": "seer",
        "run_id": "r1",
        "parent_hash": "baseline_seer",
        "candidate_hash": "candidate_r1",
        "candidate_skill_dir": candidate_dir,
        "paths": paths,
        "config": {"auto_promote": True},
        "proposals": [{"proposal_id": "p1", "target_file": "seer/vote.md"}],
        "battle_result": {"significant": True, "candidate_win_rate": 0.7},
    }
    out = asyncio.run(decide_node(state))
    assert out["result"]["recommendation"] == "promote"
    assert out["status"] == "promoted"

    from app.lib.version import VersionRegistry

    reg = VersionRegistry(paths.registry_dir)
    assert reg.get_baseline("seer") == out["result"]["published_version_id"]
    # Run state persisted.
    from app.lib.evolve import EvolutionStateManager

    mgr = EvolutionStateManager(root_dir=paths.evolution_dir)
    assert mgr.load_run("r1") is not None


def test_decide_rejects_and_saves_rejected(tmp_path):
    paths = _PathsStub(tmp_path)
    state = {
        "role": "seer",
        "run_id": "r2",
        "parent_hash": "baseline_seer",
        "candidate_hash": "candidate_r2",
        "candidate_skill_dir": str(tmp_path / "cand"),
        "paths": paths,
        "config": {"auto_promote": True},
        "proposals": [{"proposal_id": "p1", "target_file": "seer/vote.md", "rationale": "x"}],
        "battle_result": {"significant": False, "candidate_win_rate": 0.3},
    }
    out = asyncio.run(decide_node(state))
    assert out["result"]["recommendation"] == "reject"
    assert out["status"] == "rejected"

    from app.lib.version import VersionRegistry

    reg = VersionRegistry(paths.registry_dir)
    assert len(reg.load_rejected("seer")) == 1


def test_decide_review_only_without_auto_promote(tmp_path):
    candidate_dir = _seer_candidate_dir(tmp_path)
    paths = _PathsStub(tmp_path)
    state = {
        "role": "seer",
        "run_id": "r3",
        "parent_hash": "baseline_seer",
        "candidate_hash": "candidate_r3",
        "candidate_skill_dir": candidate_dir,
        "baseline_skill_dir": str(tmp_path / "baseline"),
        "paths": paths,
        "config": {"auto_promote": False},
        "proposals": [{"proposal_id": "p1", "target_file": "seer/vote.md"}],
        "battle_result": {"significant": True, "candidate_win_rate": 0.7},
    }
    out = asyncio.run(decide_node(state))
    assert out["result"]["recommendation"] == "promote"
    assert out["status"] == "reviewing"  # gate passed but no auto-promote → human review

    from app.lib.version import VersionRegistry

    reg = VersionRegistry(paths.registry_dir)
    assert reg.get_baseline("seer") is None  # registry untouched


def test_decide_records_promote_error_when_candidate_dir_missing(tmp_path):
    paths = _PathsStub(tmp_path)
    state = {
        "role": "seer",
        "run_id": "r_missing_candidate",
        "parent_hash": "baseline_seer",
        "candidate_hash": "candidate_missing",
        "candidate_skill_dir": None,
        "paths": paths,
        "config": {"auto_promote": True},
        "proposals": [{"proposal_id": "p1", "target_file": "seer/vote.md"}],
        "battle_result": {"significant": True, "candidate_win_rate": 0.7},
    }

    out = asyncio.run(decide_node(state))

    assert out["result"]["recommendation"] == "promote"
    assert out["status"] == "reviewing"
    assert out["errors"] == ["promote: missing candidate_skill_dir"]
    assert out["result"]["errors"] == out["errors"]
    assert out["diagnostics"][0]["kind"] == "registry_error"
    assert out["diagnostics"][0]["stage"] == "registry.promote"


def test_decide_records_promote_error_when_candidate_dir_empty(tmp_path):
    paths = _PathsStub(tmp_path)
    candidate_dir = tmp_path / "empty_candidate"
    candidate_dir.mkdir()
    state = {
        "role": "seer",
        "run_id": "r_empty_candidate",
        "parent_hash": "baseline_seer",
        "candidate_hash": "candidate_empty",
        "candidate_skill_dir": str(candidate_dir),
        "paths": paths,
        "config": {"auto_promote": True},
        "proposals": [{"proposal_id": "p1", "target_file": "seer/vote.md"}],
        "battle_result": {"significant": True, "candidate_win_rate": 0.7},
    }

    out = asyncio.run(decide_node(state))

    assert out["result"]["recommendation"] == "promote"
    assert out["status"] == "reviewing"
    assert "promote: no skill files found" in out["errors"][0]
    assert out["result"]["errors"] == out["errors"]


def test_decide_records_promote_error_when_candidate_read_fails(tmp_path, monkeypatch):
    import app.graphs.subgraphs.evolve.nodes as nodes

    paths = _PathsStub(tmp_path)
    candidate_dir = _seer_candidate_dir(tmp_path)

    def _boom(skill_dir):
        raise RuntimeError("candidate skills unreadable")

    monkeypatch.setattr(nodes, "_read_skill_contents", _boom)
    state = {
        "role": "seer",
        "run_id": "r_unreadable_candidate",
        "parent_hash": "baseline_seer",
        "candidate_hash": "candidate_unreadable",
        "candidate_skill_dir": candidate_dir,
        "paths": paths,
        "config": {"auto_promote": True},
        "proposals": [{"proposal_id": "p1", "target_file": "seer/vote.md"}],
        "battle_result": {"significant": True, "candidate_win_rate": 0.7},
    }

    out = asyncio.run(decide_node(state))

    assert out["result"]["recommendation"] == "promote"
    assert out["status"] == "reviewing"
    assert out["errors"] == ["promote: failed to read candidate skills: candidate skills unreadable"]
    assert out["result"]["errors"] == out["errors"]


def test_decide_records_persist_warning_in_result(tmp_path, monkeypatch):
    import app.graphs.subgraphs.evolve.nodes as nodes

    def _boom(self, run):
        raise RuntimeError("disk unavailable")

    monkeypatch.setattr("app.lib.evolve.EvolutionStateManager.save_run", _boom)
    paths = _PathsStub(tmp_path)
    state = {
        "role": "seer",
        "run_id": "r4",
        "parent_hash": "baseline_seer",
        "candidate_hash": "baseline_seer",
        "candidate_skill_dir": None,
        "paths": paths,
        "config": {"auto_promote": False},
        "proposals": [],
        "battle_result": {"skipped": True, "reason": "no_candidate_changes"},
    }

    out = asyncio.run(decide_node(state))

    assert out["result"]["recommendation"] == "reject"
    assert "warnings" in out
    assert "failed to persist run state" in out["warnings"][0]
    assert "disk unavailable" in out["result"]["warnings"][0]


def test_decide_persists_run_diagnostics(tmp_path):
    import json

    paths = _PathsStub(tmp_path)
    candidate_dir = _seer_candidate_dir(tmp_path)
    state = {
        "role": "seer",
        "run_id": "r_diag",
        "parent_hash": "baseline_seer",
        "candidate_hash": "candidate_r_diag",
        "candidate_skill_dir": candidate_dir,
        "baseline_skill_dir": str(tmp_path / "baseline"),
        "paths": paths,
        "config": {"auto_promote": False},
        "warnings": ["consolidate: dropped proposal p_bad: missing content"],
        "errors": ["apply: validation failed: invalid target"],
        "consolidation": {
            "role": "seer",
            "run_id": "r_diag",
            "parent_hash": "baseline_seer",
            "warnings": ["consolidate: dropped proposal p_bad: missing content"],
            "errors": [],
            "proposals": [{
                "proposal_id": "p1",
                "target_file": "seer/vote.md",
                "action_type": "append_rule",
                "content": "Wait one round.",
                "rationale": "two supporting games",
                "confidence": 0.8,
                "risk": "low",
                "evidence": [{"game_id": "g1"}, {"game_id": "g2"}],
                "status": "proposed",
            }],
        },
        "proposals": [{"proposal_id": "p1", "target_file": "seer/vote.md"}],
        "diff": [{
            "filename": "seer/vote.md",
            "action": "modified",
            "proposal_ref": "p1",
            "before": "old",
            "after": "new",
        }],
        "battle_result": {"significant": True, "candidate_win_rate": 0.7},
    }

    asyncio.run(decide_node(state))

    payload = json.loads((paths.evolution_dir / "r_diag" / "state.json").read_text(encoding="utf-8"))
    manifest = json.loads((paths.evolution_dir / "r_diag" / "manifest.json").read_text(encoding="utf-8"))
    assert payload["candidate_skill_dir"] == candidate_dir
    assert payload["baseline_skill_dir"] == str(tmp_path / "baseline")
    assert payload["warnings"] == ["consolidate: dropped proposal p_bad: missing content"]
    assert payload["errors"] == ["apply: validation failed: invalid target"]
    assert payload["proposals"]["proposals"][0]["proposal_id"] == "p1"
    assert payload["diff"][0]["filename"] == "seer/vote.md"
    assert payload["current_stage"] == "done"
    assert payload["progress"]["stage"] == "done"
    assert payload["progress"]["percent"] == 1.0
    assert payload["progress"]["recommendation"] == "promote"
    assert payload["last_heartbeat_at"]
    assert payload["diagnostics"] == []
    assert payload["manifest"] == manifest
    assert manifest["schema_version"] == 1
    assert manifest["run_type"] == "evolve"
    assert manifest["run_id"] == "r_diag"
    assert manifest["status"] == "reviewing"
    assert manifest["error_summary"] == "apply: validation failed: invalid target"
    assert manifest["paths"]["run_dir"] == str(paths.evolution_dir / "r_diag")
    assert manifest["paths"]["candidate_skill_dir"] == candidate_dir


def test_build_evolve_graph_signature_exposes_only_wired_parameters():
    import inspect

    from app.graphs.subgraphs.evolve.builder import build_evolve_graph

    assert list(inspect.signature(build_evolve_graph).parameters) == ["game_subgraph"]
