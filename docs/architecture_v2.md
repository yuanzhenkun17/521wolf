# Architecture: Self-Evolution & Battle Separation

> 本文档记录了 2026-06-04 完成的架构重构，涵盖存储层分离、记忆系统升级、知识版本控制、评测管线和 UI 路由拆分。

---

## 1. 设计原则

```
┌─────────────────────────────────────────────────────────┐
│                   版本注册中心 (Registry)                 │
│         Evolution 写入  ←  唯一交汇点  →  Battle 只读     │
└─────────────┬───────────────────────────┬───────────────┘
              │                           │
   ┌──────────▼──────────┐     ┌──────────▼──────────┐
   │   自进化系统          │     │   对战评测系统        │
   │   (Evolution)       │     │   (Battle)          │
   │                     │     │                     │
   │  训练 → 归纳 → 应用   │     │  对战 → 评测 → 复盘  │
   │  → A/B 对战 → 晋升   │     │  → 报告 → 排行榜     │
   │                     │     │                     │
   │  数据: evolution.db  │     │  数据: wolf.db       │
   └─────────────────────┘     └─────────────────────┘
              │                           │
   ┌──────────┴───────────────────────────┴──────────┐
   │              共享底层 (Shared)                    │
   │  engine/  agent/core/  agent/knowledge/          │
   │  agent/api/  agent/infrastructure/               │
   └──────────────────────────────────────────────────┘
```

**核心原则：**

1. **数据隔离**：`wolf.db`（对局+评测）和 `evolution.db`（进化学习）是两个独立的 SQLite 文件。Registry（文件系统）是两个系统的唯一交汇点。
2. **职责分离**：进化只管产出更好的版本，对战只管拿版本来打并评测。两者在每层内部通过子目录分离，而不是打散层结构。
3. **四层不变**：Engine（规则）、Agent（决策）、Storage（持久化）、UI（接口/界面）四层架构保持不变，在每层内部用子模块实现关注点分离。
4. **向后兼容**：`storage/__init__.py` 通过 facade re-export 保持旧导入路径可用；UI 路由路径不变；旧文件不删除。

---

## 2. 四层架构

### 2.1 Engine 层 — 不变

纯规则引擎，不知道上层在跑对战还是进化。

```
engine/
  config.py          # GameConfig, STANDARD_12
  engine.py          # GameEngine 主循环
  models.py          # Role, Phase, ActionType, Observation, ActionRequest/Response
  actions.py         # ask() 动作请求
  players.py         # PlayerAgent protocol, ScriptedAgent, HumanPlayer
  phases/            # night.py, day.py, exile.py, sheriff.py
  role_rules/        # 每个身份的技能规则
  rules/             # victory.py, death.py, voting.py, sheriff.py
```

### 2.2 Agent 层 — 核心共享，Runner 分离

```
agent/
  core/
    memory.py              # AgentMemory（运行时短期记忆，已修复 Bug）
    context.py             # AgentContext（管线状态，新增 memory_injection 字段）
    episodic_memory.py     # ★ 新增：跨局情景记忆持久化

  decision/
    steps/
      remember.py          # 记忆更新
      select_skills.py     # 技能路由
      inject_memory.py     # ★ 新增：跨局记忆注入（Pattern + 情景）
      build_prompt.py      # 组装 Prompt（已支持 memory_injection）
      call_model.py        # 调用 LLM
      parse_output.py      # 解析输出
      enforce_policy.py    # 策略校验

  knowledge/
    skills/loader.py       # Markdown 技能加载
    skills/router.py       # 技能路由（按身份 + 动作 + 条件）
    prompts/               # Prompt 模板

  api/
    runtime.py             # AgentRuntime（6→7 步决策管线）
    factory.py             # create_agents()

  runner/                  # ★ 新增：分离的 Runner
    __init__.py
    shared.py              # create_engine(), create_agents_for_game()
    battle_runner.py       # BattleRunner（支持人类玩家、实时事件、评测）
    evolution_runner.py    # EvolutionRunner（批量、固定种子、mid-memory）

  evolution/               # ★ 新增：进化子系统
    __init__.py
    models.py              # KnowledgePackage, Pattern, ProvenanceRecord, BattleMetrics
    registry.py            # VersionRegistry（文件系统版本注册中心）
    pattern_engine.py      # PatternEngine（Beta-Binomial 贝叶斯更新）
    evaluator.py           # GameEvaluator（5 维规则评分）
    reviewer.py            # GameReviewer（决策复盘 + 反事实推演）
    report.py              # ReportGenerator（结构化报告）
    dedup.py               # deduplicate_proposals()（Jaccard 去重）

  infrastructure/          # 共享：LLM、追踪、归档
  common/                  # 共享：路径、JSON、时间等工具
  learning_v2/             # 现有进化管线（已升级）
    evolution/
      pipeline.py          # 进化状态机（新增 pattern_engine 参数）
      consolidation.py     # 归纳（已集成 dedup，已标记旧路径 deprecated）
      battle.py            # A/B 测试（新增最低有效局数检查）
      ...
```

### 2.3 Storage 层 — 双库分离

```
storage/
  __init__.py              # facade re-export（向后兼容）

  shared/                  # ★ 新增：共享基础设施
    connection.py          # get_evolution_connection()
    interfaces.py          # compute_hash (12 hex), normalize, 数据类
    models.py              # 共享数据类

  battle/                  # ★ 新增：对战数据库
    schema.py              # 9 表：games, players, decisions, game_events
                           #        + evaluations, decision_reviews,
                           #          counterfactuals, reports, leaderboard
    game_repo.py           # GameStore
    event_repo.py          # GameEventStore
    decision_repo.py       # DecisionStore
    evaluation_repo.py     # ★ EvaluationStore
    review_repo.py         # ★ DecisionReviewStore, CounterfactualStore
    report_repo.py         # ★ ReportStore
    leaderboard_repo.py    # ★ BattleLeaderboardStore

  evolution/               # ★ 新增：进化数据库
    schema.py              # 8 表：evolution_runs, skill_proposals,
                           #        role_versions, experience_candidates
                           #        + patterns, rejected_proposals,
                           #          situational_records, decision_outcomes
    run_repo.py            # EvolutionStore
    pattern_repo.py        # ★ PatternStore
    experience_repo.py     # ExperienceCandidateStore
    rejected_repo.py       # ★ RejectedProposalStore
    version_repo.py        # VersionStoreDB
    situational_repo.py    # ★ SituationalRecordStore
    outcome_repo.py        # ★ DecisionOutcomeStore
```

**数据库隔离：**

| | wolf.db | evolution.db |
|---|---|---|
| 对局记录 | games, players, game_events, decisions | — |
| 评测数据 | evaluations, decision_reviews, counterfactuals, reports | — |
| 排行榜 | leaderboard (多维评分) | — |
| 进化 run | — | evolution_runs, skill_proposals |
| Pattern | — | patterns |
| 情景记忆 | — | situational_records, decision_outcomes |
| 经验候选 | — | experience_candidates |
| 被拒提案 | — | rejected_proposals |
| 版本元数据 | — | role_versions |

### 2.4 UI 层 — 路由模块化

```
ui/backend/
  app.py                   # 143 行（从 1475 行精简）
  shared/
    helpers.py             # DI 函数、共享工具
  battle/
    game_routes.py         # /api/games/* (8 routes)
    leaderboard_routes.py  # /api/leaderboards (1 route)
  evolution/
    run_routes.py          # /api/role-evolution/* (26 routes)
    batch_routes.py        # /api/role-evolution/batch/* (8 routes)
    version_routes.py      # /api/roles/* (5 routes)
    facade_routes.py       # /api/evolution-runs/* (10 routes)
  game_adapter/
    adapter_routes.py      # /api/game/* (7 routes)
    selfplay_routes.py     # /api/selfplay/* (10 routes)
```

所有路由使用 FastAPI `APIRouter`，通过 `app.include_router()` 注册。路径与原版完全一致。

---

## 3. 记忆系统：三层架构

### 3.1 短期记忆（单局内）

`agent/core/memory.py` — `AgentMemory` 类

| 组件 | 说明 | 上限 |
|------|------|------|
| events | 公开事件时间线 | 200 |
| phase_events | 按阶段分组的事件 | — |
| rolling_summary | 冷阶段压缩摘要 | 30 |
| pinned_facts | 关键事实（优先级加权驱逐） | 80 |
| self_commitments | 自己的公开口径 | 24 |
| field_notes | 结构化现场（玩家画像、投票） | — |
| player_models | 每个玩家的行为追踪 | — |

**已修复的 Bug：**
- `_pinned_fact_keys` 随 `pinned_facts` 一起驱逐（不再永久信息丢失）
- 驱逐策略从 FIFO 改为优先级加权（sheriff > death > role_claim > check > general）
- `extract_claimed_role` 新增否定词检测（"不是预言家" 不再误判为声称预言家）

### 3.2 情景记忆（跨局）

`agent/core/episodic_memory.py` — `EpisodicMemoryWriter`

每局结束后，从 `AgentMemory` 和决策记录中提取结构化数据，持久化到 `evolution.db`：

| 记录类型 | 存储位置 | 内容 |
|---------|---------|------|
| SituationalRecord | situational_records | 身份、座位、存活玩家、关键事件、胜负 |
| DecisionOutcome | decision_outcomes | 决策 ID、动作、质量标签（good/bad/neutral/uncertain）、原因 |

**决策质量标签规则（按身份）：**

| 身份 | 好决策 | 坏决策 |
|------|--------|--------|
| 预言家 | 查验到狼人 | — |
| 女巫 | 救了神职 | 毒了队友 |
| 守卫 | 守了被刀的人 | — |
| 狼人 | 杀了神职 | 杀了普通村民 |
| 猎人 | 带走了狼人 | — |
| 村民 | 投票放逐了狼人 | 投票放逐了队友 |

### 3.3 Pattern 库（统计规律）

`agent/evolution/pattern_engine.py` — `PatternEngine`

Pattern 是从大量对局中发现的 situation-action 统计规律：

```python
Pattern:
  situation:      "seer:seer_check:night:early"
  recommendation: "查验座位号相邻的玩家"
  win_rate_with:  0.62    # 执行此推荐时的胜率
  win_rate_without: 0.41  # 不执行时的胜率
  sample_size:    47
  confidence:     0.85
  status:         "crystallized"
  alpha/beta:     Beta 分布参数（贝叶斯后验）
```

**生命周期：**

```
candidate (confidence < 0.3)
  → active (samples >= 10, confidence >= 0.3)
    → crystallized (samples >= 30, confidence >= 0.7)
      → archived (confidence < 0.2 after 50+ samples)
        → deprecated (长期未命中)
```

**贝叶斯更新：** 每局结束后，对每个关键决策进行 Beta-Binomial 共轭更新：
- 赢了 → alpha += 1
- 输了 → beta += 1
- win_rate = alpha / (alpha + beta)
- confidence = |mean - 0.5| × 2 × concentration

### 3.4 运行时记忆注入

`agent/decision/steps/inject_memory.py`

在决策管线中，技能路由之后、Prompt 组装之前，注入跨局知识：

```
ActionRequest
  → remember_step       (短期记忆)
  → select_skills_step  (Markdown 技能)
  → inject_memory_step  (★ Pattern + 情景记忆)
  → build_prompt_step   (组装 Prompt)
  → call_model_step     (调用 LLM)
  → parse_output_step   (解析输出)
  → enforce_policy_step (策略校验)
  → ActionResponse
```

注入格式：
```
已注入经验记忆:
经验规律:
- [confidence=0.85] 首夜作为女巫救预言家 (胜率62%, 47局)
- [confidence=0.72] 第2天白天作为预言家跳身份 (胜率55%, 31局)

历史案例:
- 第3天白天作为预言家查验了P5(狼人)，最终获胜
- 第1天夜晚作为女巫没救P3(村民)，最终失败
```

---

## 4. 知识版本控制（Registry）

### 4.1 KnowledgePackage

替代原来的 `RoleVersion`，是一个角色的完整知识快照：

```
KnowledgePackage:
  version_id:    "a1b2c3d4e5f6"  (12 hex, 内容寻址)
  role:          "seer"
  parent_id:     "f6e5d4c3b2a1"
  skills:        [SkillFileRef]       # 技能文件引用（路径 + 内容 hash）
  patterns:      [Pattern dict]       # 活跃 + 结晶的 Pattern
  provenance:    ProvenanceRecord     # 来源追踪
  metrics:       BattleMetrics | None # A/B 对战指标
  created_at:    "2026-06-04T..."
```

### 4.2 VersionRegistry

`agent/evolution/registry.py` — 文件系统版本注册中心

**磁盘布局：**
```
data/registry/
  <role>/
    baseline.json              # {"version_id": "...", "updated_at": "..."}
    history.jsonl              # append-only 事件日志
    versions/
      <version_id>/
        package.json           # KnowledgePackage 元数据
        patterns.json          # Pattern 列表
        metrics.json           # BattleMetrics
        skills/
          *.md                 # 技能文件（唯一真实来源）
```

**API：**

| 操作 | 方法 | 说明 |
|------|------|------|
| 发布 | `publish(package, skill_contents)` | 创建版本目录，写入文件，追加 history 事件 |
| 设置基线 | `set_baseline(role, version_id, expected_current)` | CAS 更新 |
| 拒绝 | `reject(role, version_id, reason)` | 追加 rejected 事件 |
| 获取基线 | `get_baseline(role)` | 返回当前基线 version_id |
| 加载版本 | `get_package(role, version_id)` | 加载 KnowledgePackage |
| 列出版本 | `list_versions(role)` | 返回 VersionSummary 列表 |
| 差异对比 | `diff(role, old_id, new_id)` | 返回 KnowledgeDiff |
| 垃圾回收 | `gc(role, keep)` | 保留基线祖先链 + 最近 N 版 |
| 构建技能目录 | `build_skill_dir(role_versions)` | 创建临时复合目录供引擎使用 |

**版本历史（history.jsonl）：**
```jsonl
{"event": "created", "version_id": "v1", "parent": null, "source": "seed", "ts": "..."}
{"event": "baseline_set", "version_id": "v1", "from": null, "ts": "..."}
{"event": "created", "version_id": "v2", "parent": "v1", "source": "evolution", "ts": "..."}
{"event": "rejected", "version_id": "v2", "reason": "win_rate_delta=-0.03", "ts": "..."}
{"event": "baseline_set", "version_id": "v3", "from": "v1", "ts": "..."}
```

**与旧版 VersionStore 的区别：**

| | VersionStore (旧) | VersionRegistry (新) |
|---|---|---|
| 版本内容 | 仅 Markdown 技能文件 | 技能 + Pattern + 指标 + 来源 |
| Hash 长度 | 8 hex (32 bit) | 12 hex (48 bit) |
| 历史格式 | history.json (read-modify-write) | history.jsonl (append-only) |
| 技能存储 | meta.json 内嵌 + 磁盘文件（双份） | 磁盘文件为唯一来源 |
| 差异对比 | 无 API | KnowledgeDiff (技能 + Pattern + 指标) |
| 垃圾回收 | 无 | 保留基线祖先链 + 最近 N 版 |
| 缓存失效 | mtime（不可靠） | version_id 显式路由 |

---

## 5. 评测管线

### 5.1 多维评分 (Evaluator)

`agent/evolution/evaluator.py` — `GameEvaluator`

对每个玩家计算 5 个维度的评分（0-1 范围）：

| 维度 | 评分规则 |
|------|---------|
| **speech_score** | 基础 0.5 + 提及玩家数（信息密度）+ 怀疑准确度 - 过短发言惩罚 |
| **vote_score** | 基础 0.5 + 投票与怀疑一致 + 投票符合阵营利益 - 投了队友 |
| **skill_score** | 按身份特判：预言家查到狼 +0.2，女巫救神 +0.2，毒队友 -0.2 |
| **information_score** | 预言家及时报查验 +0.2，狼人协同 +0.15，村民用信息投票 +0.15 |
| **cooperation_score** | 同阵营投票一致度 + 保护队友 + 获胜奖励 |

### 5.2 决策复盘 (Reviewer)

`agent/evolution/reviewer.py` — `GameReviewer`

1. **识别转折点决策**：狼人杀神、女巫救/毒、放逐关键玩家、预言家查到狼、猎人开枪、白狼王自爆
2. **标注决策质量**：good / bad / questionable + 理由 + 替代方案
3. **生成反事实推演**：「如果 P3 没有毒 P5，好人阵营可能获胜」

### 5.3 结构化报告 (Report)

`agent/evolution/report.py` — `ReportGenerator`

报告包含：
- **game_summary**：胜负、天数、阵营平均分、死亡/放逐统计
- **player_scores**：每个玩家的 5 维雷达图数据
- **turning_points**：关键时刻分析
- **counterfactuals**：反事实推演
- **timeline**：重大事件时间线

### 5.4 排行榜 (Leaderboard)

新增 `wolf.db` 的 `leaderboard` 表，支持：
- 按身份排名
- 按版本排名（对比不同进化版本的表现）
- 多维评分趋势

---

## 6. 进化管线升级

### 6.1 提案去重

`agent/evolution/dedup.py` — `deduplicate_proposals()`

在归纳阶段 LLM 生成提案后、应用之前，程序化过滤与被拒提案重复的新提案：

1. **精确匹配**：相同 `target_file` + 相同 `action_type` → 自动拒绝
2. **内容相似度**：Jaccard 相似度（中文 2-4 字 n-gram）> 0.7 → 标记为重复

### 6.2 Pattern 生命周期管理

在进化周期的归纳阶段前，运行 Pattern GC：
- **归档**：confidence < 0.2 且 samples >= 50 的 Pattern
- **废弃**：长期未命中（< 1% 查询率，200+ 局后）的 Pattern
- **蒸馏触发**：crystallized 的 Pattern 可被 LLM 转化为 Markdown 技能规则

### 6.3 归纳路径统一

- `consolidate_from_mid_memories` 已标记 deprecated
- 统一到 `consolidate_for_role` 路径
- `_run_long_term_consolidation` 添加 TODO 注释待迁移

### 6.4 SQLite 连接隔离

- `_load_experience_candidates_for_role` 的 `sqlite3.connect()` 添加 `timeout=30`
- 替换宽泛的 `except Exception` 为具体的 `sqlite3.OperationalError`
- 数据库锁定时重试一次（1 秒后）

### 6.5 A/B 测试增强

- 新增最低有效局数检查：任一侧 > 30% 错误对局则判定不显著
- Hash 扩展到 12 hex（碰撞概率从 ~65K 降到 ~16M）

---

## 7. Runner 分离

### 7.1 BattleRunner

```python
class BattleRunner:
    async def run_game(self, config: BattleGameConfig) -> BattleGameResult
```

| 特性 | BattleRunner | EvolutionRunner |
|------|-------------|-----------------|
| 人类玩家 | 支持 | 不支持 |
| 种子 | 随机 | 固定（可复现） |
| 实时事件推送 | 有（UI SSE） | 无 |
| mid-memory 分析 | 不跑 | 每局跑 |
| 持久化目标 | wolf.db | evolution.db |
| 技能来源 | Registry 基线（只读） | 候选版本 |
| 赛后处理 | 评测 + 复盘 + 报告 + 情景记忆 | mid-memory + Pattern 更新 |

### 7.2 EvolutionRunner

```python
class EvolutionRunner:
    async def run_training_games(self, config: TrainingConfig) -> TrainingResult
    async def run_ab_battle(self, config: ABConfig) -> ABResult
```

- `run_training_games`：批量跑 N 局，固定种子，支持并发（asyncio.Semaphore）
- `run_ab_battle`：基线 vs 候选，同种子匹配对战，计算聚合指标 + 显著性检验

---

## 8. 数据流全景

```
一局对战开始
  │
  ▼
SkillRegistry.refresh_baseline(role)
  │ 从 VersionRegistry 加载当前 KnowledgePackage
  │ 获取 skills (Markdown) + patterns (统计规律)
  │
  ▼
AgentMemory 初始化
  │ 注入: skills (规则) + top-K patterns (统计) + top-K 情景记忆 (案例)
  │
  ▼
游戏进行中：每步决策 (7 步管线)
  │ remember → select_skills → inject_memory → build_prompt
  │ → call_model → parse_output → enforce_policy
  │
  ▼
游戏结束
  │
  ├──► 评测管线 (Battle 系统)
  │    evaluate_game() → review_game() → generate_report()
  │    → 写入 wolf.db (evaluations, decision_reviews, counterfactuals, reports)
  │    → 更新 leaderboard
  │
  ├──► 情景记忆 (Evolution 系统)
  │    persist_game() → label_decisions()
  │    → 写入 evolution.db (situational_records, decision_outcomes)
  │
  └──► Pattern 更新 (Evolution 系统, 周期性)
       update_after_game() → bayesian_update()
       → 更新 evolution.db (patterns)
```

```
进化外循环 (周期性)
  │
  ├─ 模式聚合: 高置信 Pattern → crystallized
  ├─ 情景挖掘: evolution.db 结构化查询
  ├─ LLM 蒸馏: crystallized patterns + 情景 → 新技能提案
  ├─ 程序化去重: vs rejected_proposals (Jaccard 相似度)
  ├─ 创建候选 KnowledgePackage (skills + patterns + provenance)
  ├─ A/B 测试: bootstrap 检验 (最低有效局数检查)
  └─ 晋升/拒绝 → 更新 history.jsonl + baseline.json
```

---

## 9. 迁移指南

### 9.1 数据库迁移

```bash
# 预览（不写入）
python scripts/migrate_storage.py --dry-run

# 执行迁移
python scripts/migrate_storage.py

# 验证
python scripts/migrate_storage.py --dry-run  # 确认行数匹配
```

两库架构：`wolf.db`（对局+评测）和 `evolution.db`（进化学习）。

### 9.2 版本存储迁移

```bash
# 预览
python scripts/migrate_versions.py --dry-run

# 执行迁移
python scripts/migrate_versions.py

# 验证：检查 data/registry/ 目录结构
ls data/registry/*/versions/
```

将 `data/versions/` 转换为 `data/registry/` 格式（KnowledgePackage + history.jsonl）。

### 9.3 路径配置

`agent/common/paths.py` 新增三个属性：

| 属性 | 路径 | 说明 |
|------|------|------|
| `battle_db_path` | `data/wolf.db` | 对战数据库（与主库合并） |
| `evolution_db_path` | `data/evolution.db` | 进化数据库 |
| `registry_dir` | `data/registry` | 版本注册中心 |

---

## 10. 测试覆盖

| 测试文件 | 覆盖模块 | 测试数 |
|---------|---------|--------|
| `test_episodic_memory.py` | EpisodicMemoryWriter, 决策标签 | 19 |
| `test_pattern_engine.py` | PatternEngine, 贝叶斯更新, 生命周期 | 27 |
| `test_evaluator.py` | GameEvaluator, 5 维评分 | 17 |
| `test_reviewer.py` | GameReviewer, 转折点, 反事实 | 16 |
| `test_knowledge_package.py` | KnowledgePackage, 序列化 | 20 |
| `test_dedup.py` | deduplicate_proposals, Jaccard | 15 |
| `test_registry.py` | VersionRegistry, publish/CAS/diff/gc | 26 |
| **合计新增** | | **150** |

**全量测试：623 passed** (473 原有 + 150 新增)
