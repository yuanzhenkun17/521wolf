# 项目结构整理方案

本文档记录本轮项目结构清理的目标和执行规则。核心目标是让评委和队友进入仓库后能快速识别三条主线：

- `engine/werewolf/`：规则引擎，只负责狼人杀规则、状态流转、日志和 `ActionRequest` / `ActionResponse` 协议。
- `agent/`：Agent 层主实现，只保留当前 v2 runtime、记忆、belief、skills、ToT、评测和可观测能力。
- `ui/`：观战 UI 和后端 API。

## 1. 清理原则

1. 根目录只保留入口文件、配置示例和顶层代码目录。
2. 旧版 Agent 包不再保留，避免 `playeragent` 和 `agent` 并存造成理解成本。
3. 规则层不再保留旧的 `agent_runtime` 兼容转发目录。
4. 根目录 Markdown 文档统一移动到 `docs/`，根目录只保留 `README.md`。
5. Python import 尽量稳定：规则包仍叫 `werewolf`，只是源码根目录从 `src/` 改为 `engine/`。

## 2. 目标目录

```text
521wolf/
  README.md
  .env.example
  pyproject.toml
  uv.lock

  engine/
    werewolf/
      actions.py
      config.py
      engine.py
      logging.py
      models.py
      phases/
      role_rules/
      rules/

  agent/
    runtime/
    nodes/
    cognition/
    skills/
    skill_system/
    reasoning/
    prompts/
    observability/
    evaluation/

  ui/
    backend/
    frontend/

  tests/
  docs/
  data/
```

## 3. 本轮执行项

### 3.1 Agent 层

- 删除旧 `playeragent/`。
- 将 `agent/` 改名为 `agent/`。
- 全量替换代码和测试中的 `agent` import 为 `agent`。
- 删除依赖旧 `playeragent` 的 legacy 测试。

### 3.2 Engine 层

- 将 `src/` 改名为 `engine/`。
- 保持 Python 包名 `werewolf` 不变，因此外部代码仍使用：

```python
from werewolf.engine import GameEngine
```

- 删除 `engine/werewolf/agent_runtime/`。
- 删除旧 `llm_agents.py` 和旧 LLM demo 入口，因为 Agent 主线已经迁移到 `agent/`。

### 3.3 文档

- 根目录的 `第一层.md`、`第二层.md`、`PLAYER_AGENT_INTERFACE.md` 移动到 `docs/`。
- `README.md` 更新为新的目录结构。

## 4. 验证标准

清理完成后必须满足：

- `rg "from playeragent|import playeragent"` 无业务代码残留。
- `rg "agent"` 无业务代码残留。
- `rg "werewolf.agent_runtime"` 无残留。
- `uv run python -m unittest discover -s tests -v` 通过。
- `npm run build` 在 `ui/frontend` 下通过。
