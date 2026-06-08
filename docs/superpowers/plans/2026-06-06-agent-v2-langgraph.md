# app/ — 迁移实施计划（详细版）

> **目标:** `app/` 完全取代 `agent/`，零 `from agent.` import。
> **原则:** 每个 Phase 完成后可独立验证；Phase 间标记并行关系；Step 级标记是否可并行。
>
> **依赖链:** `util/` ← `services/` ← `lib/` + `graphs/shared/` ← `graphs/subgraphs/` ← `graphs/main/` + `run.py`
>
> ---
>
> ## 并行标记体系

| 标记 | 含义 |
|------|------|
| `∥P{N}` | 可与 Phase N 并行执行 |
| `∥P{N1,N2}` | 可与 Phase N1、N2 并行执行 |
| `∥S{N}` | 可与本 Phase 内 Step N 并行执行 |
| `→` | 必须顺序执行（有依赖） |
| `⚠️` | LLM 调用点 — 测试时需要 mock |

---

## Phase 0: 骨架搭建 [~30 min]

> **可并行:** 无前置依赖，所有 step 可以并行

### Step 0.1 — 目录创建 ∥S{0.2,0.3,0.4}
```bash
mkdir -p app/graphs/main
mkdir -p app/graphs/subgraphs/{agent,game,play,eval,evolve}
mkdir -p app/graphs/shared/nodes
mkdir -p app/services
mkdir -p app/lib
mkdir -p app/util
```

### Step 0.2 — 依赖安装 ∥S{0.1,0.3,0.4}
```bash
uv add langgraph langgraph-checkpoint-sqlite langchain langchain-openai
```

### Step 0.3 — `app/__init__.py` ∥S{0.1,0.2,0.4}
- 空白或版本号，无 import

### Step 0.4 — `app/config.py` ∥S{0.1,0.2,0.3}
- 集中配置：model 名称、temperature、路径常量
- 来源: `agent/infrastructure/llm.py` 的 `DEFAULT_BASE_URL`、`DEFAULT_MODEL`
- 来源: `agent/common/paths.py` 的 `DEFAULT` 路径常量

### 验证
```bash
python -c "import app; from app.config import *"  # 无报错
```

---

## Phase 1: `app/util/` — 工具层 [~2h]

> 纯函数，零 LLM 依赖，零 agent/ 依赖（仅依赖 engine/ 枚举）
> **∥P{0}** (P0 目录需先创建)

### Step 1.1 — `util/json.py` (复制) ∥S{1.2,1.3}
**来源:** `agent/common/json.py`
**操作:** 复制，替换 `from agent.common` → 删除（文件内 import 变为内部引用）
**内容:** `compact_json`, `to_jsonable`, `DictMixin`, `read_json`, `read_jsonl`, `write_json`, `write_jsonl`, `write_text`
**验证:** `python -c "from app.util.json import DictMixin, write_json, read_json"`

### Step 1.2 — `util/action_types.py` (复制) ∥S{1.1,1.3}
**来源:** `agent/common/action_types.py`
**操作:** 复制，保留 `from engine.models import ActionType`
**内容:** `ActionCategory`, `VOTE_ACTION_TYPES`, `NIGHT_SKILL_ACTION_TYPES`, `SPEECH_ACTION_TYPES` 等
**验证:** `python -c "from app.util.action_types import VOTE_ACTION_TYPES"`

### Step 1.3 — `util/coercion.py` + `util/errors.py` + `util/time.py` + `util/winner.py` + `util/paths.py` + `util/callbacks.py` ∥S{1.1,1.2}
> 这 6 个文件互不依赖，可以并行复制

#### `util/coercion.py` ∥S{1.1,1.2,1.3.others}
**来源:** `agent/common/coercion.py`
**内容:** 类型安全转换 helper
**验证:** `python -c "from app.util.coercion import *"`
**耗时:** ~10 min

#### `util/errors.py` ∥S{1.1,1.2,1.3.others}
**来源:** `agent/common/errors.py`
**内容:** 异常类
**验证:** `python -c "from app.util.errors import *"`
**耗时:** ~5 min

#### `util/time.py` ∥S{1.1,1.2,1.3.others}
**来源:** `agent/common/time.py`
**内容:** `beijing_now_iso`, `beijing_now_str`
**验证:** `python -c "from app.util.time import beijing_now_iso"`
**耗时:** ~10 min

#### `util/winner.py` ∥S{1.1,1.2,1.3.others}
**来源:** `agent/common/winner.py`
**内容:** 胜者判定辅助
**验证:** `python -c "from app.util.winner import *"`
**耗时:** ~5 min

#### `util/paths.py` ∥S{1.1,1.2,1.3.others}
**来源:** `agent/common/paths.py`
**内容:** 路径解析常量 `DEFAULT`, `resolve_skill_dir` 等
**注意:** 路径常量引用 `engine/` 和 `storage/`，不引用 `agent/`
**验证:** `python -c "from app.util.paths import DEFAULT"`
**耗时:** ~20 min

#### `util/callbacks.py` ∥S{1.1,1.2,1.3.others}
**来源:** `agent/common/callbacks.py`
**内容:** Langfuse callback 封装（被 LangChain 使用）
**注意:** 此处可能引入 langfuse 依赖 — 保留为可选
**验证:** `python -c "from app.util.callbacks import *"`
**耗时:** ~15 min

### Phase 1 验证
```bash
python -c "from app.util import *"  # 所有公共符号可用
# 确认无 agent 依赖
grep -r "from agent\." app/util/ && echo "FAIL" || echo "PASS"
```

---

## Phase 2: `app/services/` — LangChain 能力组件 [~8h]

> 这是整个迁移的核心 — 所有 LLM 调用集中到这里
> **前置:** Phase 0 + Phase 1 (依赖 `app/util/`)
> **∥P{1}** (P1 完成后开始)
>
> 内部依赖链: `llm.py` ← `tool.py` + `prompt.py` + `memory.py` ← `chain.py`
> `tool.py`, `prompt.py`, `memory.py` 三者互不依赖，**可以并行**。

### Step 2.1 — `services/llm.py` — ChatOpenAI 工厂 [~1h]

**来源:** `agent/infrastructure/llm.py`

**操作:**
1. 复制 `agent/infrastructure/llm.py` → `app/services/llm.py`
2. 保留 `ModelAdapter` protocol（兼容当前非 LangChain 调用）
3. 新增 `create_chat_openai()` 工厂函数 — 返回 `ChatOpenAI` 实例
4. 保留 `ChatCompletionClient`（兼容现有调用方）作为 `ModelAdapter` 实现
5. 替换 `from agent.infrastructure.tracing` → `from app.util.callbacks`
6. 替换路径引用 → `app.config`

**新增内容:**
```python
from langchain_openai import ChatOpenAI

def create_chat_openai(
    model: str | None = None,
    temperature: float = 0.4,
    timeout: float = 45.0,
    max_retries: int = 5,
) -> ChatOpenAI:
    """Create a LangChain ChatOpenAI instance."""
    from app.config import LLM_BASE_URL, LLM_API_KEY
    return ChatOpenAI(
        model=model or LLM_DEFAULT_MODEL,
        temperature=temperature,
        timeout=timeout,
        max_retries=max_retries,
        base_url=LLM_BASE_URL,
        api_key=LLM_API_KEY,
    )
```

**验证:** `python -c "from app.services.llm import create_chat_openai, ModelAdapter"`

### Step 2.2 — `services/tool.py` — 17 个 @tool [~2h] ∥S{2.3,2.4}

> 全新编写，无 agent/ 来源

**操作:** 创建 LangChain `@tool` 函数，每个对应一种游戏 action：
1. `vote_tool` — 投票
2. `speak_tool` — 发言
3. `seer_check_tool` — 预言家查验
4. `witch_save_tool` — 女巫救人
5. `witch_poison_tool` — 女巫毒人
6. `hunter_shoot_tool` — 猎人开枪
7. `guard_protect_tool` — 守卫守人
8. `werewolf_kill_tool` — 狼人杀人
9. `sheriff_run_tool` — 竞选警长
10. `sheriff_withdraw_tool` — 退选警长
11. `sheriff_badge_tool` — 警徽传递
12. `speech_order_tool` — 发言顺序
13. `white_wolf_explode_tool` — 白狼王自爆
14. `pass_tool` — 跳过/弃权
15. `claim_role_tool` — 跳身份
16. `accuse_tool` — 指认
17. `defend_tool` — 辩护

**注意:** 每个 tool 必须依赖 `engine.models.ActionType`，但不依赖 `agent/`。

**参考:** `agent/decision/steps/enforce_policy.py` 的 `_VALID_CHOICES`、`_ACTION_VALIDATORS`
**参考:** `agent/knowledge/prompts/instructions.py` 的 `action_instruction()`

**验证:** `python -c "from app.services.tool import vote_tool; print(vote_tool.name)"`

### Step 2.3 — `services/memory.py` — 合并 agent/core/ [~2h] ∥S{2.2,2.4}

**来源:** `agent/core/memory.py` + `agent/core/memory_segments.py`

**操作:**
1. 复制 `agent/core/memory_segments.py` → `app/services/memory.py` (Segments 部分)
2. 复制 `agent/core/memory.py` → `app/services/memory.py` (AgentMemory 部分)
3. 新增 LangChain 适配 — `WolfMemory(BaseChatMessageHistory)`:
   ```python
   from langchain_core.chat_history import BaseChatMessageHistory
   
   class WolfMemory(BaseChatMessageHistory):
       """LangChain-compatible memory wrapping AgentMemory."""
       def add_message(self, message): ...
       @property
       def messages(self): ...
   ```
4. 保留原有 `build_context()` / `update_segments()` / `remember_action()` 方法
5. 替换内部 import：`from agent.core` → `from app.services.memory`
6. 替换 `from agent.common` → `from app.util.json`

**关键功能保持不变:**
- Segment 分组 (`day_phase` → `SegmentEvent` → `Segment`)
- 记忆压缩追踪 (`compressed_segment_summaries`, `compression_failed`, `compression_retry_count`)
- Prompt 窗口构建 (`build_context()`)

**验证:** `python -c "from app.services.memory import AgentMemory, WolfMemory, Segment, CompressedSegmentSummary"`

### Step 2.4 — `services/prompt.py` — 合并 agent/knowledge/ [~2h] ∥S{2.2,2.3}

**来源:** 合并以下 7 个文件:
- `agent/knowledge/prompts/base.py` — system prompt + request prompt builder
- `agent/knowledge/prompts/instructions.py` — `action_instruction()`
- `agent/knowledge/prompts/parsing.py` — 输出格式
- `agent/knowledge/skills/__init__.py` — `MarkdownSkill` 模型
- `agent/knowledge/skills/loader.py` — `load_markdown_skills()`
- `agent/knowledge/skills/router.py` — `select_skills()`, `format_skill_context()`

**操作:**
1. 复制全部 symbol → `app/services/prompt.py`
2. 替换 `from agent.core` → `from app.services.memory`
3. 替换 `from agent.common` → `from app.util.json`
4. 替换 `from engine.models` → 保留（黑盒引用）
5. 新增 LangChain 适配:
   ```python
   from langchain_core.prompts import ChatPromptTemplate
   
   def build_decision_prompt_template() -> ChatPromptTemplate:
       """Build a LangChain ChatPromptTemplate for decision-making."""
       return ChatPromptTemplate.from_messages([
           ("system", "{system_prompt}"),
           ("user", "{user_prompt}"),
       ])
   ```

**保留的公共接口:**
- `build_messages()` — 返回 `list[dict[str, str]]`（兼容当前 pipeline）
- `build_system_prompt()`
- `build_request_prompt()`
- `select_skills()` — 技能路由
- `format_skill_context()` — 格式化注入

**验证:** `python -c "from app.services.prompt import build_messages, select_skills, format_skill_context"`

### Step 2.5 — `services/chain.py` — 5 个 LCEL chain [~3h] ⚠️

> **核心纪律:** 这是 `app/` 中唯一调 LLM 的文件
> **前置:** Step 2.1-2.4 全部完成

**5 个 chain:**

#### Chain 1: `decision_chain` (替代 `call_model_step` + `parse_output_step` + `enforce_policy_step`)
```python
def create_decision_chain(llm: ChatOpenAI, tools: list):
    """Chain: prompt → llm.bind_tools(tools) → parse_decision_output"""
    prompt = build_decision_prompt_template()
    llm_with_tools = llm.bind_tools(tools)
    return prompt | llm_with_tools | DecisionOutputParser()
```
**来源:** `agent/decision/steps/call_model.py` + `agent/decision/steps/parse_output.py` + `agent/decision/steps/enforce_policy.py`
**注意:** 保留 `enforce_policy` 逻辑作为 `RunnableLambda` 后处理

#### Chain 2: `compress_chain` (替代 `compress_memory_step`)
```python
def create_compress_chain(llm: ChatOpenAI):
    """Chain: compress_prompt → llm → parse_compression_json"""
    return COMPRESS_PROMPT | llm | JsonOutputParser()
```
**来源:** `agent/decision/steps/compress_memory.py`

#### Chain 3: `consolidate_chain` (替代 `consolidation.py`)
```python
def create_consolidate_chain(llm: ChatOpenAI):
    """Chain: consolidation_prompt → llm → parse_consolidation"""
    return CONSOLIDATION_PROMPT | llm | JsonOutputParser()
```
**来源:** `agent/evolution/consolidation.py`
**注意:** 保留 `consolidate_for_role()` 逻辑 — prompt 构建 + LLM 调用 + JSON 解析

#### Chain 4: `apply_chain` (替代 `applier.py`)
```python
def create_apply_chain(llm: ChatOpenAI):
    """Chain: apply_prompt → llm → parse_skill_diff"""
    return APPLY_PROMPT | llm | JsonOutputParser()
```
**来源:** `agent/evolution/applier.py`

#### Chain 5: `evidence_chain` (替代 `judge.py`)
```python
def create_evidence_chain(llm: ChatOpenAI):
    """Chain: evidence_prompt → llm → parse_evidence"""
    return EVIDENCE_PROMPT | llm | JsonOutputParser()
```
**来源:** `agent/evidence/judge.py`

**验证:**
```bash
grep "\.invoke" app/services/chain.py | wc -l  # >= 5
# 确认 LLM 调用全部集中在 services/chain.py
grep -r "model\.invoke\|llm\.invoke\|ChatOpenAI" app/services/ --include="*.py" | grep -v chain.py && echo "FAIL" || echo "PASS"
```

### Phase 2 验证
```bash
python -c "from app.services import llm, tool, memory, prompt, chain"
grep -r "from agent\." app/services/ && echo "FAIL" || echo "PASS"
```

---

## Phase 3: `app/graphs/shared/` — 共享图组件 [~3h]

> LangGraph 的 state + 可复用于图
> **前置:** Phase 2 (依赖 `app/services/`)
> **∥P{2}** (可与 P2 并行，但 P2 的 chain.py 完成后才能联调)

### Step 3.1 — `graphs/shared/state.py` — 全部 TypedDict [~1h]

**来源:** `agent/core/context.py` (AgentContext dataclass → TypedDict)
**新写:** 为每种子图定义 `TypedDict`，`AgentContext` 的所有字段映射到 `AgentState`

```python
from typing import TypedDict, Annotated
from langgraph.graph.message import add_messages

class AgentState(TypedDict):
    """7步决策子图的状态"""
    request: dict
    player_id: int
    role: str
    memory_context: dict
    selected_skills: list[str]
    skill_context: str
    messages: Annotated[list, add_messages]
    raw_output: str
    parsed_decision: dict
    confidence: float
    response: dict | None
    source: str
    errors: list[str]
    policy_adjustments: list[str]

class GameState(TypedDict):
    """单局游戏子图的状态"""
    agents: dict
    engine: Any
    phase: str
    day: int
    alive_players: list[int]
    game_log: list[dict]
    winner: str | None
    finished: bool

class EvalBatchState(TypedDict):
    """评测批次的状态"""
    batch_config: dict
    games: list[dict]
    scores: list[dict]
    fairness: dict
    rankable: bool

class EvolveState(TypedDict):
    """自进化管道的状态"""
    role: str
    training_games: list[dict]
    candidate_hash: str | None
    battle_result: dict | None
    proposals: list[dict]
    diff: list[dict]
    status: str
```

**验证:** `python -c "from app.graphs.shared.state import AgentState, GameState, EvalBatchState, EvolveState"`

### Step 3.2 — `graphs/shared/nodes/review.py` — 复盘节点 [~1h] ∥S{3.3}

**来源:** `agent/review/scoring.py` + `agent/review/reviewer.py` + `agent/review/evaluator.py`

**操作:**
1. 复制复盘逻辑 → `app/graphs/shared/nodes/review.py`
2. 作为 LangGraph node: `review_node(state: GameState) -> dict`
3. 调用 `app/services/chain.py` 的 `evidence_chain`（评分部分不需要 LLM，仅 `analyze_game()`）
4. 保留纯 Python 评分逻辑: `_score_agent()`, `_find_highlights()`, `_find_mistakes()`
5. 替换 import: `from agent.review` → `from app.graphs.shared.nodes.review`
6. 替换 `from agent.common` → `from app.util`

**验证:** `python -c "from app.graphs.shared.nodes.review import review_node, analyze_game"`

### Step 3.3 — `graphs/shared/nodes/evidence.py` — 证据节点 [~1h] ∥S{3.2}

**来源:** `agent/evidence/pipeline.py` + `agent/evidence/normalizer.py` + `agent/evidence/selector.py`

**操作:**
1. 复制证据提取/归一化/选择逻辑
2. 作为 LangGraph node: `evidence_node(state: EvalState) -> dict`
3. LLM 调用走 `app/services/chain.py` → `evidence_chain`
4. 替换内部 import: `from agent.evidence` → `from app.graphs.shared.nodes.evidence`
5. 替换 `from agent.common` → `from app.util`

**验证:** `python -c "from app.graphs.shared.nodes.evidence import evidence_node, extract_evidence"`

### Phase 3 验证
```bash
python -c "from app.graphs.shared import state; from app.graphs.shared.nodes import review, evidence"
grep -r "from agent\." app/graphs/shared/ && echo "FAIL" || echo "PASS"
```

---

## Phase 4: `app/graphs/subgraphs/` — 子图 [~10h]

> **前置:** Phase 2 + Phase 3
> ∥P{3} (P3 完成后开始)
>
> 5 个子图之间:
> - `agent/` ∥ `game/` 互相独立 (并行)
> - `play/` 依赖 `agent/` + `game/` (→)
> - `eval/` 依赖 `agent/` + `game/` + `shared/nodes/review.py` (→)
> - `evolve/` 依赖 `agent/` + `game/` + `shared/nodes/evidence.py` + `shared/nodes/review.py` (→)

### Step 4.1 — `subgraphs/agent/` — 7 步决策子图 [~2.5h] ∥S{4.2}

**来源:** `agent/api/runtime.py` + `agent/decision/steps/*` (8 文件)

**文件:** `builder.py` + `nodes.py`

**`nodes.py` 内容 (7 个 node):**

| Node | 来源 | 调 LLM? |
|------|------|----------|
| `remember_node` | `agent/decision/steps/remember.py` | ❌ |
| `compress_node` | `agent/decision/steps/compress_memory.py` | ✅→`services/chain.py:compress_chain` |
| `select_skills_node` | `agent/decision/steps/select_skills.py` | ❌ |
| `build_prompt_node` | `agent/decision/steps/build_prompt.py` | ❌ |
| `call_model_node` | `agent/decision/steps/call_model.py` + `parse_output.py` | ✅→`services/chain.py:decision_chain` |
| `parse_node` | `agent/decision/steps/parse_output.py` | ❌ |
| `enforce_policy_node` | `agent/decision/steps/enforce_policy.py` | ❌ |

**`builder.py` — StateGraph 定义:**
```python
def build_agent_subgraph() -> CompiledGraph:
    workflow = StateGraph(AgentState)
    workflow.add_node("remember", remember_node)
    workflow.add_node("compress", compress_node)
    workflow.add_node("select_skills", select_skills_node)
    workflow.add_node("build_prompt", build_prompt_node)
    workflow.add_node("call_model", call_model_node)
    workflow.add_node("parse", parse_node)
    workflow.add_node("enforce_policy", enforce_policy_node)
    
    # 边
    workflow.add_edge(START, "remember")
    workflow.add_edge("remember", "compress")
    workflow.add_conditional_edges(
        "compress",
        lambda s: "compress" if s.get("needs_more_compression") else "select_skills"
    )
    workflow.add_edge("select_skills", "build_prompt")
    workflow.add_edge("build_prompt", "call_model")
    workflow.add_conditional_edges(
        "call_model",
        lambda s: (
            "retry_call" if s.get("llm_error") and s.get("retry_count", 0) < 2
            else "fallback" if s.get("llm_error")
            else "parse"
        ),
        {"retry_call": "call_model", "parse": "parse", "fallback": "enforce_policy"}
    )
    workflow.add_edge("parse", "enforce_policy")
    workflow.add_edge("enforce_policy", END)
    
    return workflow.compile(checkpointer=SqliteSaver.from_conn_string(":memory:"))
```

**关键差异 vs 当前 pipeline:**
1. **条件路由:** compress 可以跳过；call_model 失败可以重试或 fallback
2. **checkpoint:** 每步自动持久化状态
3. **tool calling:** `call_model_node` 使用 `llm.bind_tools(tools)`，不是纯 JSON 输出

**验证:** `python -c "from app.graphs.subgraphs.agent import build_agent_subgraph; g = build_agent_subgraph()"`

### Step 4.2 — `subgraphs/game/` — 单局游戏子图 [~2h] ∥S{4.1}

**来源:** `agent/game_run/engine.py` + `agent/api/factory.py`

**文件:** `builder.py` + `nodes.py`

**`nodes.py` 内容:**
| Node | 来源 | 调 LLM? |
|------|------|----------|
| `init_engine_node` | `agent/game_run/engine.py` → `create_engine()` | ❌ |
| `create_agents_node` | `agent/api/factory.py` → `create_agents()` | ❌ |
| `phase_loop_node` | `agent/game_run/engine.py` → `engine.run_until_finished()` | ❌ (调 agent_subgraph) |
| `record_events_node` | `agent/infrastructure/archive.py` → `AgentTraceRecorder.flush()` | ❌ |
| `persist_node` | `agent/game_run/service.py` → `GamePersistence` | ❌ |

**`builder.py` — StateGraph:**
```python
def build_game_subgraph(agent_subgraph: CompiledGraph) -> CompiledGraph:
    workflow = StateGraph(GameState)
    workflow.add_node("init_engine", init_engine_node)
    workflow.add_node("create_agents", create_agents_node)
    workflow.add_node("game_loop", phase_loop_node)  # 内部调用 agent_subgraph
    workflow.add_node("record", record_events_node)
    workflow.add_node("persist", persist_node)
    
    workflow.add_edge(START, "init_engine")
    workflow.add_edge("init_engine", "create_agents")
    workflow.add_edge("create_agents", "game_loop")
    workflow.add_edge("game_loop", "record")
    workflow.add_edge("record", "persist")
    workflow.add_edge("persist", END)
    
    return workflow.compile()
```

**关键设计:** `game_loop_node` 内部循环调用 `agent_subgraph.ainvoke()` — 这是"子图嵌套"模式。

**验证:** `python -c "from app.graphs.subgraphs.game import build_game_subgraph"`

### Step 4.3 — `subgraphs/play/` — 普通对战 pipeline [~1.5h] ∥S{4.4,4.5}

> **前置:** Step 4.1 + Step 4.2 (依赖 agent_subgraph + game_subgraph)

**来源:** UI game_runner + `agent/game_run/service.py` → `create_run()`

**文件:** `builder.py` + `nodes.py`

```python
def build_play_graph(agent_subgraph: CompiledGraph, game_subgraph: CompiledGraph):
    """普通对战: init → game_loop → review → end"""
    workflow = StateGraph(PlayState)
    workflow.add_node("init_run", init_play_run_node)    # GameRunService.create_run()
    workflow.add_node("run_game", game_subgraph)          # 嵌套 game_subgraph
    workflow.add_node("review", review_node)              # shared/nodes/review.py
    workflow.add_node("persist_result", persist_play_node)
    
    workflow.add_edge(START, "init_run")
    workflow.add_edge("init_run", "run_game")
    workflow.add_edge("run_game", "review")
    workflow.add_edge("review", "persist_result")
    workflow.add_edge("persist_result", END)
    return workflow.compile()
```

**验证:** `python -c "from app.graphs.subgraphs.play import build_play_graph"`

### Step 4.4 — `subgraphs/eval/` — 批量评测 pipeline [~2h] ∥S{4.3,4.5}

> **前置:** Step 4.1 + Step 4.2 (依赖 agent_subgraph + game_subgraph)
> **∥P{4.3}** (可与 play 并行开发)
> **来源:** `agent/evaluation/runner.py` + `agent/evaluation/config.py` + `agent/evaluation/metrics.py` + `agent/evaluation/stats.py` + `agent/evaluation/fairness.py` + `agent/evaluation/leaderboard.py`

```python
def build_eval_graph(agent_subgraph, game_subgraph):
    """
    评测 pipeline:
    for seed in seeds (并发):
        init_eval_game → game_subgraph → collect_scores
    ↓ barrier
    aggregate_scores → compute_fairness → compute_rankable → persist
    """
```

**操作细节:**
1. 复制 `EvaluationBatchRunner.run_batch()` → `eval_nodes.run_batch_node`
2. 每局游戏用 `game_subgraph` 替代 `_run_single_eval_game`
3. 三路线评测逻辑保持不变: paired / cross_version / role_focus
4. `score_summary` 聚合 → `lib/score.py`（稍后在 Phase 5）
5. leaderboard 写入逻辑保留

**验证:** `python -c "from app.graphs.subgraphs.eval import build_eval_graph"`

### Step 4.5 — `subgraphs/evolve/` — 自进化 pipeline [~2.5h] ∥S{4.3,4.4}

> **前置:** Step 4.1 + Step 4.2
> **∥P{4.3,4.4}** (可与 play/eval 并行开发)
> **来源:** `agent/evolution/pipeline.py` + `agent/evolution/batch.py` + `agent/evolution/battle.py` + `agent/evolution/games.py`

```python
def build_evolve_graph(agent_subgraph, game_subgraph, consolidate_chain, apply_chain):
    """
    自进化 pipeline:
    freeze_baseline → 
    for role in roles (并发):
        training_games (N个 game_subgraph) → 
        consolidate (LLM) → 
        apply (LLM) → 
        battle (baseline vs candidate, M个 game_subgraph) →
        decide (promote/reject)
    ↓ barrier
    combined_battle → auto_promote?
    """
```

**操作细节:**
1. 复制 `run_evolution()` → `evolve_nodes.run_evolution_node`
2. self-play 用 `game_subgraph` 替代 `run_selfplay()`
3. consolidation LLM 调用走 `services/chain.py:consolidate_chain`
4. apply LLM 调用走 `services/chain.py:apply_chain`
5. battle 逻辑保留: `run_config_battle()` → `evolve_nodes.battle_node`

**验证:** `python -c "from app.graphs.subgraphs.evolve import build_evolve_graph"`

### Phase 4 验证
```bash
python -c "from app.graphs.subgraphs import agent, game, play, eval, evolve"
# 验证无 agent import
grep -r "from agent\." app/graphs/subgraphs/ && echo "FAIL" || echo "PASS"
# 验证 graph 不调 LLM
grep -r "ChatOpenAI\|model\.invoke\|llm\.invoke" app/graphs/subgraphs/ && echo "FAIL" || echo "PASS"
```

---

## Phase 5: `app/lib/` — 业务逻辑 [~6h]

> **前置:** Phase 1 + Phase 2 (依赖 `app/util/` + `app/services/chain.py`)
> **∥P{3,4}** (与 graph 层并行开发，只依赖 util + services)
>
> 7 个 lib 文件互不依赖（或依赖 chain.py），全可并行。

### Step 5.1 — `lib/game.py` — agents + engine 工厂 [~1h] ∥S{5.2,5.3,5.4,5.5,5.6,5.7}

**来源:** `agent/api/factory.py` + `agent/game_run/engine.py`

**操作:** 复制 `create_agents()` + `create_engine()` 逻辑
**新加:** `LangGraphAgent` 包装 — 把 LangGraph compiled graph 包装成 `PlayerAgent` 协议
```python
class LangGraphAgent:
    """Wraps compiled agent_subgraph as PlayerAgent protocol."""
    def __init__(self, graph: CompiledGraph, player_id: int, role: Role):
        self.graph = graph
        self.player_id = player_id
        self.role = role
    async def act(self, request: ActionRequest) -> ActionResponse:
        result = await self.graph.ainvoke({"request": request.to_dict(), ...})
        return ActionResponse(**result["response"])
```

**验证:** `python -c "from app.lib.game import create_agents, create_engine, LangGraphAgent"`

### Step 5.2 — `lib/store.py` — GamePersistence [~40min] ∥S{5.1,5.3,5.4,5.5,5.6,5.7}

**来源:** `agent/game_run/service.py` — `GameRunService` + `GameRunConfig` + `GameRunHandle`

**操作:** 近乎完整复制，替换 import
- `from agent.common` → `from app.util.paths`
- `from storage` → 保留（黑盒引用）

**验证:** `python -c "from app.lib.store import GameRunService, GameRunConfig, GameRunHandle"`

### Step 5.3 — `lib/review.py` — 复盘引擎 [~1h] ∥S{5.1,5.2,5.4,5.5,5.6,5.7}

**来源:** 合并 `agent/review/` 6 文件
- `agent/review/scoring.py` → 核心评分
- `agent/review/reviewer.py` → 复盘 LLM 调用 (→ `services/chain.py:evidence_chain`)
- `agent/review/evaluator.py` → 维度评分
- `agent/review/service.py` → ReviewService
- `agent/review/report.py` → PlayerReview / KeyDecisionReview
- `agent/review/report_gen.py` → Markdown 报告生成

**操作:** 合并到一个文件，LLM 调用改用 `app.services.chain`
**验证:** `python -c "from app.lib.review import analyze_game, ReviewService"`

### Step 5.4 — `lib/score.py` — 评测 + 排行榜 [~1h] ∥S{5.1,5.2,5.3,5.5,5.6,5.7}

**来源:**
- `agent/evaluation/metrics.py` → `PlayerScore`, `BatchScoreSummary`, `aggregate_batch_scores()`
- `agent/evaluation/stats.py` → `compute_role_score()`
- `agent/evaluation/fairness.py` → `FairnessResult`, `validate_role_version_comparison()`
- `agent/evaluation/leaderboard.py` → `compute_role_version_leaderboard_entry()`, `compute_model_leaderboard_entry()`
- `agent/evolution/leaderboard.py` → evolution 专属 leaderboard

**操作:** 合并到 `lib/score.py`，纯计算无 LLM 调用
**验证:** `python -c "from app.lib.score import aggregate_batch_scores, compute_role_score"`

### Step 5.5 — `lib/version.py` — 角色版本 [~1h] ∥S{5.1,5.2,5.3,5.4,5.6,5.7}

**来源:**
- `agent/evolution/registry.py` → `VersionRegistry` (47 symbols)
- `agent/evolution/pipeline.py` → `promote_version()`, `reject_version()`

**操作:** 合并，DB 写入保留 `storage/` 引用
**验证:** `python -c "from app.lib.version import VersionRegistry, promote_version"`

### Step 5.6 — `lib/evidence.py` — 证据 pipeline [~1h] ∥S{5.1,5.2,5.3,5.4,5.5,5.7}

**来源:**
- `agent/evidence/pipeline.py` → `EvidencePipeline`
- `agent/evidence/normalizer.py` → `EvidenceNormalizer`
- `agent/evidence/selector.py` → `EvidenceSelector`
- `agent/evidence/rubrics.py` → 评分标准
- `agent/evidence/models.py` → 全部 dataclass

**注意:** `judge.py` 的 LLM 调用已移到 `services/chain.py:evidence_chain`，此处不调 LLM
**验证:** `python -c "from app.lib.evidence import EvidencePipeline, EvidenceNormalizer, EvidenceSelector"`

### Step 5.7 — `lib/evolve.py` — dedup + config [~40min] ∥S{5.1,5.2,5.3,5.4,5.5,5.6}

**来源:**
- `agent/evolution/dedup.py` → `deduplicate_proposals()`
- `agent/evolution/config.py` → `EvolutionConfig`
- `agent/evolution/state.py` → `EvolutionStateManager`
- `agent/evolution/models.py` → `SkillConsolidation`, `SkillProposal`, `SkillDiff`, `KnowledgeDiff`, `EvolutionRun`

**操作:** 合并，纯 data class + 程序化逻辑，无 LLM
**验证:** `python -c "from app.lib.evolve import deduplicate_proposals, EvolutionConfig"`

### Phase 5 验证
```bash
python -c "from app.lib import game, store, review, score, version, evidence, evolve"
grep -r "ChatOpenAI\|model\.invoke\|llm\.invoke" app/lib/ && echo "FAIL: lib should not call LLM directly" || echo "PASS"
# lib 可以调 chain，不应调 model
grep -r "from app.services.chain" app/lib/ && echo "OK" || echo "OK (no chain dep needed)"
grep -r "from agent\." app/lib/ && echo "FAIL" || echo "PASS"
```

---

## Phase 6: `app/graphs/main/` — 根图 + `app/run.py` [~2h]

> **前置:** Phase 2 + Phase 3 + Phase 4 + Phase 5 (全部完成)
> **∥P{5}** (P5 lib 完成后开始)

### Step 6.1 — `graphs/main/router.py` — dispatch [~30min]

```python
def dispatch(run_type: str, state: dict) -> str:
    """Route to the correct sub-pipeline based on run_type."""
    if run_type == "play":
        return "play"
    elif run_type == "eval":
        return "eval"
    elif run_type == "evolve":
        return "evolve"
    else:
        raise ValueError(f"Unknown run_type: {run_type}")
```

### Step 6.2 — `graphs/main/builder.py` — 根图 [~1h]

```python
def build_root_graph() -> CompiledGraph:
    workflow = StateGraph(RootState)
    workflow.add_node("play", build_play_graph(...))
    workflow.add_node("eval", build_eval_graph(...))
    workflow.add_node("evolve", build_evolve_graph(...))
    
    workflow.add_conditional_edges(
        START,
        lambda s: dispatch(s["run_type"], s),
        {"play": "play", "eval": "eval", "evolve": "evolve"}
    )
    workflow.add_edge("play", END)
    workflow.add_edge("eval", END)
    workflow.add_edge("evolve", END)
    return workflow.compile()
```

**验证:** `python -c "from app.graphs.main import build_root_graph"`

### Step 6.3 — `app/run.py` — 入口 [~30min]

```python
"""app/run.py — 单一入口，替代 agent/ 调用链"""

from app.graphs.main import build_root_graph
from app.lib.store import GameRunService, GameRunConfig
from app.config import *

async def run_game(*, mode: str = "dev", player_count: int = 12, ...):
    """普通对战入口"""
    graph = build_root_graph()
    result = await graph.ainvoke({"run_type": "play", "config": ...})
    return result

async def run_evaluation(*, batch_config: dict, ...):
    """评测入口"""
    graph = build_root_graph()
    result = await graph.ainvoke({"run_type": "eval", "batch_config": batch_config})
    return result

async def run_evolution(*, role: str, training_games: int = 20, ...):
    """自进化入口"""
    graph = build_root_graph()
    result = await graph.ainvoke({"run_type": "evolve", "role": role, ...})
    return result
```

**验证:** `python -c "from app.run import run_game, run_evaluation, run_evolution"`

### Phase 6 验证
```bash
python -c "from app.run import run_game; print('OK')"
grep -r "from agent\." app/run.py app/graphs/main/ && echo "FAIL" || echo "PASS"
```

---

## Phase 7: UI Backend 适配 [~2h]

> **前置:** Phase 6 (根图可用)
> **∥P{6}** (可与 P6 并行，但联调需 P6)

### Step 7.1 — FastAPI routes 更新 [~1.5h]

**操作:**
- 替换 `from agent.api` → `from app.run`
- 替换 `from agent.evaluation` → `from app.run`
- 替换 `from agent.evolution` → `from app.run`

### Step 7.2 — SSE 端点适配 [~30min]

**操作:** 如果当前 SSE 使用了 `agent/` 的进度回调，改为从 LangGraph 的 streaming 模式

### Phase 7 验证
```bash
# 启动 UI
uv run uvicorn ui.backend.main:app --reload
# 手动测试: 创建游戏、跑评测
```

---

## Phase 8: 清理 + 最终验证 [~2h]

> **前置:** Phase 1-7 全部完成

### Step 8.1 — 全局校验 [~30min]

```bash
# 规则 1: app/ 零 agent 依赖
grep -r "from agent\." app/ && echo "FAIL (1)" || echo "PASS (1)"

# 规则 2: app/graphs/ 不调 LLM
grep -r "ChatOpenAI\|model\.invoke\|llm\.invoke" app/graphs/ && echo "FAIL (2)" || echo "PASS (2)"

# 规则 3: services/chain.py 有 ≥5 个 invoke 调用
grep "\.invoke" app/services/chain.py | wc -l  # → 应 >= 5

# 规则 4: agent/ 不再被外部引用
grep -r "from agent\." engine/ storage/ ui/ tests/ && echo "WARN (4)" || echo "PASS (4)"
```

### Step 8.2 — 测试验证 [~1h]

```bash
# 如果有测试
uv run pytest tests/ -x -q
# 冒烟测试
python -c "from app.run import run_game; import asyncio; asyncio.run(run_game(mode='dev'))"
```

### Step 8.3 — 标记 agent/ 废弃 [~30min]

在 `agent/__init__.py` 顶部添加：
```python
"""
Deprecated. Use app/ instead.
This package is kept for reference until app/ is fully validated.
"""
import warnings
warnings.warn("agent/ is deprecated, use app/ instead", DeprecationWarning)
```

---

## 并行度总览

```
Phase 0 ─── (骨架, 30min)
  │
  ├─ Phase 1 (util/, 2h) ─── ∥P{0}
  │
  ├─ Phase 2 (services/, 8h) ─── ∥P{1}
  │    ├─ 2.2 tool.py ∥S{2.3, 2.4}
  │    ├─ 2.3 memory.py ∥S{2.2, 2.4}
  │    └─ 2.4 prompt.py ∥S{2.2, 2.3}
  │
  ├─ Phase 3 (graphs/shared/, 3h) ─── ∥P{2}
  │    ├─ 3.2 review ∥S{3.3}
  │    └─ 3.3 evidence ∥S{3.2}
  │
  ├─ Phase 4 (graphs/subgraphs/, 10h) ─── → P{2,3}
  │    ├─ 4.1 agent ∥S{4.2}        ─── 2.5h
  │    ├─ 4.2 game ∥S{4.1}         ─── 2h
  │    ├─ 4.3 play ∥S{4.4,4.5}     ─── 1.5h  (依赖 4.1+4.2)
  │    ├─ 4.4 eval ∥S{4.3,4.5}     ─── 2h    (依赖 4.1+4.2)
  │    └─ 4.5 evolve ∥S{4.3,4.4}   ─── 2.5h  (依赖 4.1+4.2)
  │
  ├─ Phase 5 (lib/, 6h) ─── ∥P{3,4} (仅依赖 P1+P2)
  │    └─ 5.1-5.7 全可并行 (7 人同时开工)
  │
  ├─ Phase 6 (graphs/main/ + run.py, 2h) ─── → P{4,5}
  │
  ├─ Phase 7 (UI backend, 2h) ─── → P{6}
  │
  └─ Phase 8 (清理验证, 2h) ─── → P{7}
```

### 关键并行策略

| 策略 | 说明 |
|------|------|
| **跨 Phase 并行** | P1(util) + P2(services) + P3(shared) 可由 3 人并行 |
| **Phase 内并行** | P2: tool/memory/prompt 三人并行；P4: agent+game 双人并行后 play+eval+evolve 三人并行 |
| **独立流并行** | P4(graphs) 和 P5(lib) 可以并行，因为 lib 只依赖 P1+P2，不依赖 graph |
| **最短路径** | 单人串行约 **35h**；3 人并行约 **15h**；6 人并行约 **10h** |

### 风险点

| 风险 | Phase | 缓解 |
|------|-------|------|
| LangGraph checkpoint 不兼容现有存储 | P4 | 先用 `MemorySaver`，验证后再换 `SqliteSaver` |
| Tool calling 输出格式与现有 parser 不兼容 | P2,P4 | 保留 JSON parser 作为 fallback（双模式） |
| 自进化 pipeline 复杂度高 | P4.5 | 保留现有的回调驱动模式，逐步替换为图节点 |
| UI 耦合太深 | P7 | 保持 agent/ API 不变，用 adapter 包装 app/ |
| 无测试覆盖 | P8 | 在每个 phase 验证后立即跑冒烟测试 |

---

## 附录 A: 完整文件映射 (61 files → 38 files)

> 每个 `agent/` 文件都能在映射中找到目标。标记 `→X` 表示 LLM 调用逻辑移入 `services/chain.py`，其余逻辑移入 `X`。

### agent/api/ (2 → 2)

| 旧文件 | 新文件 | Phase |
|--------|--------|-------|
| `api/runtime.py` | `graphs/subgraphs/agent/nodes.py` + `builder.py` | P4.1 |
| `api/factory.py` | `lib/game.py` | P5.1 |

### agent/common/ (8 → app/util/ 8)

| 旧文件 | 新文件 | Phase |
|--------|--------|-------|
| `common/json.py` | `util/json.py` | P1.1 |
| `common/action_types.py` | `util/action_types.py` | P1.2 |
| `common/coercion.py` | `util/coercion.py` | P1.3 |
| `common/errors.py` | `util/errors.py` | P1.3 |
| `common/time.py` | `util/time.py` | P1.3 |
| `common/winner.py` | `util/winner.py` | P1.3 |
| `common/paths.py` | `util/paths.py` | P1.3 |
| `common/callbacks.py` | `util/callbacks.py` | P1.3 |

### agent/core/ (3 → 2)

| 旧文件 | 新文件 | Phase |
|--------|--------|-------|
| `core/context.py` | `graphs/shared/state.py` | P3.1 |
| `core/memory.py` | `services/memory.py` (AgentMemory) | P2.3 |
| `core/memory_segments.py` | `services/memory.py` (Segment, CompressedSegmentSummary) | P2.3 |

### agent/decision/steps/ (7 → 3)

| 旧文件 | 新文件 | Phase |
|--------|--------|-------|
| `decision/steps/remember.py` | `graphs/subgraphs/agent/nodes.py` | P4.1 |
| `decision/steps/compress_memory.py` | `services/chain.py:compress_chain` + `graphs/subgraphs/agent/nodes.py` | P2.5 + P4.1 |
| `decision/steps/select_skills.py` | `graphs/subgraphs/agent/nodes.py` (路由逻辑在 `services/prompt.py`) | P4.1 |
| `decision/steps/build_prompt.py` | `graphs/subgraphs/agent/nodes.py` (prompt 构建在 `services/prompt.py`) | P4.1 |
| `decision/steps/call_model.py` | `services/chain.py:decision_chain` + `graphs/subgraphs/agent/nodes.py` | P2.5 + P4.1 |
| `decision/steps/parse_output.py` | `graphs/subgraphs/agent/nodes.py` | P4.1 |
| `decision/steps/enforce_policy.py` | `graphs/subgraphs/agent/nodes.py` | P4.1 |

### agent/infrastructure/ (4 → 3)

| 旧文件 | 新文件 | Phase |
|--------|--------|-------|
| `infrastructure/llm.py` | `services/llm.py` | P2.1 |
| `infrastructure/decision_log.py` | `lib/store.py` (DecisionRecord 模型) | P5.2 |
| `infrastructure/archive.py` | `lib/store.py` (GameArchive, AgentTraceRecorder) | P5.2 |
| `infrastructure/tracing.py` | `util/callbacks.py` (Langfuse 回调) | P1.3 |

### agent/knowledge/ (5 → 1)

| 旧文件 | 新文件 | Phase |
|--------|--------|-------|
| `knowledge/prompts/base.py` | `services/prompt.py` | P2.4 |
| `knowledge/prompts/instructions.py` | `services/prompt.py` | P2.4 |
| `knowledge/prompts/parsing.py` | `services/prompt.py` | P2.4 |
| `knowledge/skills/loader.py` | `services/prompt.py` | P2.4 |
| `knowledge/skills/router.py` | `services/prompt.py` | P2.4 |

### agent/evaluation/ (6 → 2)

| 旧文件 | 新文件 | Phase |
|--------|--------|-------|
| `evaluation/runner.py` | `graphs/subgraphs/eval/` (graph) + `lib/score.py` (聚合) | P4.4 + P5.4 |
| `evaluation/config.py` | `lib/score.py` | P5.4 |
| `evaluation/metrics.py` | `lib/score.py` | P5.4 |
| `evaluation/stats.py` | `lib/score.py` | P5.4 |
| `evaluation/fairness.py` | `lib/score.py` | P5.4 |
| `evaluation/leaderboard.py` | `lib/score.py` | P5.4 |

### agent/evidence/ (6 → 2)

| 旧文件 | 新文件 | Phase |
|--------|--------|-------|
| `evidence/judge.py` | `services/chain.py:evidence_chain` (LLM) + `lib/evidence.py` (非LLM) | P2.5 + P5.6 |
| `evidence/pipeline.py` | `graphs/shared/nodes/evidence.py` | P3.3 |
| `evidence/models.py` | `lib/evidence.py` | P5.6 |
| `evidence/normalizer.py` | `lib/evidence.py` | P5.6 |
| `evidence/selector.py` | `lib/evidence.py` | P5.6 |
| `evidence/rubrics.py` | `lib/evidence.py` | P5.6 |

### agent/evolution/ (13 → 4)

| 旧文件 | 新文件 | Phase |
|--------|--------|-------|
| `evolution/pipeline.py` | `lib/version.py` (promote/reject) + `graphs/subgraphs/evolve/` | P5.5 + P4.5 |
| `evolution/batch.py` | `graphs/subgraphs/evolve/nodes.py` | P4.5 |
| `evolution/battle.py` | `graphs/subgraphs/evolve/nodes.py` | P4.5 |
| `evolution/games.py` | `graphs/subgraphs/evolve/nodes.py` (selfplay) | P4.5 |
| `evolution/consolidation.py` | `services/chain.py:consolidate_chain` (LLM) + `lib/evolve.py` | P2.5 + P5.7 |
| `evolution/applier.py` | `services/chain.py:apply_chain` (LLM) + `lib/evolve.py` | P2.5 + P5.7 |
| `evolution/dedup.py` | `lib/evolve.py` | P5.7 |
| `evolution/config.py` | `lib/evolve.py` | P5.7 |
| `evolution/state.py` | `lib/evolve.py` | P5.7 |
| `evolution/models.py` | `lib/evolve.py` | P5.7 |
| `evolution/registry.py` | `lib/version.py` | P5.5 |
| `evolution/leaderboard.py` | `lib/score.py` | P5.4 |

### agent/review/ (6 → 2)

| 旧文件 | 新文件 | Phase |
|--------|--------|-------|
| `review/scoring.py` | `lib/review.py` | P5.3 |
| `review/reviewer.py` | `graphs/shared/nodes/review.py` (LLM) + `lib/review.py` | P3.2 + P5.3 |
| `review/evaluator.py` | `lib/review.py` | P5.3 |
| `review/service.py` | `lib/review.py` | P5.3 |
| `review/report.py` | `lib/review.py` | P5.3 |
| `review/report_gen.py` | `lib/review.py` | P5.3 |

### agent/game_run/ (2 → 2)

| 旧文件 | 新文件 | Phase |
|--------|--------|-------|
| `game_run/engine.py` | `lib/game.py` (create_engine) + `graphs/subgraphs/game/` | P5.1 + P4.2 |
| `game_run/service.py` | `lib/store.py` | P5.2 |

### 汇总

| 旧 (agent/) | 新 (app/) | 变化 |
|---|---|---|
| 76 files (含 15 `__init__`) | ~38 files | **50% 减少** |
| 13 个顶层目录 | 5 个顶层目录 | **62% 减少** |
| 5+ 处调 LLM | 1 处调 LLM (`chain.py`) | **80% 集中** |
| 手写 pipeline | LangGraph StateGraph | **编排升级** |
