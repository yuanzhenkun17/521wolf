"""PostgreSQL connection adapter for the shared storage protocols.

Repositories use qmark ``?`` placeholders at their boundary; this adapter
translates them to psycopg's ``%s`` style when statements are sent to
PostgreSQL.
"""

from __future__ import annotations

import json
import os
import re
from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass
from datetime import date, datetime
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo

from storage.shared.database import StorageCursor, StorageRow
from storage.shared.sql import PlaceholderStyle, convert_qmark_placeholders


_IDENTIFIER_RE = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*$")
_RETURNING_RE = re.compile(r"\bRETURNING\b", re.IGNORECASE)
_FOR_UPDATE_RE = re.compile(r"\bFOR\s+UPDATE\b", re.IGNORECASE)
_INSERT_RE = re.compile(
    r"\bINSERT\s+INTO\s+(?P<table>(?:\"?[A-Za-z_][A-Za-z0-9_]*\"?\.)?\"?[A-Za-z_][A-Za-z0-9_]*\"?)\s*"
    r"\((?P<columns>.*?)\)\s*VALUES\s*\((?P<values>.*?)\)",
    re.IGNORECASE | re.DOTALL,
)
_ASSIGNMENT_RE = re.compile(
    r"(?:\"?[A-Za-z_][A-Za-z0-9_]*\"?\.)?(\"?[A-Za-z_][A-Za-z0-9_]*\"?)\s*=\s*$",
    re.DOTALL,
)
_JSON_OIDS = {114, 3802}
_BOOL_OIDS = {16}
_DATE_TIME_OIDS = {1082, 1114, 1184}
_JSONB_COLUMNS_BY_TABLE = {
    "games": {"config", "public_events", "final_state"},
    "game_events": {"payload"},
    "leaderboard": {"scores"},
    "llm_judgments": {"input_refs", "raw_json", "normalized_fields"},
    "seed_sets": {"seeds_json"},
    "benchmark_leaderboard": {"by_role_category_scores"},
    "benchmark_saved_views": {"view_config"},
    "benchmark_leaderboard_snapshots": {"source_filter", "view_config", "rows_json", "summary_json"},
    "role_versions": {"patterns_json", "metrics_json", "provenance_json"},
    "rejected_proposals": {"proposal_json", "proposals_json"},
    "evolution_runs": {"config", "battle_result", "runtime_state"},
    "trust_bundles": {"bundle_json"},
    "skill_proposals": {"evidence"},
    "experience_candidates": {"evidence_decision_ids", "raw_json"},
    "ui_background_tasks": {"payload"},
    "ui_task_events": {"payload"},
    "ui_task_queue": {"payload", "result", "error", "progress", "metadata"},
    "ui_task_artifacts": {"metadata"},
    "ui_task_workers": {"metadata"},
    "ui_model_profiles": {"default_scopes", "capabilities", "metadata"},
    "ui_runtime_settings": {"value_json"},
    "ui_settings_audit_log": {"details"},
    "patterns": {"source_games"},
    "evolution_rounds": {"config"},
    "candidate_packages": {"proposal_ids"},
    "promotion_decisions": {"metrics"},
}
_BOOLEAN_COLUMNS_BY_TABLE = {
    "games": {"learning_eligible", "promote_eligible", "paired_seed", "rankable"},
    "players": {"alive"},
    "game_events": {"public"},
    "leaderboard": {"is_baseline", "data_sufficient"},
    "seed_sets": {"immutable"},
    "evaluation_batches": {"rankable"},
    "benchmark_leaderboard": {"rankable", "data_sufficient"},
    "experience_candidates": {"learning_eligible"},
    "evolution_rounds": {"learning_eligible"},
    "ui_model_profiles": {"enabled"},
}
_JSONB_COLUMN_NAMES = {
    column for columns in _JSONB_COLUMNS_BY_TABLE.values() for column in columns
}
_BOOLEAN_COLUMN_NAMES = {
    column for columns in _BOOLEAN_COLUMNS_BY_TABLE.values() for column in columns
}
_UNSET = object()


@dataclass(frozen=True, slots=True)
class _ColumnInfo:
    name: str
    type_code: int | None


class PostgresRow(StorageRow):
    """Row wrapper supporting both index and mapping-style name access."""

    def __init__(
        self,
        raw_row: Any,
        columns: Sequence[_ColumnInfo],
        *,
        storage_timezone: str = "Asia/Shanghai",
    ) -> None:
        self._raw_row = raw_row
        self._columns = tuple(column.name for column in columns)
        self._index_by_name = {name: index for index, name in enumerate(self._columns)}
        self._values = tuple(
            _convert_pg_value(
                self._raw_get(index, column.name),
                column.type_code,
                storage_timezone=storage_timezone,
            )
            for index, column in enumerate(columns)
        )

    def __getitem__(self, key: str | int) -> Any:
        if isinstance(key, int):
            return self._values[key]
        try:
            index = self._index_by_name[key]
        except KeyError as exc:
            raise KeyError(key) from exc
        return self._values[index]

    def keys(self) -> Iterable[str]:
        if self._columns:
            return self._columns
        if isinstance(self._raw_row, Mapping):
            return self._raw_row.keys()
        return ()

    def _raw_get(self, index: int, name: str) -> Any:
        if isinstance(self._raw_row, Mapping):
            return self._raw_row[name]
        return self._raw_row[index]


class PostgresCursor(StorageCursor):
    """Cursor wrapper that returns :class:`PostgresRow` objects."""

    def __init__(
        self,
        raw_cursor: Any,
        *,
        storage_timezone: str = "Asia/Shanghai",
    ) -> None:
        self._raw_cursor = raw_cursor
        self._columns = _cursor_columns(raw_cursor)
        self._storage_timezone = storage_timezone

    @property
    def rowcount(self) -> int:
        return int(getattr(self._raw_cursor, "rowcount", -1))

    def fetchone(self) -> PostgresRow | None:
        row = self._raw_cursor.fetchone()
        if row is None:
            return None
        return PostgresRow(
            row,
            self._columns,
            storage_timezone=self._storage_timezone,
        )

    def fetchall(self) -> list[PostgresRow]:
        return [
            PostgresRow(
                row,
                self._columns,
                storage_timezone=self._storage_timezone,
            )
            for row in self._raw_cursor.fetchall()
        ]


class PostgresConnectionAdapter:
    """Adapt a psycopg-like connection to the shared storage connection API."""

    def __init__(
        self,
        raw_conn: Any,
        *,
        schema: str = "wolf",
        search_path: Sequence[str] | None = None,
        placeholder_style: PlaceholderStyle = "format",
        storage_timezone: str = "Asia/Shanghai",
        configure_search_path: bool = True,
    ) -> None:
        _validate_identifier(schema, kind="schema")
        if placeholder_style not in {"format", "numeric"}:
            raise ValueError(
                "PostgreSQL placeholder_style must be 'format' or 'numeric'"
            )
        self._raw_conn = raw_conn
        self.schema = schema
        self.placeholder_style = placeholder_style
        self.storage_timezone = storage_timezone
        self.search_path = tuple(search_path or (schema, "public"))
        for name in self.search_path:
            _validate_identifier(name, kind="schema")
        if configure_search_path:
            self._execute_raw(
                "SET search_path TO "
                + ", ".join(_quote_identifier(name) for name in self.search_path)
            )
            self.commit()

    def execute(
        self,
        sql: str,
        parameters: Iterable[Any] | None = (),
        /,
    ) -> PostgresCursor:
        params = _normalize_parameters(parameters)
        params = _adapt_parameters(sql, params)
        sql = _cast_jsonb_parameters(sql)
        converted = convert_qmark_placeholders(
            sql,
            style=self.placeholder_style,
            expected_params=len(params),
        )
        cursor = self._execute_raw(converted.sql, params if params else _UNSET)
        return PostgresCursor(cursor, storage_timezone=self.storage_timezone)

    def commit(self) -> None:
        self._raw_conn.commit()

    def rollback(self) -> None:
        self._raw_conn.rollback()

    def close(self) -> None:
        self._raw_conn.close()

    def __enter__(self) -> "PostgresConnectionAdapter":
        return self

    def __exit__(self, exc_type: object, exc: object, tb: object) -> object:
        if exc_type is None:
            self.commit()
        else:
            self.rollback()
        return False

    def insert_returning_id(
        self,
        sql: str,
        parameters: Sequence[Any] = (),
        *,
        id_column: str = "id",
    ) -> int:
        _validate_identifier(id_column, kind="column")
        returning_sql = sql
        if _RETURNING_RE.search(returning_sql) is None:
            returning_sql = (
                _strip_trailing_semicolon(returning_sql)
                + f" RETURNING {_quote_identifier(id_column)}"
            )
        row = self.execute(returning_sql, parameters).fetchone()
        if row is None:
            raise RuntimeError("INSERT ... RETURNING did not return a row")
        return int(row[0])

    def begin_write(self) -> None:
        self._execute_raw("BEGIN")

    def execute_for_update(
        self,
        sql: str,
        parameters: Sequence[Any] = (),
    ) -> PostgresCursor:
        statement = _strip_trailing_semicolon(sql)
        if not statement.lstrip().upper().startswith("SELECT"):
            raise ValueError("execute_for_update requires a SELECT statement")
        if _FOR_UPDATE_RE.search(statement) is None:
            statement = statement + " FOR UPDATE"
        return self.execute(statement, parameters)

    def table_exists(self, table_name: str) -> bool:
        _validate_identifier(table_name, kind="table")
        row = self.execute(
            """
            SELECT 1
            FROM information_schema.tables
            WHERE table_schema = ? AND table_name = ?
            LIMIT 1
            """,
            (self.schema, table_name),
        ).fetchone()
        return row is not None

    def table_columns(self, table_name: str) -> Iterable[str]:
        _validate_identifier(table_name, kind="table")
        rows = self.execute(
            """
            SELECT column_name
            FROM information_schema.columns
            WHERE table_schema = ? AND table_name = ?
            ORDER BY ordinal_position
            """,
            (self.schema, table_name),
        ).fetchall()
        return [str(row[0]) for row in rows]

    def add_column(self, table_name: str, column_name: str, declaration: str) -> None:
        _validate_identifier(table_name, kind="table")
        _validate_identifier(column_name, kind="column")
        _validate_column_declaration(declaration)
        self.execute(
            "ALTER TABLE "
            f"{_qualified_table(self.schema, table_name)} "
            f"ADD COLUMN {_quote_identifier(column_name)} {declaration}"
        )

    def record_schema_version(
        self,
        component: str,
        version: int,
        applied_at: str,
    ) -> None:
        self.execute(
            f"""
            CREATE TABLE IF NOT EXISTS {_qualified_table(self.schema, "schema_migrations")} (
                component text PRIMARY KEY,
                version integer NOT NULL,
                applied_at timestamptz NOT NULL
            )
            """
        )
        self.execute(
            f"""
            INSERT INTO {_qualified_table(self.schema, "schema_migrations")}
                (component, version, applied_at)
            VALUES (?, ?, ?)
            ON CONFLICT(component) DO UPDATE SET
                version = excluded.version,
                applied_at = excluded.applied_at
            """,
            (component, int(version), applied_at),
        )

    def _execute_raw(self, sql: str, parameters: tuple[Any, ...] | object = _UNSET) -> Any:
        if parameters is _UNSET:
            return self._raw_conn.execute(sql)
        return self._raw_conn.execute(sql, parameters)


def connect_postgres(
    conninfo: str | None = None,
    *,
    schema: str = "wolf",
    search_path: Sequence[str] | None = None,
    placeholder_style: PlaceholderStyle = "format",
    storage_timezone: str = "Asia/Shanghai",
    configure_search_path: bool = True,
    **kwargs: Any,
) -> PostgresConnectionAdapter:
    """Open a psycopg connection and wrap it in :class:`PostgresConnectionAdapter`."""
    import psycopg

    raw_conn = (
        psycopg.connect(conninfo, **kwargs)
        if conninfo is not None
        else psycopg.connect(**kwargs)
    )
    return PostgresConnectionAdapter(
        raw_conn,
        schema=schema,
        search_path=search_path,
        placeholder_style=placeholder_style,
        storage_timezone=storage_timezone,
        configure_search_path=configure_search_path,
    )


def get_wolf_postgres_connection(
    conninfo: str | None = None,
    **kwargs: Any,
) -> PostgresConnectionAdapter:
    """Open a PostgreSQL connection for the wolf storage namespace."""
    return _get_domain_postgres_connection(conninfo, schema="wolf", **kwargs)


def get_registry_postgres_connection(
    conninfo: str | None = None,
    **kwargs: Any,
) -> PostgresConnectionAdapter:
    """Open a PostgreSQL connection for the registry storage namespace."""
    return _get_domain_postgres_connection(conninfo, schema="registry", **kwargs)


def get_evolution_postgres_connection(
    conninfo: str | None = None,
    **kwargs: Any,
) -> PostgresConnectionAdapter:
    """Open a PostgreSQL connection for the evolution storage namespace."""
    return _get_domain_postgres_connection(conninfo, schema="evolution", **kwargs)


def _get_domain_postgres_connection(
    conninfo: str | None,
    *,
    schema: str,
    **kwargs: Any,
) -> PostgresConnectionAdapter:
    resolved = conninfo or _postgres_database_url()
    if not resolved and not kwargs:
        raise ValueError(
            "PostgreSQL connection info is required; pass conninfo or set "
            "POSTGRES_DATABASE_URL/DATABASE_URL"
        )
    return connect_postgres(
        resolved,
        schema=schema,
        search_path=(schema, "public"),
        **kwargs,
    )


def _postgres_database_url() -> str | None:
    url = os.environ.get("POSTGRES_DATABASE_URL") or os.environ.get("DATABASE_URL")
    if url:
        return url
    if os.environ.get("POSTGRES_DISABLE_DOTENV", "").lower() not in {"1", "true", "yes"}:
        try:
            from dotenv import load_dotenv

            load_dotenv(Path(__file__).resolve().parents[2] / ".env", override=False)
        except Exception:
            pass
    return os.environ.get("POSTGRES_DATABASE_URL") or os.environ.get("DATABASE_URL")


def _normalize_parameters(parameters: Iterable[Any] | None) -> tuple[Any, ...]:
    if parameters is None:
        return ()
    if isinstance(parameters, str | bytes | bytearray):
        raise TypeError("SQL parameters must be an iterable of values, not a string")
    if isinstance(parameters, Mapping):
        raise TypeError("SQL parameters must be a sequence, not a mapping")
    return tuple(parameters)


def _cursor_columns(raw_cursor: Any) -> tuple[_ColumnInfo, ...]:
    description = getattr(raw_cursor, "description", None)
    if not description:
        return ()
    columns: list[_ColumnInfo] = []
    for item in description:
        name = getattr(item, "name", None)
        if name is None:
            name = item[0]
        type_code = getattr(item, "type_code", None)
        if type_code is None and not hasattr(item, "name") and len(item) > 1:
            type_code = item[1]
        columns.append(_ColumnInfo(str(name), _as_int(type_code)))
    return tuple(columns)


def _adapt_parameters(sql: str, parameters: tuple[Any, ...]) -> tuple[Any, ...]:
    if not parameters:
        return parameters
    bool_indexes = _boolean_parameter_indexes(sql)
    if not bool_indexes:
        return parameters
    values = list(parameters)
    for index in bool_indexes:
        if index < len(values):
            values[index] = _adapt_boolean_parameter(values[index])
    return tuple(values)


def _adapt_boolean_parameter(value: Any) -> Any:
    if isinstance(value, bool):
        return value
    if isinstance(value, int) and value in (0, 1):
        return bool(value)
    return value


def _cast_jsonb_parameters(sql: str) -> str:
    indexes = _jsonb_parameter_indexes(sql)
    if not indexes:
        return sql
    positions = _qmark_placeholder_positions(sql)
    replacements = {
        positions[index]: "?::jsonb"
        for index in indexes
        if index < len(positions) and not _has_cast_after(sql, positions[index])
    }
    if not replacements:
        return sql
    out: list[str] = []
    last = 0
    for position in positions:
        replacement = replacements.get(position)
        if replacement is None:
            continue
        out.append(sql[last:position])
        out.append(replacement)
        last = position + 1
    out.append(sql[last:])
    return "".join(out)


def _boolean_parameter_indexes(sql: str) -> set[int]:
    return _column_parameter_indexes(sql, _BOOLEAN_COLUMNS_BY_TABLE, _BOOLEAN_COLUMN_NAMES)


def _jsonb_parameter_indexes(sql: str) -> set[int]:
    return _column_parameter_indexes(sql, _JSONB_COLUMNS_BY_TABLE, _JSONB_COLUMN_NAMES)


def _column_parameter_indexes(
    sql: str,
    columns_by_table: Mapping[str, set[str]],
    global_columns: set[str],
) -> set[int]:
    positions = _qmark_placeholder_positions(sql)
    index_by_position = {position: index for index, position in enumerate(positions)}
    indexes: set[int] = set()
    indexes.update(_insert_parameter_indexes(sql, index_by_position, columns_by_table))
    for position, index in index_by_position.items():
        column = _assignment_column_before(sql, position)
        if column in global_columns:
            indexes.add(index)
    return indexes


def _insert_parameter_indexes(
    sql: str,
    index_by_position: Mapping[int, int],
    columns_by_table: Mapping[str, set[str]],
) -> set[int]:
    match = _INSERT_RE.search(sql)
    if match is None:
        return set()
    table = _normalize_sql_identifier(match.group("table").split(".")[-1])
    boolean_columns = columns_by_table.get(table, set())
    if not boolean_columns:
        return set()
    columns = [
        _normalize_sql_identifier(part)
        for part in _split_top_level_csv(match.group("columns"))
    ]
    value_parts = _split_top_level_csv_with_offsets(
        match.group("values"),
        match.start("values"),
    )
    indexes: set[int] = set()
    for column, (value, offset) in zip(columns, value_parts, strict=False):
        if column not in boolean_columns:
            continue
        stripped = value.strip()
        if stripped != "?":
            continue
        qmark_position = offset + value.index("?")
        index = index_by_position.get(qmark_position)
        if index is not None:
            indexes.add(index)
    return indexes


def _assignment_column_before(sql: str, placeholder_position: int) -> str:
    prefix = sql[:placeholder_position]
    match = _ASSIGNMENT_RE.search(prefix)
    if match is None:
        return ""
    return _normalize_sql_identifier(match.group(1))


def _split_top_level_csv(text: str) -> list[str]:
    return [part for part, _ in _split_top_level_csv_with_offsets(text, 0)]


def _split_top_level_csv_with_offsets(text: str, base_offset: int) -> list[tuple[str, int]]:
    parts: list[tuple[str, int]] = []
    start = 0
    depth = 0
    i = 0
    n = len(text)
    while i < n:
        ch = text[i]
        if ch == "'":
            i = _skip_single_quoted(text, i)
            continue
        if ch == '"':
            i = _skip_double_quoted(text, i)
            continue
        if ch == "(":
            depth += 1
        elif ch == ")" and depth > 0:
            depth -= 1
        elif ch == "," and depth == 0:
            parts.append((text[start:i], base_offset + start))
            start = i + 1
        i += 1
    parts.append((text[start:], base_offset + start))
    return parts


def _qmark_placeholder_positions(sql: str) -> list[int]:
    positions: list[int] = []
    i = 0
    n = len(sql)
    while i < n:
        ch = sql[i]
        nxt = sql[i + 1] if i + 1 < n else ""
        if ch == "'":
            i = _skip_single_quoted(sql, i)
            continue
        if ch == '"':
            i = _skip_double_quoted(sql, i)
            continue
        if ch == "`":
            i = _skip_backtick_quoted(sql, i)
            continue
        if ch == "[":
            i = _skip_bracket_quoted(sql, i)
            continue
        if ch == "-" and nxt == "-":
            i = _skip_line_comment(sql, i)
            continue
        if ch == "/" and nxt == "*":
            i = _skip_block_comment(sql, i)
            continue
        if ch == "$":
            end = _dollar_quote_end(sql, i)
            if end is not None:
                i = end
                continue
        if ch == "?":
            positions.append(i)
        i += 1
    return positions


def _skip_single_quoted(sql: str, start: int) -> int:
    i = start + 1
    n = len(sql)
    while i < n:
        if sql[i] == "'":
            if i + 1 < n and sql[i + 1] == "'":
                i += 2
                continue
            return i + 1
        i += 1
    return i


def _skip_double_quoted(sql: str, start: int) -> int:
    i = start + 1
    n = len(sql)
    while i < n:
        if sql[i] == '"':
            if i + 1 < n and sql[i + 1] == '"':
                i += 2
                continue
            return i + 1
        i += 1
    return i


def _skip_backtick_quoted(sql: str, start: int) -> int:
    i = start + 1
    n = len(sql)
    while i < n:
        if sql[i] == "`":
            if i + 1 < n and sql[i + 1] == "`":
                i += 2
                continue
            return i + 1
        i += 1
    return i


def _skip_bracket_quoted(sql: str, start: int) -> int:
    i = start + 1
    n = len(sql)
    while i < n:
        if sql[i] == "]":
            return i + 1
        i += 1
    return i


def _skip_line_comment(sql: str, start: int) -> int:
    i = start
    n = len(sql)
    while i < n:
        i += 1
        if sql[i - 1] == "\n":
            break
    return i


def _skip_block_comment(sql: str, start: int) -> int:
    i = start
    n = len(sql)
    while i < n:
        if sql[i] == "*" and i + 1 < n and sql[i + 1] == "/":
            return i + 2
        i += 1
    return i


def _dollar_quote_end(sql: str, start: int) -> int | None:
    n = len(sql)
    j = start + 1
    while j < n and (sql[j].isalnum() or sql[j] == "_"):
        j += 1
    if j >= n or sql[j] != "$":
        return None
    delimiter = sql[start : j + 1]
    end = sql.find(delimiter, j + 1)
    if end < 0:
        return None
    return end + len(delimiter)


def _has_cast_after(sql: str, position: int) -> bool:
    return sql[position + 1 : position + 8].lstrip().startswith("::")


def _normalize_sql_identifier(identifier: str) -> str:
    return identifier.strip().strip('"').lower()


def _convert_pg_value(
    value: Any,
    type_code: int | None,
    *,
    storage_timezone: str,
) -> Any:
    if value is None:
        return None
    if type_code in _JSON_OIDS:
        return json.dumps(value, ensure_ascii=False, default=str)
    if type_code in _BOOL_OIDS and isinstance(value, bool):
        return 1 if value else 0
    if type_code in _DATE_TIME_OIDS:
        return _date_time_to_storage_text(value, storage_timezone=storage_timezone)
    return value


def _date_time_to_storage_text(value: Any, *, storage_timezone: str) -> Any:
    if isinstance(value, datetime):
        if value.tzinfo is not None:
            value = value.astimezone(ZoneInfo(storage_timezone))
        return value.isoformat()
    if isinstance(value, date):
        return value.isoformat()
    return value


def _as_int(value: Any) -> int | None:
    if value is None:
        return None
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def _strip_trailing_semicolon(sql: str) -> str:
    stripped = sql.rstrip()
    if stripped.endswith(";"):
        return stripped[:-1].rstrip()
    return stripped


def _qualified_table(schema: str, table_name: str) -> str:
    _validate_identifier(schema, kind="schema")
    _validate_identifier(table_name, kind="table")
    return f"{_quote_identifier(schema)}.{_quote_identifier(table_name)}"


def _quote_identifier(identifier: str) -> str:
    _validate_identifier(identifier, kind="identifier")
    return f'"{identifier}"'


def _validate_identifier(identifier: str, *, kind: str) -> None:
    if not _IDENTIFIER_RE.fullmatch(identifier):
        raise ValueError(f"invalid {kind} identifier: {identifier!r}")


def _validate_column_declaration(declaration: str) -> None:
    if not declaration.strip():
        raise ValueError("column declaration must not be empty")
    forbidden = (";", "--", "/*", "*/", "\x00")
    if any(token in declaration for token in forbidden):
        raise ValueError(f"unsafe column declaration: {declaration!r}")


__all__ = [
    "PostgresConnectionAdapter",
    "PostgresCursor",
    "PostgresRow",
    "connect_postgres",
    "get_evolution_postgres_connection",
    "get_registry_postgres_connection",
    "get_wolf_postgres_connection",
]
