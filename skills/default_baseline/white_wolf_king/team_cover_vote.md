---
name: white_wolf_king_default_team_cover_vote
role: white_wolf_king
status: active
applicable_actions:
  - werewolf_kill
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

# 白狼王默认团队协同

## Strategy

- 夜间与普通狼人一致，优先处理高价值好人；白天保留自爆威慑，制造好人投票顾虑。
- 发言要像能独立找狼的好人，不主动强调特殊身份，避免过早成为全场焦点。
- 竞选警长时可用强势发言争夺控制权，但一旦被多方锁定，要准备转换成自爆收益。

## Decision Rules

- 夜刀目标要兼顾身份收益和次日发言解释，避免暴露狼队意图。
- 队友被压时，先评估是否需要切割；如果切割能保留自爆位和团队生存，就不要硬救。
- 掌握警徽或发言顺序时，让真信息位先暴露，再用发言制造对立。

## Risk Boundaries

- 不在没有收益目标时暴露自爆身份。
- 不把所有逻辑绑定到单个队友身上。
