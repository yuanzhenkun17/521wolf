---
name: guard_default_protect_policy
role: guard
status: active
applicable_actions:
  - guard_protect
evolution:
  enabled: true
  allowed_actions:
    - append_rule
    - rewrite_section
    - deprecate_rule
---

# 守卫默认守护策略

## Strategy

- 守护优先保护可信预言家、稳定带队好人、已暴露且价值高的神职。
- 若女巫可能使用解药，避免盲目守同一显眼目标造成资源冲突。
- 没有明确目标时，守护白天表现强、狼队可能优先处理、且不容易被放逐的玩家。

## Decision Rules

- 优先考虑狼队最想刀谁，而不是自己最信谁。
- 若上一轮已守过关键目标，后续要评估是否需要转守，避免被狼队利用节奏。
- 当预言家信息链清晰时，守护围绕信息链核心展开。

## Risk Boundaries

- 不为了保护自己站边而忽视真正高价值目标。
- 不把守护计划在白天过度暴露。
