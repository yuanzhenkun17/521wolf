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

    def test_game_state_schema_preserves_lifecycle_metadata(self):
        from langgraph.graph import END, START, StateGraph

        from app.graphs.shared.state import GameState

        workflow = StateGraph(GameState)

        def start_node(state: GameState) -> dict:
            return {
                "started_at": "2026-06-08T07:00:00+08:00",
                "outcome": "no_winner",
                "terminal_reason": "max_days_reached",
            }

        def finish_node(state: GameState) -> dict:
            assert state["started_at"] == "2026-06-08T07:00:00+08:00"
            assert state["terminal_reason"] == "max_days_reached"
            return {"finished_at": "2026-06-08T07:10:00+08:00"}

        workflow.add_node("start", start_node)
        workflow.add_node("finish", finish_node)
        workflow.add_edge(START, "start")
        workflow.add_edge("start", "finish")
        workflow.add_edge("finish", END)

        result = workflow.compile().invoke({"game_id": "schema_lifecycle"})

        assert result["started_at"] == "2026-06-08T07:00:00+08:00"
        assert result["finished_at"] == "2026-06-08T07:10:00+08:00"
        assert result["outcome"] == "no_winner"
        assert result["terminal_reason"] == "max_days_reached"

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

    def test_review_node_does_not_run_decision_judge_by_default(self):
        from app.graphs.shared.nodes.review import review_node
        import asyncio

        async def fail_if_called(_messages):
            raise AssertionError("decision judge should be opt-in")

        async def _run():
            return await review_node({
                "game_id": "g_judge_default_off",
                "roles": {"1": "seer", "2": "werewolf"},
                "winner": "villagers",
                "decisions": [
                    {
                        "decision_id": "d_check",
                        "player_id": 1,
                        "role": "seer",
                        "day": 1,
                        "phase": "night",
                        "action_type": "seer_check",
                        "selected_target": 2,
                    }
                ],
                "decision_judge_fn": fail_if_called,
            })

        result = asyncio.run(_run())
        assert result["review"]["status"] == "ok"
        assert "decision_judge" not in result["review"]

    def test_review_node_attaches_decision_judge_report_when_enabled(self):
        from app.graphs.shared.nodes.review import review_node
        import asyncio

        captured = []
        saved_rows = []

        async def fake_judge(messages):
            captured.append(messages)
            return (
                '{"schema_version":"1.0","decision_id":"d_check","score":8.5,'
                '"quality":"good","reason":"查验狼人有信息增量",'
                '"evidence_refs":["rule_natural_key_action"],"mistake_tags":[],'
                '"suggestion":"继续围绕查验链组织发言","confidence":0.8}'
            )

        class FakePersistence:
            def save_llm_judgments(self, rows):
                saved_rows.extend(rows)
                return [f"judgment_{index}" for index, _row in enumerate(rows)]

        async def _run():
            return await review_node({
                "game_id": "g_judge_on",
                "config": {"enable_llm_judge": True, "judge_max_decisions": 1},
                "persistence": FakePersistence(),
                "roles": {"1": "seer", "2": "werewolf"},
                "winner": "villagers",
                "decisions": [
                    {
                        "decision_id": "d_check",
                        "player_id": 1,
                        "role": "seer",
                        "day": 1,
                        "phase": "night",
                        "action_type": "seer_check",
                        "selected_target": 2,
                        "private_reasoning": "2 looks suspicious",
                        "confidence": 0.9,
                    }
                ],
                "game_events": [
                    {"event_type": "night_end", "day": 1, "phase": "night"},
                ],
                "decision_judge_fn": fake_judge,
            })

        result = asyncio.run(_run())
        report = result["review"]["decision_judge"]

        assert result["review"]["status"] == "ok"
        assert report["status"] == "ok"
        assert report["metrics"]["judged"] == 1
        assert report["selection"]["selected_for_judge"] == 1
        assert report["summary"]["average_score"] == 8.5
        assert report["judgments"][0]["decision_id"] == "d_check"
        assert report["judgments"][0]["quality"] == "good"
        assert report["persistence"]["llm_judgment_ids"] == ["judgment_0", "judgment_1"]
        assert [row["dimension"] for row in saved_rows] == ["decision_judge", "decision_judge_report"]
        assert captured
        assert "schema_version" in captured[0][1]["content"]

    def test_review_judgment_provider_fallback_delegates_to_storage_runtime(self, monkeypatch):
        from app.graphs.shared.nodes.review import _save_llm_judgment_rows
        import storage.runtime as runtime_mod

        provider = object()
        rows = [{"decision_id": "d_check"}]
        captured = {}

        def save_llm_judgments_with_provider(
            judgments,
            *,
            game_id,
            storage_provider=None,
            source_game_id=None,
        ):
            captured["judgments"] = judgments
            captured["game_id"] = game_id
            captured["storage_provider"] = storage_provider
            captured["source_game_id"] = source_game_id
            return ["stored_judgment"]

        monkeypatch.setattr(
            runtime_mod,
            "save_llm_judgments_with_provider",
            save_llm_judgments_with_provider,
        )

        saved = _save_llm_judgment_rows(
            {"storage_provider": provider},
            rows,
            game_id="g_judge_fallback",
        )

        assert saved == ["stored_judgment"]
        assert captured == {
            "judgments": rows,
            "game_id": "g_judge_fallback",
            "storage_provider": provider,
            "source_game_id": "g_judge_fallback",
        }

    def test_review_judgment_provider_fallback_noops_without_provider(self):
        from app.graphs.shared.nodes.review import _save_llm_judgment_rows

        saved = _save_llm_judgment_rows({}, [{"decision_id": "d_skip"}], game_id="g_no_provider")

        assert saved == []

    def test_review_node_keeps_report_when_decision_judge_persistence_fails(self):
        from app.graphs.shared.nodes.review import review_node
        import asyncio

        async def fake_judge(_messages):
            return (
                '{"schema_version":"1.0","decision_id":"d_check","score":8.0,'
                '"quality":"good","reason":"ok","evidence_refs":[],"mistake_tags":[],'
                '"suggestion":"hold","confidence":0.7}'
            )

        class BrokenPersistence:
            def save_llm_judgments(self, rows):
                raise RuntimeError("database down")

        async def _run():
            return await review_node({
                "game_id": "g_judge_persist_down",
                "config": {"enable_llm_judge": True, "judge_max_decisions": 1},
                "persistence": BrokenPersistence(),
                "roles": {"1": "seer", "2": "werewolf"},
                "winner": "villagers",
                "decisions": [
                    {
                        "decision_id": "d_check",
                        "player_id": 1,
                        "role": "seer",
                        "day": 1,
                        "phase": "night",
                        "action_type": "seer_check",
                        "selected_target": 2,
                    }
                ],
                "decision_judge_fn": fake_judge,
            })

        result = asyncio.run(_run())
        report = result["review"]["decision_judge"]

        assert result["review"]["status"] == "ok"
        assert report["status"] == "ok"
        assert report["metrics"]["judged"] == 1
        assert any("decision judge persistence failed" in warning for warning in result["review"]["warnings"])

    def test_review_node_keeps_heuristic_review_when_decision_judge_fails(self):
        from app.graphs.shared.nodes.review import review_node
        import asyncio

        async def broken_judge(_messages):
            raise RuntimeError("judge down")

        async def _run():
            return await review_node({
                "game_id": "g_judge_down",
                "config": {"enable_llm_judge": True, "judge_max_decisions": 1},
                "roles": {"1": "seer", "2": "werewolf"},
                "winner": "villagers",
                "decisions": [
                    {
                        "decision_id": "d_check",
                        "player_id": 1,
                        "role": "seer",
                        "day": 1,
                        "phase": "night",
                        "action_type": "seer_check",
                        "selected_target": 2,
                    }
                ],
                "decision_judge_fn": broken_judge,
            })

        result = asyncio.run(_run())
        report = result["review"]["decision_judge"]

        assert result["review"]["status"] == "ok"
        assert report["status"] == "failed"
        assert report["metrics"]["failed"] == 1
        assert any("decision judge failed for d_check" in warning for warning in result["review"]["warnings"])
        assert result["warnings"] == result["review"]["warnings"]

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

    def test_evidence_node_loads_replay_when_state_inputs_empty(self, tmp_path, monkeypatch):
        from app.graphs.shared.nodes.review import evidence_node
        from storage.replay import ReplayLookupResult
        import asyncio

        runs_root = tmp_path / "runs"
        game_dir = runs_root / "batch-1" / "game-001"
        game_dir.mkdir(parents=True)

        def fake_lookup(path, *, root=None, replay_type="events", **_kwargs):
            assert path == game_dir
            assert root == runs_root
            if replay_type == "decisions":
                return ReplayLookupResult(
                    status="ok",
                    game_id="indexed_game_001",
                    table="decisions",
                    message="decisions found",
                    data=[
                        {
                            "decision_id": "d_check",
                            "player_id": 1,
                            "role": "seer",
                            "day": 1,
                            "phase": "night",
                            "action_type": "seer_check",
                            "selected_target": 2,
                            "public_text": "checked 2",
                            "private_reasoning": "2 is wolf",
                            "confidence": 0.9,
                        }
                    ],
                )
            if replay_type == "events":
                return ReplayLookupResult(
                    status="ok",
                    game_id="indexed_game_001",
                    table="game_events",
                    message="events found",
                    data=[
                        {
                            "day": 1,
                            "phase": "night",
                            "event_type": "seer_result",
                            "message": "seer checked 2",
                            "actor": 1,
                            "target": 2,
                            "payload": {"result": "werewolves"},
                            "public": False,
                        }
                    ],
                )
            return ReplayLookupResult(
                status="ok",
                game_id="indexed_game_001",
                table="games",
                message="config found",
                data={"mode": "offline-review", "seed": 7},
            )

        monkeypatch.setattr("storage.replay.explain_replay_lookup", fake_lookup)

        async def _run():
            return await evidence_node(
                {
                    "game_dir": game_dir,
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

    def test_evidence_node_reports_replay_miss_instead_of_silent_zero(self, tmp_path, monkeypatch):
        from app.graphs.shared.nodes.review import evidence_node
        from storage.replay import ReplayLookupResult
        import asyncio

        game_dir = tmp_path / "runs" / "missing-game"
        game_dir.mkdir(parents=True)

        def fake_lookup(_path, *, replay_type="events", **_kwargs):
            table = {"decisions": "decisions", "events": "game_events", "config": "games"}[replay_type]
            return ReplayLookupResult(
                status="not_found",
                table=table,
                message="no indexed game matched the artifact path",
                candidates=(game_dir.name,),
            )

        monkeypatch.setattr("storage.replay.explain_replay_lookup", fake_lookup)

        async def _run():
            return await evidence_node(
                {
                    "game_dir": game_dir,
                    "decisions": [],
                    "game_events": [],
                }
            )

        result = asyncio.run(_run())
        assert result["evidence"]["status"] == "skipped"
        assert result["evidence"]["reason"] == "no_decisions"
        assert result["evidence"]["evidence_inputs"] == 0
        assert result["evidence"]["replay"]["decisions"]["status"] == "not_found"
        assert result["evidence"]["replay"]["events"]["status"] == "not_found"
        metadata = result["evidence"]["metadata"]
        assert metadata["used_state_decisions"] is False
        assert metadata["used_replay_decisions"] is False
        assert metadata["replay_missing"] is True
        assert metadata["replay_error"] is False
        assert metadata["evidence_source"] == "unavailable"
        assert metadata["reliability"] == "none"
        assert metadata["replay_statuses"]["decisions"] == "not_found"
        assert metadata["replay_statuses"]["events"] == "not_found"
        assert any("evidence replay decisions unavailable" in warning for warning in result["warnings"])
        assert any("no decisions available" in warning for warning in result["warnings"])

    def test_evidence_node_records_replay_storage_error_metadata(self, tmp_path, monkeypatch):
        from app.graphs.shared.nodes.review import evidence_node
        from storage.replay import ReplayLookupResult
        import asyncio

        game_dir = tmp_path / "runs" / "broken-game"
        game_dir.mkdir(parents=True)

        def fake_lookup(_path, *, replay_type="events", **_kwargs):
            table = {"decisions": "decisions", "events": "game_events", "config": "games"}[replay_type]
            return ReplayLookupResult(
                status="storage_error",
                table=table,
                message="storage error while loading replay",
                error="RuntimeError: storage unavailable",
                candidates=(game_dir.name,),
            )

        monkeypatch.setattr("storage.replay.explain_replay_lookup", fake_lookup)

        async def _run():
            return await evidence_node(
                {
                    "game_dir": game_dir,
                    "decisions": [],
                    "game_events": [],
                }
            )

        result = asyncio.run(_run())
        assert result["evidence"]["status"] == "skipped"
        assert result["evidence"]["replay"]["decisions"]["status"] == "storage_error"
        assert result["evidence"]["replay"]["events"]["status"] == "storage_error"
        metadata = result["evidence"]["metadata"]
        assert metadata["used_state_decisions"] is False
        assert metadata["used_replay_decisions"] is False
        assert metadata["replay_missing"] is False
        assert metadata["replay_error"] is True
        assert metadata["evidence_source"] == "unavailable"
        assert metadata["reliability"] == "none"
        assert metadata["replay_statuses"]["decisions"] == "storage_error"
        assert any("evidence replay decisions unavailable" in warning for warning in result["warnings"])

    def test_evidence_node_records_state_fallback_metadata_when_replay_events_missing(self, tmp_path, monkeypatch):
        from app.graphs.shared.nodes.review import evidence_node
        from storage.replay import ReplayLookupResult
        import asyncio

        def fake_lookup(_path, *, replay_type="events", **_kwargs):
            assert replay_type in {"events", "config"}
            table = {"events": "game_events", "config": "games"}[replay_type]
            return ReplayLookupResult(
                status="not_found",
                table=table,
                message="no indexed game matched the artifact path",
                candidates=(tmp_path.name,),
            )

        monkeypatch.setattr("storage.replay.explain_replay_lookup", fake_lookup)

        async def _run():
            return await evidence_node(
                {
                    "game_dir": tmp_path,
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
        assert result["evidence"]["replay"]["events"]["status"] == "not_found"
        metadata = result["evidence"]["metadata"]
        assert metadata["used_state_decisions"] is True
        assert metadata["used_state_events"] is False
        assert metadata["used_replay_decisions"] is False
        assert metadata["used_replay_events"] is False
        assert metadata["replay_missing"] is True
        assert metadata["replay_error"] is False
        assert metadata["evidence_source"] == "state"
        assert metadata["reliability"] == "degraded"
        assert metadata["replay_statuses"]["events"] == "not_found"
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

    def test_speech_quality_uses_content_diversity_and_source_signals(self):
        from app.lib.review import analyze_game
        from engine.models import Role, Team

        review = analyze_game(
            game_log=[],
            agent_decisions={
                1: [
                    {
                        "day": 1,
                        "action_type": "speak",
                        "source": "llm",
                        "confidence": 0.82,
                        "public_text": "结合昨夜信息和当前票型，我认为需要优先核验二号的身份，并保留对六号的观察。",
                    },
                    {
                        "day": 2,
                        "action_type": "speak",
                        "source": "llm",
                        "confidence": 0.76,
                        "public_text": "二号前后逻辑出现矛盾，六号的投票与发言一致，因此今天建议集中分析二号。",
                    },
                ],
                2: [
                    {
                        "day": 1,
                        "action_type": "speak",
                        "source": "fallback",
                        "confidence": 0.2,
                        "public_text": "暂无信息。",
                    },
                    {
                        "day": 2,
                        "action_type": "speak",
                        "source": "fallback",
                        "confidence": 0.2,
                        "public_text": "暂无信息。",
                    },
                ],
            },
            roles={1: Role.VILLAGER, 2: Role.WEREWOLF},
            winner_team=Team.VILLAGERS,
            game_id="speech-quality",
        )

        assert review.agent_scores[1].speech_quality > review.agent_scores[2].speech_quality
        assert review.agent_scores[1].speech_quality != 9.0
        assert review.agent_scores[2].speech_quality < 5.0

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
            {"batch_id": "b2", "model_id": "m2", "seed_set_id": "s1"},
        ]
        result = validate_model_comparison(batches)
        assert result.is_fair

        mixed_seed_result = validate_model_comparison([
            {"batch_id": "b1", "model_id": "m1", "seed_set_id": "s1"},
            {"batch_id": "b2", "model_id": "m2", "seed_set_id": "s2"},
        ])
        assert not mixed_seed_result.is_fair
        assert "same seed_set_id" in mixed_seed_result.reason

        same_subject_result = validate_model_comparison([
            {"batch_id": "b1", "model_id": "m1", "model_config_hash": "h1", "seed_set_id": "s1"},
            {"batch_id": "b2", "model_id": "m1", "model_config_hash": "h1", "seed_set_id": "s1"},
        ])
        assert not same_subject_result.is_fair
        assert "model subjects" in same_subject_result.reason

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
                '"rationale": "two games support it", '
                '"hypothesis": "When early vote pressure is unclear, waiting one round improves seer vote quality.", '
                '"trigger_condition": {"phase": ["day1"], "public_state": ["unclear_vote_pressure"]}, '
                '"expected_effect": {"primary_metric": "role_score", "expected_direction": "increase"}, '
                '"metric_targets": {"min_role_score_delta": 0.2}, '
                '"source_games": ["g1", "g2"]'
                '}]}'
            ),
            run_id="r1",
        )

        assert len(result.proposals) == 1
        assert result.proposals[0].proposal_id == "p1"
        assert result.generated_proposal_ids == ["p1"]
        assert result.preflight_passed_proposal_ids == ["p1"]
        assert result.preflight_rejected_proposal_ids == []
        assert result.proposals[0].preflight_status == "passed"

    def test_preflight_proposal_blocks_missing_hypothesis_and_specific_trigger(self):
        from app.lib.evolve import preflight_proposal

        report = preflight_proposal(
            {
                "proposal_id": "p_bad",
                "target_file": "seer/vote.md",
                "action_type": "append_rule",
                "content": "In seed 10000, vote player 3.",
                "rationale": "overfit to one replay",
                "trigger_condition": {"seed": 10000, "player": "P3"},
                "expected_effect": {"primary_metric": "role_score"},
                "metric_targets": {"min_role_score_delta": 0.2},
                "evidence_game_ids": ["g1", "g2"],
                "risk": "low",
            }
        )

        assert report["status"] == "blocked"
        assert "missing hypothesis" in report["reasons"]
        assert any("overfit-specific" in reason for reason in report["reasons"])

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

    def test_evolution_state_manager_persists_runs_to_postgresql(self, tmp_path, monkeypatch):
        from app.lib.evolve import EvolutionRun, EvolutionStateManager

        saved_runs = {}

        class FakeConn:
            def close(self):
                pass

        class FakeProvider:
            def open_evolution_connection(self):
                return FakeConn()

        class FakeEvolutionStore:
            def __init__(self, conn):
                self.conn = conn

            def save_run(self, run):
                saved_runs[run.run_id] = run

            def get_run(self, run_id):
                return saved_runs.get(run_id)

            def list_runs(self, role=None, status=None, limit=50):
                rows = list(saved_runs.values())
                if role is not None:
                    rows = [run for run in rows if run.role == role]
                if status is not None:
                    rows = [run for run in rows if run.status == status]
                return rows[:limit]

        monkeypatch.setattr(
            "storage.provider.storage_provider_from_env",
            lambda: FakeProvider(),
        )
        monkeypatch.setattr("storage.evolution.run_repo.EvolutionStore", FakeEvolutionStore)

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
        assert not (tmp_path / "evolution" / "run_001" / "state.json").exists()
        assert not (tmp_path / "evolution" / "run_001" / "manifest.json").exists()

    def test_evolution_state_manager_ignores_missing_postgres_run(self, tmp_path, monkeypatch):
        from app.lib.evolve import EvolutionRun, EvolutionStateManager

        saved_runs = {}

        class FakeConn:
            def close(self):
                pass

        class FakeProvider:
            def open_evolution_connection(self):
                return FakeConn()

        class FakeEvolutionStore:
            def __init__(self, conn):
                self.conn = conn

            def save_run(self, run):
                saved_runs[run.run_id] = run

            def get_run(self, run_id):
                return saved_runs.get(run_id)

            def list_runs(self, role=None, status=None, limit=50):
                rows = list(saved_runs.values())
                if role is not None:
                    rows = [run for run in rows if run.role == role]
                if status is not None:
                    rows = [run for run in rows if run.status == status]
                return rows[:limit]

        monkeypatch.setattr(
            "storage.provider.storage_provider_from_env",
            lambda: FakeProvider(),
        )
        monkeypatch.setattr("storage.evolution.run_repo.EvolutionStore", FakeEvolutionStore)

        manager = EvolutionStateManager(root_dir=tmp_path / "evolution")
        run = EvolutionRun(
            run_id="run_good",
            role="seer",
            parent_hash="base",
            status="training",
            training_games=3,
        )
        manager.save_run(run)

        assert manager.load_run("run_bad") is None
        assert [r.run_id for r in manager.list_runs("seer")] == ["run_good"]
        assert [r.run_id for r in manager.scan_active_runs()] == ["run_good"]
        assert list((tmp_path / "evolution").glob("**/*.json")) == []


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

    def test_version_registry_release_stage_and_provenance_summaries(self, tmp_path):
        from app.lib.version import VersionRegistry

        reg = VersionRegistry(registry_dir=tmp_path / "registry")
        baseline = reg.publish_skills(
            "seer",
            {"main.md": _registry_skill("baseline rule")},
            version_id="seer_baseline",
            source="seed",
            set_as_baseline=True,
        )
        shadow = reg.publish_skills(
            "seer",
            {"main.md": _registry_skill("shadow rule")},
            parent_id=baseline,
            source="evolve",
            run_id="run_shadow",
            proposal_ids=["p_shadow"],
            version_id="seer_shadow",
            release_stage="shadow",
            provenance={
                "trust_bundle_id": "tb_shadow",
                "release_decision": "shadow_candidate",
            },
        )
        canary = reg.publish_skills(
            "seer",
            {"main.md": _registry_skill("canary rule")},
            parent_id=shadow,
            source="evolve",
            run_id="run_canary",
            proposal_ids=["p_canary"],
            version_id="seer_canary",
            release_stage="canary",
            provenance={
                "trust_bundle_id": "tb_canary",
                "release_decision": "canary_candidate",
            },
        )

        assert reg.get_baseline("seer") == baseline

        summaries = {summary.version_id: summary for summary in reg.list_versions("seer")}
        assert summaries[baseline].is_baseline is True
        assert summaries[baseline].release_stage == "baseline"
        assert summaries[baseline].to_dict()["release_stage"] == "baseline"
        assert summaries[baseline].to_dict()["provenance"]["release_stage"] == "baseline"

        shadow_summary = summaries[shadow]
        assert shadow_summary.is_baseline is False
        assert shadow_summary.status == "shadow"
        assert shadow_summary.release_stage == "shadow"
        assert shadow_summary.provenance["source"] == "evolve"
        assert shadow_summary.provenance["run_id"] == "run_shadow"
        assert shadow_summary.provenance["proposal_ids"] == ["p_shadow"]
        assert shadow_summary.provenance["trust_bundle_id"] == "tb_shadow"
        shadow_payload = shadow_summary.to_dict()
        assert shadow_payload["release_stage"] == "shadow"
        assert shadow_payload["provenance"]["release_decision"] == "shadow_candidate"

        canary_summary = summaries[canary]
        assert canary_summary.is_baseline is False
        assert canary_summary.status == "canary"
        assert canary_summary.release_stage == "canary"
        assert canary_summary.to_dict()["provenance"]["trust_bundle_id"] == "tb_canary"

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
        captured = []

        class Sink:
            def record_decision(self, decision):
                captured.append(decision)

        rec = AgentDecisionRecorder(stream_path=p, sink=Sink())
        dr = DecisionRecord(action_type=ActionType.SPEAK)
        rec.record(dr)

        assert len(rec.records) == 1
        assert captured == [dr]
        assert not p.exists()

        exported = rec.export_jsonl(p)
        assert exported == p
        assert p.exists()
        assert "speak" in p.read_text(encoding="utf-8")

    def test_game_run_config(self):
        from app.lib.store import GameRunConfig
        cfg = GameRunConfig(mode="dev", player_count=12, max_days=15)
        assert cfg.mode == "dev"
        assert cfg.player_count == 12
        assert cfg.max_days == 15

    def test_game_run_service_creates_persistence_session(self):
        from app.lib.store import GameRunConfig, GameRunService

        class FakeConn:
            def __init__(self):
                self.committed = False
                self.closed = False

            def commit(self):
                self.committed = True

            def close(self):
                self.closed = True

        conn = FakeConn()
        svc = GameRunService()
        handle = svc.create_run_with_connection(
            GameRunConfig(run_id="run_001", run_type="ordinary_game", seed=7),
            conn,
        )

        try:
            assert handle.run_id == "run_001"
            assert handle.game_id == "run_001"
            assert handle.policy.run_type.value == "ordinary_game"
            assert handle.persistence.has_db
            assert handle.persistence.conn is conn
        finally:
            handle.close()
        assert conn.committed is True
        assert conn.closed is False

    def test_game_run_service_delegates_persistence_creation_to_storage_runtime(self, monkeypatch, tmp_path):
        from app.lib.store import GameRunConfig, GameRunService

        class FakePersistence:
            pass

        captured = {}
        persistence = FakePersistence()

        def create_game_persistence(**kwargs):
            captured.update(kwargs)
            return persistence

        monkeypatch.setattr("storage.runtime.create_game_persistence", create_game_persistence)

        svc = GameRunService(paths=tmp_path)
        config = GameRunConfig(
            run_id="run_factory",
            run_type="evaluation_batch",
            game_dir=tmp_path / "game",
            source_game_id="source_game",
            source_run_id="source_run",
            model_id="model-a",
            paired_seed=True,
            role_version_config={"seer": "seer-v1"},
        )

        handle = svc.create_run(config)

        assert handle.persistence is persistence
        assert handle.policy.run_type.value == "evaluation_batch"
        assert captured["game_id"] == "run_factory"
        assert captured["game_dir"] == tmp_path / "game"
        assert captured["conn"] is None
        assert captured["paths"] == tmp_path
        assert captured["source_game_id"] == "source_game"
        assert captured["run_type"].value == "evaluation_batch"
        assert captured["run_metadata"]["source_run_id"] == "source_run"
        assert captured["run_metadata"]["model_id"] == "model-a"
        assert captured["run_metadata"]["paired_seed"] is True
        assert captured["run_metadata"]["role_version_config"] == {"seer": "seer-v1"}

    def test_agent_trace_recorder_flush_builds_in_memory_archive(self, tmp_path):
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
        assert not (tmp_path / "archive.json").exists()
        assert not (tmp_path / "manifest.json").exists()

        exported = recorder.export_archive("g1", tmp_path, seed=9, player_roles={1: "villager"})

        assert exported.game_id == "g1"
        assert (tmp_path / "archive.json").exists()
        assert (tmp_path / "manifest.json").exists()

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
    def _sheriff_run_request():
        from engine.models import ActionRequest, ActionType, GameEvent, Observation, Phase, Role

        observation = Observation(
            player_id=1,
            self_role=Role.VILLAGER,
            phase=Phase.SHERIFF_ELECTION,
            day=1,
            alive_players=(1, 2, 3),
            dead_players=(),
            sheriff_id=None,
            visible_events=(
                GameEvent(type="sheriff_election", day=1, phase=Phase.SHERIFF_ELECTION, message="election"),
            ),
        )
        return ActionRequest(
            player_id=1,
            action_type=ActionType.SHERIFF_RUN,
            phase=Phase.SHERIFF_ELECTION,
            observation=observation,
        )

    @staticmethod
    def _seer_check_request():
        from engine.models import ActionRequest, ActionType, GameEvent, Observation, Phase, Role

        observation = Observation(
            player_id=1,
            self_role=Role.SEER,
            phase=Phase.NIGHT,
            day=1,
            alive_players=(1, 2, 3),
            dead_players=(),
            sheriff_id=None,
            visible_events=(
                GameEvent(type="night", day=1, phase=Phase.NIGHT, message="night"),
            ),
        )
        return ActionRequest(
            player_id=1,
            action_type=ActionType.SEER_CHECK,
            phase=Phase.NIGHT,
            observation=observation,
            candidates=(2, 3),
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

    def test_agent_runtime_records_model_success_diagnostics(self):
        import asyncio

        from app.graphs.subgraphs.agent.nodes import AgentRuntimeAdapter
        from app.lib.store import AgentDecisionRecorder
        from engine.models import Role

        class FakeModel:
            async def ainvoke(self, messages):
                return type("Result", (), {"content": '{"public_text":"ok","confidence":1}'})()

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
        assert response.text == "ok"
        assert recorder.records[0].source == "llm"
        diagnostics = self._diagnostic_entries(trace_recorder.contexts[0], "model_call", "model.decision_chain")
        assert diagnostics[0]["elapsed_ms"] >= 0
        assert diagnostics[0]["action_type"] == "speak"
        assert diagnostics[0]["player_id"] == 1

    def test_agent_runtime_default_mode_does_not_skip_low_value_actions(self):
        import asyncio

        from app.graphs.subgraphs.agent.nodes import AgentRuntimeAdapter
        from app.lib.store import AgentDecisionRecorder
        from engine.models import Role

        class FakeModel:
            def __init__(self):
                self.calls = 0

            async def ainvoke(self, messages):
                self.calls += 1
                return type("Result", (), {"content": '{"choice":"run","confidence":1}'})()

        async def _run():
            recorder = AgentDecisionRecorder()
            model = FakeModel()
            agent = AgentRuntimeAdapter(
                player_id=1,
                role=Role.VILLAGER,
                model=model,
                recorder=recorder,
            )
            response = await agent.act(self._sheriff_run_request())
            return response, recorder, model

        response, recorder, model = asyncio.run(_run())
        assert model.calls == 1
        assert response.choice == "run"
        assert recorder.records[0].source == "llm"

    def test_agent_runtime_fast_smoke_skips_low_value_actions(self):
        import asyncio

        from app.graphs.subgraphs.agent.nodes import AgentRuntimeAdapter
        from app.lib.store import AgentDecisionRecorder
        from engine.models import Role

        class FakeModel:
            def __init__(self):
                self.calls = 0

            async def ainvoke(self, messages):
                self.calls += 1
                raise AssertionError("fast smoke policy skip should not call the LLM")

        async def _run():
            recorder = AgentDecisionRecorder()
            trace_recorder = self._CaptureTraceRecorder()
            model = FakeModel()
            agent = AgentRuntimeAdapter(
                player_id=1,
                role=Role.VILLAGER,
                model=model,
                recorder=recorder,
                trace_recorder=trace_recorder,
                agent_runtime_config={"agent_fast_smoke": True},
            )
            response = await agent.act(self._sheriff_run_request())
            return response, recorder, trace_recorder, model

        response, recorder, trace_recorder, model = asyncio.run(_run())
        assert model.calls == 0
        assert response.choice == "pass"
        assert recorder.records[0].source == "policy_skipped"
        diagnostics = self._diagnostic_entries(trace_recorder.contexts[0], "policy_skip", "agent.policy_skip_llm")
        assert diagnostics[0]["action_type"] == "sheriff_run"
        assert diagnostics[0]["player_id"] == 1

    def test_agent_runtime_fast_smoke_skips_speech_actions(self):
        import asyncio

        from app.graphs.subgraphs.agent.nodes import AgentRuntimeAdapter
        from app.lib.store import AgentDecisionRecorder
        from engine.models import Role

        class FakeModel:
            def __init__(self):
                self.calls = 0

            async def ainvoke(self, messages):
                self.calls += 1
                raise AssertionError("fast smoke speech skip should not call the LLM")

        async def _run():
            recorder = AgentDecisionRecorder()
            trace_recorder = self._CaptureTraceRecorder()
            model = FakeModel()
            agent = AgentRuntimeAdapter(
                player_id=1,
                role=Role.VILLAGER,
                model=model,
                recorder=recorder,
                trace_recorder=trace_recorder,
                agent_runtime_config={"agent_fast_smoke": True},
            )
            response = await agent.act(self._speech_request())
            return response, recorder, trace_recorder, model

        response, recorder, trace_recorder, model = asyncio.run(_run())
        assert model.calls == 0
        assert "先过" in response.text
        assert recorder.records[0].source == "policy_skipped"
        diagnostics = self._diagnostic_entries(trace_recorder.contexts[0], "policy_skip", "agent.policy_skip_llm")
        assert diagnostics[0]["action_type"] == "speak"
        assert diagnostics[0]["player_id"] == 1

    def test_agent_runtime_fast_smoke_does_not_skip_required_target_actions(self):
        import asyncio

        from app.graphs.subgraphs.agent.nodes import AgentRuntimeAdapter
        from app.lib.store import AgentDecisionRecorder
        from engine.models import Role

        class FakeModel:
            def __init__(self):
                self.calls = 0

            async def ainvoke(self, messages):
                self.calls += 1
                return type("Result", (), {"content": '{"target":2,"confidence":1}'})()

        async def _run():
            recorder = AgentDecisionRecorder()
            model = FakeModel()
            agent = AgentRuntimeAdapter(
                player_id=1,
                role=Role.SEER,
                model=model,
                recorder=recorder,
                agent_runtime_config={"agent_fast_smoke": True},
            )
            response = await agent.act(self._seer_check_request())
            return response, recorder, model

        response, recorder, model = asyncio.run(_run())
        assert model.calls == 1
        assert response.target == 2
        assert recorder.records[0].source == "llm"

    def test_agent_runtime_skips_memory_compression_when_configured(self):
        import asyncio

        from app.graphs.subgraphs.agent.nodes import AgentRuntimeAdapter
        from app.lib.store import AgentDecisionRecorder
        from app.services.memory import AgentMemory, Segment, SegmentEvent
        from engine.models import Role

        class FakeModel:
            def __init__(self):
                self.calls = 0

            async def ainvoke(self, messages):
                self.calls += 1
                return type("Result", (), {"content": '{"public_text":"ok","confidence":1}'})()

        def memory_with_closed_segments():
            memory = AgentMemory(player_id=1, role=Role.VILLAGER)
            for index in range(5):
                segment = Segment(
                    segment_key=f"night:{index + 1}",
                    day=index + 1,
                    phase_group="night",
                    closed=True,
                )
                segment.add_event(
                    SegmentEvent(
                        day=index + 1,
                        phase="night",
                        event_type="speech",
                        actor=2,
                        target=None,
                        content=f"event {index + 1}",
                    )
                )
                memory.segments.append(segment)
            return memory

        async def _run():
            recorder = AgentDecisionRecorder()
            model = FakeModel()
            agent = AgentRuntimeAdapter(
                player_id=1,
                role=Role.VILLAGER,
                model=model,
                memory=memory_with_closed_segments(),
                recorder=recorder,
                agent_runtime_config={"agent_memory_compression_enabled": False},
            )
            response = await agent.act(self._speech_request())
            return response, recorder, model

        response, recorder, model = asyncio.run(_run())
        assert response.text == "ok"
        assert model.calls == 1
        assert recorder.records[0].source == "llm"

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
        assert diagnostics[0]["elapsed_ms"] >= 0
        assert diagnostics[0]["action_type"] == "speak"
        assert diagnostics[0]["player_id"] == 1

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

    def test_agent_runtime_falls_back_for_non_dict_json(self):
        import asyncio

        from app.graphs.subgraphs.agent.nodes import AgentRuntimeAdapter
        from app.lib.store import AgentDecisionRecorder
        from engine.models import Role

        class FakeModel:
            async def ainvoke(self, messages):
                return type("Result", (), {"content": "[]"})()

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
        assert "expected object, got list" in diagnostics[0]["exception_message"]

    def test_agent_runtime_records_invalid_confidence_diagnostic(self):
        import asyncio

        from app.graphs.subgraphs.agent.nodes import AgentRuntimeAdapter
        from app.lib.store import AgentDecisionRecorder
        from engine.models import Role

        class FakeModel:
            async def ainvoke(self, messages):
                return type("Result", (), {"content": '{"public_text":"ok","confidence":"high"}'})()

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
        assert response.text == "ok"
        assert recorder.records[0].confidence == 0.5
        diagnostics = self._diagnostic_entries(trace_recorder.contexts[0], "parse_error", "parse.confidence")
        assert diagnostics[0]["exception_type"] == "ValueError"

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

    def test_agent_runtime_records_recorder_failure_without_raising(self):
        import asyncio

        from app.graphs.subgraphs.agent.nodes import AgentRuntimeAdapter
        from engine.models import Role

        class FakeModel:
            async def ainvoke(self, messages):
                return type("Result", (), {"content": '{"public_text":"ok","confidence":1}'})()

        class BrokenRecorder:
            def record(self, decision):
                raise RuntimeError("decision sink down")

        async def _run():
            trace_recorder = self._CaptureTraceRecorder()
            agent = AgentRuntimeAdapter(
                player_id=1,
                role=Role.VILLAGER,
                model=FakeModel(),
                recorder=BrokenRecorder(),
                trace_recorder=trace_recorder,
            )
            response = await agent.act(self._speech_request())
            return response, trace_recorder

        response, trace_recorder = asyncio.run(_run())
        assert response.text == "ok"
        assert trace_recorder.contexts[0].decision_record.errors == [
            "recorder.record failed: RuntimeError: decision sink down"
        ]
        diagnostics = self._diagnostic_entries(trace_recorder.contexts[0], "record_error", "decision.record")
        assert diagnostics[0]["exception_type"] == "RuntimeError"
        assert diagnostics[0]["exception_message"] == "decision sink down"

    def test_agent_policy_does_not_force_optional_invalid_targets_to_first_candidate(self):
        from app.graphs.subgraphs.agent.nodes import _repair_or_fallback
        from engine.models import ActionRequest, ActionResponse, ActionType, GameEvent, Observation, Phase, Role

        observation = Observation(
            player_id=1,
            self_role=Role.VILLAGER,
            phase=Phase.EXILE_VOTE,
            day=1,
            alive_players=(1, 2, 3),
            dead_players=(),
            sheriff_id=None,
            visible_events=(
                GameEvent(type="vote", day=1, phase=Phase.EXILE_VOTE, message="vote"),
            ),
        )

        witch_request = ActionRequest(
            player_id=1,
            action_type=ActionType.WITCH_ACT,
            phase=Phase.NIGHT,
            observation=observation,
            candidates=(2, 3),
            metadata={"can_poison": True},
        )
        witch_response = _repair_or_fallback(
            witch_request,
            ActionResponse(ActionType.WITCH_ACT, choice="poison", target=99),
            {"policy_adjustments": []},
        )
        assert witch_response.choice == "none"
        assert witch_response.target is None

        vote_request = ActionRequest(
            player_id=1,
            action_type=ActionType.EXILE_VOTE,
            phase=Phase.EXILE_VOTE,
            observation=observation,
            candidates=(2, 3),
        )
        vote_response = _repair_or_fallback(
            vote_request,
            ActionResponse(ActionType.EXILE_VOTE, target=99),
            {"policy_adjustments": []},
        )
        assert vote_response.target is None

        white_wolf_request = ActionRequest(
            player_id=1,
            action_type=ActionType.WHITE_WOLF_EXPLODE,
            phase=Phase.DAY_SPEECH,
            observation=observation,
            candidates=(2, 3),
        )
        white_wolf_response = _repair_or_fallback(
            white_wolf_request,
            ActionResponse(ActionType.WHITE_WOLF_EXPLODE, choice="pass", target=2),
            {"policy_adjustments": []},
        )
        assert white_wolf_response.choice == "pass"
        assert white_wolf_response.target is None

        kill_request = ActionRequest(
            player_id=1,
            action_type=ActionType.WEREWOLF_KILL,
            phase=Phase.NIGHT,
            observation=observation,
            candidates=(2, 3),
        )
        kill_state = {"policy_adjustments": []}
        kill_response = _repair_or_fallback(
            kill_request,
            ActionResponse(ActionType.WEREWOLF_KILL, target=99),
            kill_state,
        )
        assert kill_response.target == 2
        assert kill_state["source"] == "policy_adjusted"
        assert kill_state["policy_adjustments"] == [
            "target not in candidates; repaired invalid target 99 to candidate 2."
        ]

        guard_state = {"policy_adjustments": []}
        guard_response = _repair_or_fallback(
            ActionRequest(
                player_id=1,
                action_type=ActionType.GUARD_PROTECT,
                phase=Phase.NIGHT,
                observation=observation,
                candidates=(2, 3),
            ),
            ActionResponse(ActionType.GUARD_PROTECT),
            guard_state,
        )
        assert guard_response.target == 2
        assert guard_state["policy_adjustments"] == [
            "required target missing; repaired to candidate 2."
        ]

        withdraw_state = {"policy_adjustments": []}
        withdraw_response = _repair_or_fallback(
            ActionRequest(
                player_id=1,
                action_type=ActionType.SHERIFF_WITHDRAW,
                phase=Phase.SHERIFF_ELECTION,
                observation=observation,
                candidates=(1, 2),
                metadata={"remaining_runners": [1, 2]},
            ),
            ActionResponse(ActionType.SHERIFF_WITHDRAW, choice="stay", target=2),
            withdraw_state,
        )
        assert withdraw_response.choice == "stay"
        assert withdraw_response.target is None
        assert withdraw_state["policy_adjustments"] == [
            "sheriff withdraw does not accept a target; cleared target."
        ]

    def test_agent_fallback_only_fills_required_targets(self):
        from app.graphs.subgraphs.agent.nodes import _fallback_response
        from engine.models import ActionRequest, ActionType, GameEvent, Observation, Phase, Role

        observation = Observation(
            player_id=1,
            self_role=Role.SEER,
            phase=Phase.NIGHT,
            day=1,
            alive_players=(1, 2, 3),
            dead_players=(),
            sheriff_id=None,
            visible_events=(
                GameEvent(type="night", day=1, phase=Phase.NIGHT, message="night"),
            ),
        )

        check_response = _fallback_response(
            ActionRequest(
                player_id=1,
                action_type=ActionType.SEER_CHECK,
                phase=Phase.NIGHT,
                observation=observation,
                candidates=(2, 3),
            )
        )
        assert check_response.target == 2

        vote_response = _fallback_response(
            ActionRequest(
                player_id=1,
                action_type=ActionType.EXILE_VOTE,
                phase=Phase.EXILE_VOTE,
                observation=observation,
                candidates=(2, 3),
            )
        )
        assert vote_response.target is None

    def test_agent_deferred_recording_only_records_engine_accepted_response(self):
        import asyncio
        from collections import Counter
        from collections import deque

        from app.graphs.subgraphs.agent.nodes import AgentRuntimeAdapter
        from app.lib.store import AgentDecisionRecorder
        from engine.config import GameConfig
        from engine.engine import GameEngine
        from engine.models import ActionResponse, ActionType, Phase, Role
        from engine.players import ScriptedAgent

        class FakeModel:
            def __init__(self):
                self.outputs = deque([
                    '{"target": 99, "public_text": "bad target", "confidence": 1}',
                    '{"target": 2, "public_text": "check 2", "confidence": 1}',
                ])

            async def ainvoke(self, messages):
                return type("Result", (), {"content": self.outputs.popleft()})()

        async def _run():
            roles = {1: Role.SEER, 2: Role.WEREWOLF, 3: Role.VILLAGER}
            recorder = AgentDecisionRecorder()
            trace_recorder = self._CaptureTraceRecorder()
            agent = AgentRuntimeAdapter(
                player_id=1,
                role=Role.SEER,
                model=FakeModel(),
                recorder=recorder,
                trace_recorder=trace_recorder,
            )
            engine = GameEngine(
                roles,
                {1: agent, 2: ScriptedAgent(), 3: ScriptedAgent()},
                config=GameConfig(name="deferred_recording_test", role_counts=Counter(roles.values())),
            )
            engine.state.day = 1
            engine.state.phase = Phase.NIGHT
            response = await engine._ask(
                1,
                ActionType.SEER_CHECK,
                candidates=(2, 3),
                validator=lambda res: res.target in (2, 3),
                default=ActionResponse(ActionType.SEER_CHECK, target=2),
            )
            return response, recorder, trace_recorder, engine

        response, recorder, trace_recorder, engine = asyncio.run(_run())

        assert response.target == 2
        assert [record.selected_target for record in recorder.records] == [2]
        assert [ctx.response.target for ctx in trace_recorder.contexts] == [2]
        assert [ctx.parsed_decision.get("target") for ctx in trace_recorder.contexts] == [99]
        assert trace_recorder.contexts[0].source == "policy_adjusted"
        assert trace_recorder.contexts[0].policy_adjustments == [
            "target not in candidates; repaired invalid target 99 to candidate 2."
        ]
        assert [event.target for event in engine.logger.entries if event.type == "invalid_response"] == []

    def test_game_graph_uses_injected_model(self):
        import asyncio

        from app.graphs.subgraphs.agent.builder import build_agent_subgraph
        from app.graphs.subgraphs.game.builder import build_game_subgraph

        class FakeModel:
            def __init__(self):
                self.calls = 0

            async def ainvoke(self, messages):
                self.calls += 1
                return type("Result", (), {"content": '{"public_text":"ok","confidence":1}'})()

        async def _run():
            model = FakeModel()
            graph = build_game_subgraph(agent_subgraph=build_agent_subgraph())
            result = await graph.ainvoke({"seed": 2, "max_days": 5, "model": model})
            return result, model

        result, model = asyncio.run(_run())
        assert result["finished"]
        assert result["winner"] == "werewolves"
        assert result.get("error") is None
        assert model.calls > 0
        assert len(result["decisions"]) > 0

    def test_game_persist_node_does_not_write_empty_artifact_files(self, tmp_path):
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

        assert not (tmp_path / "game_events.jsonl").exists()
        assert not (tmp_path / "agent_decisions.jsonl").exists()
        assert not (tmp_path / "meta.json").exists()

    def test_game_persist_node_writes_pg_persistence_when_available(self):
        import asyncio

        from app.graphs.subgraphs.game.nodes import persist_node

        class FakePersistence:
            def __init__(self):
                self.calls = []

            def save_game_result(self, **kwargs):
                self.calls.append(kwargs)

        persistence = FakePersistence()
        state = {
            "game_id": "pg_persist",
            "persistence": persistence,
            "game_events": [
                {"event_type": "night_end", "day": 1, "phase": "night", "public": True},
                {"event_type": "seer_result", "day": 1, "phase": "night", "public": False},
            ],
            "winner": "villagers",
            "seed": 3,
            "roles": {"1": "seer", 2: "werewolf"},
            "finished": True,
            "started_at": "2026-01-01T00:00:00+08:00",
            "finished_at": "2026-01-01T00:10:00+08:00",
        }

        asyncio.run(persist_node(state))

        assert len(persistence.calls) == 1
        call = persistence.calls[0]
        assert call["seed"] == 3
        assert call["player_roles"] == {1: "seer", 2: "werewolf"}
        assert call["winner"] == "villagers"
        assert call["started_at"] == "2026-01-01T00:00:00+08:00"
        assert call["finished_at"] == "2026-01-01T00:10:00+08:00"
        assert call["total_rounds"] == 1
        assert call["public_events"] == [
            {"event_type": "night_end", "day": 1, "phase": "night", "public": True}
        ]
        assert call["final_state"]["status"] == "completed"

    def test_game_persist_node_replaces_empty_started_at(self):
        import asyncio

        from app.graphs.subgraphs.game.nodes import persist_node

        class FakePersistence:
            def __init__(self):
                self.calls = []

            def save_game_result(self, **kwargs):
                self.calls.append(kwargs)

        persistence = FakePersistence()
        state = {
            "game_id": "pg_empty_started_at",
            "persistence": persistence,
            "game_events": [],
            "winner": "villagers",
            "seed": 4,
            "roles": {1: "seer"},
            "finished": True,
            "started_at": "",
        }

        out = asyncio.run(persist_node(state))

        assert len(persistence.calls) == 1
        assert persistence.calls[0]["started_at"]
        assert out["started_at"] == persistence.calls[0]["started_at"]
        assert persistence.calls[0]["final_state"]["started_at"] == out["started_at"]

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

    def test_run_entrypoints_route_judge_config_to_expected_pipelines(self, monkeypatch):
        from app.run import run_evaluation, run_evolution, run_game
        import asyncio

        captured = []

        class FakeGraph:
            async def ainvoke(self, state):
                captured.append(dict(state))
                return {"result": {"status": "captured"}}

        monkeypatch.setattr(
            "app.graphs.main.builder.build_root_graph",
            lambda **_kwargs: FakeGraph(),
        )

        judge_model = object()

        async def _run():
            model = object()
            judge_fn = object()
            await run_game(
                game_id="judge_play",
                model=model,
                enable_llm_judge=True,
                judge_max_decisions=1,
                decision_judge_fn=judge_fn,
            )
            await run_evaluation(
                batch_config={"batch_id": "judge_eval"},
                model=model,
                decision_judge_model=judge_model,
                enable_llm_judge=True,
                review_judge_max_decisions=2,
                training_llm_judge=True,
                evolve_judge_concurrency=5,
            )
            await run_evolution(
                role="seer",
                model=model,
                training_llm_judge=True,
                evolve_decision_judge=True,
                training_judge_max_decisions=3,
                evolve_judge_concurrency=4,
            )

        asyncio.run(_run())

        play_config = captured[0]["config"]
        eval_config = captured[1]["batch_config"]
        evolve_config = captured[2]["config"]
        assert play_config["enable_llm_judge"] is True
        assert play_config["judge_max_decisions"] == 1
        assert captured[0]["decision_judge_fn"] is not None
        assert eval_config["enable_llm_judge"] is True
        assert eval_config["review_judge_max_decisions"] == 2
        assert captured[1]["decision_judge_model"] is judge_model
        assert "training_llm_judge" not in eval_config
        assert "evolve_judge_concurrency" not in eval_config
        assert evolve_config["training_llm_judge"] is True
        assert evolve_config["evolve_decision_judge"] is True
        assert evolve_config["training_judge_max_decisions"] == 3
        assert evolve_config["evolve_judge_concurrency"] == 4

    def test_judge_policy_defaults_are_applied_at_run_entrypoints(self, monkeypatch):
        from app.run import run_evaluation, run_evolution, run_game
        import asyncio

        monkeypatch.setenv("WEREWOLF_JUDGE_CONCURRENCY", "6")
        captured = []

        class FakeGraph:
            async def ainvoke(self, state):
                captured.append(dict(state))
                return {"result": {"status": "captured"}}

        monkeypatch.setattr(
            "app.graphs.main.builder.build_root_graph",
            lambda **_kwargs: FakeGraph(),
        )

        async def _run():
            model = object()
            await run_game(game_id="judge_policy_play", model=model)
            await run_evaluation(batch_config={"batch_id": "judge_policy_eval"}, model=model)
            await run_evolution(role="seer", model=model)

        asyncio.run(_run())

        play_config = captured[0]["config"]
        eval_config = captured[1]["batch_config"]
        evolve_config = captured[2]["config"]
        assert play_config["enable_llm_judge"] is True
        assert play_config["review_decision_judge"] is True
        assert play_config["judge_max_decisions"] == 3
        assert play_config["review_judge_max_decisions"] == 3
        assert play_config["judge_concurrency"] == 6
        assert play_config["judge_timeout_seconds"] == 20.0
        assert play_config["review_judge_timeout_seconds"] == 20.0
        assert eval_config["enable_llm_judge"] is True
        assert eval_config["eval_decision_judge"] is True
        assert eval_config["eval_judge_max_decisions"] == 1
        assert eval_config["eval_judge_concurrency"] == 6
        assert eval_config["eval_judge_timeout_seconds"] == 20.0
        assert evolve_config["enable_llm_judge"] is True
        assert evolve_config["training_decision_judge"] is True
        assert evolve_config["evolve_decision_judge"] is True
        assert evolve_config["training_judge_max_decisions"] == 1
        assert evolve_config["training_judge_concurrency"] == 6
        assert evolve_config["training_judge_timeout_seconds"] == 20.0
        assert evolve_config["evolve_judge_timeout_seconds"] == 20.0

    def test_judge_policy_keeps_explicit_run_entrypoint_config(self, monkeypatch):
        from app.run import run_evaluation, run_game
        import asyncio

        captured = []

        class FakeGraph:
            async def ainvoke(self, state):
                captured.append(dict(state))
                return {"result": {"status": "captured"}}

        monkeypatch.setattr(
            "app.graphs.main.builder.build_root_graph",
            lambda **_kwargs: FakeGraph(),
        )

        async def _run():
            model = object()
            await run_game(
                game_id="judge_policy_play_explicit",
                model=model,
                enable_llm_judge=False,
                judge_max_decisions=7,
            )
            await run_evaluation(
                batch_config={"batch_id": "judge_policy_eval_explicit", "eval_decision_judge": False},
                model=model,
                eval_judge_max_decisions=4,
            )

        asyncio.run(_run())

        play_config = captured[0]["config"]
        eval_config = captured[1]["batch_config"]
        assert play_config["enable_llm_judge"] is False
        assert play_config["judge_max_decisions"] == 7
        assert "review_decision_judge" not in play_config
        assert eval_config["eval_decision_judge"] is False
        assert eval_config["eval_judge_max_decisions"] == 4
        assert "enable_llm_judge" not in eval_config

    def test_run_evaluation_entrypoint_propagates_langfuse_config_to_graph(self, monkeypatch):
        from app.run import run_evaluation
        import asyncio

        captured = []

        class FakeGraph:
            async def ainvoke(self, state):
                captured.append(dict(state))
                return {"result": {"status": "captured"}}

        monkeypatch.setattr(
            "app.graphs.main.builder.build_root_graph",
            lambda **_kwargs: FakeGraph(),
        )

        async def _run():
            await run_evaluation(
                batch_config={
                    "batch_id": "eval_langfuse",
                    "langfuse_dataset_name": "dataset-from-config",
                },
                model=object(),
                langfuse_dataset_name="dataset-from-kwargs",
                langfuse_experiment_name="experiment-a",
                langfuse_run_name="run-a",
            )

        asyncio.run(_run())

        state = captured[0]
        eval_config = state["batch_config"]
        assert eval_config["langfuse_dataset_name"] == "dataset-from-config"
        assert eval_config["langfuse_experiment_name"] == "experiment-a"
        assert eval_config["langfuse_run_name"] == "run-a"
        assert state["langfuse_dataset_name"] == "dataset-from-config"
        assert state["langfuse_experiment_name"] == "experiment-a"
        assert state["langfuse_run_name"] == "run-a"

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

    def test_run_game_entrypoint_propagates_agent_fast_smoke_to_game_graph(self):
        from app.run import run_game
        import asyncio

        class FakeModel:
            def __init__(self):
                self.calls = 0

            async def ainvoke(self, messages):
                self.calls += 1
                return type("Result", (), {"content": '{"public_text":"ok","choice":"pass","confidence":1}'})()

        async def _run():
            model = FakeModel()
            result = await run_game(
                game_id="entry_game_fast_smoke",
                seed=2,
                max_days=1,
                enable_sheriff=True,
                enable_llm_judge=False,
                enable_decision_judge=False,
                model=model,
                agent_fast_smoke=True,
            )
            return result, model

        result, model = asyncio.run(_run())
        sheriff_runs = [d for d in result["decisions"] if d.get("action_type") == "sheriff_run"]
        skipped = [d for d in result["decisions"] if d.get("source") == "policy_skipped"]
        assert sheriff_runs
        assert all(decision["source"] == "policy_skipped" for decision in sheriff_runs)
        assert skipped
        assert model.calls < len(result["decisions"])

    def test_run_evaluation_entrypoint_runs_graph(self):
        from app.run import run_evaluation
        import asyncio

        class FakeModel:
            async def ainvoke(self, messages):
                return type("Result", (), {"content": '{"public_text":"ok","confidence":1}'})()

        async def _run():
            return await run_evaluation(
                batch_config={"batch_id": "test_batch", "game_count": 1, "max_days": 5, "seed_start": 1},
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
