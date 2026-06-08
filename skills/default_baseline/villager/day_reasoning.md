---
name: villager_default_day_reasoning
role: villager
status: active
applicable_actions:
  - speak
  - sheriff_speak
  - pk_speak
  - last_word
  - sheriff_run
  - sheriff_withdraw
  - sheriff_badge
  - speech_order
evolution:
  enabled: true
  allowed_actions:
    - append_rule
    - rewrite_section
    - deprecate_rule
---

# 村民默认白天推理

## Strategy

- 先承认自己没有夜间信息，再用发言顺序、投票意图、站边变化和被攻击反应建立判断。
- 发言要给出当前最可疑对象、次级怀疑对象和暂时信任对象，不要只说情绪或空泛立场。
- 警上竞选只有在能稳定整理逻辑、带队归票时才报名；信息不足时优先不上警，保留投票视角。
- 成为警长后，发言顺序优先让焦点位、对跳位、被多数怀疑位靠前暴露信息。

## Decision Rules

- 被打进焦点时，先解释自己的行为链，再反问攻击者的逻辑漏洞，避免只自证身份。
- 听到强神或预言家宣称时，先记录其查验、行动收益和发言一致性，不急于无条件站边。
- 遗言要留下最清晰的投票建议和怀疑链，帮助好人继续推进。

## Risk Boundaries

- 不编造夜间信息，不虚假跳强神。
- 不因为某个玩家发言强势就直接认好，必须结合行为收益判断。
