---
name: guard_default_day_low_profile_vote
role: guard
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

# 守卫默认白天低调推进

## Strategy

- 白天以普通好人的推理方式发言，不主动暴露守卫身份。
- 重点观察谁在试探神职、谁在推动出关键好人、谁的夜间收益解释不自然。
- 投票优先保护信息链，避免关键预言家或可信带队者被错误放逐。

## Decision Rules

- 被推成焦点时，先用发言和票型自证；身份跳出只在即将造成重大损失时使用。
- 竞选警长通常保持谨慎，除非场上缺少稳定归票者。
- 拿到警徽或发言顺序时，让信息位和焦点位尽早发言，自己保持守护信息不外泄。

## Risk Boundaries

- 不公开暗示守护目标。
- 不为保护身份而放弃关键投票责任。
