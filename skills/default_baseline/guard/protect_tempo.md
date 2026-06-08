---
name: guard_protect_tempo
role: guard
status: active
applicable_actions:
  - guard_protect
  - speak
  - last_word
evolution:
  enabled: true
  allowed_actions:
    - append_rule
    - rewrite_section
    - deprecate_rule
---

# 守卫守护节奏

## Strategy

- 守护要预测狼队下一刀，而不是只守自己最信的人。
- 连守限制会改变后续选择；上一轮守过的核心位，下一轮要评估转守价值。
- 守护计划保持低调，避免让狼队根据公开发言绕开保护。

## Decision Rules

- 预言家信息链清晰时，围绕能延续信息链的人安排守护。
- 狼队压力大时，优先考虑他们最想处理的带队好人或暴露神职。
- 女巫可能救药介入时，避免和最显眼刀口机械重叠。

## Risk Boundaries

- 不连续按固定模式守同类目标。
- 不在白天公开具体守护计划。
- 不因为个人站边偏好忽略更高价值刀口。
