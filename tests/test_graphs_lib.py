"""Tests for app/graphs/ and app/lib/ — state types, graph builders, lib modules."""

import pytest


# ===========================================================================
# app/graphs/shared/state.py — all TypedDict definitions
# ===========================================================================

class TestGraphState:
    def test_agent_state_typeddict(self):
        from app.graphs.shared.state import AgentState
        s: AgentState = {
            "request": {},
            "player_id": 1,
            "role": "villager",
        }
        s["source"] = "llm"
        s["errors"] = []
        assert s["player_id"] == 1

    def test_game_state_typeddict(self):
        from app.graphs.shared.state import GameState
        s: GameState = {
            "game_id": "test_game",
            "seed": 42,
            "winner": None,
            "finished": False,
        }
        assert s["seed"] == 42

    def test_play_state_typeddict(self):
        from app.graphs.shared.state import PlayState
        s: PlayState = {
            "run_type": "play",
            "config": {},
        }
        assert s["run_type"] == "play"

    def test_eval_batch_state(self):
        from app.graphs.shared.state import EvalBatchState
        s: EvalBatchState = {
            "run_type": "eval",
            "batch_config": {"game_count": 10},
            "games": [],
            "player_scores": [],
            "rankable": False,
        }
        assert s["batch_config"]["game_count"] == 10

    def test_evolve_state(self):
        from app.graphs.shared.state import EvolveState
        s: EvolveState = {
            "run_type": "evolve",
            "role": "seer",
            "parent_hash": "abc123",
            "status": "training",
            "training_games": [],
            "errors": [],
        }
        assert s["role"] == "seer"

    def test_root_state(self):
        from app.graphs.shared.state import RootState
        s: RootState = {
            "run_type": "play",
            "config": {"mode": "dev"},
        }
        assert s["run_type"] == "play"


# ===========================================================================
# app/graphs/main/builder.py — _dispatch
# ===========================================================================

class TestRouter:
    def test_dispatch_play(self):
        from app.graphs.main.builder import _dispatch
        assert _dispatch({"run_type": "play"}) == "play"

    def test_dispatch_eval(self):
        from app.graphs.main.builder import _dispatch
        assert _dispatch({"run_type": "eval"}) == "eval"
        assert _dispatch({"run_type": "evaluation"}) == "eval"
        assert _dispatch({"run_type": "evaluation_batch"}) == "eval"

    def test_dispatch_evolve(self):
        from app.graphs.main.builder import _dispatch
        assert _dispatch({"run_type": "evolve"}) == "evolve"
        assert _dispatch({"run_type": "evolution"}) == "evolve"

    def test_dispatch_unknown(self):
        from app.graphs.main.builder import _dispatch
        with pytest.raises(ValueError, match="Unknown run_type"):
            _dispatch({"run_type": "bogus"})


# ===========================================================================
# app/graphs/shared/nodes/review.py — review_node, evidence_node
# ===========================================================================

class TestSharedNodes:
    def test_review_node_no_data(self):
        from app.graphs.shared.nodes.review import review_node
        import asyncio
        async def _run():
            return await review_node({})
        result = asyncio.run(_run())
        assert "review" in result
        assert result["review"]["status"] == "ok"

    def test_review_node_skips_decisions_without_player_id(self):
        from app.graphs.shared.nodes.review import review_node
        import asyncio
        async def _run():
            return await review_node({
                "game_id": "g_missing_pid",
                "roles": {"1": "seer"},
                "decisions": [
                    {"decision_id": "d_missing", "action_type": "seer_check"},
                ],
            })
        result = asyncio.run(_run())
        assert result["review"]["status"] == "ok"
        assert "warnings" in result["review"]
        assert "d_missing" in result["review"]["warnings"][0]
        assert result["warnings"] == result["review"]["warnings"]

    def test_review_node_surfaces_invalid_role_entries_as_warnings(self):
        from app.graphs.shared.nodes.review import review_node
        import asyncio
        async def _run():
            return await review_node({
                "game_id": "g_bad_roles",
                "roles": {
                    "1": "seer",
                    "seat_x": "witch",
                    "2": "not_a_role",
                },
            })
        result = asyncio.run(_run())
        assert result["review"]["status"] == "ok"
        assert "warnings" in result["review"]
        assert result["warnings"] == result["review"]["warnings"]
        assert any("seat_x" in warning and "witch" in warning for warning in result["review"]["warnings"])
        assert any("player_id=2" in warning and "not_a_role" in warning for warning in result["review"]["warnings"])

    @pytest.mark.parametrize(
        ("role_key", "role_value", "expected_type"),
        [
            ("roles", [("1", "seer")], "list"),
            ("roles", "not-a-role-map", "str"),
            ("roles", None, "NoneType"),
            ("player_roles", [("1", "seer")], "list"),
            ("player_roles", "not-a-role-map", "str"),
            ("player_roles", None, "NoneType"),
        ],
    )
    def test_review_node_treats_non_dict_roles_as_empty_with_warning(
        self,
        role_key,
        role_value,
        expected_type,
    ):
        from app.graphs.shared.nodes.review import review_node
        import asyncio

        async def _run():
            return await review_node({
                "game_id": f"g_bad_{role_key}_{expected_type}",
                role_key: role_value,
                "decisions": [
                    {"decision_id": "d1", "player_id": 1, "action_type": "speak"},
                ],
            })

        result = asyncio.run(_run())
        assert result["review"]["status"] == "ok"
        assert result["review"]["agent_scores"] == {}
        assert "warnings" in result["review"]
        assert result["warnings"] == result["review"]["warnings"]
        assert any(
            f"ignored {role_key}" in warning and expected_type in warning
            for warning in result["review"]["warnings"]
        )

    def test_evidence_node_failure_surfaces_top_level_warning(self, tmp_path, monkeypatch):
        from app.graphs.shared.nodes import review as review_nodes
        import asyncio

        def boom(inputs, bundle):
            raise RuntimeError("selector down")

        monkeypatch.setattr("app.lib.evidence.select_key_decisions", boom)

        async def _run():
            return await review_nodes.evidence_node({
                "game_id": "g_evidence_fail",
                "game_dir": tmp_path,
                "decisions": [
                    {
                        "decision_id": "d_fail",
                        "player_id": 1,
                        "role": "seer",
                        "day": 1,
                        "phase": "night",
                        "action_type": "seer_check",
                        "selected_target": 2,
                    }
                ],
                "game_events": [
                    {"event_type": "night_end", "day": 1, "phase": "night"},
                ],
            })

        result = asyncio.run(_run())
        assert result["evidence"]["status"] == "failed"
        assert result["evidence"]["warnings"] == ["evidence failed: RuntimeError: selector down"]
        assert result["warnings"] == result["evidence"]["warnings"]

    def test_evidence_node_no_dir(self):
        from app.graphs.shared.nodes.review import evidence_node
        import asyncio
        async def _run():
            return await evidence_node({})
        result = asyncio.run(_run())
        # No game_dir → skips
        assert isinstance(result, dict)
        assert result["evidence"]["status"] == "skipped"

    def test_evidence_node_loads_replay_when_state_inputs_empty(self, tmp_path):
        from app.graphs.shared.nodes.review import evidence_node
        from storage.interfaces import DecisionRecordData
        from storage.runtime import GamePersistence
        import asyncio

        db_path = tmp_path / "wolf.db"
        runs_root = tmp_path / "runs"
        game_dir = runs_root / "batch-1" / "game-001"
        game_dir.mkdir(parents=True)

        with GamePersistence(
            game_id="indexed_game_001",
            game_dir=game_dir,
            db_path=db_path,
            commit_every=100,
        ) as persistence:
            logger = persistence.create_event_logger()
            logger.record(
                day=1,
                phase="night",
                event_type="seer_result",
                message="seer checked 2",
                actor=1,
                target=2,
                payload={"result": "werewolves"},
                public=False,
            )

            sink = persistence.create_decision_sink()
            sink.record_decision(
                DecisionRecordData(
                    decision_id="d_check",
                    player_id=1,
                    role="seer",
                    day=1,
                    phase="night",
                    action_type="seer_check",
                    selected_target=2,
                    public_text="checked 2",
                    private_reasoning="2 is wolf",
                    confidence=0.9,
                )
            )
            persistence.save_game_result(
                seed=7,
                player_roles={1: "seer", 2: "werewolf"},
                config={"mode": "offline-review"},
                winner="villagers",
                started_at="2026-06-07T10:00:00+08:00",
                finished_at="2026-06-07T10:03:00+08:00",
                total_rounds=1,
                public_events=[],
                final_state={"winner": "villagers"},
                final_alive={1: True, 2: False},
            )

        async def _run():
            return await evidence_node(
                {
                    "game_dir": game_dir,
                    "db_path": db_path,
                    "root": runs_root,
                    "decisions": [],
                    "game_events": [],
                }
            )

        result = asyncio.run(_run())
        assert result["evidence"]["status"] == "ok"
        assert result["evidence"]["input_source"] == "replay"
        assert result["evidence"]["replay"]["decisions"]["status"] == "ok"
        assert result["evidence"]["replay"]["events"]["status"] == "ok"
        metadata = result["evidence"]["metadata"]
        assert metadata["used_state_decisions"] is False
        assert metadata["used_state_events"] is False
        assert metadata["used_replay_decisions"] is True
        assert metadata["used_replay_events"] is True
        assert metadata["replay_missing"] is False
        assert metadata["replay_error"] is False
        assert metadata["evidence_source"] == "replay"
        assert metadata["reliability"] == "high"
        assert result["decisions"][0]["decision_id"] == "d_check"
        assert result["game_events"][0]["event_type"] == "seer_result"
        assert result["evidence_inputs"][0].decision_id == "d_check"
        assert result["key_decisions"][0].decision_id == "d_check"
        assert "warnings" not in result

    def test_evidence_node_reports_replay_miss_instead_of_silent_zero(self, tmp_path):
        from app.graphs.shared.nodes.review import evidence_node
        import asyncio

        db_path = tmp_path / "missing.db"
        game_dir = tmp_path / "runs" / "missing-game"
        game_dir.mkdir(parents=True)

        async def _run():
            return await evidence_node(
                {
                    "game_dir": game_dir,
                    "db_path": db_path,
                    "decisions": [],
                    "game_events": [],
                }
            )

        result = asyncio.run(_run())
        assert result["evidence"]["status"] == "skipped"
        assert result["evidence"]["reason"] == "no_decisions"
        assert result["evidence"]["evidence_inputs"] == 0
        assert result["evidence"]["replay"]["decisions"]["status"] == "missing_db"
        assert result["evidence"]["replay"]["events"]["status"] == "missing_db"
        metadata = result["evidence"]["metadata"]
        assert metadata["used_state_decisions"] is False
        assert metadata["used_replay_decisions"] is False
        assert metadata["replay_missing"] is True
        assert metadata["replay_error"] is False
        assert metadata["evidence_source"] == "unavailable"
        assert metadata["reliability"] == "none"
        assert metadata["replay_statuses"]["decisions"] == "missing_db"
        assert metadata["replay_statuses"]["events"] == "missing_db"
        assert any("evidence replay decisions unavailable" in warning for warning in result["warnings"])
        assert any("no decisions available" in warning for warning in result["warnings"])

    def test_evidence_node_records_replay_db_error_metadata(self, tmp_path):
        from app.graphs.shared.nodes.review import evidence_node
        import asyncio

        db_path = tmp_path / "broken.db"
        db_path.write_text("not a sqlite database", encoding="utf-8")
        game_dir = tmp_path / "runs" / "broken-game"
        game_dir.mkdir(parents=True)

        async def _run():
            return await evidence_node(
                {
                    "game_dir": game_dir,
                    "db_path": db_path,
                    "decisions": [],
                    "game_events": [],
                }
            )

        result = asyncio.run(_run())
        assert result["evidence"]["status"] == "skipped"
        assert result["evidence"]["replay"]["decisions"]["status"] == "sqlite_error"
        assert result["evidence"]["replay"]["events"]["status"] == "sqlite_error"
        metadata = result["evidence"]["metadata"]
        assert metadata["used_state_decisions"] is False
        assert metadata["used_replay_decisions"] is False
        assert metadata["replay_missing"] is False
        assert metadata["replay_error"] is True
        assert metadata["evidence_source"] == "unavailable"
        assert metadata["reliability"] == "none"
        assert metadata["replay_statuses"]["decisions"] == "sqlite_error"
        assert any("evidence replay decisions unavailable" in warning for warning in result["warnings"])

    def test_evidence_node_records_state_fallback_metadata_when_replay_events_missing(self, tmp_path):
        from app.graphs.shared.nodes.review import evidence_node
        import asyncio

        db_path = tmp_path / "missing.db"

        async def _run():
            return await evidence_node(
                {
                    "game_dir": tmp_path,
                    "db_path": db_path,
                    "game_id": "state_fallback_game",
                    "game_events": [],
                    "decisions": [
                        {
                            "decision_id": "d_state",
                            "player_id": 1,
                            "role": "seer",
                            "day": 1,
                            "phase": "night",
                            "action_type": "seer_check",
                            "selected_target": 2,
                        }
                    ],
                }
            )

        result = asyncio.run(_run())
        assert result["evidence"]["status"] == "ok"
        assert result["evidence"]["input_source"] == "state"
        assert result["evidence"]["replay"]["events"]["status"] == "missing_db"
        metadata = result["evidence"]["metadata"]
        assert metadata["used_state_decisions"] is True
        assert metadata["used_state_events"] is False
        assert metadata["used_replay_decisions"] is False
        assert metadata["used_replay_events"] is False
        assert metadata["replay_missing"] is True
        assert metadata["replay_error"] is False
        assert metadata["evidence_source"] == "state"
        assert metadata["reliability"] == "degraded"
        assert metadata["replay_statuses"]["events"] == "missing_db"
        assert any("evidence replay events unavailable" in warning for warning in result["warnings"])
        assert any("running without game events" in warning for warning in result["warnings"])

    def test_evidence_node_keeps_memory_state_path_when_present(self, tmp_path, monkeypatch):
        from app.graphs.shared.nodes import review as review_nodes
        import asyncio

        def fail_replay(*args, **kwargs):
            raise AssertionError("replay should not be used when state has inputs")

        monkeypatch.setattr(review_nodes, "_load_replay_inputs", fail_replay)

        async def _run():
            return await review_nodes.evidence_node(
                {
                    "game_dir": tmp_path,
                    "db_path": tmp_path / "missing.db",
                    "game_id": "memory_game",
                    "game_events": [
                        {"event_type": "night_end", "day": 1, "phase": "night"},
                    ],
                    "decisions": [
                        {
                            "decision_id": "d_memory",
                            "player_id": 1,
                            "role": "seer",
                            "day": 1,
                            "phase": "night",
                            "action_type": "seer_check",
                            "selected_target": 2,
                        }
                    ],
                }
            )

        result = asyncio.run(_run())
        assert result["evidence"]["status"] == "ok"
        assert result["evidence"]["input_source"] == "state"
        assert "replay" not in result["evidence"]
        metadata = result["evidence"]["metadata"]
        assert metadata["used_state_decisions"] is True
        assert metadata["used_state_events"] is True
        assert metadata["used_replay_decisions"] is False
        assert metadata["used_replay_events"] is False
        assert metadata["replay_missing"] is False
        assert metadata["replay_error"] is False
        assert metadata["evidence_source"] == "state"
        assert metadata["reliability"] == "high"
        assert result["evidence_inputs"][0].decision_id == "d_memory"

    def test_shared_nodes_import(self):
        from app.graphs.shared.nodes import review_node, evidence_node
        assert review_node is not None
        assert evidence_node is not None


# ===========================================================================
# app/lib/review.py — analyze_game, scoring models
# ===========================================================================

class TestLibReview:
    def test_analyze_game_basic(self):
        from app.lib.review import analyze_game
        from engine.models import Role, Team

        roles = {1: Role.VILLAGER, 2: Role.WEREWOLF}
        decisions = {
            1: [{"day": 1, "action_type": "speak", "source": "llm", "confidence": 0.8}],
            2: [{"day": 1, "action_type": "speak", "source": "llm", "confidence": 0.6}],
        }

        review = analyze_game(
            game_log=[],
            agent_decisions=decisions,
            roles=roles,
            winner_team=Team.VILLAGERS,
            game_id="test_001",
        )
        assert review.game_id == "test_001"
        assert review.winner == "villagers"
        assert 1 in review.agent_scores
        assert 2 in review.agent_scores

    def test_analyze_game_with_events(self):
        from app.lib.review import analyze_game
        from engine.models import Role

        roles = {1: Role.HUNTER, 2: Role.WEREWOLF, 3: Role.SEER}
        decisions = {
            1: [{"day": 2, "action_type": "hunter_shoot", "selected_target": 3, "source": "llm"}],
            2: [{"day": 1, "action_type": "werewolf_kill", "selected_target": 3, "source": "llm"}],
            3: [{"day": 1, "action_type": "seer_check", "selected_target": 2, "source": "llm"}],
        }
        events = [
            {"event_type": "death", "target": 3, "day": 1, "phase": "night"},
        ]

        review = analyze_game(
            game_log=events,
            agent_decisions=decisions,
            roles=roles,
            winner_team="werewolves",
            game_id="test_002",
        )
        assert review.total_days > 0

    def test_game_review_to_dict(self):
        from app.lib.review import GameReview, AgentScores
        review = GameReview(game_id="g1", winner="villagers", total_days=3)
        review.agent_scores = {
            1: AgentScores(player_id=1, role="villager", team="villagers", overall=7.5),
        }
        d = review.to_dict()
        assert d["game_id"] == "g1"
        assert "1" in d["agent_scores"]

    def test_game_review_to_markdown(self):
        from app.lib.review import GameReview, AgentScores
        review = GameReview(game_id="g1", winner="villagers", total_days=2)
        review.agent_scores = {
            1: AgentScores(player_id=1, role="villager", team="villagers", overall=7.5),
        }
        md = review.to_markdown()
        assert "游戏复盘报告" in md
        assert "g1" in md

    def test_log_entries_list(self):
        from app.lib.review import log_entries
        assert log_entries([{"a": 1}]) == [{"a": 1}]

    def test_log_entries_dict(self):
        from app.lib.review import log_entries
        assert log_entries({"entries": [{"b": 2}]}) == [{"b": 2}]
        assert log_entries({"events": [{"c": 3}]}) == [{"c": 3}]

    def test_did_survive(self):
        from app.lib.review import did_survive
        assert did_survive(1, [])
        events = [{"event_type": "death", "target": 1, "player_id": 1}]
        assert not did_survive(1, events)

    def test_get_role_of(self):
        from app.lib.review import get_role_of
        from engine.models import Role
        roles = {1: Role.SEER, 2: Role.WEREWOLF}
        assert get_role_of(1, roles) == Role.SEER
        assert get_role_of(99, roles) is None


# ===========================================================================
# app/lib/score.py — PlayerScore, aggregation, fairness, rankable
# ===========================================================================

class TestLibScore:
    def test_player_score_creation(self):
        from app.lib.score import PlayerScore
        ps = PlayerScore(player_id=1, role="seer", speech_score=7.0, vote_score=8.0, role_score=8.5)
        d = ps.to_dict()
        assert d["player_id"] == 1
        assert d["role"] == "seer"

    def test_aggregate_batch_scores_empty(self):
        from app.lib.score import aggregate_batch_scores
        summary = aggregate_batch_scores([], batch_id="batch_01")
        assert summary.batch_id == "batch_01"
        assert summary.game_count == 0

    def test_aggregate_batch_scores_with_data(self):
        from app.lib.score import aggregate_batch_scores, PlayerScore
        scores = [
            PlayerScore(player_id=1, role="villager", role_score=8.0),
            PlayerScore(player_id=2, role="werewolf", role_score=6.0),
        ]
        summary = aggregate_batch_scores(scores, batch_id="batch_02", game_count=1)
        assert summary.game_count == 1
        assert summary.by_role_category["villager"] == 8.0
        assert summary.by_role_category["werewolf"] == 6.0

    def test_compute_role_score(self):
        from app.lib.score import compute_role_score
        score = compute_role_score(
            speech_score=8.0,
            vote_score=7.0,
            skill_score=6.0,
            logic_score=5.0,
            team_score=9.0,
            risk_penalty=1.0,
        )
        assert 0.0 < score <= 10.0

    def test_fairness_result(self):
        from app.lib.score import FairnessResult
        fr = FairnessResult(is_fair=True, reason="all ok")
        d = fr.to_dict()
        assert d["is_fair"] is True

    def test_validate_role_version_comparison(self):
        from app.lib.score import validate_role_version_comparison
        result = validate_role_version_comparison([], "seer")
        assert not result.is_fair

        batches = [
            {"batch_id": "b1", "target_role": "seer", "model_id": "m1", "seed_set_id": "s1"},
            {"batch_id": "b2", "target_role": "seer", "model_id": "m2", "seed_set_id": "s2"},
        ]
        result = validate_role_version_comparison(batches, "seer")
        assert result.is_fair

    def test_validate_model_comparison(self):
        from app.lib.score import validate_model_comparison
        result = validate_model_comparison([])
        assert not result.is_fair

        batches = [
            {"batch_id": "b1", "model_id": "m1", "seed_set_id": "s1"},
            {"batch_id": "b2", "model_id": "m2", "seed_set_id": "s2"},
        ]
        result = validate_model_comparison(batches)
        assert result.is_fair

    def test_compute_rankable(self):
        from app.lib.score import compute_rankable
        ok, reason = compute_rankable(mode="prod", game_count=10, valid_game_rate=0.9, is_fair=True)
        assert ok
        not_ok, _ = compute_rankable(mode="prod", game_count=10, valid_game_rate=0.5, is_fair=True)
        assert not not_ok

    def test_leaderboard_entries(self):
        from app.lib.score import (
            compute_role_version_leaderboard_entry,
            compute_model_leaderboard_entry,
        )
        e1 = compute_role_version_leaderboard_entry(
            batch_id="b1", target_role="seer", target_version_id="v1",
            rankable=True, game_count=20,
        )
        assert e1["target_role"] == "seer"

        e2 = compute_model_leaderboard_entry(
            batch_id="b2", model_id="m1", rankable=True, game_count=30,
        )
        assert e2["model_id"] == "m1"


# ===========================================================================
# app/lib/evidence.py — dataclasses, normalizer, selector
# ===========================================================================

class TestLibEvidence:
    def test_all_models_import(self):
        from app.lib.evidence import (
            DecisionEvidenceInput,
            DecisionEvidence,
            KeyDecision,
            GameEvidence,
            GameEvidenceBundle,
            EvidenceRunResult,
            ExperienceCandidate,
            AgentReasoning,
            PlayerView,
            DecisionResult,
            GodViewAfterGame,
        )
        # Create one instance of each to verify dataclass integrity
        devi = DecisionEvidenceInput(
            decision_id="d1",
            decision_index=0,
            day=1,
            phase="night",
            action_type="seer_check",
            player_view=PlayerView(player_id=1, role="seer"),
        )
        assert devi.decision_id == "d1"

        kd = KeyDecision(
            decision_id="d1", day=1, phase="night",
            action_type="seer_check", player_id=1,
            role="seer", key_reason="critical check",
            impact_level="high",
        )
        assert kd.impact_level == "high"

    def test_rubric_dimensions(self):
        from app.lib.evidence import RUBRIC_DIMENSIONS
        assert "result_quality" in RUBRIC_DIMENSIONS


# ===========================================================================
# app/lib/evolve.py — SkillProposal, SkillConsolidation, dedup
# ===========================================================================

class TestLibEvolve:
    def test_skill_proposal_roundtrip(self):
        from app.lib.evolve import SkillProposal
        p = SkillProposal(
            proposal_id="prop_001",
            target_file="seer.md",
            action_type="append_rule",
            content="Always check the most suspicious player first",
            rationale="Improves seer accuracy",
            confidence=0.85,
            risk="medium",
            evidence=[{"game_id": "g1", "reason": "missed check"}],
        )
        d = p.to_dict()
        p2 = SkillProposal.from_dict(d)
        assert p2.proposal_id == "prop_001"
        assert p2.confidence == 0.85

    def test_skill_consolidation(self):
        from app.lib.evolve import SkillConsolidation, SkillProposal
        c = SkillConsolidation(
            role="seer",
            run_id="run_1",
            source_games=["g1", "g2"],
            trends=["Seers are too passive"],
            proposals=[SkillProposal(proposal_id="p1", target_file="seer.md")],
        )
        d = c.to_dict()
        c2 = SkillConsolidation.from_dict(d)
        assert c2.role == "seer"
        assert len(c2.proposals) == 1

    def test_skill_diff(self):
        from app.lib.evolve import SkillDiff
        sd = SkillDiff(
            filename="seer.md",
            action="append_rule",
            proposal_ref="p1",
            before="# Old",
            after="# New",
        )
        d = sd.to_dict()
        assert d["filename"] == "seer.md"

    def test_deduplicate_proposals_no_rejected(self):
        from app.lib.evolve import deduplicate_proposals
        proposals = [
            {"target_file": "a.md", "rationale": "improve X"},
            {"target_file": "b.md", "rationale": "fix Y"},
        ]
        result = deduplicate_proposals(proposals, [])
        assert len(result) == 2

    def test_deduplicate_proposals_filters(self):
        from app.lib.evolve import deduplicate_proposals
        proposals = [
            {"target_file": "a.md", "rationale": "improve X"},
            {"target_file": "b.md", "rationale": "fix Y"},
        ]
        rejected = [
            {"target_file": "a.md", "rationale": "improve X"},
        ]
        result = deduplicate_proposals(proposals, rejected)
        assert len(result) == 1
        assert result[0]["target_file"] == "b.md"

    def test_parse_consolidation_records_invalid_json_errors(self):
        from app.lib.evolve import parse_consolidation

        result = parse_consolidation(role="seer", raw_output="not json", run_id="r1")

        assert result.proposals == []
        assert any("failed to parse LLM JSON" in item for item in result.errors)
        assert any("missing proposals list" in item for item in result.errors)

    def test_parse_consolidation_requires_proposals_list(self):
        from app.lib.evolve import parse_consolidation

        result = parse_consolidation(
            role="seer",
            raw_output='{"trends": [], "proposals": {"proposal_id": "p1"}}',
            run_id="r1",
        )

        assert result.proposals == []
        assert result.errors == ["consolidate: proposals must be a list"]

    def test_parse_consolidation_filters_low_evidence_proposals(self):
        from app.lib.evolve import parse_consolidation

        result = parse_consolidation(
            role="seer",
            raw_output=(
                '{"trends": [], "proposals": [{'
                '"proposal_id": "p1", "target_file": "seer/vote.md", '
                '"action_type": "append_rule", "content": "Wait one round.", '
                '"rationale": "single game only", "evidence": [{"game_id": "g1"}]'
                '}]}'
            ),
            run_id="r1",
        )

        assert result.proposals == []
        assert any("at least 2 distinct game_id" in item for item in result.warnings)

    def test_parse_consolidation_accepts_source_games_evidence(self):
        from app.lib.evolve import parse_consolidation

        result = parse_consolidation(
            role="seer",
            raw_output=(
                '{"trends": [], "proposals": [{'
                '"proposal_id": "p1", "target_file": "seer/vote.md", '
                '"action_type": "append_rule", "content": "Wait one round.", '
                '"rationale": "two games support it", "source_games": ["g1", "g2"]'
                '}]}'
            ),
            run_id="r1",
        )

        assert len(result.proposals) == 1
        assert result.proposals[0].proposal_id == "p1"

    def test_evolution_run_roundtrip(self):
        from app.lib.evolve import EvolutionRun
        run = EvolutionRun(
            run_id="r1", role="seer", parent_hash="abc",
            status="training", training_games=20,
        )
        d = run.to_dict()
        assert d["run_id"] == "r1"

    def test_evolution_config(self):
        from app.lib.evolve import EvolutionConfig
        cfg = EvolutionConfig(training_games=30, auto_promote=True)
        assert cfg.training_games == 30
        assert cfg.auto_promote

    def test_evolution_status_enum(self):
        from app.lib.evolve import EvolutionStatus
        assert EvolutionStatus.TRAINING == "training"
        assert EvolutionStatus.PROMOTED == "promoted"
        assert EvolutionStatus.REJECTED == "rejected"

    def test_evolution_state_manager_persists_runs(self, tmp_path):
        from app.lib.evolve import EvolutionRun, EvolutionStateManager

        manager = EvolutionStateManager(root_dir=tmp_path / "evolution")
        run = EvolutionRun(
            run_id="run_001",
            role="seer",
            parent_hash="base",
            status="training",
            training_games=3,
        )

        manager.save_run(run)
        loaded = manager.load_run("run_001")

        assert loaded is not None
        assert loaded.run_id == "run_001"
        assert loaded.role == "seer"
        assert [r.run_id for r in manager.list_runs("seer")] == ["run_001"]
        assert [r.run_id for r in manager.scan_active_runs()] == ["run_001"]

    def test_evolution_state_manager_load_run_skips_corrupt_state(self, tmp_path):
        from app.lib.evolve import EvolutionRun, EvolutionStateManager

        manager = EvolutionStateManager(root_dir=tmp_path / "evolution")
        run = EvolutionRun(
            run_id="run_good",
            role="seer",
            parent_hash="base",
            status="training",
            training_games=3,
        )
        manager.save_run(run)
        bad_dir = tmp_path / "evolution" / "run_bad"
        bad_dir.mkdir(parents=True)
        (bad_dir / "state.json").write_text("{not-json", encoding="utf-8")

        assert manager.load_run("run_bad") is None
        assert [r.run_id for r in manager.list_runs("seer")] == ["run_good"]
        assert [r.run_id for r in manager.scan_active_runs()] == ["run_good"]


# ===========================================================================
# app/lib/version.py — SkillVersionConfig, VersionRegistry
# ===========================================================================

def _registry_skill(body: str = "check suspicious players", *, role: str = "seer") -> str:
    return f"""---
name: {role}_main
role: {role}
status: active
applicable_actions:
  - vote
evolution:
  enabled: true
  allowed_actions:
    - append_rule
    - rewrite_section
---

# {role.title()}

## Strategy

{body}
"""


class TestLibVersion:
    def test_skill_version_config(self):
        from app.lib.version import SkillVersionConfig
        svc = SkillVersionConfig(
            name="baseline",
            created_at="2026-01-01",
            role_versions={"seer": "hash1", "witch": "hash2"},
        )
        d = svc.to_dict()
        assert d["role_versions"]["seer"] == "hash1"

    def test_skill_version_config_from_dict_none(self):
        from app.lib.version import SkillVersionConfig
        svc = SkillVersionConfig.from_dict(None)
        assert svc.name == ""
        assert svc.role_versions == {}

    def test_version_registry_creation(self, tmp_path):
        from app.lib.version import VersionRegistry
        reg = VersionRegistry(registry_dir=tmp_path / "registry")
        assert reg.registry_dir.exists()

    def test_version_registry_publish_promote_reject_and_composite(self, tmp_path):
        from app.lib.version import (
            VersionRegistry,
            build_baseline_config,
            build_composite_skill_dir,
            promote_version,
            reject_version,
        )

        reg = VersionRegistry(registry_dir=tmp_path / "registry")
        first = reg.publish_skills(
            "seer",
            {"main.md": _registry_skill("check suspicious players")},
            set_as_baseline=True,
        )
        second = reg.publish_skills(
            "seer",
            {"main.md": _registry_skill("check vote contradictions")},
            parent_id=first,
        )

        assert reg.get_baseline("seer") == first
        promote_version(reg, "seer", second)
        assert reg.get_baseline("seer") == second

        config = build_baseline_config(reg)
        assert config.role_versions == {"seer": second}
        skill_dir = build_composite_skill_dir(reg, config)
        assert skill_dir is not None
        assert "# Seer" in (skill_dir / "seer" / "main.md").read_text(encoding="utf-8")

        reject_version(reg, "seer", first)
        summaries = {s.version_id: s for s in reg.list_versions("seer")}
        assert summaries[first].status == "rejected"
        assert summaries[second].is_baseline

    def test_version_registry_cleanup_scratch_deletes_only_expired_owned_dirs(self, tmp_path):
        import os
        import time

        from app.lib.version import VersionRegistry

        reg = VersionRegistry(registry_dir=tmp_path / "registry")
        scratch = reg.registry_dir / "scratch"
        old_owned_single = scratch / "wolf_skill_seer_v1_old"
        old_owned_composite = scratch / "wolf_skills_old"
        new_owned = scratch / "wolf_skill_seer_v2_new"
        old_unowned = scratch / "manual_skill_old"
        old_owned_file = scratch / "wolf_skill_file_old"

        for path in [old_owned_single, old_owned_composite, new_owned, old_unowned]:
            path.mkdir(parents=True)
            (path / "marker.txt").write_text(path.name, encoding="utf-8")
        old_owned_file.write_text("not a directory", encoding="utf-8")

        old_mtime = time.time() - 3_600
        for path in [old_owned_single, old_owned_composite, old_unowned, old_owned_file]:
            os.utime(path, (old_mtime, old_mtime))

        assert reg.cleanup_scratch(max_age_seconds=60) == 2

        assert not old_owned_single.exists()
        assert not old_owned_composite.exists()
        assert new_owned.exists()
        assert old_unowned.exists()
        assert old_owned_file.exists()

    def test_version_registry_cleanup_scratch_runs_before_build_best_effort(self, tmp_path):
        import os
        import time

        from app.lib.version import VersionRegistry

        reg = VersionRegistry(registry_dir=tmp_path / "registry")
        skill = _registry_skill("baseline rule")
        version_id = reg.publish_skills("seer", {"main.md": skill}, set_as_baseline=True)
        scratch = reg.registry_dir / "scratch"
        stale = scratch / "wolf_skills_stale"
        stale.mkdir()
        old_mtime = time.time() - 3 * 24 * 60 * 60
        os.utime(stale, (old_mtime, old_mtime))

        skill_dir = reg.build_skill_dir({"seer": version_id})

        assert not stale.exists()
        assert skill_dir.exists()
        assert (skill_dir / "seer" / "main.md").read_text(encoding="utf-8") == skill

    def test_version_registry_rejects_unsafe_skill_paths(self, tmp_path):
        from app.lib.version import VersionRegistry

        reg = VersionRegistry(registry_dir=tmp_path / "registry")
        bad_paths = [
            "../escape.md",
            "C:/escape.md",
            "/abs/path.md",
            "not_markdown.txt",
        ]
        for bad_path in bad_paths:
            with pytest.raises(ValueError):
                reg.publish_skills("seer", {bad_path: "# unsafe"})

    def test_version_registry_rejects_bad_skill_manifest_without_version_dir(self, tmp_path):
        from app.lib.version import VersionRegistry

        reg = VersionRegistry(registry_dir=tmp_path / "registry")

        with pytest.raises(ValueError, match="missing required front matter field 'status'"):
            reg.publish_skills(
                "seer",
                {
                    "main.md": _registry_skill("bad").replace("status: active\n", ""),
                },
                version_id="seer_bad_manifest",
            )

        assert not (reg.registry_dir / "versions" / "seer" / "seer_bad_manifest").exists()

    def test_version_registry_publish_staging_failure_leaves_no_version_dir(self, tmp_path, monkeypatch):
        import app.lib.version as version_mod
        from app.lib.version import VersionRegistry

        reg = VersionRegistry(registry_dir=tmp_path / "registry")

        monkeypatch.setattr(version_mod, "validate_skill_dir", lambda *args, **kwargs: ["staged invalid"])
        with pytest.raises(ValueError, match="staged invalid"):
            reg.publish_skills("seer", {"main.md": _registry_skill("candidate")}, version_id="seer_staged")

        role_dir = reg.registry_dir / "versions" / "seer"
        assert not (role_dir / "seer_staged").exists()
        assert not list(role_dir.glob(".seer_staged.staging_*"))

    def test_version_registry_save_rejected_dedupes_by_direction(self, tmp_path):
        from app.lib.version import VersionRegistry

        reg = VersionRegistry(registry_dir=tmp_path / "registry")
        proposal = {
            "proposal_id": "p1",
            "target_file": "seer/vote.md",
            "action_type": "append_rule",
            "rationale": "wait one round",
            "content": "Wait before voting.",
        }

        reg.save_rejected("seer", [proposal], {"significant": False})
        reg.save_rejected("seer", [{**proposal, "proposal_id": "p2"}], {"significant": False})
        reg.save_rejected("seer", [{**proposal, "proposal_id": "p3", "content": "Wait for two checks."}])

        rows = reg.load_rejected("seer")
        assert len(rows) == 2
        assert all(row.get("dedupe_key") for row in rows)

    def test_version_registry_skips_corrupt_metadata_without_reusing_version_id(self, tmp_path):
        from app.lib.version import VersionRegistry

        reg = VersionRegistry(registry_dir=tmp_path / "registry")
        first = reg.publish_skills("seer", {"main.md": _registry_skill("first")})

        corrupt_dir = reg.registry_dir / "versions" / "seer" / "seer_v99"
        corrupt_dir.mkdir(parents=True)
        (corrupt_dir / "meta.json").write_text("{not-json", encoding="utf-8")

        summaries = {item.version_id for item in reg.list_versions("seer")}
        assert summaries == {first}

        next_version = reg.publish_skills("seer", {"main.md": _registry_skill("new")})
        assert next_version == "seer_v100"

    def test_version_registry_concurrent_publish_allocates_unique_version_ids(self, tmp_path):
        from concurrent.futures import ThreadPoolExecutor

        from app.lib.version import VersionRegistry

        registry_dir = tmp_path / "registry"

        def _publish(index: int) -> str:
            reg = VersionRegistry(registry_dir=registry_dir)
            return reg.publish_skills("seer", {"main.md": _registry_skill(f"rule {index}")})

        with ThreadPoolExecutor(max_workers=6) as pool:
            version_ids = list(pool.map(_publish, range(12)))

        assert sorted(version_ids, key=lambda item: int(item.rsplit("_v", 1)[1])) == [
            f"seer_v{i}" for i in range(1, 13)
        ]
        reg = VersionRegistry(registry_dir=registry_dir)
        assert {summary.version_id for summary in reg.list_versions("seer")} == set(version_ids)

    def test_version_registry_cas_failure_does_not_change_baseline_or_history(self, tmp_path):
        from app.lib.version import VersionRegistry
        from app.util.json import read_jsonl

        reg = VersionRegistry(registry_dir=tmp_path / "registry")
        first = reg.publish_skills("seer", {"main.md": _registry_skill("first")}, set_as_baseline=True)
        second = reg.publish_skills("seer", {"main.md": _registry_skill("second")})
        history_path = reg.registry_dir / "history.jsonl"
        before_history = read_jsonl(history_path)

        assert reg.set_baseline("seer", second, expected_current="stale_version") is False

        assert reg.get_baseline("seer") == first
        assert read_jsonl(history_path) == before_history
        summaries = {summary.version_id: summary for summary in reg.list_versions("seer")}
        assert summaries[first].is_baseline is True
        assert summaries[second].is_baseline is False
        assert summaries[second].status == "active"

    def test_version_registry_handles_corrupt_baselines_file(self, tmp_path):
        from app.lib.version import VersionRegistry

        reg = VersionRegistry(registry_dir=tmp_path / "registry")
        version_id = reg.publish_skills("seer", {"main.md": _registry_skill("baseline")})
        (reg.registry_dir / "baselines.json").write_text("{not-json", encoding="utf-8")

        assert reg.get_baseline("seer") is None
        summaries = reg.list_versions("seer")
        assert [summary.version_id for summary in summaries] == [version_id]
        assert summaries[0].is_baseline is False

    def test_storage_shared_interfaces_reexport_canonical_contracts(self):
        import storage.interfaces as canonical
        import storage
        import storage.shared as shared_pkg
        import storage.shared.interfaces as shared
        import storage.shared.models as shared_models

        assert shared.normalize_skill_path is canonical.normalize_skill_path
        assert shared.normalize_skill_text is canonical.normalize_skill_text
        assert shared.compute_hash is canonical.compute_hash
        assert shared.DecisionRecordData is canonical.DecisionRecordData
        assert shared.RoleVersionData is canonical.RoleVersionData
        assert shared.RoleHistoryData is canonical.RoleHistoryData
        assert shared_models.RoleVersionData is canonical.RoleVersionData
        assert shared_models.RoleHistoryData is canonical.RoleHistoryData
        assert shared_pkg.RoleVersionData is canonical.RoleVersionData
        assert shared_pkg.RoleHistoryData is canonical.RoleHistoryData
        assert storage.RoleVersionData is canonical.RoleVersionData
        assert storage.RoleHistoryData is canonical.RoleHistoryData
        with pytest.raises(ValueError):
            shared.normalize_skill_path("C:/escape.md")


# ===========================================================================
# app/lib/store.py — DecisionRecord, AgentDecisionRecorder
# ===========================================================================

class TestLibStore:
    def test_decision_record_creation(self):
        from app.lib.store import DecisionRecord
        from engine.models import ActionType
        dr = DecisionRecord(
            action_type=ActionType.SPEAK,
            day=1,
            phase="day_speech",
            player_id=3,
            role="villager",
            public_text="I am innocent",
            source="llm",
        )
        d = dr.to_dict()
        assert d["action_type"] == ActionType.SPEAK
        assert d["day"] == 1

    def test_agent_decision_recorder(self, tmp_path):
        from app.lib.store import AgentDecisionRecorder, DecisionRecord
        from engine.models import ActionType

        p = tmp_path / "decisions.jsonl"
        rec = AgentDecisionRecorder(stream_path=p)
        dr = DecisionRecord(action_type=ActionType.SPEAK)
        rec.record(dr)
        assert len(rec.records) == 1

    def test_game_run_config(self):
        from app.lib.store import GameRunConfig
        cfg = GameRunConfig(mode="dev", player_count=12, max_days=15)
        assert cfg.mode == "dev"
        assert cfg.player_count == 12
        assert cfg.max_days == 15

    def test_game_run_service_creates_persistence_session(self, tmp_path):
        from app.lib.store import GameRunConfig, GameRunService

        svc = GameRunService(db_path=tmp_path / "wolf.db")
        handle = svc.create_run(GameRunConfig(run_id="run_001", run_type="ordinary_game", seed=7))

        try:
            assert handle.run_id == "run_001"
            assert handle.game_id == "run_001"
            assert handle.policy.run_type.value == "ordinary_game"
            assert handle.persistence.has_db
        finally:
            handle.close()

    def test_agent_trace_recorder_flushes_archive(self, tmp_path):
        from app.lib.store import AgentTraceRecorder
        from engine.models import ActionRequest, ActionResponse, ActionType, Observation, Phase, Role

        observation = Observation(
            player_id=1,
            self_role=Role.VILLAGER,
            phase=Phase.DAY_SPEECH,
            day=1,
            alive_players=(1, 2),
            dead_players=(),
            sheriff_id=None,
            visible_events=(),
        )
        request = ActionRequest(
            player_id=1,
            action_type=ActionType.SPEAK,
            phase=Phase.DAY_SPEECH,
            observation=observation,
        )
        ctx = type(
            "Ctx",
            (),
            {
                "request": request,
                "response": ActionResponse(ActionType.SPEAK, text="hello"),
                "player_id": 1,
                "role": Role.VILLAGER,
                "source": "llm",
                "confidence": 0.8,
            },
        )()

        recorder = AgentTraceRecorder()
        recorder.record(ctx)
        archive = recorder.flush("g1", tmp_path, seed=9, player_roles={1: "villager"})

        assert recorder.count == 1
        assert archive.game_id == "g1"
        assert (tmp_path / "archive.json").exists()

    def test_agent_trace_recorder_rejects_missing_player_id(self):
        from app.lib.store import AgentTraceRecorder
        from engine.models import ActionResponse, ActionType

        ctx = type(
            "Ctx",
            (),
            {
                "response": ActionResponse(ActionType.SPEAK, text="hello"),
                "source": "llm",
                "confidence": 0.8,
            },
        )()

        recorder = AgentTraceRecorder()
        with pytest.raises(ValueError, match="player_id is required"):
            recorder.record(ctx)


# ===========================================================================
# app/lib/game.py — create_agents, create_engine (test structure only)
# ===========================================================================

class TestLibGame:
    class _CaptureTraceRecorder:
        def __init__(self):
            self.contexts = []

        def record(self, ctx):
            self.contexts.append(ctx)

    @staticmethod
    def _speech_request():
        from engine.models import ActionRequest, ActionType, GameEvent, Observation, Phase, Role

        observation = Observation(
            player_id=1,
            self_role=Role.VILLAGER,
            phase=Phase.DAY_SPEECH,
            day=1,
            alive_players=(1, 2),
            dead_players=(),
            sheriff_id=None,
            visible_events=(
                GameEvent(type="speech", day=1, phase=Phase.DAY_SPEECH, message="start"),
            ),
        )
        return ActionRequest(
            player_id=1,
            action_type=ActionType.SPEAK,
            phase=Phase.DAY_SPEECH,
            observation=observation,
        )

    @staticmethod
    def _diagnostic_entries(ctx, kind: str, stage: str) -> list[dict]:
        return [
            item
            for item in getattr(ctx, "diagnostics", [])
            if item.get("kind") == kind and item.get("stage") == stage
        ]

    def test_create_agent_runtime_imports(self):
        from app.lib.game import create_agent_runtime, create_agents, create_engine
        assert callable(create_agent_runtime)
        assert callable(create_agents)
        assert callable(create_engine)

    def test_agent_runtime_records_decision(self):
        import asyncio

        from app.lib.game import create_agent_runtime
        from app.lib.store import AgentDecisionRecorder
        from engine.models import ActionRequest, ActionType, GameEvent, Observation, Phase, Role

        class FakeModel:
            async def ainvoke(self, messages):
                return type("Result", (), {"content": '{"public_text":"ok","confidence":1}'})()

        async def _run():
            recorder = AgentDecisionRecorder()
            agent = create_agent_runtime(
                player_id=1,
                role=Role.VILLAGER,
                model=FakeModel(),
                recorder=recorder,
            )
            observation = Observation(
                player_id=1,
                self_role=Role.VILLAGER,
                phase=Phase.DAY_SPEECH,
                day=1,
                alive_players=(1, 2),
                dead_players=(),
                sheriff_id=None,
                visible_events=(
                    GameEvent(type="speech", day=1, phase=Phase.DAY_SPEECH, message="start"),
                ),
            )
            request = ActionRequest(
                player_id=1,
                action_type=ActionType.SPEAK,
                phase=Phase.DAY_SPEECH,
                observation=observation,
            )
            response = await agent.act(request)
            return response, recorder

        response, recorder = asyncio.run(_run())
        assert response.text == "ok"
        assert len(recorder.records) == 1
        assert recorder.records[0].public_text == "ok"

    def test_agent_runtime_repairs_player_id_placeholder_in_public_text(self):
        import asyncio

        from app.lib.game import create_agent_runtime
        from app.lib.store import AgentDecisionRecorder
        from engine.models import Role

        class FakeModel:
            async def ainvoke(self, messages):
                return type(
                    "Result",
                    (),
                    {"content": '{"public_text":"我是{player_id}号玩家，先过。","confidence":1}'},
                )()

        async def _run():
            recorder = AgentDecisionRecorder()
            agent = create_agent_runtime(
                player_id=4,
                role=Role.VILLAGER,
                model=FakeModel(),
                recorder=recorder,
            )
            request = self._speech_request()
            request.player_id = 4
            request.observation.player_id = 4
            response = await agent.act(request)
            return response, recorder

        response, recorder = asyncio.run(_run())
        assert response.text == "我是4号玩家，先过。"
        assert "{player_id}" not in response.text
        assert recorder.records[0].public_text == "我是4号玩家，先过。"
        assert recorder.records[0].source == "policy_adjusted"
        assert recorder.records[0].policy_adjustments == [
            "Repaired unresolved player_id placeholder in public text."
        ]

    def test_agent_runtime_records_memory_context_failure(self):
        import asyncio

        from app.graphs.subgraphs.agent.nodes import AgentRuntimeAdapter
        from app.lib.store import AgentDecisionRecorder
        from app.services.memory import AgentMemory
        from engine.models import ActionRequest, ActionType, GameEvent, Observation, Phase, Role

        class FakeModel:
            async def ainvoke(self, messages):
                return type("Result", (), {"content": '{"public_text":"ok","confidence":1}'})()

        class BrokenMemory(AgentMemory):
            def build_context(self, request):
                raise RuntimeError("memory down")

        async def _run():
            recorder = AgentDecisionRecorder()
            trace_recorder = self._CaptureTraceRecorder()
            memory = BrokenMemory(player_id=1, role=Role.VILLAGER)
            agent = AgentRuntimeAdapter(
                player_id=1,
                role=Role.VILLAGER,
                model=FakeModel(),
                memory=memory,
                recorder=recorder,
                trace_recorder=trace_recorder,
            )
            observation = Observation(
                player_id=1,
                self_role=Role.VILLAGER,
                phase=Phase.DAY_SPEECH,
                day=1,
                alive_players=(1, 2),
                dead_players=(),
                sheriff_id=None,
                visible_events=(
                    GameEvent(type="speech", day=1, phase=Phase.DAY_SPEECH, message="start"),
                ),
            )
            request = ActionRequest(
                player_id=1,
                action_type=ActionType.SPEAK,
                phase=Phase.DAY_SPEECH,
                observation=observation,
            )
            response = await agent.act(request)
            return response, recorder, memory, trace_recorder

        response, recorder, memory, trace_recorder = asyncio.run(_run())
        assert response.text == "ok"
        assert len(recorder.records) == 1
        assert any("memory build_context failed: RuntimeError: memory down" in err for err in recorder.records[0].errors)
        assert any("memory build_context failed: RuntimeError: memory down" in err for err in memory.errors)
        diagnostics = self._diagnostic_entries(trace_recorder.contexts[0], "memory_error", "memory.build_context")
        assert diagnostics[0]["exception_type"] == "RuntimeError"
        assert diagnostics[0]["exception_message"] == "memory down"

    def test_agent_runtime_records_remember_action_failure_before_recording(self):
        import asyncio

        from app.graphs.subgraphs.agent.nodes import AgentRuntimeAdapter
        from app.lib.store import AgentDecisionRecorder
        from app.services.memory import AgentMemory
        from engine.models import ActionRequest, ActionType, GameEvent, Observation, Phase, Role

        class FakeModel:
            async def ainvoke(self, messages):
                return type("Result", (), {"content": '{"public_text":"ok","confidence":1}'})()

        class BrokenMemory(AgentMemory):
            def remember_action(self, request, response, decision=None):
                raise RuntimeError("writeback down")

        async def _run():
            recorder = AgentDecisionRecorder()
            agent = AgentRuntimeAdapter(
                player_id=1,
                role=Role.VILLAGER,
                model=FakeModel(),
                memory=BrokenMemory(player_id=1, role=Role.VILLAGER),
                recorder=recorder,
            )
            observation = Observation(
                player_id=1,
                self_role=Role.VILLAGER,
                phase=Phase.DAY_SPEECH,
                day=1,
                alive_players=(1, 2),
                dead_players=(),
                sheriff_id=None,
                visible_events=(
                    GameEvent(type="speech", day=1, phase=Phase.DAY_SPEECH, message="start"),
                ),
            )
            request = ActionRequest(
                player_id=1,
                action_type=ActionType.SPEAK,
                phase=Phase.DAY_SPEECH,
                observation=observation,
            )
            response = await agent.act(request)
            return response, recorder

        response, recorder = asyncio.run(_run())
        assert response.text == "ok"
        assert len(recorder.records) == 1
        assert response.decision_id == recorder.records[0].decision_id
        assert recorder.records[0].errors == ["remember_action failed: RuntimeError: writeback down"]

    def test_agent_runtime_continues_when_skill_selection_fails(self, monkeypatch):
        import asyncio

        from app.graphs.subgraphs.agent.nodes import AgentRuntimeAdapter
        from app.lib.store import AgentDecisionRecorder
        from engine.models import ActionRequest, ActionType, GameEvent, Observation, Phase, Role

        class FakeModel:
            async def ainvoke(self, messages):
                return type("Result", (), {"content": '{"public_text":"ok","confidence":1}'})()

        def broken_select_skills(ctx, role, *, skill_root=None):
            raise RuntimeError("skill loader down")

        monkeypatch.setattr("app.graphs.subgraphs.agent.nodes.select_skills", broken_select_skills)

        async def _run():
            recorder = AgentDecisionRecorder()
            trace_recorder = self._CaptureTraceRecorder()
            agent = AgentRuntimeAdapter(
                player_id=1,
                role=Role.VILLAGER,
                model=FakeModel(),
                recorder=recorder,
                trace_recorder=trace_recorder,
            )
            observation = Observation(
                player_id=1,
                self_role=Role.VILLAGER,
                phase=Phase.DAY_SPEECH,
                day=1,
                alive_players=(1, 2),
                dead_players=(),
                sheriff_id=None,
                visible_events=(
                    GameEvent(type="speech", day=1, phase=Phase.DAY_SPEECH, message="start"),
                ),
            )
            request = ActionRequest(
                player_id=1,
                action_type=ActionType.SPEAK,
                phase=Phase.DAY_SPEECH,
                observation=observation,
            )
            response = await agent.act(request)
            return response, recorder, trace_recorder

        response, recorder, trace_recorder = asyncio.run(_run())
        assert response.text == "ok"
        assert len(recorder.records) == 1
        assert recorder.records[0].selected_skills == []
        assert recorder.records[0].errors == ["skill selection failed: RuntimeError: skill loader down"]
        diagnostics = self._diagnostic_entries(trace_recorder.contexts[0], "skill_error", "skill.select")
        assert diagnostics[0]["exception_type"] == "RuntimeError"
        assert diagnostics[0]["exception_message"] == "skill loader down"

    def test_agent_runtime_records_model_failure_diagnostics(self):
        import asyncio

        from app.graphs.subgraphs.agent.nodes import AgentRuntimeAdapter
        from app.lib.store import AgentDecisionRecorder
        from engine.models import Role

        class BrokenModel:
            async def ainvoke(self, messages):
                raise RuntimeError("llm down")

        async def _run():
            recorder = AgentDecisionRecorder()
            trace_recorder = self._CaptureTraceRecorder()
            agent = AgentRuntimeAdapter(
                player_id=1,
                role=Role.VILLAGER,
                model=BrokenModel(),
                recorder=recorder,
                trace_recorder=trace_recorder,
            )
            response = await agent.act(self._speech_request())
            return response, recorder, trace_recorder

        response, recorder, trace_recorder = asyncio.run(_run())
        assert response.text.startswith("1号玩家发言")
        assert recorder.records[0].source == "llm_error"
        diagnostics = self._diagnostic_entries(trace_recorder.contexts[0], "model_error", "model.decision_chain")
        assert diagnostics[0]["exception_type"] == "RuntimeError"
        assert diagnostics[0]["exception_message"] == "llm down"

    def test_agent_runtime_records_parse_failure_diagnostics(self):
        import asyncio

        from app.graphs.subgraphs.agent.nodes import AgentRuntimeAdapter
        from app.lib.store import AgentDecisionRecorder
        from engine.models import Role

        class FakeModel:
            async def ainvoke(self, messages):
                return type("Result", (), {"content": "not json"})()

        async def _run():
            recorder = AgentDecisionRecorder()
            trace_recorder = self._CaptureTraceRecorder()
            agent = AgentRuntimeAdapter(
                player_id=1,
                role=Role.VILLAGER,
                model=FakeModel(),
                recorder=recorder,
                trace_recorder=trace_recorder,
            )
            response = await agent.act(self._speech_request())
            return response, recorder, trace_recorder

        response, recorder, trace_recorder = asyncio.run(_run())
        assert response.text.startswith("1号玩家发言")
        assert recorder.records[0].source == "fallback"
        diagnostics = self._diagnostic_entries(trace_recorder.contexts[0], "parse_error", "parse.extract_json")
        assert diagnostics[0]["exception_type"] == "ValueError"
        assert "no JSON object" in diagnostics[0]["exception_message"]

    def test_agent_runtime_records_graph_fallback_diagnostics(self):
        import asyncio

        from app.graphs.subgraphs.agent.nodes import AgentRuntimeAdapter
        from app.lib.store import AgentDecisionRecorder
        from engine.models import Role

        class BrokenGraph:
            async def ainvoke(self, state):
                raise RuntimeError("graph down")

        class FakeModel:
            async def ainvoke(self, messages):
                return type("Result", (), {"content": '{"public_text":"ok","confidence":1}'})()

        async def _run():
            recorder = AgentDecisionRecorder()
            trace_recorder = self._CaptureTraceRecorder()
            agent = AgentRuntimeAdapter(
                graph=BrokenGraph(),
                player_id=1,
                role=Role.VILLAGER,
                model=FakeModel(),
                recorder=recorder,
                trace_recorder=trace_recorder,
            )
            response = await agent.act(self._speech_request())
            return response, recorder, trace_recorder

        response, recorder, trace_recorder = asyncio.run(_run())
        assert response.text == "ok"
        assert recorder.records[0].errors == ["Agent graph failed: graph down"]
        diagnostics = self._diagnostic_entries(trace_recorder.contexts[0], "state_error", "graph.invoke")
        assert diagnostics[0]["exception_type"] == "RuntimeError"
        assert diagnostics[0]["exception_message"] == "graph down"

    def test_agent_runtime_records_trace_recorder_failure(self):
        import asyncio

        from app.graphs.subgraphs.agent.nodes import AgentRuntimeAdapter
        from app.lib.store import AgentDecisionRecorder
        from engine.models import Role

        class FakeModel:
            async def ainvoke(self, messages):
                return type("Result", (), {"content": '{"public_text":"ok","confidence":1}'})()

        class BrokenTraceRecorder:
            def record(self, ctx):
                raise RuntimeError("trace sink down")

        async def _run():
            recorder = AgentDecisionRecorder()
            agent = AgentRuntimeAdapter(
                player_id=1,
                role=Role.VILLAGER,
                model=FakeModel(),
                recorder=recorder,
                trace_recorder=BrokenTraceRecorder(),
            )
            response = await agent.act(self._speech_request())
            return response, recorder

        response, recorder = asyncio.run(_run())
        assert response.text == "ok"
        assert recorder.records[0].errors == ["trace_recorder.record failed: RuntimeError: trace sink down"]

    def test_game_graph_uses_injected_model(self):
        import asyncio

        from app.graphs.subgraphs.agent.builder import build_agent_subgraph
        from app.graphs.subgraphs.game.builder import build_game_subgraph

        class FakeModel:
            async def ainvoke(self, messages):
                return type("Result", (), {"content": '{"public_text":"ok","confidence":1}'})()

        async def _run():
            graph = build_game_subgraph(agent_subgraph=build_agent_subgraph())
            return await graph.ainvoke({"seed": 2, "max_days": 5, "model": FakeModel()})

        result = asyncio.run(_run())
        assert result["finished"]
        assert result["winner"] == "werewolves"
        assert result.get("error") is None
        assert len(result["decisions"]) == 98

    def test_game_persist_node_writes_empty_artifact_files(self, tmp_path):
        import asyncio

        from app.graphs.subgraphs.game.nodes import persist_node

        state = {
            "game_id": "empty_artifacts",
            "game_dir": str(tmp_path),
            "game_events": [],
            "decisions": [],
            "winner": "villagers",
            "seed": 1,
            "roles": {},
            "finished": True,
        }
        asyncio.run(persist_node(state))

        assert (tmp_path / "game_events.jsonl").exists()
        assert (tmp_path / "game_events.jsonl").read_text(encoding="utf-8") == ""
        assert (tmp_path / "agent_decisions.jsonl").exists()
        assert (tmp_path / "agent_decisions.jsonl").read_text(encoding="utf-8") == ""
        assert (tmp_path / "meta.json").exists()

    def test_root_play_graph_returns_result(self):
        import asyncio

        from app.graphs.main.builder import build_root_graph

        class FakeModel:
            async def ainvoke(self, messages):
                return type("Result", (), {"content": '{"public_text":"ok","confidence":1}'})()

        async def _run():
            return await build_root_graph().ainvoke({
                "run_type": "play",
                "config": {"game_id": "play_test", "seed": 2, "max_days": 5},
                "model": FakeModel(),
            })

        result = asyncio.run(_run())
        payload = result["result"]
        assert payload["status"] == "completed"
        assert payload["game_id"] == "play_test"
        assert payload["winner"] == "werewolves"
        assert len(payload["decisions"]) > 0
        assert payload["review"]["game_id"] == "play_test"


# ===========================================================================
# app/run.py — entry points
# ===========================================================================

class TestRun:
    def test_run_game_import(self):
        from app.run import run_game, run_evaluation, run_evolution
        import asyncio
        assert asyncio.iscoroutinefunction(run_game)
        assert asyncio.iscoroutinefunction(run_evaluation)
        assert asyncio.iscoroutinefunction(run_evolution)

    def test_run_game_entrypoint_runs_graph(self):
        from app.run import run_game
        import asyncio

        class FakeModel:
            async def ainvoke(self, messages):
                return type("Result", (), {"content": '{"public_text":"ok","confidence":1}'})()

        async def _run():
            return await run_game(
                game_id="entry_game",
                seed=2,
                max_days=5,
                model=FakeModel(),
            )

        result = asyncio.run(_run())
        assert result["status"] == "completed"
        assert result["game_id"] == "entry_game"
        assert result["winner"] == "werewolves"
        assert len(result["decisions"]) > 0

    def test_run_game_entrypoint_honors_enable_sheriff(self):
        from app.run import run_game
        import asyncio

        class FakeModel:
            async def ainvoke(self, messages):
                return type("Result", (), {"content": '{"public_text":"ok","confidence":1}'})()

        async def _run():
            return await run_game(
                game_id="entry_game_no_sheriff",
                seed=2,
                max_days=5,
                enable_sheriff=False,
                model=FakeModel(),
            )

        result = asyncio.run(_run())
        assert result["status"] == "completed"
        assert all("sheriff" not in str(event.get("event_type") or event.get("type")) for event in result["events"])
        assert all("sheriff" not in str(event.get("phase")) for event in result["events"])

    def test_run_evaluation_entrypoint_runs_graph(self):
        from app.run import run_evaluation
        import asyncio

        class FakeModel:
            async def ainvoke(self, messages):
                return type("Result", (), {"content": '{"public_text":"ok","confidence":1}'})()

        async def _run():
            return await run_evaluation(
                batch_config={"batch_id": "test_batch", "game_count": 1, "max_days": 5},
                model=FakeModel(),
            )

        result = asyncio.run(_run())
        assert result["batch_id"] == "test_batch"
        assert result.get("status") != "not_" + "implemented"
        assert result["game_count"] == 1
        assert result["completed"] == 1
        assert len(result["games"]) == 1
        assert len(result["games"][0]["decisions"]) > 0
        assert result["score_summary"]["game_count"] == 1

    def test_run_evolution_entrypoint_runs_graph(self):
        from app.run import run_evolution
        import asyncio

        class FakeModel:
            async def ainvoke(self, messages):
                return type("Result", (), {"content": '{"public_text":"ok","confidence":1}'})()

        async def _run():
            return await run_evolution(
                role="seer",
                training_games=1,
                battle_games=1,
                max_days=5,
                model=FakeModel(),
                run_id="test_evolve",
            )

        result = asyncio.run(_run())
        assert result["role"] == "seer"
        assert result.get("status") != "not_" + "implemented"
        assert len(result["training_games"]) == 1
        # The trivial fake model produces no parseable proposals, so there is no
        # candidate to validate — battle skips and the run is recommended reject.
        assert result["proposals"] == []
        assert result["battle_result"]["skipped"] is True
        assert result["recommendation"] == "reject"
        assert isinstance(result["proposals"], list)
