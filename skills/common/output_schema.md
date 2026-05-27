---
name: output_schema
description: 输出格式要求：JSON schema、字段说明
scope: common
---

# 输出格式要求

- 必须只输出 JSON。
- 字段如下：

```json
{
  "choice": string | null,
  "target": number | null,
  "public_text": string,
  "private_reasoning": string,
  "confidence": 0.0~1.0,
  "alternatives": [number],
  "rejected_reasons": [string],
  "memory_refs": [string],
  "selected_skills": [string]
}
```

- `public_text` 是公开发言内容。
- `private_reasoning` 是私有推理，不能出现在公开发言中。
- `target` 必须来自 candidates，除非该行动允许弃权或不需要目标。
- `choice` 必须和当前动作匹配。
- `confidence` 是置信度（0.0 到 1.0）。
