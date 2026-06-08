---
name: white_wolf_king_default_explode_timing
role: white_wolf_king
status: active
applicable_actions:
  - white_wolf_explode
evolution:
  enabled: true
  allowed_actions:
    - append_rule
    - rewrite_section
    - deprecate_rule
---

# 白狼王默认自爆策略

## Strategy

- 自爆是高成本行动，只在能带走关键好人、破坏预言家信息链、或挽救狼队崩盘局面时使用。
- 优先带走可信预言家、女巫、守卫、猎人等高收益目标；若身份不明，选择稳定带队者。
- 白天即将被放逐且无法翻盘时，自爆可避免投票暴露更多狼队关系。

## Decision Rules

- 如果目标身份收益高且当前发言已经难以自保，选择自爆带人。
- 如果还能通过发言转移焦点，优先保留自爆威慑。
- 若自爆会明显暴露剩余队友位置，只有在带走关键神职时才执行。

## Risk Boundaries

- 不因一时压力随意自爆。
- 不带走已经会被放逐或价值很低的目标。
