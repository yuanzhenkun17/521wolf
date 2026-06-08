"""SQL text helpers shared by database adapters."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Literal


PlaceholderStyle = Literal["qmark", "format", "numeric"]


@dataclass(frozen=True, slots=True)
class PlaceholderConversion:
    sql: str
    count: int


def convert_qmark_placeholders(
    sql: str,
    *,
    style: PlaceholderStyle,
    expected_params: int | None = None,
) -> PlaceholderConversion:
    """Convert qmark placeholders while preserving quoted SQL text.

    Existing repositories use qmark placeholders. PostgreSQL adapters can call
    this at their execute boundary to convert placeholders to psycopg
    ``%s`` style or numeric ``$1`` style without corrupting question marks in
    string literals, quoted identifiers, comments, or dollar-quoted text.
    """
    if style not in {"qmark", "format", "numeric"}:
        raise ValueError(f"unsupported placeholder style: {style!r}")

    out: list[str] = []
    count = 0
    i = 0
    n = len(sql)

    while i < n:
        ch = sql[i]
        nxt = sql[i + 1] if i + 1 < n else ""

        if ch == "'":
            i = _copy_single_quoted(sql, i, out)
            continue
        if ch == '"':
            i = _copy_double_quoted(sql, i, out)
            continue
        if ch == "`":
            i = _copy_backtick_quoted(sql, i, out)
            continue
        if ch == "[":
            i = _copy_bracket_quoted(sql, i, out)
            continue
        if ch == "-" and nxt == "-":
            i = _copy_line_comment(sql, i, out)
            continue
        if ch == "/" and nxt == "*":
            i = _copy_block_comment(sql, i, out)
            continue
        if ch == "$":
            end = _dollar_quote_end(sql, i)
            if end is not None:
                out.append(sql[i:end])
                i = end
                continue
        if ch == "?":
            count += 1
            out.append(_placeholder(style, count))
            i += 1
            continue

        out.append(ch)
        i += 1

    if expected_params is not None and count != expected_params:
        raise ValueError(
            f"placeholder count mismatch: sql has {count}, "
            f"parameters have {expected_params}"
        )
    return PlaceholderConversion("".join(out), count)


def _placeholder(style: PlaceholderStyle, index: int) -> str:
    if style == "qmark":
        return "?"
    if style == "format":
        return "%s"
    return f"${index}"


def _copy_single_quoted(sql: str, start: int, out: list[str]) -> int:
    i = start
    n = len(sql)
    out.append(sql[i])
    i += 1
    while i < n:
        out.append(sql[i])
        if sql[i] == "'":
            if i + 1 < n and sql[i + 1] == "'":
                out.append(sql[i + 1])
                i += 2
                continue
            i += 1
            break
        i += 1
    return i


def _copy_double_quoted(sql: str, start: int, out: list[str]) -> int:
    i = start
    n = len(sql)
    out.append(sql[i])
    i += 1
    while i < n:
        out.append(sql[i])
        if sql[i] == '"':
            if i + 1 < n and sql[i + 1] == '"':
                out.append(sql[i + 1])
                i += 2
                continue
            i += 1
            break
        i += 1
    return i


def _copy_backtick_quoted(sql: str, start: int, out: list[str]) -> int:
    i = start
    n = len(sql)
    out.append(sql[i])
    i += 1
    while i < n:
        out.append(sql[i])
        if sql[i] == "`":
            if i + 1 < n and sql[i + 1] == "`":
                out.append(sql[i + 1])
                i += 2
                continue
            i += 1
            break
        i += 1
    return i


def _copy_bracket_quoted(sql: str, start: int, out: list[str]) -> int:
    i = start
    n = len(sql)
    while i < n:
        out.append(sql[i])
        if sql[i] == "]":
            i += 1
            break
        i += 1
    return i


def _copy_line_comment(sql: str, start: int, out: list[str]) -> int:
    i = start
    n = len(sql)
    while i < n:
        out.append(sql[i])
        i += 1
        if sql[i - 1] == "\n":
            break
    return i


def _copy_block_comment(sql: str, start: int, out: list[str]) -> int:
    i = start
    n = len(sql)
    while i < n:
        out.append(sql[i])
        if sql[i] == "*" and i + 1 < n and sql[i + 1] == "/":
            out.append("/")
            i += 2
            break
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


__all__ = ["PlaceholderConversion", "PlaceholderStyle", "convert_qmark_placeholders"]
