# Agent v2 Follow-up Review

本文档记录最新一轮 `agent/` review 结果，以及下一步设计改进建议。

当前版本相比上一轮已经修复了不少关键问题：

- `prompt_hints` 已经从 skill router 传到 prompt。
- skill router 已从 first-match 改成 score/priority 选择。
- `AgentMemoryV2` 增加了 public log 去重。
- review 已经能从 `roles` 字典获取玩家身份。
- policy 已经能处理 `poison/transfer/explode` 缺 target 的情况。
- 测试从 79 个增加到 89 个，并且全部通过。

测试结果：

```text
uv run python -m unittest discover -s tests -v
89 tests OK
```

但仍有几个设计缺口需要继续处理。

## 1. Choice 型动作仍需校验 target 是否在 candidates

### 问题

当前 policy 已经处理了以下情况：

```json
{"choice": "poison", "target": null}
{"choice": "transfer", "target": null}
{"choice": "explode", "target": null}
```

会 fallback。

但是仍然会放过非法 target：

```json
{"choice": "poison", "target": 99}
{"choice": "transfer", "target": 99}
{"choice": "explode", "target": 99}
```

原因是：

```python
_TARGET_ACTIONS = {
    ActionType.SHERIFF_VOTE,
    ActionType.GUARD_PROTECT,
    ActionType.WEREWOLF_KILL,
    ActionType.SEER_CHECK,
    ActionType.EXILE_VOTE,
    ActionType.PK_VOTE,
    ActionType.HUNTER_SHOOT,
}
```

这里没有包含：

- `WITCH_ACT`
- `SHERIFF_BADGE`
- `WHITE_WOLF_EXPLODE`

而 target candidates 校验只对 `_TARGET_ACTIONS` 生效。

### 影响

Agent v2 仍可能把非法 target 交给规则层，依赖规则层 retry/default。这不符合 v2 policy 的目标：

```text
Agent v2 自身保证最终 ActionResponse 合法。
```

### 设计建议

引入 per-action validator，不再只依赖 `_TARGET_ACTIONS`。

推荐结构：

```python
@dataclass(slots=True)
class ValidationResult:
    valid: bool
    repairable: bool = False
    reason: str = ""
```

每个 action 单独校验：

```python
def validate_witch_act(request, response) -> ValidationResult:
    if response.choice == "none":
        return ValidationResult(True)
    if response.choice == "save":
        if request.metadata.get("can_save", False):
            return ValidationResult(True)
        return ValidationResult(False, reason="save is not available")
    if response.choice == "poison":
        if not request.metadata.get("can_poison", False):
            return ValidationResult(False, reason="poison is not available")
        if response.target in request.candidates:
            return ValidationResult(True)
        return ValidationResult(False, repairable=True, reason="poison target invalid")
    return ValidationResult(False, reason="invalid witch choice")
```

对 `SHERIFF_BADGE`：

```python
def validate_sheriff_badge(request, response):
    if response.choice == "destroy":
        return ValidationResult(True)
    if response.choice == "transfer":
        return ValidationResult(response.target in request.candidates, repairable=True)
    return ValidationResult(False)
```

对白狼王：

规则层当前接受：

- `target in candidates`：自爆带人
- `target is None and choice in {"pass", None}`：不自爆

因此 policy 应按规则层实现，而不是引入 `choice="explode"` 作为必要字段。

建议：

```python
def validate_white_wolf_explode(request, response):
    if response.target in request.candidates:
        return ValidationResult(True)
    if response.target is None and response.choice in {"pass", None}:
        return ValidationResult(True)
    return ValidationResult(False, repairable=True)
```

### 需要补的测试

- `WITCH_ACT poison target=99` 应 fallback 或修正。
- `WITCH_ACT poison target in candidates` 应通过。
- `SHERIFF_BADGE transfer target=99` 应 fallback destroy 或修正。
- `SHERIFF_BADGE transfer target in candidates` 应通过。
- `WHITE_WOLF_EXPLODE target=99` 应 fallback pass。
- `WHITE_WOLF_EXPLODE target in candidates` 应通过。
- `WHITE_WOLF_EXPLODE choice=pass target=None` 应通过。

## 2. V2 Field Notes 尚未进入 Prompt

### 问题

`AgentMemoryV2` 已经生成：

```python
base_ctx["field_notes"] = self.field_notes.to_prompt_dict()
```

其中包含：

- `game_state`
- `player_profiles`
- `key_events`
- `vote_patterns`

但是 `agent/prompts.py` 当前没有把 `field_notes` 注入最终 Prompt。

当前 Prompt 中主要还是旧字段：

- `public_summary`
- `memory_events`
- `self_history`
- `suspicions`
- `claims_seen`

### 影响

虽然实现了 v2 结构化现场笔记，但 LLM 看不到这些内容。

也就是说：

```text
v2 memory 已经记录，但没有真正参与决策。
```

### 设计建议

在 `build_v2_request_prompt()` 中增加：

```python
f"结构化现场笔记: {memory_context.get('field_notes', {})}\n"
```

更推荐格式化输出，不要直接塞大 dict。

示例：

```text
结构化现场笔记:
- 当前状态: 第2天 day_speech，存活 [1,2,3,5,6,8,9,10]，死亡 [4,7]
- 玩家画像:
  - P2: 发言3次，投票给P7 2次，被P8怀疑
  - P7: 被投票2次，自称预言家
- 票型模式:
  - 第1天 P2/P3/P4 同票 P9
  - P8 连续投票给 P3
```

可以先用简化版本：

```python
def format_field_notes(field_notes: dict) -> str:
    ...
```

### 需要补的测试

- 使用 `AgentMemoryV2` 构造 field_notes。
- 调用 `prompt_node`。
- 断言 prompt 中包含：
  - `结构化现场笔记`
  - `vote_patterns`
  - `player_profiles`

## 3. Markdown Skill 尚未实现

### 当前状态

目前 skill 仍然全部是 Python 类：

```text
agent/skills/
  werewolf.py
  seer.py
  witch.py
  hunter.py
  villager.py
  guard.py
  white_wolf_king.py
```

每个 skill 已有：

- `name`
- `priority`
- `applicable_actions`
- `applies(ctx)`
- `score(ctx)`
- `decide(ctx)`
- `prompt_hints`

这比上一轮更好，但还没有实现用户期望的 Markdown skill。

### 为什么要做 Markdown Skill

Skill 本质上大部分是策略知识和 Prompt 内容，而不是复杂程序逻辑。

Markdown 形式更适合：

- 写角色打法。
- 写 Prompt hints。
- 写 few-shot。
- 做策略版本管理。
- 做长期记忆沉淀。
- 答辩展示。
- 快速调优，不频繁改 Python。

### 推荐设计

保留 Python router，但 skill 内容迁移到 Markdown。

目录：

```text
agent/
  skill_loader.py
  skills_md/
    witch/
      poison.md
    villager/
      vote_analysis.md
```

先只迁移两个 skill：

- `witch_poison`
- `villager_vote_analysis`

后续再逐步迁移全部。

### Markdown Skill 格式

使用 YAML front matter：

```markdown
---
name: witch_poison
role: witch
applicable_actions:
  - witch_act
priority: 50
requires:
  can_poison: true
output_constraints:
  choice: poison
  target_required: true
---

# 女巫毒药决策

## 目标

判断是否使用毒药以及毒杀目标。

## 策略原则

- 毒药只有一瓶，不能随便使用。
- 优先毒杀高狼面目标。
- 避免毒杀疑似预言家、女巫、猎人、守卫。
- 如果局势不明朗，可以选择不用毒。

## Prompt Hints

- 先列出最可疑的 2-3 个目标。
- 比较毒错风险。
- 如果最高嫌疑目标仍不够确定，选择不用毒。
- 输出 `choice="poison"` 时必须给出合法 `target`。

## Few-shot

```json
{
  "choice": "poison",
  "target": 7,
  "public_text": "",
  "private_reasoning": "7号连续跟随疑似狼队票型，并攻击预言家，狼面最高。",
  "confidence": 0.78,
  "alternatives": [2, 10],
  "rejected_reasons": ["2号证据不足", "10号偏划水但不构成强狼面"],
  "memory_refs": ["day1_vote", "day2_speech_7"],
  "selected_skill": "witch_poison"
}
```
```

### Loader 设计

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

加载：

```python
def load_markdown_skills(root: Path) -> list[MarkdownSkill]:
    ...
```

路由：

```python
def markdown_skill_applies(skill, ctx):
    ...

def markdown_skill_to_decision(skill, ctx):
    return SkillDecision(
        name=skill.name,
        goal=extract_goal(skill.body),
        prompt_hints=skill.prompt_hints,
        private_notes=[skill.body],
    )
```

### 依赖选择

可以用 `PyYAML` 解析 front matter，也可以先写轻量 parser。

考虑项目依赖简单，建议先写轻量 parser：

```python
def parse_front_matter(text: str) -> tuple[dict, str]:
    if not text.startswith("---"):
        return {}, text
    ...
```

front matter 初期只支持简单字段：

- string
- int
- bool
- list[string]
- nested dict one-level

这样可以避免新增依赖。

## 4. Review 输入 schema 仍偏窄

### 当前状态

`_did_survive()` 当前支持：

- `{"entries": [...]}`
- 带 `.entries` 属性的对象

但不支持：

- `list[dict]`
- 直接从 jsonl 读出的 event list
- UI backend 的 `events`

### 建议

增加统一 normalization：

```python
def _log_entries(game_log) -> list[dict]:
    if isinstance(game_log, list):
        return game_log
    if isinstance(game_log, dict):
        if "entries" in game_log:
            return game_log["entries"]
        if "events" in game_log:
            return game_log["events"]
    if hasattr(game_log, "entries"):
        return [entry.to_dict() if hasattr(entry, "to_dict") else entry for entry in game_log.entries]
    return []
```

然后 `_did_survive()` 使用 `_log_entries()`。

### 需要补的测试

- `game_log` 是 list[dict]。
- `game_log` 是 `{"events": [...]}`。
- `game_log` 是 `{"entries": [...]}`。

## 5. pytest 依赖暂时没有用途

### 当前状态

`pyproject.toml` 新增：

```toml
[dependency-groups]
dev = [
    "pytest>=9.0.3",
]
```

但当前测试仍然全部通过：

```bash
uv run python -m unittest discover -s tests -v
```

没有 pytest 测试或 pytest 配置。

### 建议

如果短期不打算迁移 pytest，建议移除 pytest 依赖，减少无意义的 lockfile 变更。

如果打算使用 pytest，则补充：

- `pytest.ini`
- 或 `pyproject.toml` 中 `[tool.pytest.ini_options]`
- 明确测试命令

例如：

```toml
[tool.pytest.ini_options]
testpaths = ["tests"]
python_files = ["test_*.py"]
```

但考虑当前项目已经稳定使用 unittest，暂时不建议引入 pytest。

## 6. 下一步推荐任务

建议优先级如下。

### P0：补 policy 合法性

目标：

- choice 型动作也校验 target 是否在 candidates。
- 与规则层白狼王自爆逻辑保持一致。

任务：

- 引入 per-action validator。
- 补单元测试。

### P1：让 v2 memory 真正参与决策

目标：

- `field_notes` 注入 prompt。
- 格式化输出结构化现场笔记。

任务：

- `format_field_notes()`
- 修改 `build_v2_request_prompt()`
- 补测试。

### P2：最小 Markdown Skill 闭环

目标：

- 支持 Markdown skill 文件。
- 先迁移 2 个 skill。

任务：

- 新建 `skill_loader.py`
- 新建 `skills_md/witch/poison.md`
- 新建 `skills_md/villager/vote_analysis.md`
- router 支持 Markdown skill 优先或合并。
- 补 loader 测试。

### P3：增强 review 输入兼容

目标：

- review 能处理 list/dict/object 多种日志输入。

任务：

- `_log_entries()` normalization。
- 更新 `_did_survive()`。
- 补测试。

### P4：清理依赖

目标：

- 移除暂时无用的 pytest，或正式配置 pytest。

建议：

- 当前先移除 pytest。

## 7. 当前状态总结

当前 Agent v2 已经具备：

- 图式 runtime。
- v2 memory。
- v2 belief。
- skill score routing。
- v2 prompt schema。
- policy adjustments。
- decision log 扩展字段。
- 初步 review。

剩余最关键问题：

- policy 对 choice 型 target 校验仍不完整。
- v2 field notes 没进 prompt。
- Markdown skill 尚未实现。
- review 日志输入兼容性还不够。
- pytest 依赖是噪声。

下一轮如果修完 P0-P2，Agent v2 就会从“结构完整”进入“策略可调优、可展示”的阶段。

