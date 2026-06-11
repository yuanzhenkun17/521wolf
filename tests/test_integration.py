"""Integration-level tests — cross-module import integrity and config.

These tests verify that all app/ modules can coexist without circular imports
and that the migration's core invariants hold.
"""

import tomllib

import pytest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def _python_files(path: Path):
    return path.rglob("*.py")


# ===========================================================================
# Rule 1: Zero root-level agent package
# ===========================================================================

class TestZeroAgentImports:
    def test_no_agent_imports_in_app(self):
        """Verify app/ contains no direct from-agent imports."""
        prefix = "from " + "agent."
        offenders = []
        for path in _python_files(ROOT / "app"):
            for line_no, line in enumerate(path.read_text(encoding="utf-8").splitlines(), start=1):
                stripped = line.strip()
                if stripped.startswith(prefix):
                    offenders.append(f"{path.relative_to(ROOT)}:{line_no}: {stripped}")

        assert not offenders, "Found direct agent imports:\n" + "\n".join(offenders)

    def test_root_agent_package_is_removed(self):
        """The migration no longer keeps a root-level agent compatibility package."""
        assert not (ROOT / "agent").exists()

    def test_packaging_excludes_root_agent_package(self):
        data = tomllib.loads((ROOT / "pyproject.toml").read_text(encoding="utf-8"))
        includes = data["tool"]["setuptools"]["packages"]["find"]["include"]

        assert "agent*" not in includes
        assert "agent" not in includes
        assert "agent.infrastructure" not in includes

    def test_no_agent_imports_in_active_migration_surface(self):
        """Verify app tests and active runtime packages do not directly import old agent modules."""
        prefixes = ("from " + "agent.", "import " + "agent.")
        offenders = []
        for root in (ROOT / "app", ROOT / "tests", ROOT / "engine", ROOT / "storage"):
            if not root.exists():
                continue
            for path in _python_files(root):
                for line_no, line in enumerate(path.read_text(encoding="utf-8").splitlines(), start=1):
                    stripped = line.strip()
                    if stripped.startswith(prefixes):
                        offenders.append(f"{path.relative_to(ROOT)}:{line_no}: {stripped}")

        assert not offenders, "Found direct agent imports:\n" + "\n".join(offenders)


# ===========================================================================
# Rule 2: app/graphs/ should not import ChatOpenAI or call model.invoke directly
# ===========================================================================

class TestGraphsNoLLM:
    def test_graphs_no_direct_llm(self):
        """Verify graphs/ doesn't contain direct LLM calls."""
        needles = (
            "ChatOpenAI",
            "load_llm_client",
            "create_llm",
            "model.invoke",
            "llm.invoke",
            "model.ainvoke",
            "llm.ainvoke",
            ".bind_tools",
        )
        offenders = []
        for path in _python_files(ROOT / "app" / "graphs"):
            for line_no, line in enumerate(path.read_text(encoding="utf-8").splitlines(), start=1):
                if any(needle in line for needle in needles):
                    offenders.append(f"{path.relative_to(ROOT)}:{line_no}: {line.strip()}")

        assert not offenders, "Found direct LLM calls:\n" + "\n".join(offenders)


# ===========================================================================
# Full app import — no circular imports
# ===========================================================================

class TestFullImportChain:
    def test_full_import(self):
        """Import everything from every app/ subpackage."""
        from app.util import (
            DictMixin, compact_json, read_json, write_json,
            AGENT_ACTION_TYPES, SPEECH_ACTION_TYPES, VOTE_ACTION_TYPES,
            NIGHT_SKILL_ACTION_TYPES, TARGET_ACTION_TYPES, CHOICE_ACTION_TYPES,
            is_valid_action_type,
            BEIJING_TZ, beijing_now_iso, beijing_now_str,
            is_werewolf_win,
            DEFAULT as PATH_DEFAULT, PathConfig,
            notify, observe, propagate_attributes, tracing_enabled,
        )

        from app.services import (
            create_llm,
            AgentMemory, Segment, CompressedSegmentSummary, SegmentEvent, normalize_phase_group,
            MarkdownSkill, build_decision_prompt_template, format_memory_messages,
            select_skills, format_skill_context, load_markdown_skills,
            action_instruction,
            build_apply_chain, build_compress_chain, build_consolidate_chain,
            build_decision_chain, build_decision_judge_chain, build_evidence_chain,
            build_raw_message_chain,
            create_apply_chain, create_consolidate_chain, create_decision_chain,
            create_decision_judge_chain, create_evidence_chain, run_apply_chain,
            run_compress_chain, run_consolidate_chain, run_decision_chain,
            run_decision_judge_chain, run_evidence_chain,
            tool,
        )

        from app.graphs.shared import (
            AgentState, GameState, PlayState, EvalBatchState, EvolveState, RootState,
        )

        from app.graphs.shared.nodes import review_node, evidence_node

        from app.graphs.main.router import _dispatch

        from app.lib import (
            AgentScores, GameReview, analyze_game,
            PlayerScore, BatchScoreSummary, aggregate_batch_scores,
            compute_role_score, compute_rankable,
            DecisionRecord, AgentDecisionRecorder, GameRunConfig, GameRunHandle, GameRunService,
            DecisionEvidenceInput, KeyDecision, GameEvidence, GameEvidenceBundle, EvidenceRunResult,
            DecisionJudgment, GameJudgmentReport, judge_key_decisions,
            SkillProposal, SkillConsolidation, SkillDiff, EvolutionRun,
            EvolutionConfig, EvolutionStateManager, deduplicate_proposals,
            SkillVersionConfig, VersionRegistry, VersionSummary,
            build_baseline_config, build_composite_skill_dir, promote_version, reject_version,
            create_agents, create_engine,
        )

        from app.config import PathConfig as AppPathConfig, load_llm_config, DEFAULT_PATHS

        from app.run import run_game, run_evaluation, run_evolution

        # If we got here without ImportError, the full import chain is clean
        assert True

    def test_no_circular_imports(self):
        """Re-importing app multiple times should not cause issues."""
        import importlib
        import app
        importlib.reload(app)
        import app.config
        importlib.reload(app.config)
        import app.util
        importlib.reload(app.util)
        import app.services
        importlib.reload(app.services)
        import app.services.llm
        importlib.reload(app.services.llm)
        import app.services.memory
        importlib.reload(app.services.memory)
        import app.services.prompt
        importlib.reload(app.services.prompt)
        import app.services.tool
        importlib.reload(app.services.tool)
        import app.services.chain
        importlib.reload(app.services.chain)
        import app.graphs.shared.state
        importlib.reload(app.graphs.shared.state)
        import app.graphs.shared.nodes.review
        importlib.reload(app.graphs.shared.nodes.review)
        import app.graphs.main.builder
        importlib.reload(app.graphs.main.builder)
        import app.lib.review
        importlib.reload(app.lib.review)
        import app.lib.score
        importlib.reload(app.lib.score)
        import app.lib.evidence
        importlib.reload(app.lib.evidence)
        import app.lib.evolve
        importlib.reload(app.lib.evolve)
        import app.lib.version
        importlib.reload(app.lib.version)
        import app.lib.store
        importlib.reload(app.lib.store)
        import app.lib.game
        importlib.reload(app.lib.game)
        import app.run
        importlib.reload(app.run)


# ===========================================================================
# app/config.py — PathConfig, load_llm_config
# ===========================================================================

class TestAppConfig:
    def test_load_llm_config(self, monkeypatch):
        monkeypatch.setenv("WEREWOLF_LLM_API_KEY", "test-key")
        monkeypatch.setenv("WEREWOLF_LLM_BASE_URL", "https://test.example.com/v1")
        monkeypatch.delenv("WEREWOLF_LLM_MODEL", raising=False)
        from app.config import load_llm_config
        cfg = load_llm_config(env_path=None)
        assert cfg["api_key"] == "test-key"
        assert cfg["model"] == "ali/qwen3.5-flash"

    def test_default_llm_env_path_is_project_root(self):
        from app.config import LLM_ENV_PATH, PathConfig

        assert LLM_ENV_PATH == PathConfig().root / ".env"

    def test_load_llm_config_env_path_is_not_cwd_relative(self, tmp_path, monkeypatch):
        import app.config as config

        cwd_env = tmp_path / ".env"
        cwd_env.write_text("WEREWOLF_LLM_API_KEY=cwd-key\n", encoding="utf-8")
        monkeypatch.chdir(tmp_path)
        monkeypatch.delenv("WEREWOLF_LLM_API_KEY", raising=False)

        loaded_paths = []

        def fake_load_dotenv(path, *, override):
            loaded_paths.append(Path(path))
            monkeypatch.setenv("WEREWOLF_LLM_API_KEY", "project-key")
            assert override is False

        monkeypatch.setattr(config, "load_dotenv", fake_load_dotenv)

        cfg = config.load_llm_config()

        assert loaded_paths == [config.LLM_ENV_PATH]
        assert cfg["api_key"] == "project-key"

    def test_default_paths(self):
        from app.config import DEFAULT_PATHS, PathConfig
        assert DEFAULT_PATHS.root.exists()


# ===========================================================================
# app/ replaces old orchestration entrypoints
# ===========================================================================

class TestAppEntrySurface:
    def test_app_run_exports_async_entrypoints(self):
        import asyncio

        from app.run import run_evaluation, run_evolution, run_game

        assert asyncio.iscoroutinefunction(run_game)
        assert asyncio.iscoroutinefunction(run_evaluation)
        assert asyncio.iscoroutinefunction(run_evolution)

    def test_fake_model_game_eval_evolve_smoke(self, tmp_path, monkeypatch):
        import asyncio

        from app.config import PathConfig
        from app.run import run_evaluation, run_evolution, run_game

        class FakeModel:
            async def ainvoke(self, messages):
                return type("Result", (), {"content": '{"public_text":"ok","confidence":1}'})()

        class FakeConnection:
            def execute(self, sql, parameters=()):
                return type(
                    "Cursor",
                    (),
                    {
                        "fetchone": lambda self: None,
                        "fetchall": lambda self: [],
                    },
                )()

            def commit(self):
                return None

            def rollback(self):
                return None

            def close(self):
                return None

        class FakeStorageProvider:
            def open_wolf_connection(self):
                return FakeConnection()

            def open_registry_connection(self):
                return FakeConnection()

            def open_evolution_connection(self):
                return FakeConnection()

        class FakeVersionRegistry:
            def list_roles(self):
                return []

            def load_rejected(self, role):
                return []

            def close(self):
                return None

        import app.lib.version as version_mod
        import storage.provider as provider_mod

        monkeypatch.setattr(provider_mod, "storage_provider_from_env", lambda *, paths=None: FakeStorageProvider())
        monkeypatch.setattr(version_mod, "version_registry_from_env", lambda *, paths=None: FakeVersionRegistry())

        async def _run():
            paths = PathConfig(root=tmp_path)
            model = FakeModel()
            game = await run_game(
                game_id="ci_smoke_game",
                seed=2,
                max_days=1,
                model=model,
                paths=paths,
            )
            evaluation = await run_evaluation(
                batch_config={"batch_id": "ci_smoke_eval", "game_count": 0, "max_days": 1},
                model=model,
                paths=paths,
            )
            evolution = await run_evolution(
                role="seer",
                training_games=0,
                battle_games=0,
                run_id="ci_smoke_evolve",
                max_days=1,
                model=model,
                paths=paths,
            )
            return game, evaluation, evolution

        game, evaluation, evolution = asyncio.run(_run())

        assert game["game_id"] == "ci_smoke_game"
        assert game["status"] in {"completed", "failed"}
        assert evaluation["batch_id"] == "ci_smoke_eval"
        assert evaluation["game_count"] == 0
        assert evolution["run_id"] == "ci_smoke_evolve"
        assert evolution["status"] in {"reviewing", "rejected", "failed"}
