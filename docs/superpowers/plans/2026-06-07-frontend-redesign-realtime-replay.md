# 前端三页面重设计 + 实时流 + 回放 + 对话气泡 + 对局持久化

> 目标:Logs / 批量评测 / 自进化 三页面彻底重写;对局全局持久(切标签不丢);
> 后端后台运行对局 + 逐事件实时 SSE 推送;历史对局事件流回放(播放/暂停/自动);
> 发言对话气泡。分 4 个阶段交付。

## 决策(已确认)

| 维度 | 决策 |
|---|---|
| 实时流 | 后端后台运行对局 + 真实时逐事件推送(边跑边看) |
| 三页面 | 彻底重写(组件树 + 样式系统) |
| 对局持久 | 全局后台状态,切任意标签不中断,可随时切回 |
| 交付 | 4 块全做,分阶段 |

## 关键技术事实(已调研)

- 引擎 `GameLogger.record()` 每步同步 append 到 `entries`,并已有 per-event seam:
  `EventSink.record_event(entry)`(`engine/logging.py:19-21,74-75`)。**无需改引擎。**
- `run_until_finished` 是普通 coroutine,只返回 `Winner`,不是 async generator。
  唯一的 mid-game 观测点是 `EventSink` 或轮询 `logger.entries`。
- `LiveGameSession` 已以 `asyncio.create_task` 后台运行(`app.py:379-421`),但只为人类玩家,
  且 snapshot 是轮询式,无 push。
- 现 `GET /games/{id}/events` SSE 是**假的**:把已存事件倒一遍再 `done`(`app.py:922-933`)。
- 旧架构有完整 push 管道(`subscribers: set[asyncio.Queue]` + `_broadcast`),已删除,
  可参照 `git show HEAD:ui/backend/game_runner.py`。
- `record_event` 是同步的 → 必须用 `queue.put_nowait`,不能 `await put`。

---

## 阶段 1:对局持久化 + 导航修复(前端为主)

> 解决"切标签丢对局"。最高优先,纯前端。

### 1.1 提取全局对局会话状态
- 现状:`game.value` 在 `useGameState` 全局,但 MatchPage 在 `inMatch=false` 时整树卸载
  (含 3D CouncilScene),切回需重建;watch SSE 在 `openLogPage` 等处被 `stopWatch()` 杀掉。
- 改:新增 `useGameSession`(或扩展 `useLiveGameState`)持有"后台运行的对局"概念:
  - `activeSession`: { gameId, mode, running, sseConnected }
  - 切标签时**不** `stopWatch()`,而是保持 SSE/轮询在后台运行,只切 `currentView`。
  - `currentView` 仍是单一字符串路由,但 `game.value` + SSE 连接与视图解耦。

### 1.2 顶栏"对局进行中"指示
- `TopNav` 增加一个 pill:当 `activeSession.running` 时显示"对局进行中 · 点此返回",
  点击 = `backToMatch()`。
- 修 `backToMatch`:即使中途切过多个标签也能恢复(目前依赖 `returnToMatchAvailable`,
  切到第二个标签会丢)。改为只要 `game.value && !winner` 就允许返回。

### 1.3 MatchPage 保活(keep-alive)
- 用 `<KeepAlive>` 包住 MatchPage,或把 3D 场景实例提到全局,避免切标签销毁/重建场景。
- 验证:开观战 → 切 Logs → 切 Evolution → 切回 Match,对局仍在跑、场景不重置。

### 阶段 1 验证
- [ ] 开一局观战,切 Logs/Benchmark/Evolution 再切回,对局继续、进度不丢
- [ ] 顶栏显示进行中指示并可一键返回
- [ ] 回放进入再退出后,原直播对局仍可恢复

---

## 阶段 2:后端后台运行 + 真实时 SSE(后端为主)

> 让观战/普通对局边跑边推事件。重建被删的 push 管道。

### 2.1 事件总线(新) `app/` 或 `ui/backend/`
- 新增 `BroadcastEventSink`(实现引擎 `EventSink` 协议):
  - 持有 `subscribers: set[asyncio.Queue]`
  - `record_event(entry)` → 每个 queue `put_nowait(to_jsonable(entry))`(同步,不 await)
  - `subscribe()` → 新建 queue,预填 backlog,注册;`unsubscribe()` → 移除
- 放在 `ui/backend/`(它是 backend 专属编排,不属于 app/ 纯逻辑层)。

### 2.2 后台运行非人类对局
- 现 `start_game` 无人类玩家时同步 `await run_game(...)` 跑完才返回(`app.py:352`)。
- 改:统一走 `LiveGameSession` 后台任务模型(`asyncio.create_task`),
  engine 用 `GameLogger(sink=BroadcastEventSink)` 构建。
  - 复用 `create_engine` 但注入带 sink 的 logger(参照 `GamePersistence.create_event_logger`
    的构造,组合 SQLite sink + broadcast sink)。
  - `start_game` 立即返回 `{game_id, status: running}`,不阻塞。
- 决策记录(agent)也需推送:`AgentDecisionRecorder` 加一个可选 observer 回调,
  或在 broadcast sink 里识别 decision 事件。

### 2.3 真 SSE 端点
- 重写 `GET /games/{id}/events`(`app.py:922-933`):
  - `queue = sink.subscribe(game_id)`;循环 `event = await queue.get()` → `yield _sse("log", event)`
  - 游戏结束推 `done`;`finally` 里 `unsubscribe`
  - 心跳:定期 `yield _sse("ping", {})` 防代理断连
- 保留 `decision_needed`(人类玩家)语义。

### 2.4 前端对接
- `useGameActions` 的 EventSource 逻辑(`useGameActions.js:237-267`)改为:
  - 不再每个 `log` 事件就 `loadCurrentGame` 全量重拉,而是**增量 apply** 单条事件到 `game.value.logs`。
  - 减少请求,真正流式。

### 阶段 2 验证
- [ ] 开观战对局,事件逐条实时出现(非整局算完才出)
- [ ] 多个浏览器/标签订阅同一局都能收到
- [ ] 对局结束收到 done,SSE 干净关闭
- [ ] 后端无人类玩家对局不再阻塞 HTTP

---

## 阶段 3:事件流回放(播放/暂停/自动)(纯前端)

> 历史对局逐事件回放,带播放控制条。替换现有静态"天/阶段"快照回放。

### 3.1 回放引擎(新) `useReplayPlayer`
- 输入:历史对局的完整 events + decisions(已在手,`selectedHistoryGame`)。
- 状态:`cursor`(当前事件索引)、`playing`、`speed`(0.5x/1x/2x/4x)。
- `play()`:定时器按 speed 推进 `cursor`,每步把"截至 cursor 的事件"重建为 game 快照
  (复用现有 `buildReplaySnapshot` 的增量死亡/警长/发言推导逻辑,但按**事件**而非"天/阶段")。
- `pause()` / `step()` / `seek(index)` / `reset()`。
- 自动播放到末尾停止。

### 3.2 回放控制条 UI(新组件)
- `ReplayControls`:播放/暂停按钮、进度条(可拖动 seek)、速度选择、
  当前事件描述(D2 白天 · P3 投票 P5)、事件计数(127/340)。
- 嵌入 MatchPage 回放模式(替代当前按页跳转)。

### 3.3 接入
- `replayHistoryGame` 进入回放模式时初始化 `useReplayPlayer`,默认暂停在第 0 帧。
- 退出回放恢复 `lastLiveGame`(已有逻辑)。

### 阶段 3 验证
- [ ] 选历史对局 → 进入回放 → 点播放,事件逐条流式出现
- [ ] 暂停/继续/拖进度条/变速正常
- [ ] 播到末尾自动停,可重播
- [ ] 退出回放回到历史列表 / 原直播对局

---

## 阶段 4:对话气泡 + 三页面重设计(前端)

### 4.1 对话气泡
- 新组件 `SpeechBubble`:发言时在对应座位旁/上方浮出气泡(玩家号 + 发言文本),
  随 `current_speaker_id` 切换,淡入淡出。
- 集成到 CouncilScene(3D 场景内 HTML 叠加层,或 2D 座位环)。
- 直播与回放共用(回放时由 replay player 驱动 current_speaker)。

### 4.2 三页面彻底重写
- **共享设计系统**:抽 `ui/frontend/src/styles/` 的 design tokens(色板/间距/卡片/表格),
  三页面统一视觉语言。
- **LogsPage(2319 行)**:拆成 子组件(对局列表 / 详情 / 复盘 / 时间线 / 回放入口)。
  接入阶段 3 的回放控制。
- **BenchmarkPage**:对齐后端新契约(role_version 对照 / 跨批次公平性 / leaderboard 真实分数,
  已在数据层修过),重做排行榜与批次视图。
- **EvolutionPage(1764 行)**:展示新的 decide 裁决(recommendation / significant /
  win_rate_delta / published_version,已在 normalizeRun 加好),baseline/candidate 对战分栏
  (side 标记已加),拆子组件。

### 阶段 4 验证
- [ ] 发言气泡在直播与回放中正确浮现/消失
- [ ] 三页面视觉统一、数据正确、交互顺畅
- [ ] `npm run build` 干净
- [ ] 后端全量 `uv run pytest tests/` 通过

---

## 风险与缓解

| 风险 | 缓解 |
|---|---|
| 后台对局生命周期泄漏(任务不回收) | 对局结束/超时/客户端断开时 cancel task + 清理 subscribers |
| `put_nowait` 队列满(慢客户端) | 有界队列 + 丢弃最旧 或 断开慢订阅者 |
| 3D 场景保活内存 | KeepAlive include 限定;退出对局时显式 dispose |
| 三页面重写回归 | 每页重写后跑现有 UI backend 契约测试 + 手动冒烟 |
| 实时 SSE 与 SQLite 持久化双 sink 顺序 | 组合 sink,先持久化后广播,保证落库不丢 |

## 阶段依赖

```
阶段1(对局持久/导航) ── 纯前端,可独立先交付 ← 最高优先
阶段2(后端实时SSE)   ── 后端为主 + 前端对接;依赖引擎现成 EventSink
阶段3(事件流回放)     ── 纯前端;与阶段2独立,可并行
阶段4(气泡+三页面)    ── 前端;气泡可与阶段2/3复用,三页面重写最后做
```

建议交付顺序:**阶段1 → 阶段2 → 阶段3 → 阶段4**,每阶段独立可验证、可提交。
