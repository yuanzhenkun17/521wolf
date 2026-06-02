# 规则层说明

本文说明当前 `engine/werewolf/` 目录的职责。旧 `engine/werewolf/agent_runtime/`、`engine/werewolf/llm_agents.py` 和 `engine/werewolf/demo_llm.py` 已删除，规则层不再保留 Agent 兼容转发代码。

## 边界

规则层是狼人杀裁判，只负责：

- 初始化玩家、身份和状态。
- 推进黑夜、警长竞选、白天发言、放逐投票。
- 校验玩家动作是否合法。
- 结算狼人、预言家、女巫、猎人、守卫、白狼王等角色规则。
- 处理死亡、遗言、警徽、胜负判断。
- 产出结构化日志。

规则层不负责 LLM prompt、记忆、belief、ToT 或复盘分析。

## 目录结构

```text
engine/werewolf/
  __init__.py
  actions.py
  config.py
  engine.py
  logging.py
  models.py
  players.py
  public_log.py
  roles.py
  phases/
  role_rules/
  rules/
```

## 对外协议

规则层只依赖玩家对象实现：

```python
class PlayerAgent(Protocol):
    async def act(self, request: ActionRequest) -> ActionResponse:
        ...
```

因此规则层可以接入 LLM Agent、脚本 Agent 或未来的人类玩家 Agent。

核心数据结构在 `models.py`：

- `Observation`：玩家可见信息，负责信息隔离。
- `ActionRequest`：规则层发给玩家的动作请求。
- `ActionResponse`：玩家返回给规则层的动作结果。
- `GameState`：整局游戏状态。

## 主流程

一局游戏从 `GameEngine.run_until_finished()` 开始：

```text
初始化
  -> 第一夜行动
  -> 警长竞选
  -> 公布第一夜死亡
  -> 白天发言
  -> 放逐投票
  -> 循环黑夜/白天
  -> 胜负判定
```

阶段逻辑拆在：

- `phases/night.py`
- `phases/sheriff.py`
- `phases/day.py`
- `phases/exile.py`

角色技能拆在：

- `role_rules/werewolf.py`
- `role_rules/white_wolf_king.py`
- `role_rules/seer.py`
- `role_rules/witch.py`
- `role_rules/hunter.py`
- `role_rules/guard.py`
- `role_rules/villager.py`

通用规则拆在：

- `rules/death.py`
- `rules/sheriff.py`
- `rules/victory.py`
- `rules/voting.py`

## 信息隔离

规则层生成每个玩家自己的 `Observation`。

示例：

- 狼人能看到狼队友。
- 预言家能看到自己的查验记录。
- 村民看不到夜间行动和私有身份。

Agent 层只能读取 `ActionRequest`，不能直接读取完整 `GameState`。

## 日志

规则层输出完整对局日志：

```text
logs/gameX/events.jsonl
```

UI 读取这些日志还原：

- 当前天数和阶段。
- 存活/出局玩家。
- 夜间行动结果。
- 白天发言。
- 投票票型。
- 放逐结果。
- 胜负结果。

Agent 决策日志由 `agent/` 侧写出。

## 扩展建议

新增人数配置时，优先新增 `GameConfig`。

新增角色时，优先：

1. 在 `models.Role` 中加角色。
2. 如有必要，在 `models.ActionType` 中加动作。
3. 在 `role_rules/` 中新增角色规则。
4. 在 `role_rules/registry.py` 注册。
5. 把跨角色逻辑放到 `rules/`。
6. 补测试覆盖技能、死亡、投票和胜负边界。
