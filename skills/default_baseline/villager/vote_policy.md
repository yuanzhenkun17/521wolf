---
name: villager_default_vote_policy
role: villager
status: active
applicable_actions:
  - exile_vote
  - pk_vote
  - sheriff_vote
evolution:
  enabled: true
  allowed_actions:
    - append_rule
    - rewrite_section
    - deprecate_rule
---

# 村民默认投票策略

## Strategy

- 投票优先服务于好人阵营的信息增益：投给逻辑矛盾多、站边摇摆、收益更像狼人的玩家。
- 警长票优先给发言结构清楚、愿意公开验人或判断路径、能承担归票责任的候选人。
- PK 投票时比较两名候选人的行为链完整度，而不是只比较临场求生欲。

## Decision Rules

- 如果有可信预言家视角，优先跟随其明确查杀或狼坑；可信度不足时保留独立判断。
- 如果票型能暴露团队关系，优先投向能最大化信息的焦点位。
- 平票或分票风险高时，跟随当前最可信归票，避免好人票被拆散。

## Risk Boundaries

- 不投纯情绪票。
- 不为了隐藏视角而故意弃票，除非候选人都明显不该出。
