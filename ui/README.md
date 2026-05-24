# 521wolf UI

第三层 UI 代码独立放在 `ui/` 下，不进入规则层 `src/werewolf`。

## 后端

FastAPI 后端负责启动现有 `GameEngine`、监听结构化日志，并通过 SSE 推送给前端。

```bash
uv run uvicorn ui.backend.app:app --reload --host 127.0.0.1 --port 8000
```

主要接口：

- `POST /api/games`：启动一局新游戏。
- `GET /api/games`：列出当前和历史游戏。
- `GET /api/games/{game_id}`：读取游戏快照。
- `GET /api/games/{game_id}/events`：订阅实时日志事件。

## 前端

React + Vite + Tailwind CSS，使用本地 shadcn/ui 风格组件。

```bash
cd ui/frontend
npm install
npm run dev
```

开发服务器默认访问 `http://127.0.0.1:5173`，并把 `/api` 代理到 `http://127.0.0.1:8000`。

