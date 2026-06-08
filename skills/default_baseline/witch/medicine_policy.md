---
name: witch_default_medicine_policy
role: witch
status: active
applicable_actions:
  - witch_act
evolution:
  enabled: true
  allowed_actions:
    - append_rule
    - rewrite_section
    - deprecate_rule
---

# 女巫默认用药策略

## Strategy

- 解药优先救高价值好人或首夜信息不足时的关键生存位；明确低价值或疑似狼目标可不救。
- 毒药优先用于高置信狼人、悍跳强势位、或白天难以放逐但持续破坏好人视角的玩家。
- 两瓶药都要考虑信息收益，避免在身份不清时过早消耗。

## Decision Rules

- 若死亡目标明显是可信预言家或稳定带队者，倾向使用解药。
- 若场上已有明确查杀且白天难以推出，可考虑夜间用毒处理。
- 信息不足且毒错代价高时，选择不用毒，保留后续回合主动权。

## Risk Boundaries

- 不因个人被攻击就优先毒攻击者。
- 不为了证明身份而浪费用药。
