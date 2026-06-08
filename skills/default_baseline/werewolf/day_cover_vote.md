---
name: werewolf_default_day_cover_vote
role: werewolf
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

# 狼人默认白天伪装与投票

## Strategy

- 伪装成有独立思考的普通好人，主动给出怀疑链，但不要过度保护队友。
- 发言中混入真实观察，提高可信度；关键处引导好人怀疑非狼玩家。
- 竞选警长时只有在能稳定控场或干扰真预言家时才上警，压力过大时及时退水。

## Decision Rules

- 队友轻微受压时可以软性拆火；队友明显暴露时要适度切割，保住整体阵营。
- 投票优先选择好人焦点位；如果必须投队友，提前铺垫理由，避免突兀。
- 拿到警徽或发言顺序权时，让好人焦点位先发言，让队友避开最危险位置。

## Risk Boundaries

- 不频繁改口，不制造无法解释的票型。
- 不直接替队友硬辩到底，除非全队收益明确。
