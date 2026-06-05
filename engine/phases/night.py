from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING

from engine.models import DeathCause, Phase, Role
from engine.role_rules.registry import rule_for

if TYPE_CHECKING:
    from engine.engine import GameEngine


@dataclass(slots=True)
class NightResult:
    protected_target: int | None
    killed_target: int | None
    saved: bool
    poisoned_target: int | None
    deaths: list[tuple[int, DeathCause]]

    @property
    def death_ids(self) -> list[int]:
        return [player_id for player_id, _cause in self.deaths]

    def payload(self, *, include_deaths: bool = True) -> dict:
        payload = {
            "protected_target": self.protected_target,
            "killed_target": self.killed_target,
            "saved": self.saved,
            "poisoned_target": self.poisoned_target,
        }
        if include_deaths:
            payload["deaths"] = self.death_ids
        return payload


async def run_night(engine: GameEngine) -> list[int]:
    result = await resolve_night_actions(engine)
    return await reveal_night_deaths(engine, result)


async def run_night_without_death_reveal(engine: GameEngine) -> NightResult:
    result = await resolve_night_actions(engine)
    engine._record(
        "night_end",
        message=f"第 {engine.state.day} 夜结束，死亡结果将在警长竞选后公布",
        payload={**result.payload(include_deaths=False), "deferred_death_reveal": True},
    )
    return result


async def resolve_night_actions(engine: GameEngine) -> NightResult:
    engine.state.phase = Phase.NIGHT
    engine.state.day += 1
    engine._record("night_start", message=f"第 {engine.state.day} 夜开始", payload={"alive": engine.alive_ids()})
    protected_target = None
    killed_target = None
    saved = False
    poisoned_target = None

    for role in engine.config.night_order:
        if role is Role.GUARD:
            protected_target = await rule_for(Role.GUARD).night_action(engine)
        elif role is Role.WEREWOLF:
            killed_target = await rule_for(Role.WEREWOLF).night_action(engine)
        elif role is Role.SEER:
            await rule_for(Role.SEER).night_action(engine)
        elif role is Role.WITCH:
            saved, poisoned_target = await rule_for(Role.WITCH).night_action(engine, killed_target)
        else:
            await rule_for(role).night_action(engine)

    deaths: list[tuple[int, DeathCause]] = []
    if killed_target is not None:
        protected = protected_target == killed_target
        if protected and saved:
            deaths.append((killed_target, DeathCause.WEREWOLF))
        elif not protected and not saved:
            deaths.append((killed_target, DeathCause.WEREWOLF))
    if poisoned_target is not None and poisoned_target not in {player_id for player_id, _cause in deaths}:
        deaths.append((poisoned_target, DeathCause.WITCH_POISON))

    return NightResult(
        protected_target=protected_target,
        killed_target=killed_target,
        saved=saved,
        poisoned_target=poisoned_target,
        deaths=deaths,
    )


async def reveal_night_deaths(
    engine: GameEngine,
    result: NightResult,
    *,
    event_type: str = "night_end",
    message: str | None = None,
) -> list[int]:
    night_death_start = len(engine.state.deaths)
    for player_id, cause in result.deaths:
        engine.kill_player(player_id, cause)

    night_deaths = [death.player_id for death in engine.state.deaths[night_death_start:]]
    await engine.resolve_death_triggers(night_deaths)
    engine._record(
        event_type,
        message=message or f"第 {engine.state.day} 夜结束，死亡玩家：{night_deaths or '无'}",
        payload={**result.payload(include_deaths=False), "deaths": night_deaths},
    )
    return night_deaths
