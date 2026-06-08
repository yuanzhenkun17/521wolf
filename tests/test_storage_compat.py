from __future__ import annotations

import sqlite3

import pytest


def _open_registry_db(path):
    from storage.registry.schema import ensure_registry_schema

    conn = sqlite3.connect(path)
    conn.row_factory = sqlite3.Row
    ensure_registry_schema(conn)
    return conn


def _role_version_statuses(conn, role: str) -> dict[str, str]:
    rows = conn.execute(
        "SELECT id, status FROM role_versions WHERE role = ? ORDER BY created_at",
        (role,),
    ).fetchall()
    return {row["id"]: row["status"] for row in rows}


def test_battle_stores_reexport_canonical_runtime_stores():
    from storage.battle.decision_repo import DecisionStore as BattleDecisionStore
    from storage.battle.event_repo import GameEventStore as BattleGameEventStore
    from storage.battle.evaluation_repo import EvaluationStore as BattleEvaluationStore
    from storage.battle.game_repo import GameStore as BattleGameStore
    from storage.battle.review_repo import (
        CounterfactualStore as BattleCounterfactualStore,
        DecisionReviewStore as BattleDecisionReviewStore,
    )
    from storage.decision_store import DecisionStore
    from storage.evaluation_store import EvaluationStore
    from storage.game_event_store import GameEventStore
    from storage.game_store import GameStore
    from storage.review_store import CounterfactualStore, DecisionReviewStore

    assert BattleDecisionStore is DecisionStore
    assert BattleGameEventStore is GameEventStore
    assert BattleGameStore is GameStore
    assert BattleEvaluationStore is EvaluationStore
    assert BattleDecisionReviewStore is DecisionReviewStore
    assert BattleCounterfactualStore is CounterfactualStore


def test_storage_battle_package_exports_canonical_runtime_stores():
    import storage.battle as battle
    from storage.decision_store import DecisionStore
    from storage.evaluation_store import EvaluationStore
    from storage.game_event_store import GameEventStore
    from storage.game_store import GameStore
    from storage.review_store import CounterfactualStore, DecisionReviewStore

    assert battle.DecisionStore is DecisionStore
    assert battle.GameEventStore is GameEventStore
    assert battle.GameStore is GameStore
    assert battle.EvaluationStore is EvaluationStore
    assert battle.DecisionReviewStore is DecisionReviewStore
    assert battle.CounterfactualStore is CounterfactualStore


def test_storage_interface_import_paths_share_canonical_objects():
    import storage
    import storage.interfaces as canonical
    import storage.shared as shared
    import storage.shared.interfaces as shared_interfaces

    exported_names = [
        "DecisionArchiveData",
        "DecisionRecordData",
        "EvolutionRunData",
        "RoleHistoryData",
        "RoleVersionData",
        "SkillProposalData",
        "SkillVersionConfigData",
        "compute_hash",
        "normalize_skill_path",
        "normalize_skill_text",
    ]

    for name in exported_names:
        assert getattr(shared_interfaces, name) is getattr(canonical, name)
        assert getattr(shared, name) is getattr(canonical, name)
        assert getattr(storage, name) is getattr(canonical, name)


def test_decision_store_rejects_missing_player_id(tmp_path):
    from storage.decision_store import DecisionStore
    from storage.interfaces import DecisionRecordData
    from storage.schema import get_connection

    conn = get_connection(tmp_path / "wolf.db")
    try:
        store = DecisionStore(conn)
        with pytest.raises(ValueError, match="player_id is required"):
            store.insert_record(
                "g1",
                DecisionRecordData(
                    decision_id="d_missing",
                    player_id=None,
                    role="seer",
                    day=1,
                    phase="night",
                    action_type="seer_check",
                ),
            )
        count = conn.execute("SELECT COUNT(*) AS n FROM decisions").fetchone()["n"]
        assert count == 0
    finally:
        conn.close()


def test_decision_store_scopes_record_ids_by_game_and_returns_public_ids(tmp_path):
    from storage.decision_store import DecisionStore
    from storage.interfaces import DecisionRecordData
    from storage.schema import get_connection

    conn = get_connection(tmp_path / "wolf.db")
    try:
        store = DecisionStore(conn)
        first = store.insert_record(
            "g1",
            DecisionRecordData(
                decision_id="d_same",
                player_id=1,
                role="seer",
                day=1,
                phase="night",
                action_type="seer_check",
                selected_target=2,
                public_text="g1 decision",
            ),
            created_at="2026-06-07T10:00:00+08:00",
        )
        second = store.insert_record(
            "g2",
            DecisionRecordData(
                decision_id="d_same",
                player_id=3,
                role="seer",
                day=1,
                phase="night",
                action_type="seer_check",
                selected_target=4,
                public_text="g2 decision",
            ),
            created_at="2026-06-07T10:01:00+08:00",
        )

        assert first == "d_same"
        assert second == "d_same"
        stored = conn.execute(
            "SELECT id, game_id, selected_target FROM decisions ORDER BY game_id"
        ).fetchall()
        assert [(row["id"], row["game_id"], row["selected_target"]) for row in stored] == [
            ("g1::d_same", "g1", 2),
            ("g2::d_same", "g2", 4),
        ]

        g1_rows = store.get_for_game("g1")
        assert len(g1_rows) == 1
        assert g1_rows[0]["id"] == "d_same"
        assert g1_rows[0]["decision_id"] == "d_same"
        assert g1_rows[0]["storage_id"] == "g1::d_same"
        assert g1_rows[0]["selected_target"] == 2

        queried = store.query(role="seer", limit=10)
        assert {(row["game_id"], row["decision_id"]) for row in queried} == {
            ("g1", "d_same"),
            ("g2", "d_same"),
        }
    finally:
        conn.close()


def test_decision_store_scopes_archive_ids_and_replay_returns_public_ids(tmp_path):
    from storage.decision_store import DecisionStore
    from storage.interfaces import DecisionArchiveData
    from storage.replay import read_decisions_for_artifact
    from storage.schema import get_connection

    db_path = tmp_path / "wolf.db"
    conn = get_connection(db_path)
    try:
        store = DecisionStore(conn)
        for game_id, target in [("g1", 2), ("g2", 4)]:
            returned = store.insert_archive(
                game_id,
                DecisionArchiveData(
                    decision_id="archive_same",
                    index=1,
                    player_id=1,
                    role="seer",
                    day=1,
                    phase="night",
                    action_type="seer_check",
                    candidates=[target],
                    observation_summary={"day": 1},
                    memory_context={},
                    selected_skills=["seer/check.md"],
                    prompt_messages=[],
                    raw_output="{}",
                    parsed_decision={"target": target},
                    final_response={"text": f"checked {target}"},
                    source="test",
                    confidence=0.8,
                    policy_adjustments=[],
                    errors=[],
                ),
                player_id=1,
                created_at=f"2026-06-07T10:0{target}:00+08:00",
            )
            assert returned == "archive_same"

        stored_ids = [
            row["id"]
            for row in conn.execute("SELECT id FROM decisions ORDER BY game_id").fetchall()
        ]
        assert stored_ids == ["g1::archive_same", "g2::archive_same"]
    finally:
        conn.close()

    decisions = read_decisions_for_artifact(db_path, tmp_path / "g1")
    assert decisions is not None
    assert len(decisions) == 1
    assert decisions[0]["decision_id"] == "archive_same"
    assert decisions[0]["selected_target"] == 2


def test_version_store_set_baseline_cas_failure_leaves_history_unchanged(tmp_path):
    from storage.version_store import VersionStoreDB

    conn = _open_registry_db(tmp_path / "registry.db")
    try:
        store = VersionStoreDB(conn)
        first = store.save_version("seer", {"main.md": "first"}, None, "test")
        second = store.save_version("seer", {"main.md": "second"}, first, "test")
        assert store.set_baseline("seer", first, expected_current=first) is True

        before = _role_version_statuses(conn, "seer")

        assert store.set_baseline("seer", second, expected_current="stale") is False
        assert store.get_history("seer").baseline == first
        assert _role_version_statuses(conn, "seer") == before
    finally:
        conn.close()


def test_version_store_set_baseline_success_keeps_single_role_baseline(tmp_path):
    from storage.version_store import VersionStoreDB

    conn = _open_registry_db(tmp_path / "registry.db")
    try:
        store = VersionStoreDB(conn)
        first = store.save_version("seer", {"main.md": "first"}, None, "test")
        second = store.save_version("seer", {"main.md": "second"}, first, "test")
        witch = store.save_version("witch", {"main.md": "witch"}, None, "test")
        assert store.set_baseline("seer", first, expected_current=first) is True
        assert store.set_baseline("witch", witch, expected_current=witch) is True

        assert store.set_baseline("seer", second, expected_current=first) is True

        seer_statuses = _role_version_statuses(conn, "seer")
        assert seer_statuses == {first: "archived", second: "baseline"}
        seer_baselines = conn.execute(
            "SELECT id FROM role_versions WHERE role = ? AND status = 'baseline'",
            ("seer",),
        ).fetchall()
        assert [row["id"] for row in seer_baselines] == [second]
        assert store.get_history("seer").baseline == second
        assert store.get_history("witch").baseline == witch
    finally:
        conn.close()


def test_battle_decision_store_rejects_missing_player_id(tmp_path):
    from storage.battle.decision_repo import DecisionStore
    from storage.interfaces import DecisionRecordData
    from storage.schema import get_connection

    conn = get_connection(tmp_path / "wolf.db")
    try:
        store = DecisionStore(conn)
        with pytest.raises(ValueError, match="player_id is required"):
            store.insert_record(
                "g1",
                DecisionRecordData(
                    decision_id="d_missing",
                    player_id=None,
                    role="seer",
                    day=1,
                    phase="night",
                    action_type="seer_check",
                ),
            )
    finally:
        conn.close()
