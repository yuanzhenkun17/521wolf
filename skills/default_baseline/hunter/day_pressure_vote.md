---
name: hunter_default_day_pressure_vote
role: hunter
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

# 猎人默认白天施压

## Strategy

- 发言要主动压迫矛盾位，利用猎人潜在威慑让狼人不敢轻易强推。
- 不轻易明跳猎人，除非自己即将被错误放逐或需要保护关键好人。
- 投票优先跟随可信信息源，同时保留对推动错误归票者的追责。

## Decision Rules

- 被怀疑时，先交代行为逻辑和投票理由，再说明自己会追责强推者。
- 竞选警长时，只有在能强势整理焦点和归票时参与；否则保持低调观察票型。
- 遗言要明确自己最想带走或最怀疑的目标，减少好人后续分歧。

## Risk Boundaries

- 不用身份威胁替代推理。
- 不因持枪身份过度冲锋导致过早暴露。
