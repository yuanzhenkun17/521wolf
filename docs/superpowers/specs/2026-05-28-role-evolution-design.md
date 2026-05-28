# 角色级技能版本化 & 自进化系统设计

## 概述

当前系统的版本控制颗粒度太大 — 整个 `skills/` 目录作为一个快照版本化。本设计将其改为按角色独立版本化，用内容哈希命名，并构建完整的自进化闭环：对局 → 分析 → 调整 → 再对局。

### 核心设计决策

| 决策 | 结论 |
|------|------|
| 版本粒度 | 按角色独立版本化 |
| 命名方式 | 内容哈希（sha256 前 8 位），不用 v1/v2 |
| 版本历史 | append-only version log + baseline pointer + parent provenance |
| 组合版本 | SkillVersionConfig 映射表（role → hash） |
| 中期记忆归属 | 手动开局 → 只用于评测；自进化 → 合并为技能建议 |
| common 技能 | output_schema 硬编码到 base.py，router 删除 common 注入逻辑 |
| 模型配置 | 不纳入版本化，全系统统一一种配置 |
| 合并与应用 | 分两步：合并产出建议 → 应用产出新技能文件 |
| 建议应用方式 | 一次性应用所有建议，输出变更清单 |
| 自进化触发 | 仅通过 UI |
| 对手配置 | 对战阶段其他角色固定用 baseline |
| 回滚方式 | 自动：对战失败则拒绝，不改 baseline |
| 排行榜 | 两种：对局排行榜 + 角色演化排行榜 |
| 推广/拒绝 | 半自动审批 + UI 推荐判定，用户有最终决策权 |
| 架构方案 | 从头重写（方案 C）：废弃 `versioning/` 和 `evaluation/evolution.py`、`version_battle.py`、`mixed_version_battle.py`；保留复用 `selfplay.py`、`review_enhanced.py`、`leaderboard.py`、`mid_memory.py`、`long_term_consolidator.py` |

## 目录结构

### agent 模块

```
agent/
  role_evolution/
    __init__.py
    models.py          ← 数据模型（RoleVersion, SkillVersionConfig, EvolutionRun, SkillConsolidation, SkillProposal）
    store.py           ← 版本存储（哈希生成、读写、baseline指针、版本历史）
    config.py          ← 组合版本配置（SkillVersionConfig 的构建和解析）
    pipeline.py        ← 自进化主流程（训练→合并→应用→对战→暂停→推广/拒绝）+ 对战逻辑
    applier.py         ← 应用合并建议，产出新技能文件
    leaderboard.py     ← 角色演化排行榜
```

### 版本存储

```
agent_versions/
  <role>/
    <hash>/
      skills/
        *.md
      meta.json            ← RoleVersion 序列化（immutable）
    history.json           ← append-only version log + baseline pointer
```

### 运行输出

```
runs/
  evolution/
    <run_id>/
      state.json           ← run 状态（持久化，重启后可恢复）
      config.json
      training/
        games/game*/       ← 训练局数据（含中期记忆）
      consolidations/
        proposals.json
      candidate/
        diff.json
        battle/
          summary.json
      result.json
  manual/
    <run_id>/
      games/game*/         ← 手动开局数据
```

### 废弃模块

| 旧模块 | 处理 |
|--------|------|
| `agent/versioning/manifest.py` | 删除 |
| `agent/evaluation/evolution.py` | 删除 |
| `agent/evaluation/version_battle.py` | 删除 |
| `agent/evaluation/mixed_version_battle.py` | 删除 |

### 保留复用模块

| 模块 | 用途 |
|------|------|
| `agent/evaluation/selfplay.py` | 训练和对战阶段调用 |
| `agent/evaluation/review_enhanced.py` | 多维评测 |
| `agent/evaluation/leaderboard.py` | 对局排行榜 |
| `agent/cognition/mid_memory.py` | 中期记忆生成（改造：provenance 标注） |
| `agent/cognition/long_term_consolidator.py` | 合并中期记忆 → 建议（改造：按角色过滤） |
| `agent/prompts/base.py` | 输出格式硬编码（原 common/output_schema.md） |

## 版本存储（store.py）

### 数据模型

```python
@dataclass
class RoleVersion:
    """Immutable 版本记录。状态从 run.status 和 history events 推导。"""
    hash: str                          # 8位sha256截断
    role: str                          # werewolf, seer, etc.
    skills: dict[str, str]             # {filename: content}
    created_at: str                    # UTC ISO时间戳
    parent_hash: str | None            # 创建时的 baseline（不是 versions 列表的前一个）
    source: str                        # "initial" | "evolution" | "manual"
    source_run_id: str | None
    notes: list[str]

@dataclass
class RoleHistory:
    role: str
    baseline: str                      # 当前生产指针，可指向 versions 中任意已存在版本
    versions: list[str]                # append-only，按创建时间排序的所有版本哈希
```

版本术语定义：
- `versions`：该角色所有被创建的版本，append-only log（包括 rejected 的）
- `baseline`：当前生产指针，可指向 versions 中任意已存在版本
- `parent_hash`：该版本创建时所基于的 baseline
- rollback 只移动 baseline，不创建新版本，不改 parent_hash
- reject 只更新 run 状态，不移动 baseline，candidate 版本仍保留
- next evolution 总是从当前 baseline 创建 candidate

### 哈希生成

```python
def normalize_skill_text(text: str) -> str:
    text = text.replace("\r\n", "\n").replace("\r", "\n")
    return text.rstrip() + "\n"

def normalize_skill_path(path: str) -> str:
    """规范化并校验技能文件路径。store 层是最后防线，与 applier 校验一致。"""
    if not path or not path.strip():
        raise ValueError(f"Empty path")
    p = PurePosixPath(path.replace("\\", "/"))
    normalized = p.as_posix()
    # 禁止绝对路径、parent traversal、drive paths、非 .md
    if p.is_absolute() or ".." in p.parts or ":" in normalized:
        raise ValueError(f"Unsafe path: {path}")
    if not normalized.endswith(".md"):
        raise ValueError(f"Non-md file: {path}")
    return normalized

def compute_hash(skills: dict[str, str]) -> str:
    files = []
    seen_paths: set[str] = set()
    for path in sorted(skills.keys()):
        normalized_path = normalize_skill_path(path)
        if normalized_path in seen_paths:
            raise ValueError(f"Duplicate normalized path: {path} → {normalized_path}")
        seen_paths.add(normalized_path)
        content = normalize_skill_text(skills[path])
        files.append({
            "path": normalized_path,
            "sha256": hashlib.sha256(content.encode("utf-8")).hexdigest(),
        })
    payload = {
        "hash_schema": 1,
        "files": files,
    }
    manifest_json = json.dumps(
        payload, sort_keys=True, ensure_ascii=False, separators=(",", ":"),
    )
    return hashlib.sha256(manifest_json.encode("utf-8")).hexdigest()[:8]
```

### 核心操作

```python
class VersionStore:
    def __init__(self, base_dir: Path): ...

    async def save_version(self, role: str, skills: dict[str, str],
                           parent_hash: str | None, source: str,
                           source_run_id: str | None = None,
                           notes: list[str] | None = None) -> str:
        """幂等：哈希已存在且内容一致 → 返回；内容不同 → HashCollisionError；
           history 已有 → 不重复 append。使用 asyncio.Lock per-role。"""

    async def set_baseline(self, role: str, target_hash: str,
                           expected_current: str) -> bool:
        """CAS：expected_current 不匹配则拒绝。原子写入 history.json。"""

    def load_version(self, role: str, hash: str) -> RoleVersion: ...
    def get_history(self, role: str) -> RoleHistory: ...
    def get_baseline(self, role: str) -> RoleVersion: ...
    def list_roles(self) -> list[str]: ...
    def list_versions(self, role: str) -> list[RoleVersion]: ...
    def get_skill_dir(self, role: str, hash: str) -> Path:
        """返回 agent_versions/<role>/<hash>/skills/ 路径"""
```

### 并发与原子写入

- per-role `asyncio.Lock`（UI-only 单进程，不需要 OS 文件锁）
- history.json 写入用临时文件 + `os.replace()` 原子操作
- `save_version` 幂等：相同哈希+内容 → 返回；相同哈希不同内容 → `HashCollisionError`；history 已有 → 不重复 append
- `set_baseline` 带 CAS：`expected_current` 不匹配 → 拒绝
- promote/reject 幂等：已是目标状态 → 返回成功

### 初始化

首次运行时从 `skills/<role>/` 读取技能文件，为每个角色创建 baseline 版本，哈希由内容计算。

## 组合版本配置（config.py）

注意：命名为 `SkillVersionConfig`，避免与 `engine.config.GameConfig`（游戏人数/角色配置）混淆。

### 数据模型

```python
@dataclass
class SkillVersionConfig:
    name: str                    # "baseline", "test-wolf-v2"
    role_versions: dict[str, str]  # {role: hash}
    created_at: str
    notes: list[str]
```

### 预设配置

- `build_baseline_config(store)` — 所有角色用 baseline 哈希
- `build_role_override_config(store, role, role_hash)` — 目标角色用指定哈希，其他用 baseline。训练阶段传 `parent_hash`（目标角色也用 baseline），对战阶段传 `candidate_hash`（目标角色用候选哈希）

### 运行时技能加载

```python
def skill_dir_for_role(store: VersionStore, config: SkillVersionConfig, role: str) -> Path:
    """返回指定角色的技能目录路径。agent 构造时直接传此路径作为 skill_dir。"""
    hash = config.role_versions[role]
    return store.get_skill_dir(role, hash)  # agent_versions/<role>/<hash>/skills/
```

运行时集成：`_create_agents()` 改造 — 对每个 player，根据其角色调用 `skill_dir_for_role()` 获取路径，传给 `LLMPlayerAgent(skill_dir=...)`。现有 `_SKILL_CACHE` 按 Path 键自动隔离不同版本，无需额外改造。

SkillVersionConfig 不持久化为独立文件，在 run 目录中记录为 `config.json`。

## 自进化主流程（pipeline.py）

### 状态机

```
queued → training → consolidating → applying → battling → reviewing
reviewing → promoted / rejected
running stage → failed
promoted/rejected/failed 是终态
重复 promote/reject 幂等
promote→rejected 或 rejected→promote 冲突拒绝
```

### 流程定义

```python
@dataclass
class EvolutionRun:
    run_id: str
    role: str
    parent_hash: str
    status: str  # queued | training | consolidating | applying | battling | reviewing | promoted | rejected | failed
    training_games: int
    battle_games: int
    candidate_hash: str | None
    battle_result: dict | None
    proposals: SkillConsolidation | None
    diff: list[SkillDiff] | None
    errors: list[str]
```

### 主流程

```python
async def run_evolution(
    store: VersionStore,
    role: str,
    training_games: int = 20,
    battle_games: int = 10,
    model_adapter: ModelAdapter = None,
    on_progress: Callable[[str, dict], None] = None,
) -> EvolutionRun:
```

**阶段 1：训练**
- 配置：`build_role_override_config(store, role, parent_hash)` — 目标角色用 baseline，其他角色也用 baseline
- 调用 `run_selfplay()`，启用 `enable_mid_memory=True`，禁用 `enable_long_term_consolidation`
- 中期记忆存在 `training/games/game*/mid_memory/`

**阶段 2：合并**
- 调用 `consolidate_for_role(run_dir, role, model_adapter)`
- 从中期记忆中按角色过滤，产出 `SkillConsolidation`（结构化建议）
- 只有 `relevance=direct` 的洞察可以生成 actionable proposal

**阶段 3：应用建议**
- 调用 `apply_proposals(current_skills, proposals, model_adapter)`
- LLM 读取当前技能文件 + 建议，输出修改后的完整技能文件
- 全部校验通过后才 `save_version`，避免非法 candidate 进入版本库
- 输出变更清单（`diff.json`）

**阶段 4：对战验证**
- 配置 A：`build_baseline_config(store)` — 全 baseline
- 配置 B：`build_role_override_config(store, role, candidate_hash)` — 目标角色用候选哈希
- 对战逻辑在 `pipeline.py` 内部实现（废弃 `version_battle.py` 和 `mixed_version_battle.py`）
- 两组配置使用相同种子范围各跑 N 局，产出对战胜率和各项指标对比
- 指标按目标角色聚合（per-role aggregation）
- battle 失败时，candidate 保留但 run 为 failed，禁止 promote/reject

**阶段 5：暂停，等待用户决策**
- 状态变为 `reviewing`
- UI 展示变更清单 + 对战数据 + 推荐判定
- 用户点击推广或拒绝

### 推广与拒绝

```python
async def promote(run: EvolutionRun, store: VersionStore):
    """CAS 推广。幂等 + 终态保护。"""
    # 幂等
    if run.status == "promoted":
        return
    # 终态冲突
    if run.status in {"rejected", "failed"}:
        raise InvalidRunStateError(f"Cannot promote a {run.status} run")
    # 只有 reviewing 状态才能 promote
    if run.status != "reviewing":
        raise InvalidRunStateError(f"Cannot promote a {run.status} run (must be reviewing)")

    # baseline 已是 candidate（幂等）
    current = store.get_history(run.role).baseline
    if current == run.candidate_hash:
        run.status = "promoted"
        return
    # baseline 已被其他人改过（既不是原始 baseline 也不是 candidate）
    if current != run.parent_hash:
        raise BaselineChangedError(
            f"Baseline has changed from {run.parent_hash} to {current} since this evolution started"
        )

    await store.set_baseline(run.role, run.candidate_hash, expected_current=run.parent_hash)
    run.status = "promoted"

async def reject(run: EvolutionRun, store: VersionStore):
    """拒绝：candidate 保留在历史中，baseline 不变。幂等 + 终态保护。"""
    if run.status == "rejected":
        return
    if run.status in {"promoted", "failed"}:
        raise InvalidRunStateError(f"Cannot reject a {run.status} run")
    if run.status != "reviewing":
        raise InvalidRunStateError(f"Cannot reject a {run.status} run (must be reviewing)")
    run.status = "rejected"
```

### 失败恢复

- 只有 `reviewing` 状态是可恢复的
- `training/consolidating/applying/battling` 在后端重启后标记为 `failed (reason=interrupted)`
- `promoted/rejected/failed` 是终态
- 不支持断点续跑（每个阶段是原子的，失败就从头重跑该阶段）
- 重启扫描时把 `reviewing` 视为该角色 active run，阻塞同角色新演化
- 同角色 active run 检查用内存，启动时扫描 state.json 恢复

state.json schema（每阶段更新，`os.replace()` 原子写入）：

```json
{
  "run_id": "evol_werewolf_20260528_120000",
  "role": "werewolf",
  "parent_hash": "a3f2b1c4",
  "candidate_hash": null,
  "status": "training",
  "updated_at": "2026-05-28T12:05:00Z",
  "error": null,
  "failed_stage": null,
  "training_games": 20,
  "battle_games": 10
}
```

## 应用建议（applier.py）

### 数据模型

```python
@dataclass
class SkillDiff:
    filename: str
    action: str        # "modified" | "added" | "deprecated"
    before: str | None
    after: str | None
    proposal_ref: str
```

### 核心函数

```python
async def apply_proposals(
    current_skills: dict[str, str],
    proposals: SkillConsolidation,
    model_adapter: ModelAdapter,
) -> tuple[dict[str, str], list[SkillDiff]]:
```

### Prompt 设计

- 输入：当前技能文件完整内容 + 结构化建议（append_rule / rewrite_section / deprecate_rule）
- 要求：输出完整修改后的文件，保持 Markdown 格式和 YAML front matter
- 输出：JSON `{files: {filename: content}, changes: [{filename, action, description}]}`

### 防护（完整清单）

筛选：
- 只应用 `confidence >= threshold && risk != "high" && status == "proposed"` 的 proposal
- 冲突 proposal 默认都 skip（除非有显式 resolver）

LLM 输出校验（任何一项失败 → 拒绝整批）：
1. 只能修改 eligible proposal 指向的文件（禁止改无关文件）
2. 禁止删除文件（当前没有 delete_file proposal）
3. `name` 字段不能改
4. `applicable_actions` 不能扩大范围
5. `scope` 不能改成 `common`
6. `role` 不能改
7. `output_constraints` 不能删除
8. `evolvable: false` 的文件不能改
9. 文件路径安全校验（禁止绝对路径、`..`、反斜杠、非 `.md`）
10. front matter 能被现有 YAML-like parser 解析
11. 单文件长度上限
12. 差异大小限制（最多改 N 个文件、新增/删除比例上限）
13. 禁止泄露其他角色私有策略

Smoke test：
- 校验通过后写入临时目录，调用 `load_markdown_skills()` + `select_skills()` 确认 runtime 能正常读

全部校验通过后才调用 `store.save_version()`。

## 合并建议（SkillConsolidation schema）

### 数据模型

```python
@dataclass
class EvidenceRef:
    game_id: str
    player_id: int | None
    decision_id: str | None
    role: str
    action_type: str | None
    quote: str | None

@dataclass
class SkillProposal:
    proposal_id: str
    target_file: str
    action_type: str          # "append_rule" | "rewrite_section" | "deprecate_rule"
    section: str | None       # rewrite_section 时的目标 section
    content: str              # 新增/修改的内容，deprecate 时为空
    rationale: str            # 为什么要改
    confidence: float         # LLM 对这条建议的置信度
    evidence: list[EvidenceRef]
    risk: str                 # "low" | "medium" | "high"
    expected_metric: str      # 预期影响的指标
    expected_direction: str   # "increase" | "decrease"
    conflicts_with: list[str] # 与其他 proposal 的冲突（proposal_id 列表）
    status: str = "proposed"  # "proposed" | "applied" | "skipped" | "rejected"

@dataclass
class SkillConsolidation:
    role: str
    run_id: str
    parent_hash: str
    proposals: list[SkillProposal]
    trends: list[str]         # 跨局趋势总结
    generated_at: str
    source_games: list[str]
    source_window: int
    model_name: str | None
    prompt_version: str
```

约束：
- `relevance=direct` 的洞察才能生成 actionable proposal
- `relevance=contextual` 的洞察只能作为背景解释，不能变成可执行规则
- `turning_points` 只作为 evidence/context，除非能绑定到目标角色的 decision review
- `confidence >= threshold && risk != high` 才自动应用
- 冲突 proposal 默认都 skip

## 中期记忆处理

### 原则

- 手动开局 → 只用于评测展示（多维评分、复盘、排行榜）
- 自进化 → 合并沉淀为技能修改建议
- provenance 必须在中期记忆生成时由 LLM 输出，不能事后猜

### 中期记忆 schema 改造

```python
@dataclass
class ScoredInsight:
    text: str
    source_roles: list[str]           # 来源角色（可能涉及多个角色的交互）
    source_player_ids: list[int]
    source_decision_ids: list[str]
    game_id: str
    relevance: str                    # "direct" | "contextual"
    confidence: float                 # 0.0 - 1.0

@dataclass
class GameAnalysis:
    # ... 现有字段 ...
    strategic_insights: list[ScoredInsight]   # 原来是 list[str]
    error_patterns: list[ScoredInsight]       # 原来是 list[str]
    turning_points: list[TurningPointAnalysis]  # 加 involved_roles 字段
```

中期记忆生成 prompt 改造：要求 LLM 为每条洞察输出来源角色、玩家 ID、关联决策 ID、置信度。

### 合并时过滤

```python
def filter_mid_memory_for_role(analysis: GameAnalysis, role: str) -> FilteredAnalysis:
    """从全局中期记忆中提取指定角色的数据，标注 relevance"""
```

过滤规则：
- `decision_reviews`：只保留 `role` 匹配的
- `strategic_insights`：来源是目标角色 → `relevance=direct`；其他角色 → `relevance=contextual`
- `error_patterns`：同上
- `turning_points`：标注 `involved_roles`，只作为 context

硬规则：只有 `relevance=direct` 的洞察可以生成 `append_rule/rewrite_section/deprecate_rule`。`contextual` 只能作为背景。

### 合并改造

```python
async def consolidate_for_role(
    run_dir: Path,
    role: str,
    model_adapter: ModelAdapter,
    window: int = 5,
) -> SkillConsolidation:
```

中期记忆存储位置不变：`runs/evolution/<run_id>/training/games/game*/mid_memory/*.json`，用完即弃。

## 排行榜

### 对局排行榜（手动开局用）

沿用 `agent/evaluation/leaderboard.py`，增加 SkillVersionConfig 信息展示（每个角色用的哈希版本）。

### 角色演化排行榜（自进化用）

```python
@dataclass
class RoleLeaderboardEntry:
    hash: str
    role: str
    is_baseline: bool
    total_games: int

    # 目标角色过滤后的指标（只统计该角色玩家的数据）
    target_role_role_weighted_score: float
    target_role_speech_score: float
    target_role_vote_score: float
    target_role_skill_score: float
    target_role_information_score: float
    target_role_cooperation_score: float
    target_role_fallback_rate: float
    target_role_bad_case_rate: float      # bad_case_count / games

    # 阵营指标（按 target_side 映射：werewolf/white_wolf_king → 狼人，其他 → 好人）
    target_side_win_rate: float
    target_side_win_rate_ci: tuple[float, float]

    # 对比 baseline
    delta_vs_baseline: dict[str, float]
    battle_record: str                    # "W:8 L:2"
    recommendation: str                   # "promote" | "caution" | "reject"
    data_sufficient: bool                 # battle_games >= 10
```

按角色分组，展示该角色所有哈希版本的指标对比。支持回滚操作（baseline 指针移回指定哈希）。

### 推荐判定标准（advisory，不自动触发）

target_side 映射：
- werewolf, white_wolf_king → 狼人阵营
- seer, witch, hunter, guard, villager → 好人阵营

默认门槛（字段名与 RoleLeaderboardEntry schema 一致，baseline 指同批 battle seed 下的对照指标，不是排行榜历史）：
- target_role_role_weighted_score >= baseline
- target_role_fallback_rate <= baseline
- target_role_bad_case_rate <= baseline
- target_side_win_rate drop <= 10%
- battle_games < 10 → 标注"数据不足，仅供参考"

三档推荐：
- 建议推广：全部达标
- 谨慎推广：部分未达标或样本不足
- 建议拒绝：核心指标明显退化

推广按钮永远不禁用，用户有最终决策权。

## UI 层

### API 路由

**新路由（Role Evolution）：**

| 方法 | 路径 | 说明 |
|------|------|------|
| GET | `/api/roles` | 角色列表 |
| GET | `/api/roles/{role}/versions` | 版本列表 |
| GET | `/api/roles/{role}/versions/{hash}` | 版本详情 |
| GET | `/api/roles/{role}/leaderboard` | 角色演化排行榜 |
| POST | `/api/roles/{role}/rollback/{hash}` | 回滚 baseline |
| POST | `/api/role-evolution/start` | 启动自进化 |
| GET | `/api/role-evolution/{run_id}/status` | 获取演化状态 |
| GET | `/api/role-evolution/{run_id}/diff` | 获取变更清单 |
| POST | `/api/role-evolution/{run_id}/promote` | 推广候选版本 |
| POST | `/api/role-evolution/{run_id}/reject` | 拒绝候选版本 |

**旧路由（deprecated，保留到迁移完成）：**

| 方法 | 路径 | 说明 |
|------|------|------|
| * | `/api/evolution/...` | deprecated，保持原样，指向旧 `ui.backend.evolution_runner` |

响应格式加 `kind: "role_evolution_run"` + `schema_version: 1` 避免新旧混淆。

旧路由删除条件：
1. 前端不再调用 `/api/evolution`
2. 对应测试迁移完成
3. 旧 `agent/versioning` 模块删除完成
4. `rg "agent.versioning|evaluation.evolution|version_battle|mixed_version_battle"` 无生产代码引用
5. 文档更新完成

### 前端页面

**角色演化面板（独立 tab，不与旧 Versions/Evolution 混合）：**
- 角色 tab 切换
- 当前 baseline 信息
- 角色演化排行榜（哈希、基线标记、胜率、角色分、对战记录、推荐判定）
- 启动自进化表单（训练局数、对战局数）
- 实时进度展示（UI 后端通过 SSE 推送 `on_progress` 回调的事件：阶段变更、每局完成计数）
- 审查结果面板（变更清单、对战数据、三档推荐、推广/拒绝按钮）

**改造现有页面：**
- 对局页面增加 SkillVersionConfig 信息展示

## 测试迁移

### 第一阶段：先建新测试

```
tests/test_role_evolution/
  test_store.py
    - hash normalization: LF/CRLF 等价
    - existing same hash same content returns existing
    - existing same hash different content raises HashCollisionError
    - set_baseline expected_current mismatch rejects
    - rollback only moves baseline, does not mutate parent_hash
    - history append is idempotent

  test_config.py
    - baseline config maps every role to current baseline
    - evolution config changes only target role
    - generated skill bundle loads target role skills correctly
    - no cross-role skill leakage

  test_applier.py
    - skips low-confidence/high-risk/conflicting proposals
    - rejects role/scope/name/action expansion changes
    - rejects unsafe paths and non-md files
    - rejects deleting files
    - rejects changing non-evolvable files
    - smoke test through load_markdown_skills/select_skills

  test_pipeline.py
    - mocked training → consolidation → apply → battle → reviewing
    - promote updates baseline only if CAS matches
    - reject leaves baseline unchanged
    - repeated promote/reject idempotency/conflict behavior
    - state.json written per stage and reloadable after restart
    - active same-role run blocked

  test_leaderboard.py
    - aggregates target-role metrics only
    - compares target side win rate
    - marks battle_games < 10 as insufficient data
    - recommendation: promote/caution/reject

tests/test_role_evolution_api.py
    - /api/role-evolution/start
    - /status
    - /diff
    - /promote
    - /reject
    - /api/roles/{role}/versions
    - /rollback
    - legacy /api/evolution still works and is deprecated
```

### 第二阶段：旧测试迁移

| 旧测试文件 | 对应新测试 |
|-----------|-----------|
| `tests/test_manifest.py` | `test_store.py` |
| `tests/test_evolution_pipeline.py` | `test_pipeline.py` |
| `tests/test_evolution_runner.py` | `test_pipeline.py` |
| `tests/test_version_battle_ext.py` | `test_pipeline.py` |
| `tests/test_mixed_version_battle.py` | `test_pipeline.py` |
| `tests/test_agent_version_battle.py` | `test_pipeline.py` |

### 第三阶段：删除旧模块

条件：
1. 新测试全部通过
2. 前端不再调用旧路由
3. `rg "agent.versioning|evaluation.evolution|version_battle|mixed_version_battle"` 无生产代码引用
4. 旧测试文件删除
5. 文档更新完成
