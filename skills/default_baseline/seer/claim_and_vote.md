---
name: seer_default_claim_and_vote
role: seer
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

# 预言家默认报验与归票

## Strategy

- 有查杀或关键金水时，优先上警建立信息源；没有足够收益时也要清晰说明查验逻辑。
- 报验必须包含查验结果、查验理由、下一步警徽流或后续关注位。
- 投票围绕查验信息推进，不让场面被无关争吵带偏。

## Decision Rules

- 遭遇对跳时，比较双方查验链、警徽流、发言前后一致性，并明确要求好人按信息收益投票。
- 若自己出局，遗言要留下全部查验结果、最可信好人、优先放逐目标。
- 拿到警徽后，发言顺序优先安排对跳位、查杀位和强怀疑位暴露更多信息。

## Risk Boundaries

- 不隐瞒关键查验结果。
- 不在没有理由时随意更改警徽流或归票目标。
