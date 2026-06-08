"""Review store: CRUD for decision reviews and counterfactuals."""

from __future__ import annotations

from typing import Any

from storage.shared.database import StorageConnection
from storage.shared.interfaces import TimestampProvider, storage_timestamp


class DecisionReviewStore:
    """Store and query decision quality reviews."""

    def __init__(
        self,
        conn: StorageConnection,
        timestamp_provider: TimestampProvider | None = None,
    ) -> None:
        self._conn = conn
        self._timestamp = timestamp_provider or storage_timestamp

    def save_review(
        self,
        review_id: str,
        game_id: str,
        decision_id: str,
        player_seat: int,
        day: int,
        phase: str,
        action_type: str,
        quality: str,
        *,
        reason: str | None = None,
        alternative_action: str | None = None,
        created_at: str | None = None,
    ) -> str:
        now = created_at or self._timestamp()
        self._conn.execute(
            "INSERT INTO decision_reviews "
            "(id, game_id, decision_id, player_seat, day, phase, action_type, "
            "quality, reason, alternative_action, created_at) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?) "
            "ON CONFLICT(id) DO UPDATE SET "
            "game_id = excluded.game_id, "
            "decision_id = excluded.decision_id, "
            "player_seat = excluded.player_seat, "
            "day = excluded.day, "
            "phase = excluded.phase, "
            "action_type = excluded.action_type, "
            "quality = excluded.quality, "
            "reason = excluded.reason, "
            "alternative_action = excluded.alternative_action, "
            "created_at = excluded.created_at",
            (
                review_id,
                game_id,
                decision_id,
                player_seat,
                day,
                phase,
                action_type,
                quality,
                reason,
                alternative_action,
                now,
            ),
        )
        self._conn.commit()
        return review_id

    def save_batch(self, reviews: list[dict[str, Any]]) -> list[str]:
        """Save multiple reviews in a single transaction."""
        saved: list[str] = []
        now = self._timestamp()
        with self._conn:
            for rev in reviews:
                rid = str(rev["id"])
                self._conn.execute(
                    "INSERT INTO decision_reviews "
                    "(id, game_id, decision_id, player_seat, day, phase, action_type, "
                    "quality, reason, alternative_action, created_at) "
                    "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?) "
                    "ON CONFLICT(id) DO UPDATE SET "
                    "game_id = excluded.game_id, "
                    "decision_id = excluded.decision_id, "
                    "player_seat = excluded.player_seat, "
                    "day = excluded.day, "
                    "phase = excluded.phase, "
                    "action_type = excluded.action_type, "
                    "quality = excluded.quality, "
                    "reason = excluded.reason, "
                    "alternative_action = excluded.alternative_action, "
                    "created_at = excluded.created_at",
                    (
                        rid,
                        str(rev["game_id"]),
                        str(rev["decision_id"]),
                        int(rev["player_seat"]),
                        int(rev["day"]),
                        str(rev["phase"]),
                        str(rev["action_type"]),
                        str(rev["quality"]),
                        rev.get("reason"),
                        rev.get("alternative_action"),
                        str(rev.get("created_at") or now),
                    ),
                )
                saved.append(rid)
        return saved

    def get_review(self, review_id: str) -> dict[str, Any] | None:
        row = self._conn.execute(
            "SELECT * FROM decision_reviews WHERE id = ?", (review_id,)
        ).fetchone()
        return dict(row) if row is not None else None

    def get_for_game(self, game_id: str) -> list[dict[str, Any]]:
        rows = self._conn.execute(
            "SELECT * FROM decision_reviews WHERE game_id = ? ORDER BY day, player_seat",
            (game_id,),
        ).fetchall()
        return [dict(row) for row in rows]

    def get_for_decision(self, decision_id: str) -> list[dict[str, Any]]:
        rows = self._conn.execute(
            "SELECT * FROM decision_reviews WHERE decision_id = ?",
            (decision_id,),
        ).fetchall()
        return [dict(row) for row in rows]

    def query(
        self,
        *,
        game_id: str | None = None,
        quality: str | None = None,
        role: str | None = None,
        action_type: str | None = None,
        limit: int = 100,
    ) -> list[dict[str, Any]]:
        conditions: list[str] = []
        params: list[Any] = []

        if game_id:
            conditions.append("game_id = ?")
            params.append(game_id)
        if quality:
            conditions.append("quality = ?")
            params.append(quality)
        if action_type:
            conditions.append("action_type = ?")
            params.append(action_type)

        where = " WHERE " + " AND ".join(conditions) if conditions else ""
        params.append(limit)
        rows = self._conn.execute(
            f"SELECT * FROM decision_reviews{where} ORDER BY created_at DESC LIMIT ?",
            params,
        ).fetchall()
        return [dict(row) for row in rows]

    def quality_distribution(self, game_id: str | None = None) -> dict[str, int]:
        """Return counts of reviews grouped by quality label."""
        if game_id:
            rows = self._conn.execute(
                "SELECT quality, COUNT(*) AS cnt FROM decision_reviews "
                "WHERE game_id = ? GROUP BY quality",
                (game_id,),
            ).fetchall()
        else:
            rows = self._conn.execute(
                "SELECT quality, COUNT(*) AS cnt FROM decision_reviews "
                "GROUP BY quality"
            ).fetchall()
        return {row["quality"]: row["cnt"] for row in rows}

    def delete_for_game(self, game_id: str) -> int:
        cursor = self._conn.execute(
            "DELETE FROM decision_reviews WHERE game_id = ?", (game_id,)
        )
        self._conn.commit()
        return cursor.rowcount


class CounterfactualStore:
    """Store and query what-if counterfactual analyses for decisions."""

    def __init__(
        self,
        conn: StorageConnection,
        timestamp_provider: TimestampProvider | None = None,
    ) -> None:
        self._conn = conn
        self._timestamp = timestamp_provider or storage_timestamp

    def save_counterfactual(
        self,
        cf_id: str,
        game_id: str,
        decision_id: str,
        what_if: str,
        *,
        likely_outcome: str | None = None,
        confidence: float | None = None,
        created_at: str | None = None,
    ) -> str:
        now = created_at or self._timestamp()
        self._conn.execute(
            "INSERT INTO counterfactuals "
            "(id, game_id, decision_id, what_if, likely_outcome, confidence, created_at) "
            "VALUES (?, ?, ?, ?, ?, ?, ?) "
            "ON CONFLICT(id) DO UPDATE SET "
            "game_id = excluded.game_id, "
            "decision_id = excluded.decision_id, "
            "what_if = excluded.what_if, "
            "likely_outcome = excluded.likely_outcome, "
            "confidence = excluded.confidence, "
            "created_at = excluded.created_at",
            (cf_id, game_id, decision_id, what_if, likely_outcome, confidence, now),
        )
        self._conn.commit()
        return cf_id

    def save_batch(self, counterfactuals: list[dict[str, Any]]) -> list[str]:
        """Save multiple counterfactuals in a single transaction."""
        saved: list[str] = []
        now = self._timestamp()
        with self._conn:
            for cf in counterfactuals:
                cid = str(cf["id"])
                self._conn.execute(
                    "INSERT INTO counterfactuals "
                    "(id, game_id, decision_id, what_if, likely_outcome, confidence, created_at) "
                    "VALUES (?, ?, ?, ?, ?, ?, ?) "
                    "ON CONFLICT(id) DO UPDATE SET "
                    "game_id = excluded.game_id, "
                    "decision_id = excluded.decision_id, "
                    "what_if = excluded.what_if, "
                    "likely_outcome = excluded.likely_outcome, "
                    "confidence = excluded.confidence, "
                    "created_at = excluded.created_at",
                    (
                        cid,
                        str(cf["game_id"]),
                        str(cf["decision_id"]),
                        str(cf["what_if"]),
                        cf.get("likely_outcome"),
                        cf.get("confidence"),
                        str(cf.get("created_at") or now),
                    ),
                )
                saved.append(cid)
        return saved

    def get_counterfactual(self, cf_id: str) -> dict[str, Any] | None:
        row = self._conn.execute(
            "SELECT * FROM counterfactuals WHERE id = ?", (cf_id,)
        ).fetchone()
        return dict(row) if row is not None else None

    def get_for_decision(self, decision_id: str) -> list[dict[str, Any]]:
        rows = self._conn.execute(
            "SELECT * FROM counterfactuals WHERE decision_id = ?",
            (decision_id,),
        ).fetchall()
        return [dict(row) for row in rows]

    def get_for_game(self, game_id: str) -> list[dict[str, Any]]:
        rows = self._conn.execute(
            "SELECT * FROM counterfactuals WHERE game_id = ? ORDER BY created_at",
            (game_id,),
        ).fetchall()
        return [dict(row) for row in rows]

    def query(
        self,
        *,
        game_id: str | None = None,
        decision_id: str | None = None,
        limit: int = 100,
    ) -> list[dict[str, Any]]:
        conditions: list[str] = []
        params: list[Any] = []

        if game_id:
            conditions.append("game_id = ?")
            params.append(game_id)
        if decision_id:
            conditions.append("decision_id = ?")
            params.append(decision_id)

        where = " WHERE " + " AND ".join(conditions) if conditions else ""
        params.append(limit)
        rows = self._conn.execute(
            f"SELECT * FROM counterfactuals{where} ORDER BY created_at DESC LIMIT ?",
            params,
        ).fetchall()
        return [dict(row) for row in rows]

    def delete_for_game(self, game_id: str) -> int:
        cursor = self._conn.execute(
            "DELETE FROM counterfactuals WHERE game_id = ?", (game_id,)
        )
        self._conn.commit()
        return cursor.rowcount
