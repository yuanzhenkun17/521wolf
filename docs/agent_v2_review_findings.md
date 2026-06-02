# Agent v2 Review Findings

本文档记录当前 `agent/` 实现的代码 review 结果，以及下一轮改造建议。

当前版本已经比初版 v2 明显前进：

- 有 v2 memory。
- 有 v2 belief。
- 有 skill registry。
- 有 v2 prompt schema。
- 有 policy adjustment。
- 有扩展后的 decision log 字段。
- 有 post-game review 模块雏形。

但当前仍存在几个会影响真实效果和答辩展示的问题，需要优先修复。

## 1. 复盘评分目前基本不可用

问题位置：

- `agent/review.py`
- `_get_role_of()`
- `_did_survive()`

当前问题：

```python
def _did_survive(player_id: int, game_log: dict) -> bool:
    return True


def _get_role_of(player_id: int, game_log: dict) -> Role | None:
    return None
```

这会导致：

- 投票准确率无法真实计算。
- 技能准确率无法真实计算。
- 女巫毒错无法识别。
- 猎人开错枪无法识别。
- 高光决策无法识别。
- 玩家是否存活无法判断。

影响：

当前 review 模块只能生成表面报告，不能作为“评测 + 复盘”的有效证据。

建议：

明确 `game_log` 输入 schema，优先支持以下两种来源：

1. `roles: dict[int, Role]`
2. engine logger 的 `game_init` 事件 payload

`_get_role_of()` 应优先从 `roles` 参数查角色，不要从不稳定日志中猜。

建议改成：

```python
def _get_role_of(player_id: int, roles: dict[int, Role]) -> Role | None:
    return roles.get(player_id)
```

`_did_survive()` 应从死亡事件或最终玩家快照判断。

## 2. Policy 仍不能保证所有动作合法

问题位置：

- `agent/nodes/policy.py`

当前 `_TARGET_ACTIONS` 不包含一些由 `choice` 决定是否需要 target 的动作：

- `WITCH_ACT`
- `SHERIFF_BADGE`
- `WHITE_WOLF_EXPLODE`

导致以下非法响应可能通过 policy：

```json
{"choice": "poison", "target": null}
```

女巫毒人必须有目标。

```json
{"choice": "transfer", "target": null}
```

警徽移交必须有目标。

```json
{"choice": "explode", "target": null}
```

白狼王自爆带人必须有目标。并且现有规则文档更偏向：

- 不自爆：`choice="pass"`
- 自爆：给 `target`

不一定需要 `choice="explode"`。

影响：

Agent v2 仍可能把非法动作交给规则层，依赖规则层 retry/default。这样不符合 v2 “自身保证合法 ActionResponse”的目标。

建议：

为每个 `ActionType` 单独定义 validator。

示例：

```python
def validate_witch_act(request, response):
    if response.choice == "poison":
        return response.target in request.candidates
    if response.choice == "save":
        return request.metadata.get("can_save", False)
    if response.choice == "none":
        return True
    return False
```

需要补充测试：

- `WITCH_ACT poison` 无 target 时修正为合法动作。
- `SHERIFF_BADGE transfer` 无 target 时补合法 target 或 fallback destroy。
- `WHITE_WOLF_EXPLODE` 无 target 时 fallback pass。

## 3. Skill 路由存在顺序遮蔽

问题位置：

- `skills/__init__.py`
- `skills/werewolf.py`
- `skills/witch.py`
- `skills/seer.py`

当前 `route_skill()` 逻辑是：

```python
for skill in skills_for(role):
    if action_type in skill.applicable_actions and skill.applies(ctx):
        return skill.decide(ctx)
```

即选第一个匹配的 skill。

但多个 skill 的 `applies()` 恒为 `True`，导致后面的专用 skill 很难被选中。

例子：

- 狼人：
  - `DeepWolfSkill` 对 `SPEAK` 恒 True。
  - `VoteRushSkill` 对 `WEREWOLF_KILL` 恒 True。
  - `FindGodSkill` 排在后面，基本不会被选到。

- 女巫：
  - `SaveDecisionSkill` 在 `can_save=True` 且有被刀目标时总是优先。
  - 即使同时可以毒人，也不会进入 `PoisonDecisionSkill`。

- 预言家：
  - `BadgeFlowSkill.applies()` 恒 True。
  - 会遮蔽后面的 `CounterClaimSkill`。

影响：

表面上有多个 skill，实际运行可能总是固定几个 skill，达不到“局势 skill 路由”的目标。

建议：

把 skill 路由从“第一个匹配”改成“评分选择”。

每个 skill 增加：

```python
def score(self, ctx: AgentContext) -> float:
    ...
```

路由逻辑：

```python
candidates = []
for skill in skills_for(role):
    if action_type in skill.applicable_actions and skill.applies(ctx):
        candidates.append((skill.score(ctx), skill))

best = max(candidates, key=lambda item: item[0])
```

或者更简单：

- 专用 skill 的 `applies()` 写得更严格。
- 通用 skill 放在最后。
- 通用 skill 只在没有特殊局势时触发。

推荐优先采用评分式，因为后续可解释性更好。

## 4. Skill 的 prompt_hints 没有进入 Prompt

问题位置：

- `agent/nodes/skill_router.py`
- `agent/nodes/prompt.py`
- `agent/prompts.py`

当前流程：

1. `skill_router_node` 把 `prompt_hints` 放入 `ctx.strategy_advice`。
2. `prompt_node` 又把 `ctx.strategy_advice` 转成旧的 `StrategyAdvice`。
3. 旧的 `StrategyAdvice` 没有 `prompt_hints` 字段。
4. `build_v2_request_prompt()` 再从 `advice` 里读 `prompt_hints`，但已经丢失。

结果：

各 skill 最关键的专属提示没有进入最终 Prompt。

影响：

skill 虽然被选中了，但 LLM 不知道这个 skill 的具体打法。日志中能看到 skill 名称，实际 prompt 中却缺少技能提示。

建议：

不要把 v2 skill advice 强行塞回 v1 `StrategyAdvice`。

方案一：新增 `SkillPromptAdvice`。

```python
@dataclass
class SkillPromptAdvice:
    goal: str
    preferred_targets: list[int]
    avoid_targets: list[int]
    public_stance: str
    private_notes: list[str]
    prompt_hints: list[str]
```

方案二：`build_v2_messages()` 直接接收 `ctx.strategy_advice` dict。

推荐方案二，改动更小。

## 5. V2 Memory 会重复处理 public_log

问题位置：

- `agent/memory_v2.py`

当前 `_update_field_notes()` 每次都会遍历完整 `obs.public_log`：

```python
for item in obs.public_log:
    self._parse_public_item(str(item), obs.day, request.phase.value)
```

但没有记录已处理条目。

影响：

同一条公开日志会被重复记录：

- 重复发言
- 重复投票
- 重复 vote pattern
- 虚假的连续投票
- 虚假的同票模式

这会污染：

- `field_notes`
- vote patterns
- belief
- prompt

建议：

像 v1 `AgentMemory` 一样添加：

```python
self._seen_public_entries: set[str]
```

只处理新日志：

```python
for item in obs.public_log:
    if item in self._seen_public_entries:
        continue
    self._seen_public_entries.add(item)
    self._parse_public_item(...)
```

## 6. 测试没有覆盖新增核心能力

问题位置：

- `tests/test_agent_v2.py`

当前测试仍有大量节点测试使用 v1：

```python
self.memory = AgentMemory(...)
self.belief = BeliefState(...)
```

这不能覆盖默认 runtime 中使用的：

- `AgentMemoryV2`
- `BeliefStateV2`
- v2 skill registry
- v2 prompt schema
- v2 review

缺少测试：

- `prompt_hints` 是否进入 prompt。
- `poison` 无 target 是否被 policy 修正。
- `transfer` 无 target 是否被 policy 修正。
- `white_wolf_explode` 无 target 是否 fallback pass。
- skill router 是否能选到：
  - `witch_poison`
  - `seer_counter_claim`
  - `werewolf_find_god`
  - `villager_vote_analysis`
- memory 是否不会重复处理 public log。
- review 是否能识别毒错、枪错、投票准确率。

建议：

新增独立测试文件：

```text
tests/test_agent_v2_policy.py
tests/test_agent_v2_skills.py
tests/test_agent_v2_memory.py
tests/test_agent_v2_review.py
```

## 7. 建议优先修复顺序

### P0：修 correctness

1. 修复 policy 合法性。
2. 修复 prompt_hints 丢失。
3. 修复 memory 重复处理 public_log。

### P1：修 skill 路由有效性

1. 增加 skill score。
2. 或者让通用 skill 后置，专用 skill 的 applies 更严格。
3. 给关键 skill 补测试。

### P2：修复盘可用性

1. 明确 review 输入 schema。
2. 使用 `roles` 判断目标身份。
3. 使用死亡事件判断存活。
4. 补投票/技能评分测试。

### P3：增强展示价值

1. review 输出 Markdown 报告。
2. 前端展示 selected_skill、confidence、policy_adjustments。
3. 加多版本对比。

## 8. 关于 Skill 改成 Markdown 形式

你希望 skill 采用 Markdown 形式，这个方向是合理的，甚至比把 skill 全写死在 Python 类里更适合本项目。

原因：

- Skill 本质是策略知识，不完全是程序逻辑。
- Markdown 更适合写角色打法、触发条件、Prompt 提示、few-shot。
- 后续调 Prompt 不需要频繁改 Python。
- 答辩时更容易展示“策略库”。
- 可以作为长期记忆 / 经验卡片的载体。

## 9. 推荐的 Markdown Skill 设计

建议把 skill 拆成两层：

1. Python 负责读取、路由、校验和注入 Prompt。
2. Markdown 负责描述策略内容。

推荐目录：

```text
agent/
  skill_loader.py
  skills_md/
    werewolf/
      fake_seer.md
      deep_wolf.md
      vote_rush.md
      find_god.md
    seer/
      claim.md
      badge_flow.md
      check_priority.md
      counter_claim.md
    witch/
      save.md
      poison.md
      hide_identity.md
    hunter/
      shoot.md
      hide_identity.md
      threat.md
    villager/
      speech_analysis.md
      vote_analysis.md
      seer_side.md
      wolf_pit.md
```

## 10. Markdown Skill 文件格式

推荐使用 Markdown + YAML front matter。

示例：`skills_md/witch/poison.md`

```markdown
---
name: witch_poison
role: witch
applicable_actions:
  - witch_act
priority: 80
requires:
  can_poison: true
output_constraints:
  choice: poison
  target_required: true
---

# 女巫毒药决策

## 目标

判断是否使用毒药，以及毒杀哪个玩家。

## 适用局势

- 毒药仍可用。
- 当前存在高狼面目标。
- 好人阵营需要通过毒药追回轮次。

## 策略原则

- 毒药只有一瓶，不能随便使用。
- 优先毒杀高狼面且有带队能力的玩家。
- 避免毒杀疑似预言家、女巫、猎人、守卫。
- 如果局势不明朗，可以选择不用毒。

## 判断线索

- 目标是否连续攻击真预言家。
- 目标是否与疑似狼队票型高度一致。
- 目标是否发言视角异常。
- 目标是否可能是被狼人抗推的好人。

## Prompt Hints

- 先列出最可疑的 2-3 个目标。
- 比较毒错风险。
- 如果最高嫌疑目标仍不够确定，选择不用毒。
- 输出 `choice="poison"` 时必须给出合法 `target`。

## Few-shot

### 示例 1

输入局势：

- 7 号连续两天跟随 2 号投票。
- 7 号攻击预言家但没有解释查验逻辑。
- 毒药仍可用。

推荐输出：

```json
{
  "choice": "poison",
  "target": 7,
  "public_text": "",
  "private_reasoning": "7号连续跟随疑似狼队票型，并攻击预言家，狼面最高。",
  "confidence": 0.78,
  "alternatives": [2, 10],
  "rejected_reasons": ["2号更像带队位但证据不足", "10号偏划水但不构成强狼面"],
  "memory_refs": ["day1_vote", "day2_speech_7"],
  "selected_skill": "witch_poison"
}
```
```

## 11. Markdown Skill Loader 设计

Python 中只保留轻量 loader 和 router。

数据结构：

```python
@dataclass(slots=True)
class MarkdownSkill:
    name: str
    role: Role
    applicable_actions: set[ActionType]
    priority: int
    requires: dict
    output_constraints: dict
    body: str
    prompt_hints: list[str]
```

加载流程：

```python
def load_markdown_skills(root: Path) -> list[MarkdownSkill]:
    ...
```

路由流程：

```python
def route_skill(ctx, role):
    candidates = [
        skill for skill in skills
        if skill.role == role
        and ctx.request.action_type in skill.applicable_actions
        and requirements_match(skill.requires, ctx)
    ]
    return max(candidates, key=lambda s: s.priority)
```

这样可以用 front matter 控制：

- name
- role
- applicable_actions
- priority
- requires
- output_constraints

用正文控制：

- 策略说明
- Prompt hints
- few-shot
- 注意事项

## 12. Markdown Skill 的好处

### 12.1 Prompt 调优更快

调策略时只改 `.md`，不改 Python。

### 12.2 更适合答辩展示

可以直接展示：

```text
狼人 fake_seer.md
女巫 poison.md
村民 vote_analysis.md
```

评委能直观看到你有策略库，而不是只有代码。

### 12.3 方便长期记忆融合

后续中期/长期记忆可以沉淀成新的 Markdown skill 或 patch 到已有 skill。

例如：

```text
根据 5 局经验，更新 werewolf/fake_seer.md：
- 发言位置靠后时不建议悍跳。
- 没有队友铺垫时不要给真预言家查杀。
```

### 12.4 方便多版本对比

可以维护：

```text
skills_md_v1/
skills_md_v2/
skills_md_v3/
```

然后跑多局对比，做 Leaderboard。

## 13. Markdown Skill 改造建议

不要一次性删除 Python skill。

推荐渐进式改造：

### 阶段 1：保留 Python router，skill 内容迁到 Markdown

Python skill 只负责：

- applies
- priority
- output constraints

Markdown 负责：

- goal
- prompt_hints
- few-shot
- public_stance
- private_notes

### 阶段 2：实现通用 MarkdownSkill

用 front matter 替代大部分 Python skill 类。

### 阶段 3：支持 skill version

支持：

```text
skills_md/v1/
skills_md/v2/
```

用于对比 Agent 版本。

### 阶段 4：结合长期记忆

赛后复盘生成经验卡片，再人工或半自动写回 skill markdown。

## 14. 下一轮推荐任务

建议下一轮按这个顺序做：

1. 修复 policy 合法性问题。
2. 修复 prompt_hints 丢失。
3. 修复 memory 重复处理 public_log。
4. 给 skill router 加 priority/score。
5. 新建 Markdown skill 格式，并先迁移 2 个 skill：
   - `witch/poison.md`
   - `villager/vote_analysis.md`
6. 给 Markdown skill loader 加测试。
7. 修复 review 的 `_get_role_of()` 和 `_did_survive()`。

## 15. 总结

当前 Agent v2 已经具备比较完整的外形，但仍需要修几个核心问题才能真正可用：

- policy 必须能保证合法动作。
- skill 必须真的影响 prompt。
- skill 路由不能被注册顺序遮蔽。
- memory 不能重复计数。
- review 必须能基于真实角色和死亡信息评分。

此外，skill 改成 Markdown 是一个很好的方向。建议把 Markdown skill 作为“策略库”，Python 只做加载、路由、校验和注入 Prompt。这样既便于快速调优，也更贴合课题评分中的 Prompt 工程、策略差异和可观测性要求。

