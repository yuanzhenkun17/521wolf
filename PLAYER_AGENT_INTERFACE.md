# 玩家 Agent 接口要求

本文档说明 521wolf 规则引擎对玩家 agent 的接口要求。规则引擎只负责游戏规则、阶段推进、合法性校验和结算；每个玩家的决策由对应 agent 通过统一接口完成。

## 1. 必须实现的接口

每个玩家 agent 必须实现一个异步方法：

```python
from werewolf.models import ActionRequest, ActionResponse


class MyAgent:
    async def act(self, request: ActionRequest) -> ActionResponse:
        ...
```

类型协议在 `src/werewolf/players.py` 中定义：

```python
class PlayerAgent(Protocol):
    async def act(self, request: ActionRequest) -> ActionResponse:
        ...
```

规则引擎会在需要玩家行动时调用 `act(request)`。agent 不应该直接修改 `GameState`，只能返回一个 `ActionResponse`，由规则引擎校验并执行。

## 2. ActionRequest 字段

`ActionRequest` 是规则引擎发给 agent 的行动请求。

```python
@dataclass(slots=True)
class ActionRequest:
    player_id: int
    action_type: ActionType
    phase: Phase
    observation: Observation
    candidates: tuple[int, ...] = ()
    retry_count: int = 0
    metadata: dict[str, Any] = field(default_factory=dict)
```

字段含义：

- `player_id`：当前被请求行动的玩家座位号。
- `action_type`：这次需要执行的行动类型，例如发言、投票、狼人刀人、预言家查验。
- `phase`：当前游戏阶段。
- `observation`：该玩家可见的信息，已经由规则引擎按身份过滤。
- `candidates`：本次行动允许选择的目标座位号。需要选目标时，`target` 必须来自这里。
- `retry_count`：第几次请求。第一次为 `0`，如果上一次响应非法，规则引擎会重试一次并传入 `1`。
- `metadata`：本次行动的补充信息，例如女巫是否能救、昨晚被刀目标等。

## 3. Observation 字段

`Observation` 是玩家当前能看到的局势。

```python
@dataclass(slots=True)
class Observation:
    player_id: int
    self_role: Role
    phase: Phase
    day: int
    alive_players: tuple[int, ...]
    dead_players: tuple[int, ...]
    sheriff_id: int | None
    public_log: tuple[str, ...]
    known_roles: dict[int, Role] = field(default_factory=dict)
    seer_checks: dict[int, Team] = field(default_factory=dict)
    metadata: dict[str, Any] = field(default_factory=dict)
```

信息边界：

- 所有玩家都能看到自己的身份 `self_role`、存活/死亡玩家、警长、公开日志。
- 狼人能在 `known_roles` 中看到其他狼人身份。
- 预言家能在 `seer_checks` 中看到自己已经查验过的结果。
- 普通村民和其他神职不会看到其他玩家的隐藏身份。

agent 可以维护自己的长期记忆，但记忆更新应该基于 `Observation`、公开日志和自己收到过的请求，不应该读取规则引擎内部状态。

## 4. ActionResponse 字段

agent 必须返回 `ActionResponse`。

```python
@dataclass(slots=True)
class ActionResponse:
    action_type: ActionType
    target: int | None = None
    choice: str | None = None
    text: str = ""
```

字段含义：

- `action_type`：必须等于请求中的 `request.action_type`。
- `target`：目标玩家座位号。需要选人时必须来自 `request.candidates`。
- `choice`：非目标型选择，例如是否竞选、是否退水、女巫用药、警徽移交或撕毁。
- `text`：发言内容。规则引擎只记录/传递文本，不解析策略。

如果返回非法响应，规则引擎会重试一次。第二次仍非法时，引擎使用默认动作：发言为空、投票弃票、技能不发动。狼人夜间不允许空刀，因此非法后会由引擎选择默认合法刀人目标。

## 5. 当前行动类型与返回要求

| `ActionType` | 触发时机 | 合法返回 |
| --- | --- | --- |
| `SHERIFF_RUN` | 警长竞选报名 | `choice="run"` 或 `choice="pass"` |
| `SHERIFF_SPEAK` | 警上发言 | `text="..."` |
| `SHERIFF_WITHDRAW` | 竞选退水 | `choice="withdraw"` 或 `choice="stay"` |
| `SHERIFF_VOTE` | 警长投票 | `target` 为候选警长之一，或 `None` 弃票 |
| `SHERIFF_BADGE` | 警长死亡处理警徽 | `choice="transfer", target=存活玩家`，或 `choice="destroy"` |
| `SPEECH_ORDER` | 有警长时，白天发言前由警长选择顺序 | `choice="forward"` 顺序，或 `choice="reverse"` 逆序 |
| `GUARD_PROTECT` | 守卫夜间守护 | `target` 为可守护玩家，不能连续两晚守同一人 |
| `WEREWOLF_KILL` | 狼人夜间刀人 | `target` 为存活非狼人玩家，不允许空刀 |
| `SEER_CHECK` | 预言家夜间查验 | `target` 为可查验玩家 |
| `WITCH_ACT` | 女巫夜间用药 | `choice="save"`、`choice="poison", target=目标`，或 `choice="none"` |
| `LAST_WORD` | 首夜死亡玩家遗言 | `text="..."` |
| `SPEAK` | 白天顺序发言 | `text="..."` |
| `WHITE_WOLF_EXPLODE` | 白狼王白天发言期自爆 | `target` 为存活非狼人玩家，或 `choice="pass"` |
| `EXILE_VOTE` | 白天放逐投票 | `target` 为存活玩家，或 `None` 弃票 |
| `PK_SPEAK` | 放逐平票后的 PK 发言 | `text="..."` |
| `PK_VOTE` | PK 后再次投票 | `target` 为 PK 候选人，或 `None` 弃票 |
| `HUNTER_SHOOT` | 猎人开枪 | 当前类型已预留；后续流程接入时应返回 `target` 为合法可射击玩家 |

## 6. 女巫行动 metadata

女巫收到 `ActionType.WITCH_ACT` 时，`request.metadata` 会包含：

```python
{
    "attacked_player": int | None,
    "can_save": bool,
    "can_poison": bool,
}
```

返回示例：

```python
# 使用解药
ActionResponse(ActionType.WITCH_ACT, choice="save")

# 使用毒药
ActionResponse(ActionType.WITCH_ACT, choice="poison", target=8)

# 不用药
ActionResponse(ActionType.WITCH_ACT, choice="none")
```

规则限制：

- 解药和毒药各只能使用一次。
- 同一晚不能同时使用解药和毒药。
- 守卫守护和女巫救同一名被刀玩家时，该玩家仍死亡。

## 7. 最小 agent 示例

```python
from werewolf.models import ActionRequest, ActionResponse, ActionType


class SimpleAgent:
    async def act(self, request: ActionRequest) -> ActionResponse:
        if request.action_type in {
            ActionType.SPEAK,
            ActionType.SHERIFF_SPEAK,
            ActionType.PK_SPEAK,
            ActionType.LAST_WORD,
        }:
            return ActionResponse(request.action_type, text="我先过。")

        if request.action_type == ActionType.SHERIFF_RUN:
            return ActionResponse(request.action_type, choice="pass")

        if request.action_type == ActionType.SHERIFF_WITHDRAW:
            return ActionResponse(request.action_type, choice="stay")

        if request.action_type == ActionType.SPEECH_ORDER:
            return ActionResponse(request.action_type, choice="forward")

        if request.action_type == ActionType.WITCH_ACT:
            return ActionResponse(request.action_type, choice="none")

        if request.action_type == ActionType.WHITE_WOLF_EXPLODE:
            return ActionResponse(request.action_type, choice="pass")

        if request.candidates:
            return ActionResponse(request.action_type, target=request.candidates[0])

        return ActionResponse(request.action_type)
```

后续接 LangChain 时，只需要在 `act(request)` 里把 `request` 转成模型 prompt 或 tool input，再把模型输出解析成 `ActionResponse`。
