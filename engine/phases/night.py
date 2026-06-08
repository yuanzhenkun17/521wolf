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
    deaths: list[tuple[int, tuple[DeathCause, ...]]]

    @property
    def death_ids(self) -> list[int]:
        return [player_id for player_id, _causes in self.deaths]

    def payload(self, *, include_deaths: bool = True, public: bool = False) -> dict:
        payload = {} if public else {
            "protected_target": self.protected_target,
            "killed_target": self.killed_target,
            "saved": self.saved,
            "poisoned_target": self.poisoned_target,
        }
        if include_deaths:
            payload["deaths"] = self.death_ids if public else [
                {"player_id": player_id, "causes": [cause.value for cause in causes]}
                for player_id, causes in self.deaths
            ]
        return payload


async def run_night(engine: GameEngine) -> list[int]:
    result = await resolve_night_actions(engine)
    return await reveal_night_deaths(engine, result)


async def run_night_without_death_reveal(engine: GameEngine) -> NightResult:
    result = await resolve_night_actions(engine)
    engine._record(
        "night_end",
        message=f"第 {engine.state.day} 夜结束，死亡结果将在警长竞选后公布",
        payload={"deferred_death_reveal": True},
    )
    engine._record(
        "night_result",
        message=f"第 {engine.state.day} 夜晚结算完成",
        payload={**result.payload(include_deaths=True), "deferred_death_reveal": True},
        public=False,
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

    death_causes: dict[int, list[DeathCause]] = {}
    if killed_target is not None:
        protected = protected_target == killed_target
        if protected and saved:
            death_causes.setdefault(killed_target, []).append(DeathCause.WEREWOLF)
        elif not protected and not saved:
            death_causes.setdefault(killed_target, []).append(DeathCause.WEREWOLF)
    if poisoned_target is not None:
        death_causes.setdefault(poisoned_target, []).append(DeathCause.WITCH_POISON)

    ordered_deaths: list[tuple[int, tuple[DeathCause, ...]]] = []
    if killed_target in death_causes:
        ordered_deaths.append((killed_target, tuple(death_causes[killed_target])))
    if poisoned_target is not None and poisoned_target in death_causes and poisoned_target != killed_target:
        ordered_deaths.append((poisoned_target, tuple(death_causes[poisoned_target])))

    return NightResult(
        protected_target=protected_target,
        killed_target=killed_target,
        saved=saved,
        poisoned_target=poisoned_target,
        deaths=ordered_deaths,
    )


async def reveal_night_deaths(
    engine: GameEngine,
    result: NightResult,
    *,
    event_type: str = "night_end",
    message: str | None = None,
) -> list[int]:
    night_death_start = len(engine.state.deaths)
    for player_id, causes in result.deaths:
        engine.kill_player(player_id, causes[0], causes=causes, announce=False)

    night_deaths = list(result.death_ids)
    engine._record(
        event_type,
        message=message or f"第 {engine.state.day} 夜结束，死亡玩家：{night_deaths or '无'}",
        payload={"deaths": night_deaths},
    )
    engine._record(
        "night_death_detail",
        message=f"第 {engine.state.day} 夜死亡详情",
        payload=result.payload(include_deaths=True),
        public=False,
    )
    await engine.resolve_death_triggers(night_deaths, delay_night_hunter=False)
    return night_deaths
