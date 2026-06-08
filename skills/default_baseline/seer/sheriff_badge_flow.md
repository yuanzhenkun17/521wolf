---
name: seer_sheriff_badge_flow
role: seer
status: active
applicable_actions:
  - sheriff_run
  - sheriff_speak
  - sheriff_badge
  - speak
  - last_word
evolution:
  enabled: true
  allowed_actions:
    - append_rule
    - rewrite_section
    - deprecate_rule
---

# 预言家警徽流

## Strategy

- 警徽流要服务信息延续：说明当前验人、下一轮优先查验方向、以及警徽应交给谁承接信息。
- 对跳或被强压时，优先拆解验人链、票型收益和发言矛盾，不只反复强调身份。
- 发言要区分已知查验、公开事实和个人推理，方便好人阵营复盘。

## Decision Rules

- 上警时先交代验人结果，再给出后续查验顺序和警徽移交原则。
- 若存在对跳，优先解释哪条预言家线能产生更多可验证信息。
- 临终或移交警徽时，优先交给能继续带队、身份相对可信、且能复述验人链的人。

## Risk Boundaries

- 不把警徽交给身份未明且强势带偏的人。
- 不把低置信怀疑包装成查验事实。
- 不因被攻击就放弃交代警徽流。
