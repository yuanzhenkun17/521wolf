# 前端重构设计：main.js 拆分为 Vue 3 SFC + Composables

**日期：** 2026-06-04  
**状态：** 已确认

---

## 背景

`ui/frontend/src/main.js` 是一个 ~2500 行的巨型文件，包含全部状态（~80 个 ref）、计算属性（~50 个）、方法（~100 个）、HTML 模板字符串、watcher 和生命周期钩子。所有视图（大厅、对局、日志、自进化）都在同一个 `createApp()` 内。

这次重构的目标是将代码拆分为标准 Vue 3 SFC（`.vue`）文件，并通过 Composables 管理逻辑，使每个文件控制在 300 行以内。

---

## 目录结构

```
ui/frontend/src/
├── main.js                     # 入口，createApp + mount（~30行）
├── App.vue                     # 根组件，页面路由 + TopNav
├── style.css                   # 全局变量、reset、公共样式
│
├── composables/
│   ├── useGameState.js         # game ref, loading, error, phase, player 计算属性
│   ├── useGameActions.js       # submitSpeech/Vote/Action, startMode, reset, step, watch
│   ├── useGameHistory.js       # history list, select game, replay, pages, decisions
│   ├── useMatchUtils.js        # playerLabel, normalizePlayerText, cardImage, roleIconImage
│   └── useCouncilScene.js      # mount/sync/dispose, scene ref, rAF throttle
│
├── pages/
│   ├── LobbyPage.vue           # 模式选择、开始按钮
│   ├── MatchPage.vue           # 对局主视图（组合子组件）
│   ├── LogsPage.vue            # 日志浏览器
│   └── EvolutionPage.vue       # 自进化页面
│
├── components/
│   ├── TopNav.vue              # 顶部导航栏
│   ├── CouncilScene.vue        # Three.js 场景封装
│   ├── PlayerCarousel.vue      # 发言者轮播卡片
│   ├── JudgeStrip.vue          # 法官消息滚动条
│   ├── ChatLog.vue             # 玩家聊天日志
│   ├── RoleStats.vue           # 角色统计条
│   ├── ActionPanel.vue         # 投票/行动操作面板
│   ├── NightActionCard.vue     # 夜间行动卡片
│   ├── DecisionDetail.vue      # 决策详情（多 tab）
│   ├── VoteResults.vue         # 投票结果
│   ├── SeatLedger.vue          # 玩家席位
│   ├── MultiAssess.vue         # 多维测评柱状图
│   └── HistoryGameList.vue     # 历史对局列表
│
├── mockAgentGame.js            # 保持不变
└── CouncilHallScene.js         # 保持不变
```

---

## Composables 职责划分

### 数据流

```
App.vue（持有 composable 实例，页面路由）
  ├── useGameState()    ← game, loading, error, players, phase 等响应式状态
  ├── useGameActions()  ← 依赖 useGameState，所有 API 调用
  ├── useGameHistory()  ← 独立，历史对局数据管理
  ├── useMatchUtils()   ← 纯函数，玩家标签、文本替换
  └── useCouncilScene() ← 依赖 useGameState，Three.js 生命周期
```

### Composable 之间如何共享状态

App.vue 调用 `useGameState()` 拿到返回对象后，将其作为参数传给依赖它的 composable：

```js
// App.vue
const state = useGameState()
const actions = useGameActions(state)        // state = { game, loading, error, ... }
const utils = useMatchUtils(state)
const scene = useCouncilScene(state)
const history = useGameHistory()             // 独立，不依赖 state
```

Composables 之间**不**直接调用彼此，也不使用 provide/inject。所有数据流通过 App.vue 中转，保持单向、可追踪的依赖关系。

### 各 Composable 职责

#### `useGameState`
**输入：** 无  
**输出：** `game`, `loading`, `error`, `currentView`, `isNight`, `inLobby`, `inMatch`, `inLogs`, `inEvolution`, `isWatch`, `humanPlayer`, `livingPlayers`, `canVotePlayers`, `publicLogs`, `chatLogs`, `judgeLogs`, `groupedJudgeLogs`, `speakingPlayer`, `speakerMessage`, `speakerCarousel`, `displayPhase`, `promptText`, `roleName`, `pendingAction`, `pendingActionType`, `skillState`, `isHumanWitch`, `isHumanWhiteWolf`, `actionCandidates`, `needsTarget`, `actionInstruction`, `speechCountdownText`, `pageVoteTally`, `sceneVoteTally`, `roleStats`, `playerIdentityList`, `decisionRows`, `judgeStripMessage`, `sheriffElection`, `inferredSheriffId`, `visualSeatPlayers`

**注意：** 所有响应式状态的唯一来源。其他 composable 通过接收 `{ game, loading }` 等参数来访问共享状态。

#### `useGameActions`
**输入：** `{ game, loading, error, isReplayMode, backendMode, watchRunning, isWatch }`  
**输出：** `startMode`, `resetGame`, `stepGame`, `startWatch`, `stopWatch`, `toggleWatch`, `submitSpeech`, `submitVote`, `submitAction`, `submitWhiteWolfBurst`, `chooseScenePlayer`, `startFromJudgeBoard`, `refreshHealth`

**职责：** 封装所有对后端 API 的调用，管理 watch timer 和 EventSource。

#### `useGameHistory`
**输入：** 无  
**输出：** `gameHistory`, `selectedHistoryGame`, `selectedHistoryGameId`, `selectedHistoryPageKey`, `historyPhase`, `historyLoading`, `historyPages`, `selectedHistoryPage`, `historyDecisionRows`, `filteredHistoryDecisionRows`, `pageNightActions`, `pageVoteResults`, `pageLastWords`, `pageSpeechDecisions`, `historyStats`, `playerAssessmentScores`, `activeAssessScores`, `playerAliveAtPage`, `nightResult`, `sheriffResult`, `enterReplayPage`, `exitReplayMode`, `selectHistoryGame`, `openLogPage`, `loadArchive`, `loadReview`, `historyLogSpeaker`, `historyNormalizeText`, `historyPhaseName`, `historyPlayerById`, `historyPageTitle`

#### `useMatchUtils`
**输入：** `{ game, isWatch, backendMode, visualSeatSalt, visualSeatPlayers }`  
**输出：** `playerLabel`, `playerNumberById`, `normalizePlayerText`, `cardImage`, `roleIconImage`, `speakerImage`, `logSpeaker`, `logMessage`

**职责：** 纯计算函数，无副作用，可在多个组件间复用。

#### `useCouncilScene`
**输入：** `{ game, isNight, visualSeatPlayers, isWatch, ... }`  
**输出：** `gameSceneRef`, `mountCouncilScene`, `syncCouncilScene`, `disposeCouncilScene`, `scheduleSyncCouncilScene`

**职责：** 管理 Three.js 场景的创建、更新和销毁，含 rAF 节流。

---

### 页面组件如何获取数据

App.vue 将 composable 返回的值通过 props 传递给页面组件，页面组件通过 emit 向上传递事件：

```vue
<!-- App.vue -->
<LobbyPage
  v-if="inLobby"
  :backend-mode="backendMode"
  :loading="loading"
  @start="startMode"
/>
```

页面组件**不**直接调用 composable，所有数据来自 props。

---

## 页面组件组成

### MatchPage.vue
```
MatchPage
├── <CouncilScene />              ← Three.js 3D 场景
├── <PlayerCarousel />            ← 发言者轮播卡片
├── <JudgeStrip />                ← 法官消息滚动条
├── <ChatLog />                   ← 玩家聊天日志（可折叠）
├── <RoleStats />                 ← 角色统计条
├── <ActionPanel />               ← 投票/行动操作面板
└── <div class="speech-input">    ← 发言输入（内联）
```

### LogsPage.vue
```
LogsPage
├── <HistoryGameList />           ← 左侧历史对局列表
├── <MultiAssess />               ← 多维测评柱状图
├── <SeatLedger />                ← 玩家席位
├── <nav class="phase-tabs">     ← 阶段切换（内联）
├── 页面内容区（按 phase）：
│   ├── night → <NightActionCard /> + <DecisionDetail />
│   ├── speech → 发言决策卡片（内联）
│   ├── vote → <VoteResults />
│   └── ended → 结算信息
└── 复盘控制栏（底部，内联）
```

### EvolutionPage.vue
角色选择网格 + 排行榜 + 演化路径（单文件，不拆子组件）

### LobbyPage.vue
模式选择按钮 + 开始/观战（模板简短，单文件即可）

---

## CSS 迁移策略

1. **全局 style.css 保留**：CSS 变量（`--bg`, `--primary`, `--text` 等）、reset、`body` 基础样式、`.lycan-app` 容器样式
2. **逐步迁移**：当把某个组件模板抽出来时，把 style.css 中**该组件用到的选择器**一并搬入该 `.vue` 文件的 `<style scoped>`
3. **不做一次性大拆**：随组件迁移逐步进行，降低风险

**不做的事：**
- 不引入 Tailwind / UnoCSS
- 不做 CSS-in-JS
- 不重新设计视觉风格，只做结构迁移

---

## 保持不变的部分

- `CouncilHallScene.js` — Three.js 场景逻辑不动，仅通过 `useCouncilScene` 包一层 Vue 生命周期管理
- `mockAgentGame.js` — mock 数据保持不变
- `public/` — 所有静态资源（图片、模型）保持不变
- 后端 API 接口 — 不改动任何 API 调用方式

---

## 迁移顺序

建议分步迁移，每步都保持应用可运行：

1. **Phase 1：搭建骨架**  
   创建目录结构，App.vue（仅路由），`main.js` 精简为入口

2. **Phase 2：提取 Composables**  
   按 `useGameState` → `useMatchUtils` → `useGameActions` → `useCouncilScene` → `useGameHistory` 顺序提取，每提取一个就运行验证

3. **Phase 3：拆分页面组件**  
   按 `LobbyPage` → `MatchPage` → `LogsPage` → `EvolutionPage` 顺序拆分

4. **Phase 4：提取子组件**  
   从 MatchPage 和 LogsPage 中逐步提取 `JudgeStrip`、`ChatLog`、`NightActionCard` 等

5. **Phase 5：CSS 迁移**  
   随组件迁移逐步搬移 style.css 中对应的样式到 `<style scoped>`

---

## 约束

- 保持 Vue 3 + Vite 技术栈
- 不改动后端 API 或 Three.js 场景核心逻辑
- 不引入新的状态管理库（Pinia），composables 足够
- 每个文件目标 < 300 行
- 迁移过程中应用必须始终可运行
