"""Decision timeline ordering helpers."""

from __future__ import annotations

from storage.shared.database import StorageConnection


def decision_timeline_order_clause(conn: StorageConnection) -> str:
    """Return PostgreSQL ORDER BY terms that preserve recorder write order."""

    columns = _decision_columns(conn)
    terms: list[str] = []

    if "decision_index" in columns:
        terms.extend(_nullable_order_terms("decision_index"))
    elif "index" in columns:
        terms.extend(_nullable_order_terms('"index"'))

    if "created_at" in columns or not columns:
        terms.append("created_at")

    if "id" in columns or not columns:
        terms.append("id")

    return ", ".join(dict.fromkeys(terms)) or "id"


def _nullable_order_terms(column: str) -> list[str]:
    return [f"CASE WHEN {column} IS NULL THEN 1 ELSE 0 END", column]


def _decision_columns(conn: StorageConnection) -> set[str]:
    table_columns = getattr(conn, "table_columns", None)
    if callable(table_columns):
        try:
            return {str(column) for column in table_columns("decisions")}
        except Exception:  # noqa: BLE001 - fallback ordering should stay best-effort
            pass

    return set()


__all__ = ["decision_timeline_order_clause"]
