---
name: witch_default_day_control_vote
role: witch
status: active
applicable_actions:
  - speak
  - sheriff_speak
  - pk_speak
  - last_word
  - exile_vote
  - pk_vote
  - sheriff_vote
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

# 女巫默认白天控场

## Strategy

- 白天不轻易暴露女巫身份，除非需要阻止好人误出或保护关键预言家视角。
- 发言可强调夜间结果带来的局势变化，但不要泄露不必要的用药细节。
- 投票优先处理高置信狼人，必要时用身份压力统一好人票。

## Decision Rules

- 如果自己掌握的信息能直接纠正错误归票，应及时发言干预。
- 被推上焦点时，先用逻辑自保；身份跳出只作为避免好人重大损失的手段。
- 拿到警徽或发言顺序时，让预言家、查杀位、对跳位尽早发言，便于判断是否用身份控场。

## Risk Boundaries

- 不随意报出完整药况，避免狼人精准安排夜刀。
- 不把身份权威用于低置信目标。
