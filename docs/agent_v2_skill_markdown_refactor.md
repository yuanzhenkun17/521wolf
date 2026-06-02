# Agent v2 Skill Markdown 重构设计

本文档记录最新 review 发现的问题，以及下一步 skill 系统重构要求。

## 1. 当前 Review 结论

当前版本已经实现了：

- per-action policy validator。
- `field_notes` prompt block。
- Markdown skill loader 雏形。
- review log normalization。
- 更完整的测试覆盖。

但仍有几个问题：

1. Markdown skill 没有真正注册进运行时。
2. `field_notes` 格式化字段和 `AgentMemoryV2` 输出不匹配。
3. Markdown skill 正文和 few-shot 没有充分进入 Prompt。
4. `skills/` Python skill 目录和 `skills_md/` Markdown skill 目录并存，结构变复杂。
5. skill priority 机制没有必要，反而增加理解成本。

## 2. 新的约束要求

后续按以下要求重构：

1. 删除当前 Python skill 目录：

```text
skills/
```

2. 将当前 Markdown skill 目录改名：

```text
skills_md/
```

改为：

```text
skills/
```

3. skill 全部使用 Markdown 表达。

4. 游戏规则作为一个通用 skill，所有角色都必须注入。

5. 角色 skill 只按当前角色注入。

6. 去掉 skill priority，不再做复杂优先级路由。

## 3. 目标目录结构

重构后目录建议如下：

```text
agent/
  skill_loader.py
  skill_router.py
  skills/
    common/
      game_rules.md
      output_schema.md
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
    guard/
      protect.md
    white_wolf_king/
      explode.md
      hide.md
```

说明：

- `common/` 是所有 Agent 都会注入的通用 skill。
- 每个角色目录只给对应角色注入。
- 不再保留 Python skill 类。
- Python 只负责读取 Markdown、选择当前需要注入哪些 Markdown。

## 4. 通用游戏规则 Skill

需要新增：

```text
skills/common/game_rules.md
```

这个 skill 所有角色都必须注入。

建议内容包括：

```markdown
---
name: game_rules
scope: common
---

# 狼人杀游戏规则

## 基本目标

- 狼人阵营：隐藏身份，夜晚击杀好人，白天推动好人出局。
- 好人阵营：通过发言、投票、技能信息找出狼人。

## 信息隔离

- 只能根据自己可见信息决策。
- 不得假设上帝视角。
- 不得在公开发言中泄露无法公开解释的私有信息。

## 行动输出

- 必须输出合法 JSON。
- `target` 必须来自 candidates，除非该行动允许弃权或不需要目标。
- 公开发言只能写在 `public_text`。
- 私有推理只能写在 `private_reasoning`。

## 白天流程

- 顺序发言。
- 投票放逐。
- 平票进入 PK。

## 夜晚流程

- 守卫守护。
- 狼人刀人。
- 预言家查验。
- 女巫用药。

## 胜负条件

- 所有狼人死亡，好人胜利。
- 狼人屠民、屠神或人数达到优势，狼人胜利。
```

也可以新增：

```text
skills/common/output_schema.md
```

专门维护输出格式。

## 5. 角色 Skill 注入规则

每次 Agent 决策时注入：

```text
common skills + 当前角色 skills + 当前 action 相关 skills
```

不要注入其他角色的 skill。

例如：

### 女巫行动

注入：

```text
common/game_rules.md
common/output_schema.md
witch/save.md
witch/poison.md
witch/hide_identity.md
```

不注入：

```text
werewolf/fake_seer.md
seer/claim.md
hunter/shoot.md
```

### 村民投票

注入：

```text
common/game_rules.md
common/output_schema.md
villager/vote_analysis.md
villager/wolf_pit.md
villager/seer_side.md
```

不注入女巫、狼人、预言家 skill。

## 6. 不再使用 Priority

之前 skill 使用：

```yaml
priority: 50
```

这个机制现在不建议保留。

原因：

- 当前 skill 数量不多，优先级没有必要。
- 优先级会让策略选择变成隐式规则，答辩时不好解释。
- Markdown skill 更适合“注入相关策略”，而不是只选一个。
- 狼人杀决策经常需要综合多个策略，例如女巫既要考虑救人，也要考虑毒人。

因此改为：

```text
根据 role + action_type 过滤多个相关 skill，一起注入 prompt。
```

不是：

```text
选一个最高优先级 skill。
```

## 7. Markdown Skill Front Matter

推荐简化 front matter。

去掉：

```yaml
priority
```

保留：

```yaml
---
name: witch_poison
scope: role
role: witch
applicable_actions:
  - witch_act
requires:
  can_poison: true
output_constraints:
  choice: poison
  target_required: true
---
```

字段说明：

- `name`：skill 名称。
- `scope`：`common` 或 `role`。
- `role`：角色 skill 必填，common skill 可省略。
- `applicable_actions`：适用动作。
- `requires`：可选，根据 request metadata 判断是否注入。
- `output_constraints`：可选，用于提示和 policy 对齐。

## 8. Skill Loader 设计

`skill_loader.py` 负责：

1. 读取 `skills/**/*.md`。
2. 解析 front matter。
3. 返回 `MarkdownSkill` 对象。

建议数据结构：

```python
@dataclass(slots=True)
class MarkdownSkill:
    name: str
    scope: str
    role: Role | None
    applicable_actions: set[ActionType]
    requires: dict
    output_constraints: dict
    body: str
    prompt_hints: list[str]
```

不再包含：

```python
priority
```

## 9. Skill Router 设计

`skill_router.py` 负责选择要注入的 Markdown skill。

推荐接口：

```python
def select_skills(ctx: AgentContext, role: Role) -> list[MarkdownSkill]:
    ...
```

逻辑：

```python
selected = []

# 1. always inject common skills
selected.extend(common_skills)

# 2. inject role skills matching current role
for skill in role_skills[role]:
    if ctx.request.action_type in skill.applicable_actions:
        if requirements_match(skill.requires, ctx):
            selected.append(skill)

return selected
```

`requirements_match()` 示例：

```python
def requirements_match(requires: dict, ctx: AgentContext) -> bool:
    for key, expected in requires.items():
        if ctx.request.metadata.get(key) != expected:
            return False
    return True
```

如果一个角色 skill 没有 `applicable_actions`，可以默认所有动作都适用，但不建议这样做，容易 prompt 过长。

## 10. Prompt 注入设计

`prompt_node` 不再处理一个 `selected_skill`，而是处理多个 skill。

`AgentContext` 建议从：

```python
selected_skill: str | None
strategy_advice: dict
```

调整为：

```python
selected_skills: list[str]
skill_context: str
```

或者保留兼容字段：

```python
selected_skill = ",".join(selected_skills)
```

Prompt 中注入：

```text
已注入策略 Skill：
- game_rules
- output_schema
- witch_poison
- witch_hide_identity

Skill 内容：
...
```

建议格式：

```text
## 通用规则 Skill

{common/game_rules.md}

## 角色策略 Skill

### witch_poison

{witch/poison.md}
```

注意：

- common skill 永远放前面。
- role skill 放后面。
- 当前 action 强相关的 skill 放在角色 skill 中靠前。

## 11. 输出日志设计

DecisionRecord 当前有：

```python
selected_skill: str
```

后续建议扩展为：

```python
selected_skills: list[str]
```

为了兼容旧字段，可以临时这样做：

```python
selected_skill=",".join(selected_skills)
```

日志中应记录：

- 注入了哪些 common skill。
- 注入了哪些 role skill。
- 每个 skill 的文件路径。

示例：

```json
{
  "selected_skills": [
    "game_rules",
    "output_schema",
    "witch_poison",
    "witch_hide_identity"
  ],
  "skill_files": [
    "skills/common/game_rules.md",
    "skills/common/output_schema.md",
    "skills/witch/poison.md",
    "skills/witch/hide_identity.md"
  ]
}
```

## 12. 删除 Python skills 目录的步骤

建议分步骤做，避免一次性破坏运行。

### Step 1：新增 Markdown 目录

```text
skills_new/
```

先放 Markdown skill。

### Step 2：修改 loader 和 router

让 runtime 读取 Markdown skill。

### Step 3：测试通过后重命名

```text
删除 skills/
将 skills_new/ 改为 skills/
```

### Step 4：清理 import

删除所有：

```python
from agent.skills import ...
```

改成：

```python
from agent.skill_loader import ...
from agent.skill_router import ...
```

### Step 5：更新测试

测试不再检查 Python skill class。

改为检查：

- Markdown 文件存在。
- common skill 必定注入。
- 当前角色 skill 注入。
- 非当前角色 skill 不注入。
- priority 字段不存在也能加载。

## 13. 测试要求

需要新增或修改以下测试。

### 13.1 Common skill 注入

```python
def test_common_game_rules_injected_for_all_roles():
    ...
```

断言：

- 狼人 prompt 包含 `game_rules`
- 女巫 prompt 包含 `game_rules`
- 村民 prompt 包含 `game_rules`

### 13.2 角色隔离

```python
def test_only_current_role_skills_are_injected():
    ...
```

例如女巫 prompt：

应包含：

- `witch_poison`
- `witch_hide_identity`

不应包含：

- `werewolf_fake_seer`
- `seer_claim`
- `hunter_shoot`

### 13.3 无 priority

```python
def test_markdown_skill_does_not_require_priority():
    ...
```

### 13.4 多 skill 注入

```python
def test_multiple_matching_role_skills_are_injected():
    ...
```

例如女巫 `WITCH_ACT` 同时注入：

- `witch_save`
- `witch_poison`

如果 metadata 满足二者。

### 13.5 游戏规则 skill 必定存在

```python
def test_game_rules_skill_exists():
    ...
```

## 14. Field Notes 修复

当前 review 发现：

`AgentMemoryV2.PlayerProfile.to_dict()` 输出：

```python
votes_cast
votes_received
attacked
defended
followed
```

但 `format_field_notes()` 读取：

```python
votes
relations
```

这两个 schema 不一致。

应改为读取真实字段：

```python
for vote in info.get("votes_cast", []):
    ...

received = info.get("votes_received", [])
attacked = info.get("attacked", [])
defended = info.get("defended", [])
followed = info.get("followed", [])
```

并新增测试：

```python
def test_format_field_notes_matches_memory_v2_schema():
    ...
```

## 15. Policy 状态

当前 policy 已经切换到 per-action validator，这是正确方向。

但仍建议保持测试覆盖：

- 女巫 poison target 不合法。
- 警徽 transfer target 不合法。
- 白狼王自爆 target 不合法。
- 白狼王 pass 合法。

这部分已经基本完成。

## 16. 迁移后目标状态

最终希望变成：

```text
规则层:
  ActionRequest -> ActionResponse

Agent v2:
  observe
  memory
  belief
  markdown skill selection
  prompt
  llm
  parse
  policy
  log

skills:
  全部 Markdown
  common skill 所有角色注入
  role skill 按角色注入
  不使用 priority
```

这样更符合项目定位：

- Agent 策略可以用 Markdown 展示。
- Prompt 工程可被直接评审。
- 角色差异清晰。
- 后续长期记忆可以沉淀到 Markdown。
- 不需要维护 Python skill 类和 priority 路由。

## 17. 下一步推荐任务

按顺序做：

1. 修复 Markdown skill 路径错误。
2. 删除 Python `skills/` 目录。
3. 将 `skills_md` 改名为 `skills`。
4. 新增 `common/game_rules.md`。
5. 新增 `common/output_schema.md`。
6. 重写 skill loader/router：
   - common skill 永远注入。
   - role skill 按角色和 action 注入。
   - 不使用 priority。
7. 修改 `AgentContext`：
   - 支持 `selected_skills: list[str]`
   - 支持 `skill_context: str`
8. 修改 prompt。
9. 修改 decision log。
10. 补测试。
11. 修复 `format_field_notes()` schema 不一致问题。

