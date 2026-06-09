from __future__ import annotations

import json
import sys
from dataclasses import dataclass
from datetime import datetime, timezone
from types import SimpleNamespace
from typing import Any

import pytest

from storage.postgres.connection import (
    PostgresConnectionAdapter,
    get_registry_postgres_connection,
    get_wolf_postgres_connection,
)


_UNSET = object()


@dataclass(frozen=True)
class _Column:
    name: str
    type_code: int | None = None


class _FakeCursor:
    rowcount = 0

    def __init__(
        self,
        rows: list[tuple[Any, ...]] | None = None,
        columns: list[str] | None = None,
    ) -> None:
        self._rows = list(rows or [])
        self.description = [_Column(name) for name in columns or []]

    def fetchone(self) -> tuple[Any, ...] | None:
        if not self._rows:
            return None
        return self._rows.pop(0)

    def fetchall(self) -> list[tuple[Any, ...]]:
        rows = self._rows
        self._rows = []
        return rows


class _FakeRawConnection:
    def __init__(self) -> None:
        self.calls: list[tuple[str, tuple[Any, ...] | object]] = []
        self.results: list[_FakeCursor] = []
        self.committed = False
        self.rolled_back = False
        self.closed = False

    def queue(
        self,
        rows: list[tuple[Any, ...]] | None = None,
        columns: list[str] | None = None,
        type_codes: list[int | None] | None = None,
    ) -> None:
        cursor = _FakeCursor(rows, columns)
        if type_codes is not None:
            cursor.description = [
                _Column(name, type_code)
                for name, type_code in zip(columns or [], type_codes, strict=False)
            ]
        self.results.append(cursor)

    def execute(
        self,
        sql: str,
        parameters: tuple[Any, ...] | object = _UNSET,
    ) -> _FakeCursor:
        self.calls.append((sql, parameters))
        if self.results:
            return self.results.pop(0)
        return _FakeCursor()

    def commit(self) -> None:
        self.committed = True

    def rollback(self) -> None:
        self.rolled_back = True

    def close(self) -> None:
        self.closed = True


def _adapter(raw: _FakeRawConnection, *, schema: str = "wolf") -> PostgresConnectionAdapter:
    return PostgresConnectionAdapter(raw, schema=schema)


def test_adapter_configures_search_path_for_schema_namespace() -> None:
    raw = _FakeRawConnection()

    _adapter(raw, schema="registry")

    assert raw.calls == [('SET search_path TO "registry", "public"', _UNSET)]
    assert raw.committed is True


def test_execute_converts_qmark_placeholders_and_materializes_parameters() -> None:
    raw = _FakeRawConnection()
    adapter = _adapter(raw)
    raw.calls.clear()

    adapter.execute(
        "SELECT * FROM games WHERE id LIKE ? AND total_rounds > ? LIMIT ?",
        ["g-%", 3, 10],
    )

    assert raw.calls == [
        (
            "SELECT * FROM games WHERE id LIKE %s AND total_rounds > %s LIMIT %s",
            ("g-%", 3, 10),
        )
    ]


def test_execute_preserves_question_marks_inside_sql_text() -> None:
    raw = _FakeRawConnection()
    adapter = _adapter(raw)
    raw.calls.clear()

    adapter.execute(
        """
        SELECT '?', "column?", $$ dollar ? $$, payload
        FROM game_events -- comment ?
        WHERE id = ? AND message = 'literal ?'
        """,
        (7,),
    )

    executed_sql, params = raw.calls[0]
    assert "'?'" in executed_sql
    assert '"column?"' in executed_sql
    assert "$$ dollar ? $$" in executed_sql
    assert "-- comment ?" in executed_sql
    assert "id = %s" in executed_sql
    assert "message = 'literal ?'" in executed_sql
    assert params == (7,)


def test_execute_rejects_placeholder_count_mismatch_before_raw_execute() -> None:
    raw = _FakeRawConnection()
    adapter = _adapter(raw)
    raw.calls.clear()

    with pytest.raises(ValueError, match="placeholder count mismatch"):
        adapter.execute("SELECT payload ? 'key' FROM game_events")

    assert raw.calls == []


def test_execute_rejects_string_parameters() -> None:
    raw = _FakeRawConnection()
    adapter = _adapter(raw)

    with pytest.raises(TypeError, match="parameters"):
        adapter.execute("SELECT * FROM games WHERE id = ?", "g-1")


def test_execute_omits_empty_parameter_argument() -> None:
    raw = _FakeRawConnection()
    adapter = _adapter(raw)
    raw.calls.clear()

    adapter.execute("SELECT 1")

    assert raw.calls == [("SELECT 1", _UNSET)]


def test_execute_casts_jsonb_insert_parameters_and_adapts_boolean_parameters() -> None:
    raw = _FakeRawConnection()
    adapter = _adapter(raw)
    raw.calls.clear()

    adapter.execute(
        """
        INSERT INTO games (id, config, learning_eligible, rankable, started_at)
        VALUES (?, ?, ?, ?, ?)
        """,
        ("g-1", '{"mode":"dev"}', 1, 0, "2026-06-08T00:00:00+08:00"),
    )

    sql, params = raw.calls[0]
    assert "VALUES (%s, %s::jsonb, %s, %s, %s)" in " ".join(sql.split())
    assert params == (
        "g-1",
        '{"mode":"dev"}',
        True,
        False,
        "2026-06-08T00:00:00+08:00",
    )


def test_execute_casts_benchmark_saved_view_jsonb_insert_parameter() -> None:
    raw = _FakeRawConnection()
    adapter = _adapter(raw)
    raw.calls.clear()

    adapter.execute(
        """
        INSERT INTO benchmark_saved_views
        (view_key, name, scope, view_config, created_at, updated_at)
        VALUES (?, ?, ?, ?, ?, ?)
        """,
        (
            "view-1",
            "Release view",
            "role_version",
            '{"columns":["score"]}',
            "2026-06-10T00:00:00+08:00",
            "2026-06-10T00:00:00+08:00",
        ),
    )

    sql, params = raw.calls[0]
    assert "VALUES (%s, %s, %s, %s::jsonb, %s, %s)" in " ".join(sql.split())
    assert params == (
        "view-1",
        "Release view",
        "role_version",
        '{"columns":["score"]}',
        "2026-06-10T00:00:00+08:00",
        "2026-06-10T00:00:00+08:00",
    )


def test_execute_casts_jsonb_update_parameters_and_adapts_boolean_where() -> None:
    raw = _FakeRawConnection()
    adapter = _adapter(raw)
    raw.calls.clear()

    adapter.execute(
        "UPDATE games SET final_state = ?, paired_seed = ? "
        "WHERE learning_eligible = ? AND id = ?",
        ('{"winner":"good"}', 1, 0, "g-1"),
    )

    assert raw.calls == [
        (
            "UPDATE games SET final_state = %s::jsonb, paired_seed = %s "
            "WHERE learning_eligible = %s AND id = %s",
            ('{"winner":"good"}', True, False, "g-1"),
        )
    ]


def test_execute_adapts_boolean_filter_parameters_without_touching_limit() -> None:
    raw = _FakeRawConnection()
    adapter = _adapter(raw, schema="evolution")
    raw.calls.clear()

    adapter.execute(
        "SELECT * FROM experience_candidates WHERE learning_eligible = ? LIMIT ?",
        (1, 25),
    )

    assert raw.calls == [
        (
            "SELECT * FROM experience_candidates WHERE learning_eligible = %s LIMIT %s",
            (True, 25),
        )
    ]


def test_row_adapter_supports_index_name_and_keys() -> None:
    raw = _FakeRawConnection()
    adapter = _adapter(raw)
    raw.calls.clear()
    raw.queue(rows=[("g-1", "good")], columns=["id", "winner"])

    row = adapter.execute("SELECT id, winner FROM games").fetchone()

    assert row is not None
    assert row[0] == "g-1"
    assert row["winner"] == "good"
    assert tuple(row.keys()) == ("id", "winner")
    assert dict(row) == {"id": "g-1", "winner": "good"}


def test_row_adapter_normalizes_pg_native_values_for_repository_rows() -> None:
    raw = _FakeRawConnection()
    adapter = _adapter(raw)
    raw.calls.clear()
    raw.queue(
        rows=[
            (
                {"mode": "dev"},
                [{"type": "day_start"}],
                True,
                datetime(2026, 6, 7, 16, 0, tzinfo=timezone.utc),
            )
        ],
        columns=["config", "public_events", "learning_eligible", "started_at"],
        type_codes=[3802, 3802, 16, 1184],
    )

    row = adapter.execute(
        "SELECT config, public_events, learning_eligible, started_at FROM games"
    ).fetchone()

    assert row is not None
    assert json.loads(row["config"]) == {"mode": "dev"}
    assert json.loads(row["public_events"]) == [{"type": "day_start"}]
    assert row["learning_eligible"] == 1
    assert dict(row)["learning_eligible"] == 1
    assert row["started_at"] == "2026-06-08T00:00:00+08:00"


def test_jsonb_scalar_string_returns_json_text() -> None:
    raw = _FakeRawConnection()
    adapter = _adapter(raw)
    raw.calls.clear()
    raw.queue(
        rows=[("scalar",)],
        columns=["raw_json"],
        type_codes=[3802],
    )

    row = adapter.execute("SELECT raw_json FROM llm_judgments").fetchone()

    assert row is not None
    assert row["raw_json"] == '"scalar"'
    assert json.loads(row["raw_json"]) == "scalar"


def test_cursor_adapter_supports_empty_fetchone_fetchall_and_rowcount() -> None:
    raw = _FakeRawConnection()
    adapter = _adapter(raw)
    raw.calls.clear()
    cursor = _FakeCursor(rows=[(1,), (2,)], columns=["id"])
    cursor.rowcount = 2
    raw.results.append(cursor)

    wrapped = adapter.execute("SELECT id FROM players")

    assert wrapped.rowcount == 2
    rows = wrapped.fetchall()
    assert [row["id"] for row in rows] == [1, 2]
    assert wrapped.fetchone() is None


def test_context_manager_commits_without_closing_raw_connection() -> None:
    raw = _FakeRawConnection()
    adapter = _adapter(raw)

    with adapter as entered:
        assert entered is adapter

    assert raw.committed is True
    assert raw.closed is False


def test_context_manager_rolls_back_without_closing_raw_connection() -> None:
    raw = _FakeRawConnection()
    adapter = _adapter(raw)

    with pytest.raises(RuntimeError, match="boom"):
        with adapter:
            raise RuntimeError("boom")

    assert raw.rolled_back is True
    assert raw.closed is False


def test_insert_returning_id_appends_returning_before_semicolon() -> None:
    raw = _FakeRawConnection()
    adapter = _adapter(raw)
    raw.calls.clear()
    raw.queue(rows=[(42,)], columns=["id"])

    result = adapter.insert_returning_id(
        "INSERT INTO players (game_id, seat) VALUES (?, ?);",
        ("g-1", 1),
    )

    assert result == 42
    assert raw.calls == [
        (
            'INSERT INTO players (game_id, seat) VALUES (%s, %s) RETURNING "id"',
            ("g-1", 1),
        )
    ]


def test_insert_returning_id_does_not_duplicate_existing_returning_clause() -> None:
    raw = _FakeRawConnection()
    adapter = _adapter(raw)
    raw.calls.clear()
    raw.queue(rows=[(9,)], columns=["custom_id"])

    result = adapter.insert_returning_id(
        "INSERT INTO t (name) VALUES (?) RETURNING custom_id",
        ("sample",),
        id_column="custom_id",
    )

    assert result == 9
    assert raw.calls == [
        ("INSERT INTO t (name) VALUES (%s) RETURNING custom_id", ("sample",))
    ]


def test_insert_returning_id_rejects_unsafe_identifier() -> None:
    raw = _FakeRawConnection()
    adapter = _adapter(raw)

    with pytest.raises(ValueError, match="invalid column identifier"):
        adapter.insert_returning_id("INSERT INTO t DEFAULT VALUES", id_column="bad-id")


def test_begin_write_uses_postgres_transaction_begin() -> None:
    raw = _FakeRawConnection()
    adapter = _adapter(raw)
    raw.calls.clear()

    adapter.begin_write()

    assert raw.calls == [("BEGIN", _UNSET)]


def test_execute_for_update_appends_locking_clause_before_trailing_semicolon() -> None:
    raw = _FakeRawConnection()
    adapter = _adapter(raw)
    raw.calls.clear()

    adapter.execute_for_update(
        "SELECT id, status FROM role_versions WHERE role = ? ORDER BY created_at;",
        ("seer",),
    )

    assert raw.calls == [
        (
            "SELECT id, status FROM role_versions WHERE role = %s "
            "ORDER BY created_at FOR UPDATE",
            ("seer",),
        )
    ]


def test_execute_for_update_rejects_non_select_sql() -> None:
    raw = _FakeRawConnection()
    adapter = _adapter(raw)

    with pytest.raises(ValueError, match="SELECT"):
        adapter.execute_for_update("UPDATE role_versions SET status = ?", ("active",))


def test_catalog_methods_use_postgres_information_schema() -> None:
    raw = _FakeRawConnection()
    adapter = _adapter(raw, schema="evolution")
    raw.calls.clear()
    raw.queue(rows=[(1,)], columns=["exists"])
    raw.queue(rows=[("id",), ("role",)], columns=["column_name"])

    assert adapter.table_exists("evolution_runs") is True
    assert list(adapter.table_columns("evolution_runs")) == ["id", "role"]

    executed = "\n".join(sql for sql, _ in raw.calls)
    assert "information_schema.tables" in executed
    assert "information_schema.columns" in executed
    assert raw.calls[0][1] == ("evolution", "evolution_runs")
    assert raw.calls[1][1] == ("evolution", "evolution_runs")


def test_add_column_uses_qualified_postgres_identifier() -> None:
    raw = _FakeRawConnection()
    adapter = _adapter(raw, schema="wolf")
    raw.calls.clear()

    adapter.add_column("games", "review_status", "text DEFAULT 'pending'")

    assert raw.calls == [
        (
            'ALTER TABLE "wolf"."games" ADD COLUMN "review_status" '
            "text DEFAULT 'pending'",
            _UNSET,
        )
    ]


def test_record_schema_version_uses_postgres_upsert_without_legacy_catalog_fallbacks() -> None:
    raw = _FakeRawConnection()
    adapter = _adapter(raw, schema="registry")
    raw.calls.clear()

    adapter.record_schema_version("registry", 3, "2026-06-08T00:00:00+08:00")

    executed = "\n".join(sql for sql, _ in raw.calls)
    assert 'CREATE TABLE IF NOT EXISTS "registry"."schema_migrations"' in executed
    assert 'INSERT INTO "registry"."schema_migrations"' in executed
    assert "ON CONFLICT(component) DO UPDATE" in executed
    assert raw.calls[-1][1] == ("registry", 3, "2026-06-08T00:00:00+08:00")


def test_domain_factories_use_database_url_and_schema_search_path(monkeypatch: pytest.MonkeyPatch) -> None:
    raw = _FakeRawConnection()
    calls: list[tuple[str | None, dict[str, Any]]] = []

    def fake_connect(conninfo: str | None = None, **kwargs: Any) -> _FakeRawConnection:
        calls.append((conninfo, kwargs))
        return raw

    monkeypatch.setitem(sys.modules, "psycopg", SimpleNamespace(connect=fake_connect))
    monkeypatch.setenv("POSTGRES_DATABASE_URL", "postgresql://wolf_app@localhost/db")

    adapter = get_registry_postgres_connection()

    assert adapter.schema == "registry"
    assert adapter.search_path == ("registry", "public")
    assert calls == [("postgresql://wolf_app@localhost/db", {})]
    assert raw.calls == [('SET search_path TO "registry", "public"', _UNSET)]
    assert raw.committed is True


def test_domain_factories_require_connection_info(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("POSTGRES_DATABASE_URL", raising=False)
    monkeypatch.delenv("DATABASE_URL", raising=False)
    monkeypatch.setenv("POSTGRES_DISABLE_DOTENV", "1")

    with pytest.raises(ValueError, match="PostgreSQL connection info is required"):
        get_wolf_postgres_connection()
