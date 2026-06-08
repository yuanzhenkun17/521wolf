"""Rejected proposal repo: store proposals that were not adopted (evolution database)."""

from __future__ import annotations

import json
import logging
import sqlite3
from typing import Any

from storage.shared.interfaces import storage_timestamp, TimestampProvider

_log = logging.getLogger(__name__)


class RejectedProposalStore:
    """Store and query skill proposals that were rejected during evolution."""

    def __init__(
        self,
        conn: sqlite3.Connection,
        timestamp_provider: TimestampProvider | None = None,
    ) -> None:
        self._conn = conn
        self._timestamp = timestamp_provider or storage_timestamp

    def save_rejection(
        self,
        role: str,
        proposal: Any,
        *,
        battle_score_delta: float | None = None,
        battle_win_rate_delta: float | None = None,
        created_at: str | None = None,
    ) -> int:
        """Save a rejected proposal. Returns the auto-increment row id."""
        now = created_at or self._timestamp()
        if hasattr(proposal, "to_dict"):
            proposal_json = json.dumps(proposal.to_dict(), ensure_ascii=False)
        elif isinstance(proposal, dict):
            proposal_json = json.dumps(proposal, ensure_ascii=False)
        elif isinstance(proposal, str):
            proposal_json = proposal
        else:
            proposal_json = json.dumps(proposal, ensure_ascii=False, default=str)

        cursor = self._conn.execute(
            "INSERT INTO rejected_proposals "
            "(role, proposal_json, battle_score_delta, battle_win_rate_delta, created_at) "
            "VALUES (?, ?, ?, ?, ?)",
            (role, proposal_json, battle_score_delta, battle_win_rate_delta, now),
        )
        self._conn.commit()
        return cursor.lastrowid or 0

    def save_batch(
        self,
        rejections: list[dict[str, Any]],
    ) -> list[int]:
        """Save multiple rejected proposals. Each dict needs at least 'role' and 'proposal'."""
        saved: list[int] = []
        now = self._timestamp()
        for rej in rejections:
            proposal = rej.get("proposal", {})
            if hasattr(proposal, "to_dict"):
                proposal_json = json.dumps(proposal.to_dict(), ensure_ascii=False)
            elif isinstance(proposal, dict):
                proposal_json = json.dumps(proposal, ensure_ascii=False)
            else:
                proposal_json = json.dumps(proposal, ensure_ascii=False, default=str)

            cursor = self._conn.execute(
                "INSERT INTO rejected_proposals "
                "(role, proposal_json, battle_score_delta, battle_win_rate_delta, created_at) "
                "VALUES (?, ?, ?, ?, ?)",
                (
                    str(rej["role"]),
                    proposal_json,
                    rej.get("battle_score_delta"),
                    rej.get("battle_win_rate_delta"),
                    str(rej.get("created_at") or now),
                ),
            )
            saved.append(cursor.lastrowid or 0)
        self._conn.commit()
        return saved

    def list_rejections(
        self,
        *,
        role: str | None = None,
        limit: int = 100,
    ) -> list[dict[str, Any]]:
        conditions: list[str] = []
        params: list[Any] = []

        if role:
            conditions.append("role = ?")
            params.append(role)

        where = " WHERE " + " AND ".join(conditions) if conditions else ""
        params.append(limit)
        rows = self._conn.execute(
            f"SELECT * FROM rejected_proposals{where} ORDER BY created_at DESC LIMIT ?",
            params,
        ).fetchall()
        return [_row_to_dict(row) for row in rows]

    def get_rejection(self, rejection_id: int) -> dict[str, Any] | None:
        row = self._conn.execute(
            "SELECT * FROM rejected_proposals WHERE id = ?", (rejection_id,)
        ).fetchone()
        return _row_to_dict(row) if row is not None else None

    def count_by_role(self) -> dict[str, int]:
        rows = self._conn.execute(
            "SELECT role, COUNT(*) AS cnt FROM rejected_proposals GROUP BY role"
        ).fetchall()
        return {row["role"]: row["cnt"] for row in rows}

    def delete_rejection(self, rejection_id: int) -> int:
        cursor = self._conn.execute(
            "DELETE FROM rejected_proposals WHERE id = ?", (rejection_id,)
        )
        self._conn.commit()
        return cursor.rowcount


def _row_to_dict(row: sqlite3.Row) -> dict[str, Any]:
    data = dict(row)
    raw = data.get("proposal_json")
    if raw:
        try:
            data["proposal"] = json.loads(raw)
        except json.JSONDecodeError:
            data["proposal"] = raw
    else:
        data["proposal"] = None
    return data
