from __future__ import annotations

import json
from types import SimpleNamespace
from typing import Any

import pytest

from storage.registry.version_repo import RegistryVersionRepository


class _Row(dict):
    pass


class _RegistryConn:
    def __init__(self) -> None:
        self.rejected: dict[str, str] = {}
        self.statements: list[str] = []
        self.begins = 0
        self.commits = 0
        self.rollbacks = 0
        self.closed = False

    def execute(self, sql: str, parameters: Any = ()) -> Any:
        text = " ".join(sql.split())
        self.statements.append(text)
        if text.startswith("INSERT INTO rejected_proposals"):
            role, proposals_json = parameters
            self.rejected.setdefault(role, proposals_json)
            return SimpleNamespace(rowcount=1, fetchone=lambda: None, fetchall=lambda: [])
        if text.startswith("SELECT proposals_json FROM rejected_proposals"):
            role = parameters[0]
            row = _Row({"proposals_json": self.rejected[role]}) if role in self.rejected else None
            return SimpleNamespace(rowcount=1 if row else 0, fetchone=lambda: row, fetchall=lambda: [row] if row else [])
        if text.startswith("UPDATE rejected_proposals SET proposals_json"):
            proposals_json, role = parameters
            self.rejected[role] = proposals_json
            return SimpleNamespace(rowcount=1, fetchone=lambda: None, fetchall=lambda: [])
        raise AssertionError(f"unexpected SQL: {text}")

    def begin_write(self) -> None:
        self.begins += 1

    def execute_for_update(self, sql: str, parameters: Any = ()) -> Any:
        return self.execute(sql, parameters)

    def commit(self) -> None:
        self.commits += 1

    def rollback(self) -> None:
        self.rollbacks += 1

    def close(self) -> None:
        self.closed = True

    def __enter__(self) -> "_RegistryConn":
        return self

    def __exit__(self, exc_type: object, exc: object, tb: object) -> bool:
        return False


def test_registry_rejected_payload_update_commits_atomically() -> None:
    conn = _RegistryConn()
    repo = RegistryVersionRepository(conn)

    repo.save_rejected_payload(
        role="seer",
        build_payload=lambda existing: json.dumps(
            [*json.loads(existing or "[]"), {"proposal_id": "p1"}],
            ensure_ascii=False,
        ),
    )

    assert conn.begins == 1
    assert conn.commits == 1
    assert conn.rollbacks == 0
    assert json.loads(conn.rejected["seer"]) == [{"proposal_id": "p1"}]


def test_registry_rejected_payload_update_rolls_back_on_payload_error() -> None:
    conn = _RegistryConn()
    repo = RegistryVersionRepository(conn)

    def fail_payload(_existing: Any) -> str:
        raise RuntimeError("bad payload")

    with pytest.raises(RuntimeError, match="bad payload"):
        repo.save_rejected_payload(role="seer", build_payload=fail_payload)

    assert conn.begins == 1
    assert conn.commits == 0
    assert conn.rollbacks == 1
    assert not any(
        statement.startswith("UPDATE rejected_proposals SET proposals_json")
        for statement in conn.statements
    )
