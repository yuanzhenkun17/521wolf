---
name: reasoning_contract
scope: common
category: foundation
evolvable: false
---

public_text 是公开内容，private_reasoning 是私有推理。
confidence 是你对此决策的置信度 (0.0 到 1.0)。
memory_refs 可选，用于标注引用的记忆条目。
target 必须是 candidates 里的数字，除非该行动允许弃权或不需要目标。
