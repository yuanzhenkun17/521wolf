# Spec #2: 评测与复盘系统

> 对应进阶课题 B：多维评测 → 关键决策复盘 → 反事实推演 → 结构化报告 → Leaderboard
> 核心设计：采用 learning_v2 架构（认识论分离 + 四面相 + 经验候选）
> 与进化系统的关系：评测产出 ExperienceCandidate（中期记忆），直接输入 Consolidation

---

## 1. 设计原则

### 1.1 认识论分离

评测的核心原则是**防止事后诸葛亮偏见**：

- **player_view**：agent 决策时实际知道的信息（只用这个判断"过程质量"）
- **god_view_after_game**：赛后真相（所有角色身份、最终胜负，只用这个判断"结果质量"）

```python
# 错误做法：用上帝视角评判 "预言家查验了狼人但没起跳"
# → 这是事后诸葛亮，因为预言家起跳有风险

# 正确做法：
# player_view: 预言家只知道查验了1号是狼，其他信息不确定
# god_view: 1号确实是狼，最终好人赢了
# 过程评判：基于 player_view — "查验后选择不起跳，在信息不足时是合理策略"
# 结果评判：基于 god_view — "最终好人赢了，策略有效"
```

### 1.2 每局自动评测

每局对局结束后自动触发 evidence pipeline，不需要手动干预。

### 1.3 经验候选 = 中期记忆

评测产出的 `ExperienceCandidate` 就是中期记忆，直接输入进化系统的 Consolidation 阶段。不需要额外的"中期记忆"概念层。

---

## 2. 评测管线

### 2.1 Pipeline 流程

```
selfplay game_dir
  ├── archive.json        (完整决策 trace)
  ├── agent_decisions.jsonl (轻量决策日志)
  ├── game_events.jsonl    (引擎事件流)
  └── meta.json           (对局元数据)

        ↓ load_game_bundle
GameEvidenceBundle (原始数据打包)

        ↓ normalize_decisions
DecisionEvidenceInput[] (每个决策拆分为四面相)

        ↓ select_key_decisions
KeyDecision[] (筛选出值得评估的关键决策)

        ↓ judge_game_evidence (LLM)
EvidenceRunResult
  ├── DecisionEvidence[]   (每个关键决策的评判)
  ├── GameEvidence          (全局评判：胜负路径、转折点、团队协作)
  └── ExperienceCandidate[] (经验候选 = 中期记忆)

        ↓ render_evidence_report
Markdown 报告

        ↓ write_evidence_outputs
JSON + JSONL + Markdown 文件
```

### 2.2 四面相模型

每个决策被拆分为四个面相：

```python
@dataclass
class DecisionEvidenceInput:
    decision_id: str
    player_id: int
    role: str
    action_type: str
    day: int
    phase: str

    # 面相 1: Agent 决策时知道什么（用于过程评判）
    player_view: PlayerView
    # 包含：可见事件、已知角色、查验结果、当前情境

    # 面相 2: Agent 的推理过程
    agent_reasoning: AgentReasoning
    # 包含：private_reasoning、confidence、alternatives、selected_skills

    # 面相 3: Agent 做了什么
    decision_result: DecisionResult
    # 包含：最终 target、choice、public_text

    # 面相 4: 赛后真相（仅用于结果评判）
    god_view_after_game: GodViewAfterGame
    # 包含：所有角色真实身份、该决策的实际效果、最终胜负
```

### 2.3 关键决策选择

不是每个决策都值得 LLM 评判（太贵）。选择策略：

**规则选择**（始终入选）：
- 关键动作类型：`seer_check`、`werewolf_kill`、`witch_act`、`hunter_shoot`、`exile_vote`
- 所有导致死亡/放逐的决策

**转折点窗口**（事件附近 ±1 轮的决策入选）：
- 玩家死亡事件
- 放逐投票事件
- 游戏结束事件

### 2.4 LLM 评判

**单次调用评判所有关键决策**（批量打包，节省 token）：

```
System: "你是狼人杀对局评判专家。请基于以下规则评判每个关键决策..."

User: {
  game_meta: {...},
  key_decisions: [
    {decision_id, player_view, agent_reasoning, decision_result, god_view, rubric},
    ...
  ]
}

Output: {
  decision_evidence: [...],   # 每个决策的评判
  game_evidence: {...},        # 全局评判
  experience_candidates: [...] # 经验候选
}
```

---

## 3. 评判维度

### 3.1 决策评判 (DecisionEvidence)

```python
@dataclass
class DecisionEvidence:
    decision_id: str

    # 质量评分 (0-10)
    process_quality: float     # 基于 player_view：推理是否合理
    result_quality: float      # 基于 god_view：实际效果如何

    # 样本分类
    sample_type: str
    # "strong_positive"   — 过程好 + 结果好（值得学习的标杆）
    # "lucky_positive"    — 过程一般 + 结果好（运气成分）
    # "reasonable_failure" — 过程好 + 结果差（不改策略也行）
    # "true_error"        — 过程差 + 结果差（需要修正）
    # "execution_issue"   — 意图对但执行错（skill 问题）
    # "low_learning_value" — 信息不足无法评判
    # "unclear"           — 模糊，无法分类

    # 改进建议
    better_alternatives: list[str]  # 更好的做法

    # 角色专属评价
    role_specific_evaluation: str

    # 信息流评价
    info_flow_quality: str  # 信息获取和利用是否充分
```

### 3.2 全局评判 (GameEvidence)

```python
@dataclass
class GameEvidence:
    # 胜负路径
    win_path: str              # 赢/输的关键原因

    # 转折点
    turning_points: list[TurningPoint]
    # 每个转折点：时间、事件、影响、为什么是转折

    # 信息流
    info_threads: list[str]    # 关键信息的传播链路

    # 团队协作
    team_coordination: str     # 好人/狼人的团队配合评价
```

### 3.3 角色专属评分标准 (Rubrics)

每个角色有独立的评分维度和权重：

```python
ROLE_RUBRICS = {
    "seer": {
        "核心职责": "查验并传递信息",
        "关键指标": ["查验准确率", "起跳时机", "信息传递效果"],
        "常见错误": ["过早暴露", "查验顺序不合理", "不起跳导致信息丢失"],
    },
    "werewolf": {
        "核心职责": "隐藏身份 + 淘汰好人",
        "关键指标": ["伪装可信度", "投票一致性", "刀法精准度"],
        "常见错误": ["投票暴露队友", "发言矛盾", "刀到神职"],
    },
    "witch": {
        "核心职责": "救人/毒人",
        "关键指标": ["用药时机", "信息利用", "存活轮数"],
        "常见错误": ["浪费解药", "毒到好人", "第一夜不用药"],
    },
    # ... 其他角色
}
```

---

## 4. 经验候选（中期记忆）

### 4.1 数据结构

```python
@dataclass
class ExperienceCandidate:
    pattern_type: str     # "positive_pattern" | "anti_pattern" | "boundary_warning"
    role: str             # 相关角色
    description: str      # 具体描述
    confidence: float     # 0-1，置信度
    context: str          # 发生在什么情境下
    misleading_risk: bool # 是否可能误导（如"狼人假装预言家"在某些情况是好策略）
    source_decisions: list[str]  # 来源 decision_id 列表
```

### 4.2 样本分类 → 经验候选映射

| 样本类型 | 产生经验候选？ | 类型 |
|----------|---------------|------|
| strong_positive | ✅ | positive_pattern |
| true_error | ✅ | anti_pattern |
| execution_issue | ✅ | anti_pattern（skill 问题） |
| boundary_warning | ✅ | boundary_warning |
| lucky_positive | ⚠️ | 仅当 confidence > 0.7 时 |
| reasonable_failure | ❌ | 不产生（策略没问题，只是运气差） |
| low_learning_value | ❌ | 不产生 |
| unclear | ❌ | 不产生 |

### 4.3 在进化闭环中的位置

```
对局结束
  ↓
evidence pipeline → ExperienceCandidate[] (中期记忆)
  ↓ 多局累积到 consolidation_window (如 5 局)
consolidation: LLM 读取中期记忆 + 当前 skill + 历史 rejected proposals
  ↓
SkillProposal (skill 修改提案)
  ↓
apply → battle → promote/reject
```

---

## 5. Leaderboard

### 5.1 维度

| 指标 | 数据来源 | 用途 |
|------|----------|------|
| 胜率 (win_rate) | 对局结果 | 基础指标 |
| 角色加权分 (role_weighted_score) | 评测评分 | 综合质量 |
| 过程质量均分 (avg_process_quality) | DecisionEvidence | 决策质量 |
| 结果质量均分 (avg_result_quality) | DecisionEvidence | 运气成分 |
| 强正向样本率 | ExperienceCandidate | 可学习性 |
| 真错误率 | ExperienceCandidate | 需修正程度 |
| Wilson CI | 统计计算 | 置信区间 |

### 5.2 Leaderboard 展示

```
排行榜 — seer 角色
┌─────────┬───────┬──────────┬──────────┬──────────┬──────────┐
│ 版本     │ 局数  │ 胜率      │ 角色分    │ 过程质量  │ 推荐      │
├─────────┼───────┼──────────┼──────────┼──────────┼──────────┤
│ v5 (新)  │ 20    │ 65%±10%  │ 7.8      │ 8.1      │ promote  │
│ v4       │ 20    │ 55%±11%  │ 7.2      │ 7.5      │ caution  │
│ v3 (基线)│ 20    │ 50%±12%  │ 6.8      │ 7.0      │ baseline │
│ v2       │ 20    │ 45%±11%  │ 6.5      │ 6.8      │ rejected │
└─────────┴───────┴──────────┴──────────┴──────────┴──────────┘
```

### 5.3 版本趋势

```
seer 角色进化趋势:
  v1 (基线) ████████████ 45%
  v2         █████████████ 50%
  v3         ██████████████ 55%
  v4         ███████████████ 60%
  v5 (新)    ████████████████ 65% ← 新基线
```

---

## 6. 报告格式

### 6.1 单局报告 (Markdown)

```markdown
# 对局报告: game_003 (seed=42)

## 概要
- 胜方: 好人阵营
- 总轮数: 5 天
- 关键决策数: 12

## 胜负路径
好人通过预言家起跳+女巫毒杀狼人，在第4天放逐最后一只狼获胜。

## 转折点
1. 第2夜 女巫毒杀2号(狼人) — 信息来源: 狼人投票暴露
2. 第3天 预言家起跳报查验 — 信息来源: 第1夜查验结果

## 关键决策评判

### P3 (seer) 第1夜 查验
- 过程质量: 8/10 — 查验了沉默玩家，策略合理
- 结果质量: 10/10 — 查验到狼人
- 分类: strong_positive ✅

### P5 (witch) 第2夜 毒杀
- 过程质量: 9/10 — 基于投票模式推断2号是狼
- 结果质量: 10/10 — 毒杀了真狼
- 分类: strong_positive ✅
- 经验候选: "女巫通过投票模式识别狼人的策略有效"

## 改进建议
- P1 (villager): 第3天发言缺乏分析，建议增加逻辑推理

## 经验候选
- [positive_pattern] 预言家起跳时机: 第3天起跳比第1天更安全
- [anti_pattern] P7 (hunter): 过早暴露身份导致被狼人优先击杀
```

---

## 7. 与现有代码的替换关系

| 现有模块 | learning_v2 对应 | 动作 |
|----------|-----------------|------|
| `learning/review/scoring.py` | 无直接对应 | 可删除（被 evidence pipeline 替代） |
| `learning/review/report.py` | `report.py` | 替换为 learning_v2 的报告生成 |
| `learning/game_analysis.py` | `judge.py` + `normalizer.py` | 替换为 evidence pipeline |
| `learning/stats.py` (部分) | `rubrics.py` | 保留统计工具，新增 rubrics |
| `learning/leaderboard.py` | 新增 leaderboard 模块 | 重写，增加评测维度 |
| `learning/calibration.py` | 保留 | 置信度校准独立于评测 |

---

## 8. 与现有代码的 Gap Analysis

| 设计点 | 现状 | 差距 | 优先级 |
|--------|------|------|--------|
| 认识论分离 | 无（review 混用上帝视角） | 引入 player_view/god_view 分离 | P0 |
| 四面相模型 | 无 | 新建 normalizer 拆分决策 | P0 |
| 关键决策选择 | review 无选择逻辑 | 引入规则+转折点选择 | P1 |
| 样本分类 | 无 | 新建 7 类分类体系 | P0 |
| ExperienceCandidate | 无（有 mid_memory 但非结构化） | 用 ExperienceCandidate 替代 | P0 |
| 角色 rubrics | 无 | 新建 7 角色评分标准 | P1 |
| Leaderboard | 简单胜率统计 | 增加多维度 + 版本趋势 | P1 |
| 批量 LLM 评判 | 每局多次 LLM 调用 | 改为单次批量调用 | P1 |
