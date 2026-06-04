from __future__ import annotations
from collections import Counter
from typing import Any, Callable

from engine.actions import ask as ask_action
from engine.config import GameConfig, STANDARD_12
from engine.logging import GameLogger, LogLevel
from engine.models import (
    ActionResponse,
    ActionType,
    DeathCause,
    DeathRecord,
    GameEvent,
    GameState,
    Observation,
    Phase,
    PlayerState,
    Role,
    Team,
    Winner,
)
from engine.phases import day, exile, night, sheriff
from engine.players import PlayerAgent
from engine.role_rules.registry import rule_for
from engine.rules import death, sheriff as sheriff_rules, victory, voting


class GameEngine:
    def __init__(
        self,
        roles: dict[int, Role],
        agents: dict[int, PlayerAgent],
        config: GameConfig = STANDARD_12,
        log_stream_path: str | None = None,
        logger: GameLogger | None = None,
    ):
        self.config = config
        self.state = GameState(
            players={player_id: PlayerState(player_id, role) for player_id, role in sorted(roles.items())}
        )
        self.agents = agents
        self.logger = logger or GameLogger(stream_path=log_stream_path)
        self._log(
            "game_init",
            f"游戏初始化：{self.config.name}，已创建 {len(self.state.players)} 名玩家",
            payload={"roles": {player_id: role.value for player_id, role in sorted(roles.items())}},
        )
        self._validate_setup()
        # Initialize per-player role_state from each role's rule
        for player_id, ps in self.state.players.items():
            ps.role_state = rule_for(ps.role).init_role_state()

    def _validate_setup(self) -> None:
        if len(self.state.players) != self.config.player_count:
            raise ValueError(
                f"expected {self.config.player_count} players for {self.config.name}, got {len(self.state.players)}"
            )
        expected = self.config.role_counter
        actual = Counter(player.role for player in self.state.players.values())
        if actual != expected:
            raise ValueError(f"expected roles for {self.config.name}: {dict(expected)}, got {dict(actual)}")
        for role in actual:
            rule_for(role)
        missing_agents = set(self.state.players) - set(self.agents)
        if missing_agents:
            raise ValueError(f"missing agents for players: {sorted(missing_agents)}")

    def alive_ids(self) -> tuple[int, ...]:
        return tuple(player_id for player_id, player in self.state.players.items() if player.alive)

    def dead_ids(self) -> tuple[int, ...]:
        return tuple(player_id for player_id, player in self.state.players.items() if not player.alive)

    def role_ids(self, *roles: Role, alive_only: bool = False) -> tuple[int, ...]:
        return tuple(
            player_id
            for player_id, player in self.state.players.items()
            if player.role in roles and (player.alive or not alive_only)
        )

    def team_ids(self, team: Team, alive_only: bool = False) -> tuple[int, ...]:
        return tuple(
            player_id
            for player_id, player in self.state.players.items()
            if player.team is team and (player.alive or not alive_only)
        )

    def observation_for(self, player_id: int, metadata: dict | None = None) -> Observation:
        player = self.state.players[player_id]
        role_rule = rule_for(player.role)
        return Observation(
            player_id=player_id,
            self_role=player.role,
            phase=self.state.phase,
            day=self.state.day,
            alive_players=self.alive_ids(),
            dead_players=self.dead_ids(),
            sheriff_id=self.state.sheriff_id,
            public_log=tuple(self.state.public_log),
            known_roles=role_rule.visible_roles(self, player_id),
            seer_checks=role_rule.seer_checks(self, player_id),
            role_state=role_rule.get_role_state(self, player_id),
            metadata=metadata or {},
        )

    def snapshot(self) -> dict[str, Any]:
        """Return a complete, JSON-serializable snapshot of engine state."""
        return {
            "day": self.state.day,
            "phase": self.state.phase.value if hasattr(self.state.phase, "value") else str(self.state.phase),
            "sheriff_id": self.state.sheriff_id,
            "badge_destroyed": self.state.badge_destroyed,
            "winner": self.state.winner.value if self.state.winner else None,
            "players": {
                pid: {
                    "id": ps.id,
                    "role": ps.role.value if hasattr(ps.role, "value") else str(ps.role),
                    "alive": ps.alive,
                    "role_state": rule_for(ps.role).get_role_state(self, pid),
                }
                for pid, ps in self.state.players.items()
            },
            "deaths": [
                {
                    "player_id": d.player_id,
                    "cause": d.cause.value if hasattr(d.cause, "value") else str(d.cause),
                    "day": d.day,
                    "phase": d.phase.value if hasattr(d.phase, "value") else str(d.phase),
                }
                for d in self.state.deaths
            ],
            "events_count": len(self.state.events),
        }

    async def _ask(
        self,
        player_id: int,
        action_type: ActionType,
        candidates: tuple[int, ...] = (),
        metadata: dict | None = None,
        validator: Callable[[ActionResponse], bool] | None = None,
        default: ActionResponse | None = None,
    ) -> ActionResponse:
        return await ask_action(self, player_id, action_type, candidates, metadata, validator, default)

    def _log(
        self,
        event_type: str,
        message: str,
        actor: int | None = None,
        target: int | None = None,
        payload: dict | None = None,
        level: LogLevel = LogLevel.INFO,
    ) -> None:
        self.logger.record(
            day=self.state.day,
            phase=self.state.phase,
            event_type=event_type,
            message=message,
            level=level,
            actor=actor,
            target=target,
            payload=payload or {},
        )

    def _record(
        self,
        event_type: str,
        actor: int | None = None,
        target: int | None = None,
        payload: dict | None = None,
        public: bool = True,
    ) -> None:
        self.state.events.append(
            GameEvent(
                type=event_type,
                day=self.state.day,
                phase=self.state.phase,
                actor=actor,
                target=target,
                payload=payload or {},
                public=public,
            )
        )

    def kill_player(self, player_id: int, cause: DeathCause) -> None:
        death.kill_player(self, player_id, cause)

    def revive_player(self, player_id: int) -> None:
        death.revive_player(self, player_id)

    def last_death_for(self, player_id: int) -> DeathRecord | None:
        return death.last_death_for(self, player_id)

    def can_hunter_shoot(self, player_id: int) -> bool:
        return death.can_hunter_shoot(self, player_id)

    async def resolve_hunter_death(self, hunter_id: int) -> int | None:
        return await death.resolve_hunter_death(self, hunter_id)

    async def resolve_death_triggers(self, player_ids: list[int] | tuple[int, ...]) -> None:
        await death.resolve_death_triggers(self, player_ids)

    async def resolve_sheriff_death(self, sheriff_id: int) -> None:
        await sheriff_rules.resolve_sheriff_death(self, sheriff_id)

    async def run_sheriff_election(self) -> int | None:
        return await sheriff.run_sheriff_election(self)

    async def run_night(self) -> list[int]:
        return await night.run_night(self)

    async def run_day_speeches(self) -> str:
        return await day.run_day_speeches(self)

    async def resolve_pending_daybreak_actions(self) -> None:
        await death.resolve_pending_daybreak_actions(self)

    async def resolve_last_word(self, player_id: int) -> None:
        await death.resolve_last_word(self, player_id)

    async def resolve_exiled_player(self, player_id: int) -> None:
        await death.resolve_exiled_player(self, player_id)

    async def run_exile_vote(self) -> int | None:
        return await exile.run_exile_vote(self)

    def resolve_exile_votes(
        self,
        votes: dict[int, int],
        candidates: tuple[int, ...] | None = None,
        return_ties: bool = False,
    ) -> int | tuple[int, ...] | None:
        return voting.resolve_votes(votes, self.state.sheriff_id, candidates, return_ties, sheriff_vote_weight=self.config.sheriff_vote_weight)

    def check_winner(self) -> Winner | None:
        return victory.check_winner(self)

    async def run_until_finished(self, max_days: int | None = None) -> Winner:
        effective_max_days = max_days if max_days is not None else self.config.max_days
        for day_index in range(effective_max_days):
            if day_index == 0:
                first_night = await night.run_night_without_death_reveal(self)
                if self.config.enable_sheriff:
                    await self.run_sheriff_election()
                self.state.phase = Phase.DAY_SPEECH
                await night.reveal_night_deaths(
                    self,
                    first_night,
                    event_type="night_death_reveal",
                    message=f"第 {self.state.day} 天天亮，公布昨夜死亡玩家：{first_night.death_ids or '无'}",
                )
            else:
                await self.run_night()
            if not self.state.pending_hunter_shots:
                winner = self.check_winner()
                if winner is not None:
                    return winner
            day_result = await self.run_day_speeches()
            winner = self.check_winner()
            if winner is not None:
                return winner
            if day_result == "white_wolf_exploded":
                continue
            await self.run_exile_vote()
            winner = self.check_winner()
            if winner is not None:
                return winner
        raise RuntimeError("game did not finish within max_days")
