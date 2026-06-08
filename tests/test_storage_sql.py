from __future__ import annotations

import pytest

from storage.shared.sql import convert_qmark_placeholders


def test_convert_qmark_placeholders_to_format_style() -> None:
    result = convert_qmark_placeholders(
        "SELECT * FROM games WHERE id = ? AND winner = ? LIMIT ?",
        style="format",
    )

    assert result.sql == "SELECT * FROM games WHERE id = %s AND winner = %s LIMIT %s"
    assert result.count == 3


def test_convert_qmark_placeholders_to_numeric_style() -> None:
    result = convert_qmark_placeholders(
        "UPDATE games SET winner = ?, finished_at = ? WHERE id = ?",
        style="numeric",
    )

    assert result.sql == "UPDATE games SET winner = $1, finished_at = $2 WHERE id = $3"
    assert result.count == 3


def test_convert_qmark_placeholders_preserves_qmark_style() -> None:
    sql = "SELECT * FROM games WHERE id = ?"

    result = convert_qmark_placeholders(sql, style="qmark")

    assert result.sql == sql
    assert result.count == 1


def test_convert_qmark_placeholders_skips_quoted_text_and_identifiers() -> None:
    result = convert_qmark_placeholders(
        """
        SELECT '?', "column?", `legacy?`, [odd?]
        FROM games
        WHERE id = ? AND message = 'don''t replace ? here'
        """,
        style="numeric",
    )

    assert "'?'" in result.sql
    assert '"column?"' in result.sql
    assert "`legacy?`" in result.sql
    assert "[odd?]" in result.sql
    assert "'don''t replace ? here'" in result.sql
    assert "id = $1" in result.sql
    assert result.count == 1


def test_convert_qmark_placeholders_skips_comments() -> None:
    result = convert_qmark_placeholders(
        """
        SELECT *
        FROM games -- comment ?
        WHERE id = ?
        /* block ? comment */
        AND winner = ?
        """,
        style="format",
    )

    assert "-- comment ?" in result.sql
    assert "/* block ? comment */" in result.sql
    assert "id = %s" in result.sql
    assert "winner = %s" in result.sql
    assert result.count == 2


def test_convert_qmark_placeholders_skips_dollar_quoted_text() -> None:
    result = convert_qmark_placeholders(
        "SELECT $tag$do not replace ?$tag$, $$nor this ?$$ WHERE id = ?",
        style="numeric",
    )

    assert "$tag$do not replace ?$tag$" in result.sql
    assert "$$nor this ?$$" in result.sql
    assert "id = $1" in result.sql
    assert result.count == 1


def test_convert_qmark_placeholders_rejects_unknown_style() -> None:
    with pytest.raises(ValueError, match="unsupported placeholder style"):
        convert_qmark_placeholders("SELECT ?", style="named")  # type: ignore[arg-type]


def test_convert_qmark_placeholders_validates_expected_param_count() -> None:
    result = convert_qmark_placeholders(
        "SELECT * FROM games WHERE id = ? AND winner = ?",
        style="format",
        expected_params=2,
    )

    assert result.count == 2


def test_convert_qmark_placeholders_rejects_param_count_mismatch() -> None:
    with pytest.raises(ValueError, match="placeholder count mismatch"):
        convert_qmark_placeholders(
            "SELECT * FROM games WHERE id = ?",
            style="format",
            expected_params=2,
        )
