# Spec #1: 游戏引擎 + Agent 决策系统（现状分析 + 改动方案）

> 方法：先精确描述现有实现，再逐项列出要改什么、改成什么样。
> 不做理想化设计，只做增量改进。

---

## 1. 游戏引擎

### 1.1 现状

**GameState** (`engine/models.py:157-173`) 是一个 14 字段的 dataclass：

```python
@dataclass
class GameState:
    players: dict[int, PlayerState]
    day: int = 0
    phase: Phase = Phase.SETUP
    events: list[GameEvent]
    public_log: list[str]           # 字符串列表，非结构化
    deaths: list[DeathRecord]
    sheriff_id: int | None
    badge_destroyed: bool = False
    witch_antidote_available: bool = True    # ← 角色特定状态
    witch_poison_available: bool = True      # ← 角色特定状态
    guard_last_target: int | None            # ← 角色特定状态
    seer_checks: dict[int, dict[int, Team]] # ← 角色特定状态
    pending_last_words: list[int]
    pending_hunter_shots: list[int]
    winner: Winner | None
```

**问题**：`witch_antidote_available`、`witch_poison_available`、`guard_last_target`、`seer_checks` 是角色特定状态，混在通用 GameState 里。新增角色就要往这个 struct 里塞字段。

**GameEvent** (`engine/models.py:100-119`) 有 `public: bool` 字段区分公开/私有，但没有细粒度的可见性控制。

**Observation** (`engine/models.py:122-134`) 的 `public_log: tuple[str, ...]` 是字符串列表，不是结构化事件。

**夜间行动解析** (`engine/phases/night.py:62-71`) 是硬编码 if/elif 链：

```python
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
```

**ask()** (`engine/actions.py:14-100`) 重试 2 次，无效响应循环重试，2 次失败后用 default。**没有 try/except**——agent 异常会直接中断对局。

**RoleRule registry** (`engine/role_rules/registry.py`) 是模块级单例 dict，规则实例无状态，所有状态通过 `engine` 参数读写。

### 1.2 改动方案

| 改动 | 现状 | 目标 | 优先级 |
|------|------|------|--------|
| **GameState 拆分角色状态** | 4 个角色字段混在 GameState | 新增 `GameEngine.role_state: dict[Role, dict]`，角色规则通过 `engine.role_state[Role.WITCH]` 读写 | P2 |
| **GameEvent 加 visibility** | 只有 `public: bool` | 新增 `visibility: Visibility` enum（PUBLIC/WEREWOLF/WITCH/SEER/GUARD/SYSTEM），替代 `public` 字段 | P1 |
| **Observation 用结构化事件** | `public_log: tuple[str, ...]` | 改为 `visible_events: tuple[GameEvent, ...]`，引擎通过 `filter_events()` 按 visibility 过滤 | P1 |
| **ask() 捕获 agent 异常** | 无 try/except，异常中断对局 | 加 try/except，异常时用规则默认行为（狼人→随机杀非狼人，预言家→不查验，其他→跳过），记录 llm_error_count | P1 |
| **夜间解析简化** | 硬编码 if/elif | 保持现状（7 个角色够用，不需要为扩展性过度设计） | 不改 |

**GameState 拆分详情**：

```python
# 现在
state.witch_antidote_available = True
state.guard_last_target = None

# 改后
engine.role_state = {
    Role.WITCH: {"antidote_available": True, "poison_available": True},
    Role.GUARD: {"last_target": None},
    Role.SEER: {"checks": {}},
}
# 角色规则读写改为:
engine.role_state[Role.WITCH]["antidote_available"] = False
```

**ask() 异常捕获详情**：

```python
# 现在 (actions.py:47)
response = await engine.agents[player_id].act(request)  # 异常直接抛出

# 改后
try:
    response = await engine.agents[player_id].act(request)
except Exception as exc:
    engine._log("agent_disconnect", f"P{player_id} 断线: {exc}", actor=player_id)
    engine.state.llm_error_count += 1
    return default  # 用规则默认行为
```

---

## 2. Agent 决策管线

### 2.1 现状

**6 步管线** (`agent/api/runtime.py:85-94`)：

```
1. remember_step        → memory.build_context(request) → ctx.memory_context
2. select_skills_step   → router.select_skills() → ctx.selected_skills + ctx.skill_context
3. build_prompt_step    → prompts.build_messages() → ctx.messages
4. call_model_step      → model.complete(messages) → ctx.raw_output
5. parse_output_step    → 解析 JSON → ctx.response + ctx.parsed_decision
6. enforce_policy_step  → 校验+修复 → ctx.response (最终)
```

**call_model_step** (`agent/decision/steps/call_model.py:8-18`)：异常时设 `ctx.source = "llm_error"`，`ctx.raw_output = ""`，**不抛异常**。

**parse_output_step** (`agent/decision/steps/parse_output.py`)：`raw_output` 为空时设 `source = "fallback"`。

**enforce_policy_step** (`agent/decision/steps/enforce_policy.py:111-198`)：三阶段保障——无响应 fallback、choice 校验修复、target 校验修复。

### 2.2 改动方案

| 改动 | 现状 | 目标 | 优先级 |
|------|------|------|--------|
| **合并 remember + select_skills** | 两个独立 step，remember 只有一行调用 | 合并为一个 step，减少管线长度 | P2 |
| **合并 call_model + parse_output** | parse 依赖 call 的输出，天然顺序 | 合并为 `call_and_parse` step | P2 |
| **管线从 6 步精简为 4 步** | 6 步过长 | `select_skills → build_prompt → call_and_parse → enforce_policy` | P2 |

**注意**：这是低优先级重构，不影响功能。现有 6 步管线能正常工作，精简主要是为了可读性。

---

## 3. 记忆系统

### 3.1 现状

**AgentMemory** (`agent/core/memory.py:286-306`) 有 15+ 个字段：

```python
class AgentMemory:
    player_id, role                    # 身份（不变）
    events, phase_events, phase_order  # 事件索引
    self_history, decision_history     # ← 今天已从 build_context 移除，但字段还在
    suspicions, claims_seen            # ← 今天已从 build_context 移除，但字段还在
    errors, _seen_public_entries       # 错误 + 去重
    field_notes                        # 结构化笔记
    rolling_summary                    # 阶段摘要（规则压缩）
    _summarized_phase_keys             # 已摘要的阶段标记
    pinned_facts, _pinned_fact_keys    # 关键事实
    self_commitments                   # 公开口径
```

**build_context()** (`memory.py:308-329`) 输出的字段（实际被 prompt 使用的）：
- `private_facts`（known_roles + seer_checks + metadata）
- `errors[-3:]`
- `rolling_summary[-30:]`
- `pinned_facts[-80:]`
- `recent_timeline`（最近 2 阶段原始事件）
- `player_models`（来自 field_notes）
- `self_commitments[-24:]`
- `field_notes`

**阶段压缩** (`_roll_old_phases`, `memory.py:414-425`)：滑动窗口 2 阶段，更早的用规则提取压缩（`_summarize_phase`），每个阶段压缩成 1 行文本。

### 3.2 改动方案

| 改动 | 现状 | 目标 | 优先级 |
|------|------|------|--------|
| **阶段压缩改为 LLM 摘要** | 规则提取（`_summarize_phase`） | 用 LLM 生成 2-3 句摘要，budget 超 6000 tokens 时触发压缩 | P1 |
| **保留 30 条上限** | `rolling_summary` 截断为 30 | 保持（安全阀） | 不改 |
| **清理已移除字段** | `self_history` 等字段声明还在 | 保留声明（避免大改），但确认 build_context 不使用 | 不改 |
| **其余保持现状** | 6 字段记忆 + 现有更新逻辑 | 不改 | 不改 |

**LLM 摘要替换规则压缩**：

```python
# 现在 (memory.py:561-627)
def _summarize_phase(key, events):
    # 规则提取: deaths, votes, speeches, claims, checks → 1行文本
    return "day1/night: 死亡 P3；查验声明 P2报P7=狼"

# 改后
async def _llm_summarize_phase(key, events, model):
    prompt = f"将以下狼人杀事件压缩为2-3句话：{events}"
    return await model.complete([{"role": "user", "content": prompt}])

# Fallback: LLM 失败时用原有规则压缩
```

---

## 4. Skill 系统

### 4.1 现状

**Front matter 驱动**：每个 skill 文件通过 front matter 声明适用场景：

```markdown
---
name: check_priority
role: seer
applicable_actions: [seer_check]
---
# 查验优先级
先查验沉默玩家...
```

**路由逻辑** (`router.py:78`)：按 `role` 过滤 → 按 `applicable_actions` 匹配 action_type → 检查 `requires` 条件 → 按 name 排序。

**版本管理**：`VersionStore` 管理多版本，`SkillVersionConfig` 每局固定一个版本组合。

### 4.2 改动方案

**与现状一致，不改。** Skill 系统设计已经合理。

---

## 5. Prompt 结构

### 5.1 现状

**System prompt** (`base.py:72-79`)：角色人设 + 行为准则 + private/public 分离要求。

**User prompt** (`base.py:208-267`)，按顺序：
1. 当前情境（phase, day, action_type, candidates, alive/dead, sheriff, known_roles, seer_checks）
2. 短期记忆（rolling_summary, pinned_facts, player_models, self_commitments, recent_timeline）
3. field notes（备用）
4. skill context
5. action instruction（`action_instruction()` 的 1 行指令）
6. 输出格式（JSON schema）

**Token 预算**：各部分有字符上限，超出截断。

### 5.2 改动方案

**与现状一致，不改。** Prompt 结构已经合理。

---

## 6. LLM 集成

### 6.1 现状

**AgentRuntime.act()** (`runtime.py:74-119`)：6 步管线 → 构建 DecisionRecord → 归档 trace → 更新 memory。

**call_model_step** (`call_model.py:8-18`)：异常时 `ctx.source = "llm_error"`，不抛异常。

**enforce_policy_step** (`enforce_policy.py`)：LLM 失败时（raw_output 为空）生成 fallback 响应。

**最终效果**：LLM 失败 → 空输出 → fallback 响应（随机选第一个 candidate 或 "pass"）。agent 不会"断线"，而是默默降级。

### 6.2 改动方案

| 改动 | 现状 | 目标 | 优先级 |
|------|------|------|--------|
| **LLM 失败时引擎层处理** | agent 层吞异常 + fallback | 引擎层 `ask()` 加 try/except，捕获后用规则默认行为，记录 llm_error_count | P1 |

**注意**：agent 层的 fallback 机制保留（作为 LLM 返回格式错误时的修复），但 LLM 完全失败（超时/网络错误）应该让引擎知道。

---

## 7. 改动优先级汇总

| 优先级 | 改动 | 影响范围 | 工作量 |
|--------|------|----------|--------|
| **P1** | GameEvent 加 visibility enum | models.py + 所有生成事件的代码 | 中 |
| **P1** | Observation 用 visible_events 替代 public_log | models.py + 所有读取 public_log 的代码 | 中 |
| **P1** | ask() 捕获 agent 异常 + 规则默认行为 | actions.py + 各角色规则 | 小 |
| **P1** | 阶段压缩改为 LLM 摘要 | memory.py | 中 |
| **P2** | GameState 拆分角色状态到 role_state | models.py + engine.py + 所有角色规则 | 大 |
| **P2** | 决策管线从 6 步精简为 4 步 | runtime.py + steps/ | 小 |

**P1 是必须做的**（影响评审得分），P2 是可选优化。

---

## 8. 不改的部分

以下设计经分析确认不需要修改：

| 设计点 | 现状 | 理由 |
|--------|------|------|
| Skill 系统 | front matter 驱动 + router 匹配 | 设计合理，扩展性好 |
| Prompt 结构 | 2 消息 + token 预算 | 结构清晰 |
| RoleRule 单例 | 无状态 singleton | 确认安全，无需改 |
| 夜间 if/elif 链 | 硬编码 7 角色 | 角色数量固定，不需要多态分发 |
| PlayerAgent 协议 | 单方法 `act()` | 简洁够用 |
| AgentMemory 字段 | 15+ 字段，build_context 输出 8 个 | 已清理死代码，保留的都有消费者 |
| 输出 Schema | choice/target/public_text/private_reasoning/confidence/alternatives/rejected_reasons/selected_skills | 完整够用 |
