---
name: seer_claim
description: 预言家起跳：跳预言家时机、查验报告、警徽流
role: seer
applicable_actions:
  - sheriff_run
  - sheriff_speak
  - speak
requires: {}
evolution:
  enabled: true
  allowed_actions:
    - append_rule
    - rewrite_section
---

# 预言家起跳

## 目标

在适当时机跳预言家，公布查验结果，引导好人阵营。

## 策略原则

- 第一天尽早跳预言家，越晚跳可信度越低。
- 明确报告查验结果：查验了谁，是金水还是查杀。
- 给出警徽流，安排死后验人顺序。
- 归票日带头组织投票。

