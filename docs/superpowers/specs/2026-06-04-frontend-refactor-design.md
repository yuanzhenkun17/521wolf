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
│   ├── NightActionCard.vue     # 夜间行动卡片（单个决策卡片）
│   ├── DecisionDetail.vue      # 决策详情（多 tab）
│   ├── NightSection.vue        # 夜间阶段内容（含多张 NightActionCard）
│   ├── SpeechSection.vue       # 发言阶段内容（发言卡片 + 遗言）
│   ├── VoteSection.vue         # 投票阶段内容（投票结果 + 警长投票）
│   ├── VoteResults.vue         # 投票结果展示
│   ├── SeatLedger.vue          # 玩家席位
│   ├── MultiAssess.vue         # 多维测评柱状图
│   ├── HistoryGameList.vue     # 历史对局列表
│   ├── PhaseTabs.vue           # 日志阶段切换导航
│   └── ReplayControls.vue      # 复盘控制栏
│
├── mockAgentGame.js            # 保持不变
└── CouncilHallScene.js         # 保持不变
```

---

## Composables 职责划分

### 数据流

```
App.vue（持有 composable 实例，页面路由）
  ├── useGameState()    ← game, loading, error, players, phase, match UI state 等
  ├── useGameActions(state)  ← 所有 API 调用，修改 state refs
  ├── useGameHistory(state, actions)  ← 历史对局 + 复盘（依赖 state 和 actions）
  ├── useMatchUtils(state)   ← 纯函数，玩家标签、文本替换
  └── useCouncilScene(state) ← Three.js 生命周期
```

### Composable 之间如何共享状态

App.vue 调用 `useGameState()` 拿到返回对象后，将其作为参数传给依赖它的 composable：

```js
// App.vue
const state = useGameState()
const actions = useGameActions(state)        // state = { game, loading, error, ... }
const utils = useMatchUtils(state)
const scene = useCouncilScene(state)
const history = useGameHistory(state, actions) // 依赖 state + actions
```

Composables 之间**不**直接调用彼此，也不使用 provide/inject。所有数据流通过 App.vue 中转，保持单向、可追踪的依赖关系。

### 各 Composable 职责

#### `useGameState`
**输入：** 无  
**输出：** `game`, `loading`, `error`, `currentView`, `isNight`, `inLobby`, `inMatch`, `inLogs`, `inEvolution`, `isWatch`, `isReplayMode`, `backendMode`, `watchRunning`, `humanPlayer`, `livingPlayers`, `canVotePlayers`, `publicLogs`, `chatLogs`, `judgeLogs`, `groupedJudgeLogs`, `speakingPlayer`, `speakerMessage`, `speakerCarousel`, `displayPhase`, `promptText`, `roleName`, `pendingAction`, `pendingActionType`, `skillState`, `isHumanWitch`, `isHumanWhiteWolf`, `actionCandidates`, `needsTarget`, `actionInstruction`, `speechCountdownText`, `pageVoteTally`, `sceneVoteTally`, `roleStats`, `playerIdentityList`, `decisionRows`, `judgeStripMessage`, `sheriffElection`, `inferredSheriffId`, `visualSeatPlayers`, `speech`, `speechRemaining`, `voteTarget`, `actionTarget`, `witchChoice`, `burstArmed`, `playerCount`, `judgeBoardStarted`, `judgeBoardStarting`, `roleAssignmentComplete`, `roleAssignmentCompleteNotice`, `lastLiveGame`, `returnToMatchAvailable`, `chatLogExpanded`, `chatListRef`, `judgeListRef`, `judgeStripRef`, `gameSceneRef`, `visualSeatSalt`, `externalStatus`

**注意：** 所有响应式状态的唯一来源。其他 composable 通过接收 `{ game, loading }` 等参数来访问共享状态。

#### `useGameActions`
**输入：**
- 来自 `useGameState`：`game`, `loading`, `error`, `isWatch`, `isReplayMode`, `backendMode`
- 来自 `useGameState`（match UI 状态）：`watchRunning`, `speech`, `speechRemaining`, `voteTarget`, `actionTarget`, `witchChoice`, `burstArmed`, `playerCount`, `judgeBoardStarted`, `judgeBoardStarting`, `roleAssignmentComplete`, `roleAssignmentCompleteNotice`, `currentView`, `lastLiveGame`
- 来自 `useGameState`（computed）：`livingPlayers`, `canVotePlayers`, `actionCandidates`, `pendingActionType`, `whiteWolfTargets`

**输出：** `startMode`, `resetGame`, `stepGame`, `startWatch`, `stopWatch`, `toggleWatch`, `submitSpeech`, `submitVote`, `submitAction`, `submitWhiteWolfBurst`, `chooseScenePlayer`, `startFromJudgeBoard`, `refreshHealth`, `startSpeechTimer`, `clearSpeechTimer`

**职责：** 封装所有对后端 API 的调用，管理 watch timer、EventSource 和发言倒计时。

> **说明：** `useGameState` 负责声明所有 refs，`useGameActions` 通过参数访问并修改它们（如 `loading.value = true`、`currentView.value = 'match'`）。这是 Vue composable 的标准模式——refs 是可变引用，传入即可读写。

#### `useGameHistory`
**输入：** 来自 `useGameState` 的 `game`, `currentView`, `isReplayMode`, `lastLiveGame`, `returnToMatchAvailable`；来自 `useGameActions` 的 `stopWatch`, `startWatch`
**输出：** `gameHistory`, `selectedHistoryGame`, `selectedHistoryGameId`, `selectedHistoryPageKey`, `historyPhase`, `historyLoading`, `historyPages`, `selectedHistoryPage`, `historyDecisionRows`, `filteredHistoryDecisionRows`, `pageNightActions`, `pageVoteResults`, `pageLastWords`, `pageSpeechDecisions`, `historyStats`, `playerAssessmentScores`, `activeAssessScores`, `playerAliveAtPage`, `nightResult`, `sheriffResult`, `enterReplayPage`, `exitReplayMode`, `selectHistoryGame`, `openLogPage`, `loadArchive`, `loadReview`, `historyLogSpeaker`, `historyNormalizeText`, `historyPhaseName`, `historyPlayerById`, `historyPageTitle`

> **说明：** `enterReplayPage` 会修改 `game.value`（构建 snapshot）、设置 `isReplayMode.value = true`、保存 `lastLiveGame`、切换 `currentView`。`exitReplayMode` 会恢复 `game.value` 并重启 watch。因此 `useGameHistory` **不是独立的**，必须接收 state 和 actions 才能正确执行。

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

**跨页面状态**（game、currentView、loading 等）由 App.vue 通过 props 传递。

**页面局部 UI 状态**（如 `assessDimension`、`selectedDecision`、`detailTab`、`speech`、`voteTarget`、`witchChoice`、`chatLogExpanded` 等）由页面组件自己管理——可以内联在 `<script setup>` 中作为 `ref()`，也可以提取为页面级 composable（如 `useLogsPageState()`）。

```vue
<!-- App.vue — 只传跨页面状态 -->
<LobbyPage
  v-if="inLobby"
  :backend-mode="backendMode"
  :loading="loading"
  @start="startMode"
/>

<!-- LogsPage.vue — 自己管理 assessDimension、selectedDecision、detailTab 等 -->
<script setup>
const assessDimension = ref('speech')
const selectedDecision = ref(null)
const detailTab = ref('summary')
// ...
</script>
```

这样 App.vue 只承担真正的路由职责，不会变成巨大的接线层。

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
LogsPage（管理 assessDimension, selectedDecision, detailTab 等局部状态）
├── <HistoryGameList />           ← 左侧历史对局列表
├── <MultiAssess />               ← 多维测评柱状图
├── <SeatLedger />                ← 玩家席位
├── <PhaseTabs />                 ← 阶段切换（独立组件）
├── 页面内容区（按 phase）：
│   ├── night → <NightSection />  ← 含 NightActionCard + DecisionDetail
│   ├── speech → <SpeechSection /> ← 发言决策卡片列表 + 遗言
│   ├── vote → <VoteSection />    ← VoteResults + 警长投票
│   └── ended → 结算信息（内联，模板短）
└── <ReplayControls />            ← 复盘控制栏（底部）
```

> **说明：** 原方案把 `night/speech/vote/ended` 内容和复盘控制栏都内联在 LogsPage，加上 scoped CSS，模板会超过 300 行。因此将各阶段内容和复盘控制栏拆为独立子组件。每个阶段组件只需 props 传入当前 page 和 filtered decisions，自己负责渲染。

### EvolutionPage.vue
角色选择网格 + 排行榜 + 演化路径（单文件，不拆子组件）

### LobbyPage.vue
模式选择按钮 + 开始/观战（模板简短，单文件即可）

---

## CSS 迁移策略

1. **全局 style.css 保留**：CSS 变量（`--bg`, `--primary`, `--text` 等）、reset、`body` 基础样式、`.lycan-app` 容器样式
2. **状态依赖选择器保持全局**：`.lycan-app.night`、`.lycan-app.day`、`.lycan-app.logbook`、`.lycan-app.evolution` 等**根状态选择器及其子选择器**必须保留在全局 style.css 中。这些选择器依赖 `<main :class="lycan-app night/day">`，放进子组件 scoped style 后会因 scoped 属性哈希而失效。
3. **普通选择器迁移至 scoped**：当把某个组件模板抽出来时，把 style.css 中**不依赖父级状态类**的选择器搬入该 `.vue` 文件的 `<style scoped>`
4. **混合情况用 `:deep()`**：如果一个选择器同时需要 scoped 隔离和访问父级状态类，在 scoped style 中使用 `:deep(.lycan-app.night) .my-component` 明确穿透

**分类指引（迁移时按此判断）：**

| 选择器模式 | 归属 | 示例 |
|---|---|---|
| `.lycan-app.night .foo` | 全局 style.css | 依赖根状态类 |
| `.lycan-app.day .foo` | 全局 style.css | 依赖根状态类 |
| `.lycan-app.logbook .foo` | 全局 style.css | 依赖根状态类 |
| `.foo .bar`（无祖先状态类） | 组件 `<style scoped>` | 纯组件内部选择器 |
| 需要两者兼有 | scoped + `:deep()` | 少数情况 |

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
