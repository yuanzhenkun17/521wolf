# app/ — 目标架构

> 完全取代旧 `agent/`。零 `from agent.` import。`engine/` `storage/` 黑盒。
> LangGraph = 流程编排。LangChain = 能力组件。

---

## 一、目录

```
app/
├── __init__.py
├── config.py
├── run.py
│
├── graphs/
│   ├── main/
│   │   ├── builder.py            # 根图: dispatch → play / eval / evolve
│   │   └── router.py             # dispatch(run_type)
│   │
│   ├── subgraphs/
│   │   ├── agent/                # ★ 可复用子图: 7步决策
│   │   │   ├── builder.py
│   │   │   └── nodes.py
│   │   │
│   │   ├── game/                 # ★ 可复用子图: 跑一局
│   │   │   ├── builder.py
│   │   │   └── nodes.py
│   │   │
│   │   ├── play/                 # pipeline: 普通对战
│   │   │   ├── builder.py
│   │   │   └── nodes.py
│   │   │
│   │   ├── eval/                 # pipeline: 批量评测
│   │   │   ├── builder.py
│   │   │   └── nodes.py
│   │   │
│   │   └── evolve/               # pipeline: 自进化
│   │       ├── builder.py
│   │       └── nodes.py
│   │
│   └── shared/
│       ├── state.py              # 全部 TypedDict
│       └── nodes/                # 通用节点 (被多个 pipeline 共用)
│           ├── review.py         # 复盘 (play / eval 共用)
│           └── evidence.py       # 证据 (evolve 用)
│
├── services/                     # ★ 纯 LangChain 能力组件
│   ├── llm.py                    # ChatOpenAI 工厂
│   ├── chain.py                  # ★ 5 个 LCEL chain (唯一调 LLM)
│   ├── tool.py                   # 17 个 @tool
│   ├── memory.py                 # BaseChatMessageHistory
│   └── prompt.py                 # ChatPromptTemplate + skill
│
├── lib/                          # 业务逻辑 — 被 graph node 调用
│   ├── game.py                   # agents + engine 工厂
│   ├── store.py                  # GamePersistence
│   ├── review.py                 # 复盘引擎
│   ├── score.py                  # 评测 + 排行榜
│   ├── version.py                # 角色版本
│   ├── evidence.py               # 证据 pipeline
│   └── evolve.py                 # dedup + config
│
└── util/
    ├── action_types.py
    ├── callbacks.py
    ├── coercion.py
    ├── errors.py
    ├── json.py
    ├── paths.py
    ├── time.py
    └── winner.py
```

---

## 二、职责边界

| 目录 | 是什么 | 调 LLM？ |
|---|---|---|
| `graphs/main/` | 根图 dispatch | ❌ |
| `graphs/subgraphs/` | pipeline 图 + 可复用子图 | ❌ |
| `graphs/shared/state.py` | 全部 TypedDict | ❌ |
| `graphs/shared/graphs/` | 被 subgraphs 复用的子图 | ❌ |
| `graphs/shared/nodes/` | 被多个 pipeline 共用的节点 | ❌ |
| `services/` | LangChain 组件 (model/chain/tool/memory/prompt) | ✅ chain.py |
| `lib/` | 业务逻辑 (工厂/评分/版本/证据) | ❌ 调 chain，不调 model |

---

## 三、迁移映射

### graphs/ — 新写

| 文件 | 替代 |
|---|---|
| `main/builder.py` + `router.py` | — |
| `subgraphs/agent/*` | `agent/api/runtime.py` + `agent/decision/steps/*` (9 files) |
| `subgraphs/game/*` | `agent/game_run/engine.py` + 编排 |
| `subgraphs/play/*` | UI game_runner |
| `subgraphs/eval/*` | `agent/evaluation/runner.py` |
| `subgraphs/evolve/*` | `agent/evolution/pipeline.py` + `battle.py` + `batch.py` |
| `shared/state.py` | `agent/core/context.py` |
| `shared/graphs/agent.py` | — |
| `shared/graphs/game.py` | — |
| `shared/nodes/review.py` | — |
| `shared/nodes/evidence.py` | — |

### services/ — LangChain 化

| 文件 | 旧位置 | 操作 |
|---|---|---|
| `llm.py` | `agent/infrastructure/llm.py` | ChatOpenAI |
| `chain.py` | `agent/decision/steps/call_model.py` + `compress_memory.py` + `agent/evolution/consolidation.py` + `applier.py` + `agent/evidence/judge.py` | **5 个 LCEL chain** |
| `tool.py` | 新写 | 17 个 @tool |
| `memory.py` | `agent/core/memory.py` + `memory_segments.py` | |
| `prompt.py` | `agent/knowledge/` 全部 7 文件 | |

### lib/ — 从 agent/ 迁移

| 文件 | 旧位置 | 操作 |
|---|---|---|
| `game.py` | `agent/api/factory.py` + `agent/game_run/engine.py` + `agent/evolution/games.py`(SelfPlayConfig/SelfPlayGameResult) | +LangGraphAgent + dataclass |
| `store.py` | `agent/game_run/service.py` | 复制 |
| `review.py` | `agent/review/*` (6 files) | 合并, 含 generate_enhanced_review |
| `score.py` | `agent/evaluation/{metrics,stats,fairness,leaderboard}.py` + `agent/evolution/leaderboard.py` + `EvaluationBatchConfig` | 合并 + 配置 dataclass |
| `version.py` | `agent/evolution/registry.py` + `pipeline.py`(promote/reject/scan_active_runs) | 合并, scan 改为扫描 checkpoint DB |
| `evidence.py` | `agent/evidence/{pipeline,normalizer,selector,rubrics}.py` | 合并 (judge 逻辑已移到 services/chain.py) |
| `evolve.py` | `agent/evolution/{dedup,config}.py` + `models.py`(EvolutionRun,SkillConsolidation,SkillProposal) | 合并 + dataclass |

---

## 四、依赖

```
graphs → services/chain.py → services/llm.py → API
graphs → lib/* (被 node 调用)
graphs → engine (GameEngine)
graphs → storage (GamePersistence)
lib    → services/chain.py (evidence/lib.review 调 LLM)
lib    → util
services → util

硬规则:
- graphs/ 不含 ChatOpenAI / model.invoke()
- services/chain.py 是唯一调 LLM 的地方
- app/ 不含 from agent.
```

---

## 五、LLM 调用点 (5 个, 全部在 services/chain.py)

| # | chain | 作用 |
|---|---|---|
| 1 | `decision_chain` | 每步决策 (tool calling) |
| 2 | `compress_chain` | 记忆压缩 |
| 3 | `consolidate_chain` | 经验→提案 |
| 4 | `apply_chain` | 提案→改写技能 |
| 5 | `evidence_chain` | 证据评估 |

---

## 六、文件数量

| | 旧 | 新 |
|---|---|---|
| app/ | — | **~38 files, 5 个顶级目录** |
| agent/ | 76 files | 保留废弃 |

---

## 七、验证

- [ ] `grep -r "from agent\." app/` → 0
- [ ] `grep -r "ChatOpenAI\|model\.invoke\|llm\.invoke" app/graphs/` → 0
- [ ] `grep "\.invoke" app/services/chain.py` → ≥ 5
- [ ] `uv run pytest tests/ -x -q` → pass
- [ ] `from app.run import run_game` → 跑通
