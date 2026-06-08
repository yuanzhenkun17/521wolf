---
name: werewolf_claim_and_vote_pressure
role: werewolf
status: active
applicable_actions:
  - sheriff_run
  - sheriff_speak
  - speak
  - last_word
  - exile_vote
  - pk_vote
  - sheriff_vote
evolution:
  enabled: true
  allowed_actions:
    - append_rule
    - rewrite_section
    - deprecate_rule
---

# 狼人悍跳与投票施压

## Strategy

- 悍跳或强势发言要构造自洽伪视角，目标是压制真信息链并制造好人误判。
- 投票路线在冲票、倒钩和切割之间选择团队收益最高的方案。
- 发言可以混入真实公开观察来提高可信度，但不要暴露狼队协同痕迹。

## Decision Rules

- 上警悍跳时，伪验人、站边理由和后续发言顺序要能互相解释。
- 队友轻压时软拆火，队友明显暴露时适度切割，保住整体身份结构。
- 关键票型中优先推动好人焦点位出局，同时保留合理投票理由。

## Risk Boundaries

- 不硬保明显暴露的队友。
- 不频繁改口导致伪视角崩坏。
- 不为个人存活破坏狼队整体收益。
