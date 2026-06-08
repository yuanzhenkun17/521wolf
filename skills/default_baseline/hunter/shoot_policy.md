---
name: hunter_default_shoot_policy
role: hunter
status: active
applicable_actions:
  - hunter_shoot
evolution:
  enabled: true
  allowed_actions:
    - append_rule
    - rewrite_section
    - deprecate_rule
---

# 猎人默认开枪策略

## Strategy

- 开枪目标优先选择高置信狼人、悍跳位、票型暴露位或持续带偏好人的玩家。
- 如果没有足够置信度，宁可不开枪或选择收益最高的明确焦点，避免带走关键好人。
- 开枪前结合自己死亡原因判断：夜死可能来自狼刀，白天出局则重点审视推动自己出局的人。

## Decision Rules

- 有预言家可靠查杀时，优先带走查杀目标。
- 若多个目标可选，选择能最大化揭示阵营关系的玩家。
- 若自己被错误归票出局，优先带走推动链条中逻辑最矛盾、收益最像狼人的玩家。

## Risk Boundaries

- 不因私人恩怨开枪。
- 不在判断明显不足时强行带走疑似神职。
