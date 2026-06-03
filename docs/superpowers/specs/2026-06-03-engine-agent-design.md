# Spec #1: 游戏引擎 + Agent 决策系统

> 目标：定义狼人杀对局引擎和 LLM Agent 决策系统的理想架构。
> 方法：先写理想设计，再对照现有代码做 gap analysis。
> 评审导向：重点覆盖"单 Agent 能力"和"多 Agent 协作"两个维度。

---

## 1. 游戏引擎

### 1.1 信息隔离模型：事件流 + 视角过滤

引擎维护一个**完整的全局事件流**，记录对局中发生的所有事件。每个玩家在每个决策点收到一个**视角过滤后的视图**——引擎根据角色权限过滤事件流，只暴露该角色在该阶段有权知道的信息。

**核心原则**：信息隔离在引擎层强制执行，Agent 不可能获取不该看到的信息。

**事件类型**：

| 类别 | 事件 | 可见范围 |
|------|------|----------|
| 公开 | 发言、投票、放逐、死亡（公开原因） | 所有存活玩家 |
| 狼人私有 | 狼人互认、夜间杀人目标 | 仅狼人 |
| 女巫私有 | 被杀者身份、解药/毒药使用 | 仅女巫 |
| 预言家私有 | 查验结果 | 仅预言家 |
| 守卫私有 | 守护目标 | 仅守卫 |
| 系统 | 游戏初始化、阶段切换 | 引擎内部 |

**视角过滤示例**：

```
全局事件流: [夜1_狼人杀3号, 夜1_女巫救3号, 夜1_预言家查验7号=狼, 日1_3号发言, ...]

预言家视角: [夜1_预言家查验7号=狼, 日1_3号发言, ...]  ← 能看到查验结果
女巫视角:   [夜1_女巫救3号, 日1_3号发言, ...]         ← 能看到被救信息
狼人视角:   [夜1_狼人杀3号, 日1_3号发言, ...]         ← 能看到刀人信息
村民视角:   [日1_3号发言, ...]                         ← 只能看到公开事件
```

### 1.2 阶段模型

```
SETUP → SHERIFF_ELECTION → {NIGHT → DAY_SPEECH → EXILE_VOTE} × N → FINISHED
```

每个阶段有明确的：
- **参与者**：哪些角色在该阶段需要做决策
- **事件生成**：该阶段产生哪些类型的事件
- **信息可见性**：该阶段的哪些信息对哪些角色可见

### 1.3 角色定义

| 角色 | 阵营 | 夜间行动 | 特殊能力 |
|------|------|----------|----------|
| 狼人 (werewolf) | 狼人 | 选择杀人目标 | 狼人互认 |
| 白狼王 (white_wolf_king) | 狼人 | 选择杀人目标 | 自爆带走一人 |
| 预言家 (seer) | 好人 | 查验一人身份 | 知道查验结果 |
| 女巫 (witch) | 好人 | 用药（解药/毒药） | 知道被杀者身份 |
| 守卫 (guard) | 好人 | 选择守护目标 | 同一人不能连续守护 |
| 猎人 (hunter) | 好人 | — | 死亡时可开枪带走一人 |
| 村民 (villager) | 好人 | — | 无特殊能力 |

### 1.4 GameState 设计原则

**反对上帝对象**：GameState 不应包含角色特定的可变状态（如 `witch_antidote_available`）。

**建议方案**：GameState 只包含通用状态（玩家存活状态、阶段、轮次），角色特定状态由各 RoleRule 自己维护（通过一个 per-game 的 state dict）。

```
GameState:
  players: dict[int, PlayerState]  # 存活状态
  day: int
  phase: Phase
  events: list[GameEvent]          # 全局事件流
  deaths: list[DeathRecord]
  winner: Winner | None

RoleState (per-role):
  witch: {antidote_available, poison_available}
  guard: {last_target}
  seer: {checks: dict[int, Team]}
```

---

## 2. Agent 决策系统

### 2.1 决策管线：4 步顺序执行

```
Step 1: select_skills
  输入: role, phase, action_type
  输出: selected_skills: list[str]
  职责: 根据角色和阶段，从 skill 目录选择相关 skill 文件

Step 2: build_prompt
  输入: action_request, memory_context, selected_skills
  输出: messages: [system_prompt, user_prompt]
  职责: 拼装 system prompt（角色人设）和 user prompt（情境+记忆+skill+格式）

Step 3: call_and_parse
  输入: messages
  输出: parsed_decision: {target, choice, public_text, private_reasoning, confidence, ...}
  职责: 调用 LLM，解析 JSON 输出
  错误处理: LLM 失败时直接抛异常（不生成 fallback 决策）

Step 4: enforce_policy
  输入: parsed_decision, action_request
  输出: final_decision
  职责: 规则校验（target 是否在 candidates 中等），校验失败返回合法默认值
```

**关键设计决策**：
- **LLM 失败 = agent 断线**：不生成 fallback，GameEngine 标记该 agent 不可用
- **管线是严格顺序的**：没有并行分支，不需要 DAG 编排
- **每步有明确的输入/输出契约**：中间状态保存在 DecisionContext 中供 trace

### 2.2 Skill 系统

**目录结构**（每个角色一个目录，按场景分文件）：

```
skills/
├── seer/
│   ├── strategy.md          ← 基本策略（什么时候暴露身份）
│   ├── check_priority.md    ← 查验优先级（night + seer_check 时加载）
│   ├── claim.md             ← 预言家起跳策略（day + speak 时加载）
│   └── counter_claim.md     ← 反对假预言家（day + speak 时加载）
├── werewolf/
│   ├── strategy.md          ← 基本策略（隐藏身份）
│   ├── fake_seer.md         ← 假跳预言家（day + speak 时加载）
│   └── vote_rush.md         ← 冲票策略（day + exile_vote 时加载）
├── witch/
│   ├── save.md              ← 救人策略（night + witch_act 时加载）
│   └── poison.md            ← 毒人策略（night + witch_act 时加载）
...
```

**选择逻辑**：

```python
SKILL_ROUTER: dict[(role, phase, action_type), list[str]] = {
    ("seer", "night", "seer_check"): ["check_priority.md"],
    ("seer", "day_speech", "speak"): ["claim.md", "counter_claim.md"],
    ("werewolf", "day_speech", "speak"): ["fake_seer.md"],
    ("werewolf", "exile_vote", "exile_vote"): ["vote_rush.md"],
    ("witch", "night", "witch_act"): ["save.md", "poison.md"],
    ...
}

def select_skills(role, phase, action_type) -> list[str]:
    skills = [load(f"skills/{role}/strategy.md")]  # 始终加载基础策略
    for skill_name in SKILL_ROUTER.get((role, phase, action_type), []):
        skills.append(load(f"skills/{role}/{skill_name}"))
    return skills
```

### 2.3 Skill 版本管理

**版本流转模型**：

```
VersionStore (多版本存储)
  └── <role>/<content_hash>/skills/*.md

        ↓ 每局游戏开始时，SkillVersionConfig 确定使用哪个版本

SkillVersionConfig (每局固定)
  seer → hash_abc (v2)
  werewolf → hash_def (v3)
  ...

        ↓ Agent 运行时，skill_dir 指向具体版本的目录

Agent: skill_dir = data/versions/seer/hash_abc/skills/
```

**关键规则**：
- 一局之内版本不变——所有 agent 使用同一份 SkillVersionConfig
- 版本由进化系统管理——Agent 不感知版本，只感知 skill_dir 路径
- 版本切换发生在局间

---

## 3. Agent 记忆系统

### 3.1 记忆字段（与现状一致）

| 字段 | 类型 | 更新频率 | 说明 |
|------|------|----------|------|
| `rolling_summary` | list[str] | 每阶段结束 | 早期阶段的 LLM 压缩摘要，完整保留不截断 |
| `recent_timeline` | list[dict] | 实时 | 最近 2 个阶段的原始事件流，不压缩 |
| `pinned_facts` | list[dict] | 实时 | 关键事实（如"7号被查验为狼"），不会被摘要覆盖 |
| `player_models` | dict[int, dict] | 实时 | 对其他玩家的画像（发言次数、投票记录、关系） |
| `self_commitments` | list[dict] | 实时 | 自己的公开口径（说过什么、投过谁、声称过什么身份） |
| `field_notes` | FieldNotes | 实时 | 结构化笔记（投票关系图、角色推测、阶段事件索引） |

### 3.2 记忆压缩策略：混合模式

**规则**：

1. **最近 2 个阶段**：始终保留原始事件（`recent_timeline`），不压缩
2. **更早的阶段**：先保留原始事件，直到总 token 接近预算上限（~6000 tokens）
3. **触发压缩**：超出预算时，从最老的未压缩阶段开始，逐个做 LLM 摘要
4. **摘要内容**：2-3 句话，保留关键事件（死亡、投票、声明、查验结果）
5. **完整保留**：`rolling_summary` 不截断，一局狼人杀最多 ~20 个阶段，总 token 可控
6. **Fallback**：LLM 摘要失败时用规则压缩（现有 `_summarize_phase` 逻辑）

**Token 预算**：

```python
BUDGET = 6000  # rolling_summary + recent_timeline 的总 token 预算

def compress_if_needed(memory):
    raw_tokens = estimate_tokens(memory.raw_phases)
    summary_tokens = estimate_tokens(memory.rolling_summary)
    total = raw_tokens + summary_tokens

    while total > BUDGET and memory.has_uncompressed_phases():
        oldest = memory.get_oldest_uncompressed_phase()
        summary = llm_summarize(memory.raw_phases[oldest])
        memory.rolling_summary.append(summary)
        total -= estimate_tokens(memory.raw_phases[oldest])
        total += estimate_tokens(summary)
```

### 3.3 记忆生命周期

- 每个新 game 创建新 AgentMemory 实例
- 每次决策后：`remember_action()` 累加到 self_commitments，`update_player_model()` 更新画像
- 每阶段结束：压缩旧阶段（如需要），更新 rolling_summary
- `reset()` 清空所有动态记忆（保留在同一局内复用场景）

---

## 4. Prompt 结构

### 4.1 消息格式：2 消息

```
System Prompt:
  "你正在扮演一名狼人杀玩家。你是 {player_id} 号，身份: {role}。
   必须区分 private_reasoning 和 public_text...
   不要在公开发言中泄露你不可公开解释的私有视角。"

User Prompt:
  "## 当前情境
   第{day}天 {phase}，行动: {action_type}
   候选目标: {candidates}

   ## 公共事件
   {recent_timeline}

   ## 我的记忆
   前史摘要: {rolling_summary}
   不可丢关键事实: {pinned_facts}
   玩家画像: {player_models}
   我的公开口径: {self_commitments}

   ## 技能指导
   {skill_content}

   ## 输出格式
   {json_schema}"
```

### 4.2 Token 预算管理

各部分有字符上限，超出时按优先级截断：

| 部分 | 预算 | 优先级 | 截断策略 |
|------|------|--------|----------|
| skill_content | 2000 chars | 最高 | 必须完整 |
| recent_timeline | 1500 chars | 高 | 截断最早的事件 |
| rolling_summary | 无上限 | 中 | 完整保留 |
| player_models | 1000 chars | 中 | 按重要性排序截断 |
| pinned_facts | 500 chars | 低 | 截断最早的 facts |

### 4.3 输出 Schema

```json
{
  "choice": "string | null",
  "target": "number | null",
  "public_text": "string",
  "private_reasoning": "string",
  "confidence": "0.0~1.0",
  "alternatives": ["number"],
  "rejected_reasons": ["string"],
  "selected_skills": ["string"]
}
```

**不含 `memory_refs`**（已确认删除——解析了但无消费者）。

---

## 5. LLM 集成

### 5.1 调用链路

```
AgentRuntime.act(request)
  → select_skills(role, phase, action_type)
  → build_prompt(request, memory, skills)
  → call_and_parse(messages)          ← LLM 调用点
  → enforce_policy(decision, request)
  → memory.update(request, response)
  → return final_decision
```

### 5.2 错误处理

- **LLM 超时/认证失败/格式错误** → 抛异常，GameEngine 标记 agent 断线
- **不生成 fallback 决策** — 断线 agent 在该轮不行动
- **source 标记**：成功 = `"llm"`，失败 = `"llm_error"`
- **重试策略**：不重试（快速失败，让游戏继续）

### 5.3 速率控制

- 全局 rate limiter（RPM 限制）
- 全局 semaphore（并发限制）
- 每个 agent 共享同一个 LLM client

---

## 6. 数据结构

### 6.1 核心 dataclass

```python
@dataclass
class ActionRequest:
    player_id: int
    action_type: ActionType
    phase: Phase
    observation: Observation        # 视角过滤后的可见信息
    candidates: tuple[int, ...]     # 合法目标列表

@dataclass
class Observation:
    player_id: int
    self_role: Role
    phase: Phase
    day: int
    alive_players: tuple[int, ...]
    dead_players: tuple[int, ...]
    sheriff_id: int | None
    public_log: tuple[str, ...]     # 视角过滤后的公开事件
    known_roles: dict[int, Role]    # 已知角色（仅特殊角色）
    seer_checks: dict[int, Team]    # 查验结果（仅预言家）
    metadata: dict[str, Any]

@dataclass
class ActionResponse:
    action_type: ActionType
    target: int | None = None
    choice: str | None = None
    text: str = ""                  # public_text
    decision_id: str | None = None

@dataclass
class DecisionContext:
    """管线中间状态，用于 trace 和 debug"""
    request: ActionRequest
    selected_skills: list[str]
    messages: list[dict]
    raw_output: str
    parsed_decision: dict
    final_decision: ActionResponse
    source: str                     # "llm" | "llm_error"
    confidence: float
    errors: list[str]
```

---

## 7. 与现有代码的 Gap Analysis

| 设计点 | 现状 | 差距 | 优先级 |
|--------|------|------|--------|
| 信息隔离 | Observation 类已有，但 public_log 是字符串列表 | 需要结构化为事件流 | P1 |
| GameState | 上帝对象，角色状态混在一起 | 需要拆分 | P2 |
| 决策管线 | 6 步，含冗余 step | 精简为 4 步 | P1 |
| 记忆压缩 | 规则压缩 | 改为 LLM 摘要 + 预算触发 | P1 |
| Skill 选择 | 已有 SKILL_ROUTER | 与 spec 一致 | 无需改动 |
| Prompt 结构 | 已有 2 消息结构 | 与 spec 一致 | 无需改动 |
| LLM 错误处理 | fallback 而非失败 | 改为直接失败 | P1 |
| memory_refs | 已删除 | 与 spec 一致 | 无需改动 |
| AgentMemory.reset() | 已修复 | 与 spec 一致 | 无需改动 |
