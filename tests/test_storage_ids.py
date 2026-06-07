from __future__ import annotations

import pytest

from storage.ids import artifact_game_id, public_decision_id, safe_storage_id, storage_decision_id


def test_safe_storage_id_converts_relative_artifact_path_to_stable_id():
    assert safe_storage_id("runs/eval 01/game-001") == "runs::eval_01::game-001"
    assert safe_storage_id("  ") == "unknown"


@pytest.mark.parametrize(
    "value",
    [
        "../secret",
        "runs/../secret",
        "./secret",
        "/tmp/game",
        "C:/tmp/game",
        r"D:\tmp\game",
        r"\\server\share\game",
        "game:bad",
    ],
)
def test_safe_storage_id_rejects_path_semantics(value: str):
    with pytest.raises(ValueError):
        safe_storage_id(value)


def test_artifact_game_id_uses_relative_path_under_root(tmp_path):
    root = tmp_path / "runs"
    game_dir = root / "batch 1" / "game-001"
    game_dir.mkdir(parents=True)

    assert artifact_game_id(game_dir, root=root) == "batch_1::game-001"


def test_artifact_game_id_rejects_path_outside_root(tmp_path):
    root = tmp_path / "runs"
    game_dir = tmp_path / "other" / "game-001"
    game_dir.mkdir(parents=True)

    with pytest.raises(ValueError, match="not under root"):
        artifact_game_id(game_dir, root=root)


def test_storage_decision_id_scopes_and_sanitizes_raw_decision_id():
    storage_id = storage_decision_id("game-001", "decision 1")

    assert storage_id == "game-001::decision_1"
    assert public_decision_id(storage_id, "game-001") == "decision_1"


def test_storage_decision_id_rejects_unsafe_raw_decision_id():
    with pytest.raises(ValueError):
        storage_decision_id("game-001", "../decision")
