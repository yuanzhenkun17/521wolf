# 前端重构实现计划：main.js → Vue 3 SFC + Composables

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 将 `ui/frontend/src/main.js`（~2500行）拆分为标准 Vue 3 SFC 组件和 Composables，使每个文件 < 300 行。

**Architecture:** 提取 5 个 Composables（逻辑层）+ 4 个页面组件 + 13 个子组件（UI层）。Composables 通过函数参数共享 refs，页面组件通过 props 接收跨页面状态、自行管理局部 UI 状态。

**Tech Stack:** Vue 3 Composition API (SFC), Vite, Three.js（不变）

**验证方式：** 每个 Task 完成后运行 `npm run dev`，在浏览器中确认大厅、对局、日志、自进化四个页面均正常渲染，控制台无报错。

**Spec:** `docs/superpowers/specs/2026-06-04-frontend-refactor-design.md`

---

## 文件结构总览

```
ui/frontend/src/
├── main.js                     # 入口（Phase 1 后变为 ~30 行）
├── App.vue                     # 根组件：页面路由 + TopNav
├── style.css                   # 全局样式（逐步精简）
├── composables/
│   ├── useGameState.js         # 所有响应式状态 + computed
│   ├── useMatchUtils.js        # 纯函数：playerLabel、normalizePlayerText 等
│   ├── useGameActions.js       # API 调用 + watch timer
│   ├── useCouncilScene.js      # Three.js 生命周期封装
│   └── useGameHistory.js       # 历史对局 + 复盘
├── pages/
│   ├── LobbyPage.vue
│   ├── MatchPage.vue
│   ├── LogsPage.vue
│   └── EvolutionPage.vue
├── components/
│   ├── TopNav.vue
│   ├── CouncilScene.vue
│   ├── PlayerCarousel.vue
│   ├── JudgeStrip.vue
│   ├── ChatLog.vue
│   ├── RoleStats.vue
│   ├── ActionPanel.vue
│   ├── NightSection.vue
│   ├── SpeechSection.vue
│   ├── VoteSection.vue
│   ├── NightActionCard.vue
│   ├── DecisionDetail.vue
│   ├── VoteResults.vue
│   ├── SeatLedger.vue
│   ├── MultiAssess.vue
│   ├── HistoryGameList.vue
│   ├── PhaseTabs.vue
│   └── ReplayControls.vue
├── mockAgentGame.js            # 不变
└── CouncilHallScene.js         # 不变
```

---

## Phase 1：搭建骨架

### Task 1: 创建目录结构和 App.vue 骨架

**Files:**
- Create: `ui/frontend/src/composables/`（目录）
- Create: `ui/frontend/src/pages/`（目录）
- Create: `ui/frontend/src/components/`（目录）
- Create: `ui/frontend/src/App.vue`

- [ ] **Step 1: 创建目录**

```bash
cd ui/frontend
mkdir -p src/composables src/pages src/components
```

- [ ] **Step 2: 创建 App.vue 骨架**

创建 `ui/frontend/src/App.vue`，包含以下结构：

```vue
<script setup>
import { createApp, computed, nextTick, onBeforeUnmount, onMounted, ref, watch } from 'vue'
// 后续 Task 中逐步 import composables 和 pages
</script>

<template>
  <main :class="['lycan-app', { night: isNight, day: !isNight, lobbying: inLobby && !inLogs, logbook: inLogs, evolution: inEvolution }]">
    <div class="atmosphere"></div>
    <div class="noise"></div>
    <!-- TopNav 和页面组件将在后续 Task 中逐步填充 -->
  </main>
</template>

<style scoped>
/* 组件特有样式将在此添加 */
</style>
```

此时 App.vue 内容为空壳，所有逻辑仍在 main.js 中。

- [ ] **Step 3: 验证**

运行 `npm run dev`，确认应用仍使用旧的 main.js 正常运行（App.vue 此时未被引用）。

- [ ] **Step 4: Commit**

```bash
git add ui/frontend/src/App.vue ui/frontend/src/composables/ ui/frontend/src/pages/ ui/frontend/src/components/
git commit -m "refactor: create directory structure and App.vue skeleton"
```

---

### Task 2: 切换入口到 App.vue（保持旧逻辑完整）

**Files:**
- Modify: `ui/frontend/src/main.js`
- Modify: `ui/frontend/src/index.html`

这一步将 main.js 中的旧 `createApp({setup..., template: ...})` 移到 App.vue，并让 main.js 变为只调用 `createApp(App).mount('#app')`。

**策略：** 不在此 Task 拆分逻辑，而是把整个旧代码原样搬到 App.vue 的 `<script setup>` 和 `<template>` 中。这保证应用行为完全不变，同时建立 SFC 结构。

- [ ] **Step 1: 将 main.js 的逻辑搬到 App.vue**

把 `ui/frontend/src/main.js` 中以下内容搬到 `App.vue`：

1. **import 语句**（main.js 第 1-4 行）→ App.vue `<script setup>` 顶部
2. **常量定义**（第 6-56 行：`API`, `phaseText`, `phaseLabel`, `roleIconSpecs`, `roleMatches`, `evolutionRoles`）→ `<script setup>`
3. **setup() 函数体**（第 58-1533 行：所有 ref、computed、methods、watch、lifecycle）→ `<script setup>`（去掉 `setup()` 包裹）
4. **return 语句**（第 1534-1674 行）→ **删除**（SFC `<script setup>` 自动暴露所有顶层绑定）
5. **template 字符串**（第 1676-2485 行）→ App.vue `<template>`

注意：Vue SFC 的 `<script setup>` 中不能用 `vue/dist/vue.esm-bundler.js`，改为标准 `import { ... } from 'vue'`。

- [ ] **Step 2: 精简 main.js**

将 `ui/frontend/src/main.js` 改为：

```js
import { createApp } from 'vue'
import App from './App.vue'
import './style.css'

createApp(App).mount('#app')
```

- [ ] **Step 3: 确认 index.html 不需要改动**

`index.html` 第 14 行引用 `<script type="module" src="/src/main.js">`，无需修改。

- [ ] **Step 4: 验证**

```bash
npm run dev
```

在浏览器中打开，验证：大厅页面渲染正常、点击"观战"可进入对局、切换到日志和自进化页面正常、3D 场景加载正常、控制台无报错。

- [ ] **Step 5: Commit**

```bash
git add ui/frontend/src/main.js ui/frontend/src/App.vue
git commit -m "refactor: migrate all logic from main.js to App.vue SFC"
```

---

## Phase 2：提取 Composables

### Task 3: 提取 useMatchUtils.js

**Files:**
- Create: `ui/frontend/src/composables/useMatchUtils.js`
- Modify: `ui/frontend/src/App.vue`

这是第一个提取的 composable，因为它是最简单的——纯函数，无副作用。

- [ ] **Step 1: 创建 useMatchUtils.js**

```js
import { computed } from 'vue'

const roleIconSpecs = [
  { key: 'whiteWolfKing', role: '白狼王', tokens: ['白狼王'], image: '/role-crops/white-wolf-king.png' },
  { key: 'werewolf', role: '狼人', tokens: ['狼人'], image: '/role-crops/werewolf.png' },
  { key: 'villager', role: '村民', tokens: ['村民'], image: '/role-crops/villager.png' },
  { key: 'seer', role: '预言家', tokens: ['预言'], image: '/role-crops/seer.png' },
  { key: 'witch', role: '女巫', tokens: ['女巫'], image: '/role-crops/witch.png' },
  { key: 'hunter', role: '猎人', tokens: ['猎人'], image: '/role-crops/hunter.png' },
  { key: 'guard', role: '守卫', tokens: ['守卫'], image: '/role-crops/guard.png' }
]

function roleMatches(role = '', tokens = []) {
  return tokens.some((token) => role.includes(token))
}

export { roleIconSpecs, roleMatches }

export function useMatchUtils(state) {
  const { game, isWatch, backendMode, visualSeatSalt, visualSeatPlayers } = state

  // --- 座位映射 ---
  const visualSeatById = computed(() =>
    new Map(visualSeatPlayers.value.map((player, index) => [player.id, index + 1]))
  )

  function playerNumber(player) {
    if (!player) return ''
    return visualSeatById.value.get(player.id) || player.seat || player.id
  }

  function playerNumberById(id) {
    const player = game.value?.players?.find((item) => item.id === id)
    return player ? playerNumber(player) : id
  }

  function playerLabel(player) {
    const number = playerNumber(player)
    return number ? `${number}号` : ''
  }

  // --- 文本标准化（含 regex 缓存）---
  let _normRegexCache = []
  let _normRegexSig = ''

  function _buildNormRegexCache(players) {
    const sig = `${isWatch.value}:${backendMode.value}:${visualSeatSalt.value}:` +
      players.map((p) => `${p.id}:${p.seat}:${p.name}`).join('|')
    if (sig === _normRegexSig) return
    _normRegexSig = sig
    const sorted = [...players].sort((a, b) => String(b.name || '').length - String(a.name || '').length)
    _normRegexCache = sorted.map((player) => {
      const visual = playerLabel(player)
      if (!visual) return null
      const escapedName = String(player.name || '').replace(/[.*+?^${}()|[\]\\]/g, '\\$&')
      return {
        visual,
        seatNameSp: `${player.seat}号 ${player.name}`,
        seatName: `${player.seat}号${player.name}`,
        nameRe: escapedName ? new RegExp(escapedName, 'g') : null,
        seatRe: new RegExp(`${player.seat}\\s*号`, 'g')
      }
    }).filter(Boolean)
  }

  function normalizePlayerText(text = '') {
    let value = String(text || '')
    const players = game.value?.players ?? []
    if (!players.length) return value
    _buildNormRegexCache(players)
    for (const entry of _normRegexCache) {
      value = value.replaceAll(entry.seatNameSp, entry.visual)
      value = value.replaceAll(entry.seatName, entry.visual)
      if (entry.nameRe) value = value.replace(entry.nameRe, entry.visual)
      value = value.replace(entry.seatRe, entry.visual)
    }
    return value
  }

  function logSpeaker(log) {
    const player = game.value?.players?.find((item) => item.id === log?.actor_id || item.name === log?.speaker)
    if (!player) return normalizePlayerText(log?.speaker || '')
    const roleSuffix = String(log?.speaker || '').replace(new RegExp(`^${player.seat}\\s*号`), '')
    return roleSuffix && roleSuffix !== player.name ? `${playerLabel(player)}${roleSuffix}` : playerLabel(player)
  }

  function logMessage(log) {
    return normalizePlayerText(log?.message || '')
  }

  // --- 卡片/图标映射 ---
  function cardImage(player) {
    if (!isWatch.value && player && !player.is_human) return '/cards/card-back.png'
    const hint = player?.role_hint || ''
    if (hint.includes('预言')) return '/cards/seer.png'
    if (hint.includes('女巫')) return '/cards/witch.png'
    if (hint.includes('猎人')) return '/cards/hunter.png'
    if (hint.includes('守卫')) return '/cards/guard.png'
    if (hint.includes('白狼王')) return '/cards/white-wolf-king.png'
    if (hint.includes('狼人')) return '/cards/wolf.png'
    return '/cards/villager.png'
  }

  function roleIconImage(player) {
    const hint = player?.role_hint || ''
    if (hint.includes('预言')) return '/role-icons/预言家.png'
    if (hint.includes('女巫')) return '/role-icons/女巫.png'
    if (hint.includes('猎人')) return '/role-icons/猎人.png'
    if (hint.includes('守卫')) return '/role-icons/守卫.png'
    if (hint.includes('白狼王')) return '/role-icons/白狼王.png'
    if (hint.includes('狼人')) return '/role-icons/普通狼.png'
    return '/role-icons/平民.png'
  }

  function speakerImage(player) {
    return player ? cardImage(player) : '/cards/judge.png'
  }

  return {
    roleIconSpecs,
    roleMatches,
    playerNumber,
    playerNumberById,
    playerLabel,
    normalizePlayerText,
    logSpeaker,
    logMessage,
    cardImage,
    roleIconImage,
    speakerImage
  }
}
```

- [ ] **Step 2: 在 App.vue 中引用 useMatchUtils**

在 App.vue `<script setup>` 中：

```js
import { useMatchUtils, roleIconSpecs, roleMatches } from './composables/useMatchUtils'

// ... 在所有 ref 和 computed 定义之后 ...
const state = { game, isWatch, backendMode, visualSeatSalt, visualSeatPlayers }
const { playerNumber, playerNumberById, playerLabel, normalizePlayerText,
        logSpeaker, logMessage, cardImage, roleIconImage, speakerImage } = useMatchUtils(state)
```

然后**删除** App.vue 中已搬到 useMatchUtils 的代码：
- `roleIconSpecs` 常量
- `roleMatches` 函数
- `visualSeatById` computed
- `playerNumber`, `playerNumberById`, `playerLabel` 函数
- `_normRegexCache`, `_normRegexSig`, `_buildNormRegexCache`, `normalizePlayerText` 函数
- `logSpeaker`, `logMessage` 函数
- `cardImage`, `roleIconImage`, `speakerImage` 函数

同时删除 return 中对应的条目（SFC 自动暴露 import 的绑定）。

- [ ] **Step 3: 验证**

```bash
npm run dev
```

验证所有页面正常，特别注意玩家标签显示（如"1号"）和角色图标是否正确。

- [ ] **Step 4: Commit**

```bash
git add ui/frontend/src/composables/useMatchUtils.js ui/frontend/src/App.vue
git commit -m "refactor: extract useMatchUtils composable"
```

---

### Task 4: 提取 useGameState.js

**Files:**
- Create: `ui/frontend/src/composables/useGameState.js`
- Modify: `ui/frontend/src/App.vue`

提取所有 ref 声明和纯 computed 属性。这是最大的 composable。

- [ ] **Step 1: 创建 useGameState.js**

从 App.vue 中提取以下内容到 `useGameState.js`：

**输入参数：** 无（但接收 `useMatchUtils` 返回的 `playerLabel`, `normalizePlayerText`, `cardImage`, `roleIconImage`, `logSpeaker`, `logMessage` 作为参数，因为 computed 依赖它们）

**要搬移的 refs（原 main.js 第 60-108 行）：**
```js
const game = ref(null)
const loading = ref(false)
const error = ref('')
const speech = ref('我先报一下自己的视角：目前重点听发言逻辑和票型。')
const speechRemaining = ref(180)
const voteTarget = ref(1)
const actionTarget = ref(null)
const witchChoice = ref('skip')
const burstArmed = ref(false)
const playerCount = ref(12)
const watchRunning = ref(false)
const backendMode = ref('mock')
const externalStatus = ref(null)
const archiveByGameId = ref({})
const reviewByGameId = ref({})
const archiveLoading = ref(false)
const reviewLoading = ref(false)
const judgeBoardStarted = ref(false)
const judgeBoardStarting = ref(false)
const roleAssignmentComplete = ref(false)
const roleAssignmentCompleteNotice = ref(false)
const initialHash = window.location.hash
const currentView = ref(initialHash === '#logs' ? 'logs' : (initialHash === '#evolution' ? 'evolution' : 'lobby'))
const gameHistory = ref([])
const selectedHistoryGameId = ref(null)
const selectedHistoryGame = ref(null)
const historyLoading = ref(false)
const historyPhase = ref('all')
const assessDimension = ref('speech')
const selectedHistoryPageKey = ref('')
const isReplayMode = ref(false)
const replaySourceGameId = ref(null)
const replayPageKey = ref('')
const lastLiveGame = ref(null)
const visualSeatSalt = ref(Math.random().toString(36).slice(2))
const returnToMatchAvailable = ref(false)
const evolutionSelectedRoles = ref([])
const selectedDecision = ref(null)
const detailTab = ref('summary')
const chatLogExpanded = ref(false)
const chatListRef = ref(null)
const judgeListRef = ref(null)
const judgeStripRef = ref(null)
const gameSceneRef = ref(null)
```

**要搬移的 computed（原 main.js 第 112-434 行）：**
所有 computed 属性原样搬移，包括 `isNight`, `inLogs`, `inEvolution`, `inLobby`, `inMatch`, `isWatch`, `humanPlayer`, `livingPlayers`, `canVotePlayers`, `publicLogs`, `chatLogs`, `judgeLogs`, `groupedJudgeLogs`, `speakingPlayer`, `displayPhase`, `visualSeatPlayers`, `playerIdentityList`, `roleStats`, `promptText`, `speakerMessage`, `speakerCarousel`, `inferredSheriffId`, `sheriffElection`, `roleName`, `pendingAction`, `pendingActionType`, `skillState`, `isHumanWitch`, `isHumanWhiteWolf`, `canUseWitchAntidote`, `canUseWitchPoison`, `actionCandidates`, `whiteWolfTargets`, `canWhiteWolfBurst`, `needsTarget`, `actionInstruction`, `speechCountdownText`, `pageVoteTally`, `sceneVoteTally`, `decisionRows`, `judgeStripMessage`, `judgeBoardMessage`

以及 history 相关 computed（第 470-831 行）：`historyPhaseTabs`, `historyPages`, `selectedHistoryPage`, `playerAliveAtPage`, `historyLogs`, `nightResult`, `sheriffResult`, `sheriffVotes`, `sheriffVoteTally`, `currentVoteTally`, `voteDecisions`, `historyDecisionRows`, `filteredHistoryDecisionRows`, `pageNightActions`, `pageVoteResults`, `pageLastWords`, `pageSpeechDecisions`, `historyStats`, `playerAssessmentScores`, `activeAssessScores`

**函数定义也要搬（被 computed 引用的）：**
- `canSeeLog`（第 121 行）
- `historyPlayerById`, `historyPlayerLabelById`, `historyLogSpeaker`, `historyPhaseName`, `historyPageKeyFor`, `historyPageTitle`, `historyNormalizeText`, `historyDecisionMatchesPage`, `nightActionDetail`（第 492-730 行）
- `formatJson`, `compactList`（第 884-893 行）
- `decisionActionText` 常量（第 436-469 行）
- `historyPhaseTabs` 常量（第 470-480 行）
- `seatHash` 函数（第 361-368 行）

**useGameState 函数签名：**

```js
import { computed, ref, watch, nextTick, onBeforeUnmount, onMounted } from 'vue'

export function useGameState(utils) {
  // utils = { playerLabel, normalizePlayerText, cardImage, roleIconImage, logSpeaker, logMessage }
  // ... 所有 ref 和 computed 定义 ...

  return {
    game, loading, error, currentView, isNight, inLobby, inMatch, inLogs, inEvolution,
    isWatch, isReplayMode, backendMode, watchRunning, externalStatus,
    humanPlayer, livingPlayers, canVotePlayers,
    // ... 所有 ref 和 computed ...
    // ... 所有被其他 composable 需要的函数 ...
  }
}
```

- [ ] **Step 2: 在 App.vue 中引用 useGameState**

由于 `useMatchUtils` 和 `useGameState` 存在循环依赖（`useMatchUtils` 需要 `visualSeatPlayers`，`useGameState` 需要 `playerLabel`），采用**先声明 refs，再分别传入**的方式打破：

```js
// App.vue <script setup>
import { ref, computed } from 'vue'
import { useMatchUtils, roleIconSpecs, roleMatches } from './composables/useMatchUtils'
import { useGameState } from './composables/useGameState'

// 1. 先声明所有 base refs（useGameState 内部的 ref 声明搬到此处，或 useGameState 接受外部 refs）
//    推荐方式：useGameState 内部声明 refs，返回值包含所有 refs
const state = useGameState()

// 2. 用 state 的 refs 构造 utils（Vue reactivity 会延迟追踪，此时 state.visualSeatPlayers 是 ref）
const utils = useMatchUtils({
  game: state.game,
  isWatch: state.isWatch,
  backendMode: state.backendMode,
  visualSeatSalt: state.visualSeatSalt,
  visualSeatPlayers: state.visualSeatPlayers
})

// 3. 把 utils 传回 useGameState（如果 computed 需要 playerLabel 等）
//    但由于 useGameState 已经在 Step 1 执行完毕，这里的 computed 需要在 Step 1 就能访问 utils
```

**实际可行方案：把 `visualSeatPlayers` 等 computed 的构建延迟到 App.vue 中，不放在 useGameState 里。**

具体做法：
- `useGameState` 中**不定义** `visualSeatPlayers`、`playerIdentityList`、`roleStats` 等依赖 `playerLabel`/`roleIconImage` 的 computed
- 这些 computed 放在 App.vue 中定义（它们依赖 utils 和 state 两者）
- `useGameState` 返回的 state 不含这些 computed
- App.vue 中补充这些 computed 后再传给页面组件

这样 `useGameState` 不依赖 utils，`useMatchUtils` 依赖 state 的 refs（但不依赖 computed），无循环。

```js
// App.vue
const state = useGameState()  // 不含 visualSeatPlayers 等
const utils = useMatchUtils({
  game: state.game, isWatch: state.isWatch, backendMode: state.backendMode,
  visualSeatSalt: state.visualSeatSalt,
  visualSeatPlayers: computed(() => { /* 原 main.js 第 369-418 行的逻辑 */ })
})
// 此后 utils.playerLabel 等可用
const playerIdentityList = computed(() => { /* 需要 state + utils */ })
const roleStats = computed(() => { /* 需要 state + utils */ })
// ... 传给页面组件
```

- [ ] **Step 3: 删除 App.vue 中已搬到 useGameState 的代码**

删除所有已搬走的 ref 声明、computed 属性、辅助函数。保留 import 和 composable 调用。

- [ ] **Step 4: 验证**

```bash
npm run dev
```

验证所有页面正常渲染，computed 属性（如 `playerIdentityList`, `roleStats`）工作正常。

- [ ] **Step 5: Commit**

```bash
git add ui/frontend/src/composables/useGameState.js ui/frontend/src/App.vue
git commit -m "refactor: extract useGameState composable"
```

---

### Task 5: 提取 useGameActions.js

**Files:**
- Create: `ui/frontend/src/composables/useGameActions.js`
- Modify: `ui/frontend/src/App.vue`

- [ ] **Step 1: 创建 useGameActions.js**

从 App.vue 提取以下函数（原 main.js 第 864-1281 行）。**函数体从 App.vue 原样搬移**，不改变任何逻辑。下方只列函数签名和结构，实际实现时把对应行号的代码粘贴到函数体中。

```js
const API = import.meta.env.VITE_API_BASE || '/api'

export function useGameActions(state, utils) {
  // state = { game, loading, error, currentView, isWatch, isReplayMode, backendMode,
  //           watchRunning, speech, speechRemaining, voteTarget, actionTarget, witchChoice,
  //           burstArmed, playerCount, judgeBoardStarted, judgeBoardStarting,
  //           roleAssignmentComplete, roleAssignmentCompleteNotice, lastLiveGame,
  //           returnToMatchAvailable, visualSeatSalt, externalStatus }
  // utils = { playerLabel, normalizePlayerText }

  let timer = null
  let speechTimer = null
  let eventSource = null

  // --- API 基础 ---
  async function apiFetch(path, options = {}) { /* 原 main.js 第 864-882 行 */ }
  async function refreshHealth() { /* 第 895-904 行 */ }
  async function request(path, options = {}) { /* 第 906-927 行 */ }

  // --- 对局控制 ---
  function startMode(mode, testRole = null) { /* 第 1088-1105 行 */ }
  function resetGame() { /* 第 1115-1125 行 */ }
  function stepGame() { /* 第 1127-1129 行 */ }

  // --- Watch 控制 ---
  function startWatch() { /* 第 1132-1163 行 */ }
  function stopWatch() { /* 第 1190-1198 行 */ }
  function toggleWatch() { /* 第 1200-1206 行 */ }

  // --- 发言 ---
  function clearSpeechTimer() { /* 第 1208-1212 行 */ }
  function startSpeechTimer() { /* 第 1215-1225 行 */ }
  function submitSpeech(textOverride = null) { /* 第 1227-1234 行 */ }

  // --- 投票/行动 ---
  function submitVote() { /* 第 1236-1242 行 */ }
  function submitAction(action, targetId, choice) { /* 第 1244-1253 行 */ }
  function submitWhiteWolfBurst(targetId) { /* 第 1255-1259 行 */ }
  function chooseScenePlayer(playerId) { /* 第 1262-1281 行 */ }

  // --- 法官开局 ---
  function startFromJudgeBoard() { /* 第 1165-1188 行 */ }

  return {
    apiFetch, refreshHealth, request,
    startMode, resetGame, stepGame,
    startWatch, stopWatch, toggleWatch,
    clearSpeechTimer, startSpeechTimer, submitSpeech,
    submitVote, submitAction, submitWhiteWolfBurst,
    chooseScenePlayer, startFromJudgeBoard
  }
}
```

每个函数体从 App.vue 原样搬移，只把内部引用的 `game.value`、`loading.value` 等改为 `state.game.value`、`state.loading.value`。或者使用解构：

```js
export function useGameActions(state, utils) {
  const { game, loading, error, currentView, isWatch, isReplayMode, backendMode,
          watchRunning, speech, speechRemaining, voteTarget, actionTarget, witchChoice,
          burstArmed, playerCount, judgeBoardStarted, judgeBoardStarting,
          roleAssignmentComplete, roleAssignmentCompleteNotice, lastLiveGame,
          returnToMatchAvailable, visualSeatSalt, externalStatus } = state
  // ... 函数体中直接用 game.value, loading.value 等
}
```

- [ ] **Step 2: 在 App.vue 中引用**

```js
import { useGameActions } from './composables/useGameActions'
const actions = useGameActions(state, utils)
```

删除 App.vue 中已搬走的函数。

- [ ] **Step 3: 验证**

```bash
npm run dev
```

重点测试：点击"观战"按钮启动对局、watch 自动推进、发言提交、投票提交、法官开局流程。

- [ ] **Step 4: Commit**

```bash
git add ui/frontend/src/composables/useGameActions.js ui/frontend/src/App.vue
git commit -m "refactor: extract useGameActions composable"
```

---

### Task 6: 提取 useCouncilScene.js

**Files:**
- Create: `ui/frontend/src/composables/useCouncilScene.js`
- Modify: `ui/frontend/src/App.vue`

- [ ] **Step 1: 创建 useCouncilScene.js**

从 App.vue 提取以下代码（原 main.js 第 1407-1517 行）。**函数体从 App.vue 原样搬移**，只调整引用前缀（如 `game.value` 改为 `state.game.value` 或解构后的局部变量）。

```js
import { nextTick, onBeforeUnmount, watch } from 'vue'
import { createCouncilHallScene } from '../CouncilHallScene.js'

export function useCouncilScene(state, utils) {
  // state 中需要: game, isNight, isWatch, isReplayMode, judgeBoardStarted,
  //               roleAssignmentComplete, roleAssignmentCompleteNotice,
  //               gameSceneRef, visualSeatPlayers
  // utils 中需要: roleIconImage, normalizePlayerText, playerLabel, logSpeaker, logMessage

  let councilScene = null
  let syncRafId = 0
  let syncScheduled = false

  function canSeeLog(log) {
    return log.visibility !== 'private' && (log.visibility !== 'god' || state.isWatch.value)
  }

  async function mountCouncilScene() { /* 原第 1407-1415 行 */ }
  async function waitForCouncilModels() { /* 原第 1417-1424 行 */ }
  function hideCouncilScene() { /* 原第 1426-1430 行 */ }
  function syncCouncilScene() { /* 原第 1432-1480 行 */ }
  function scheduleSyncCouncilScene() { /* 原第 1484-1491 行 */ }

  // Watchers（原第 1498-1517 行）
  watch(() => [
    state.game.value?.players?.map((p) => `${p.id}:${p.role_hint}:${p.alive}`).join('|'),
    state.game.value?.current_speaker_id,
    state.game.value?.logs?.length,
    state.judgeBoardStarted.value,
    state.roleAssignmentComplete.value,
    // ... 其他依赖 ...
  ], scheduleSyncCouncilScene)

  onBeforeUnmount(() => {
    if (syncRafId) cancelAnimationFrame(syncRafId)
    councilScene?.dispose?.()
    councilScene = null
  })

  return {
    gameSceneRef: state.gameSceneRef,
    mountCouncilScene,
    waitForCouncilModels,
    hideCouncilScene,
    syncCouncilScene,
    scheduleSyncCouncilScene
  }
}
```

- [ ] **Step 2: 在 App.vue 中引用并删除旧代码**

- [ ] **Step 3: 验证**

```bash
npm run dev
```

重点测试：3D 场景加载、玩家 standee 显示、气泡消息、发言时场景同步。

- [ ] **Step 4: Commit**

```bash
git add ui/frontend/src/composables/useCouncilScene.js ui/frontend/src/App.vue
git commit -m "refactor: extract useCouncilScene composable"
```

---

### Task 7: 提取 useGameHistory.js

**Files:**
- Create: `ui/frontend/src/composables/useGameHistory.js`
- Modify: `ui/frontend/src/App.vue`

- [ ] **Step 1: 创建 useGameHistory.js**

从 App.vue 提取以下代码。**函数体从 App.vue 原样搬移**，只调整引用前缀。

**函数：**
- `refreshHistoryList`（原第 929-942 行）
- `selectHistoryGame`（原第 944-958 行）
- `openLogPage`（原第 960-967 行）
- `openEvolutionPage`（原第 969-974 行）
- `toggleEvolutionRole`, `isEvolutionRoleSelected`（第 976-984 行）
- `goLobby`（第 986-992 行）
- `backToMatch`（第 994-1007 行）
- `buildReplaySnapshot`（第 1009-1047 行）
- `enterReplayPage`（第 1049-1063 行）
- `returnToHistoryFromReplay`（第 1065-1069 行）
- `exitReplayMode`（第 1071-1086 行）
- `loadArchive`, `loadReview`（第 1362-1384 行）

```js
export function useGameHistory(state, actions) {
  // state = { game, loading, error, currentView, isReplayMode, lastLiveGame,
  //           returnToMatchAvailable, selectedHistoryGameId, selectedHistoryGame,
  //           selectedHistoryPageKey, historyPhase, historyLoading, gameHistory,
  //           judgeBoardStarted, judgeBoardStarting, roleAssignmentComplete,
  //           roleAssignmentCompleteNotice, visualSeatSalt,
  //           archiveByGameId, reviewByGameId, archiveLoading, reviewLoading,
  //           evolutionSelectedRoles, watchRunning }
  // actions = { stopWatch, startWatch, apiFetch, request }

  async function refreshHistoryList({ silent = false } = {}) { /* ... */ }
  async function selectHistoryGame(gameId) { /* ... */ }
  async function openLogPage(gameId, { rememberOrigin = true } = {}) { /* ... */ }
  function openEvolutionPage({ rememberOrigin = true } = {}) { /* ... */ }
  function toggleEvolutionRole(key) { /* ... */ }
  function isEvolutionRoleSelected(key) { /* ... */ }
  function goLobby() { /* ... */ }
  function backToMatch() { /* ... */ }
  function buildReplaySnapshot(source, page) { /* ... */ }
  function enterReplayPage(page) { /* ... */ }
  function returnToHistoryFromReplay() { /* ... */ }
  function exitReplayMode() { /* ... */ }
  async function loadArchive(gameId) { /* ... */ }
  async function loadReview(gameId) { /* ... */ }

  return {
    refreshHistoryList, selectHistoryGame,
    openLogPage, openEvolutionPage,
    toggleEvolutionRole, isEvolutionRoleSelected,
    goLobby, backToMatch,
    buildReplaySnapshot, enterReplayPage, returnToHistoryFromReplay, exitReplayMode,
    loadArchive, loadReview
  }
}
```

- [ ] **Step 2: 在 App.vue 中引用并删除旧代码**

```js
import { useGameHistory } from './composables/useGameHistory'
const history = useGameHistory(state, actions)
```

- [ ] **Step 3: 验证**

```bash
npm run dev
```

重点测试：日志页面加载、选择历史对局、点击复盘按钮、退出复盘、返回对局、自进化页面。

- [ ] **Step 4: Commit**

```bash
git add ui/frontend/src/composables/useGameHistory.js ui/frontend/src/App.vue
git commit -m "refactor: extract useGameHistory composable"
```

---

## Phase 3：拆分页面组件

### Task 8: 创建 TopNav.vue + LobbyPage.vue

**Files:**
- Create: `ui/frontend/src/components/TopNav.vue`
- Create: `ui/frontend/src/pages/LobbyPage.vue`
- Modify: `ui/frontend/src/App.vue`

- [ ] **Step 1: 创建 TopNav.vue**

从 App.vue template 中提取 `<header class="topbar">` 部分（原 main.js 第 1681-1691 行）：

```vue
<script setup>
defineProps({
  currentView: String
})
const emit = defineEmits(['go-lobby', 'open-logs', 'open-evolution'])
</script>

<template>
  <header class="topbar">
    <div class="brand">
      <img src="/topbar-characters.png" alt="NightCouncil" />
      <strong>NightCouncil</strong>
    </div>
    <nav>
      <button @click="emit('go-lobby')">大厅</button>
      <button @click="emit('open-logs')">日志</button>
      <button @click="emit('open-evolution')">自进化</button>
    </nav>
  </header>
</template>
```

- [ ] **Step 2: 创建 LobbyPage.vue**

从 App.vue template 中提取 `v-if="inLobby"` 的大厅部分（原 main.js 对应的 lobby 视图模板）。props 接收 `backendMode`, `loading`, `error`；emit `start-mode`, `start-vote-test`。

- [ ] **Step 3: 在 App.vue 中引用**

```vue
<script setup>
import TopNav from './components/TopNav.vue'
import LobbyPage from './pages/LobbyPage.vue'
</script>

<template>
  <main :class="[...]">
    <div class="atmosphere"></div>
    <div class="noise"></div>
    <TopNav @go-lobby="history.goLobby()" @open-logs="history.openLogPage()" @open-evolution="history.openEvolutionPage()" />
    <LobbyPage v-if="state.inLobby.value" ... />
    <!-- 其他页面后续添加 -->
  </main>
</template>
```

- [ ] **Step 4: 验证**

```bash
npm run dev
```

- [ ] **Step 5: Commit**

```bash
git add ui/frontend/src/components/TopNav.vue ui/frontend/src/pages/LobbyPage.vue ui/frontend/src/App.vue
git commit -m "refactor: extract TopNav and LobbyPage components"
```

---

### Task 9: 创建 MatchPage.vue + 子组件

**Files:**
- Create: `ui/frontend/src/pages/MatchPage.vue`
- Create: `ui/frontend/src/components/CouncilScene.vue`
- Create: `ui/frontend/src/components/PlayerCarousel.vue`
- Create: `ui/frontend/src/components/JudgeStrip.vue`
- Create: `ui/frontend/src/components/ChatLog.vue`
- Create: `ui/frontend/src/components/RoleStats.vue`
- Create: `ui/frontend/src/components/ActionPanel.vue`
- Modify: `ui/frontend/src/App.vue`

- [ ] **Step 1: 创建子组件**

逐个从 App.vue template 中提取 match 视图的子区块：

**CouncilScene.vue：** 简单封装 `<div class="council-scene" ref="gameSceneRef">`，接收 `gameSceneRef` 作为 prop 或通过 template ref。

**PlayerCarousel.vue：** 提取 `speakerCarousel` 轮播卡片模板（原 template 中 `.speaker-carousel` 部分）。Props: `carousel`, `cardImage`。包含发言者消息展示。

**JudgeStrip.vue：** 提取法官消息条（`.judge-strip` 部分）。Props: `messages`, `judgeStripRef`。

**ChatLog.vue：** 提取聊天日志（`.chat-log` 部分）。Props: `logs`, `expanded`, `chatListRef`。Emit: `toggle-expand`。

**RoleStats.vue：** 提取角色统计条（`.role-stats` 部分）。Props: `stats`。

**ActionPanel.vue：** 提取投票/行动面板（`.action-panel` 和 `.speech-bar` 部分）。Props: `pendingActionType`, `witchChoice`, `actionInstruction`, `speech`, `speechCountdownText`, `voteTarget`, `canVotePlayers`, `isWatch`, `isReplayMode`, `roleName` 等。Emit: `submit-speech`, `submit-vote`, `arm-burst`。

- [ ] **Step 2: 创建 MatchPage.vue 组装子组件**

```vue
<script setup>
import CouncilScene from '../components/CouncilScene.vue'
import PlayerCarousel from '../components/PlayerCarousel.vue'
import JudgeStrip from '../components/JudgeStrip.vue'
import ChatLog from '../components/ChatLog.vue'
import RoleStats from '../components/RoleStats.vue'
import ActionPanel from '../components/ActionPanel.vue'

const props = defineProps({
  game: Object,
  isNight: Boolean,
  isWatch: Boolean,
  judgeBoardStarted: Boolean,
  judgeBoardStarting: Boolean,
  roleAssignmentComplete: Boolean,
  roleAssignmentCompleteNotice: Boolean,
  // ... 所有 match 视图需要的 props
})
const emit = defineEmits([...])
</script>

<template>
  <div class="match-layout">
    <CouncilScene :game-scene-ref="props.gameSceneRef" />
    <PlayerCarousel ... />
    <JudgeStrip ... />
    <ChatLog ... />
    <RoleStats ... />
    <ActionPanel ... />
  </div>
</template>
```

- [ ] **Step 3: 在 App.vue 中引用 MatchPage**

- [ ] **Step 4: 验证**

```bash
npm run dev
```

重点测试：观战模式对局流程、3D 场景、发言/投票交互。

- [ ] **Step 5: Commit**

```bash
git add ui/frontend/src/pages/MatchPage.vue ui/frontend/src/components/CouncilScene.vue \
       ui/frontend/src/components/PlayerCarousel.vue ui/frontend/src/components/JudgeStrip.vue \
       ui/frontend/src/components/ChatLog.vue ui/frontend/src/components/RoleStats.vue \
       ui/frontend/src/components/ActionPanel.vue ui/frontend/src/App.vue
git commit -m "refactor: extract MatchPage and sub-components"
```

---

### Task 10: 创建 LogsPage.vue + 子组件

**Files:**
- Create: `ui/frontend/src/pages/LogsPage.vue`
- Create: `ui/frontend/src/components/HistoryGameList.vue`
- Create: `ui/frontend/src/components/MultiAssess.vue`
- Create: `ui/frontend/src/components/SeatLedger.vue`
- Create: `ui/frontend/src/components/PhaseTabs.vue`
- Create: `ui/frontend/src/components/NightSection.vue`
- Create: `ui/frontend/src/components/SpeechSection.vue`
- Create: `ui/frontend/src/components/VoteSection.vue`
- Create: `ui/frontend/src/components/NightActionCard.vue`
- Create: `ui/frontend/src/components/DecisionDetail.vue`
- Create: `ui/frontend/src/components/ReplayControls.vue`
- Modify: `ui/frontend/src/App.vue`

- [ ] **Step 1: 创建 HistoryGameList.vue**

提取 `.history-games-panel` 侧边栏（原 main.js 第 1701-1720 行）。Props: `games`, `selectedGameId`, `loading`。Emit: `select-game`, `replay-game`。

- [ ] **Step 2: 创建 MultiAssess.vue**

提取 `.multi-assess-module`（原 main.js 第 1725-1746 行）。Props: `scores`, `dimension`, `roleIconImage`。Emit: `update:dimension`。

- [ ] **Step 3: 创建 SeatLedger.vue**

提取 `.history-seat-ledger`（原 main.js 第 1751-1758 行）。Props: `players`, `aliveMap`, `sheriffId`, `selectedPage`, `roleIconImage`。

- [ ] **Step 4: 创建 PhaseTabs.vue**

提取 `.history-phase-tabs`（原 main.js 第 1760-1769 行）。Props: `pages`, `selectedPageKey`, `pageTitle`。Emit: `select-page`。

- [ ] **Step 5: 创建 DecisionDetail.vue**

提取决策详情多 tab 面板（原 main.js 中重复出现 4 次的 `.nmc-tabs` + `.nmc-detail-body` 区块）。这是最重要的复用——原代码中相同的 detail panel 复制了 4 次（night、speech/sheriff、sheriff_result、vote），现在只需一个组件。

Props: `decision`, `detailTab`。Emit: `update:detailTab`。

```vue
<script setup>
const props = defineProps({
  decision: Object,
  detailTab: { type: String, default: 'summary' }
})
const emit = defineEmits(['update:detail-tab'])

const tabs = [
  { key: 'summary', label: '理由' },
  { key: 'candidates', label: '候选' },
  { key: 'process', label: '决策' },
  { key: 'memory', label: '记忆' },
  { key: 'skills', label: 'Skills' },
  { key: 'prompt', label: 'Prompt' },
  { key: 'raw', label: 'Raw Output' }
]
</script>

<template>
  <div class="night-right" v-if="decision">
    <div class="nmc-tabs">
      <button v-for="tab in tabs" :key="tab.key"
        :class="['nmc-tab', { on: detailTab === tab.key }]"
        @click="emit('update:detail-tab', tab.key)">
        {{ tab.label }}
      </button>
    </div>
    <div class="nmc-detail-body">
      <!-- 各 tab 内容（原样搬移） -->
    </div>
  </div>
  <div v-else class="night-right night-right-empty">点击左侧卡片查看详情</div>
</template>
```

- [ ] **Step 6: 创建 NightActionCard.vue**

提取单个夜间行动小卡片（`.night-mini-card`，原 main.js 第 1780-1794 行）。Props: `action`, `selected`, `nightActionDetail`。Emit: `select`。

- [ ] **Step 7: 创建 NightSection.vue**

组装夜间阶段内容（原 main.js 第 1774-1857 行）：NightActionCard 列表 + DecisionDetail。Props: `page`, `nightActions`, `nightResult`, `selectedDecision`, `detailTab`, `nightActionDetail`。

- [ ] **Step 8: 创建 SpeechSection.vue**

提取发言阶段内容（原 main.js 第 1859-1935 行）：发言决策卡片列表 + DecisionDetail。结构与 NightSection 非常相似。

- [ ] **Step 9: 创建 VoteSection.vue**

提取投票阶段内容（原 main.js 第 2022-2104 行）：投票统计图 + 投票卡片 + DecisionDetail。Props: `currentVoteTally`, `voteDecisions`, `selectedDecision`, `detailTab`。

- [ ] **Step 10: 创建 ReplayControls.vue**

提取复盘控制栏（底部"返回日志"/"退出复盘"按钮，原 template 末尾的 replay 控制部分）。Props: `isReplayMode`。Emit: `return-to-history`, `exit-replay`。

- [ ] **Step 11: 创建 LogsPage.vue 组装所有子组件**

```vue
<script setup>
import { ref } from 'vue'
import HistoryGameList from '../components/HistoryGameList.vue'
import MultiAssess from '../components/MultiAssess.vue'
import SeatLedger from '../components/SeatLedger.vue'
import PhaseTabs from '../components/PhaseTabs.vue'
import NightSection from '../components/NightSection.vue'
import SpeechSection from '../components/SpeechSection.vue'
import VoteSection from '../components/VoteSection.vue'
import ReplayControls from '../components/ReplayControls.vue'

// 局部 UI 状态（不从 props 传）
const assessDimension = ref('speech')
const selectedDecision = ref(null)
const detailTab = ref('summary')

const props = defineProps({
  returnToMatchAvailable: Boolean,
  gameHistory: Array,
  selectedHistoryGameId: [String, Number],
  selectedHistoryGame: Object,
  historyLoading: Boolean,
  historyPages: Array,
  selectedHistoryPage: Object,
  historyLogs: Array,
  pageNightActions: Array,
  pageSpeechDecisions: Array,
  pageVoteResults: Array,
  pageLastWords: Array,
  nightResult: String,
  sheriffResult: Object,
  isReplayMode: Boolean,
  // ... 其他需要的 props
  roleIconImage: Function,
  historyPageTitle: Function,
  historyPhaseName: Function,
  historyLogSpeaker: Function,
  historyNormalizeText: Function,
  formatJson: Function,
  nightActionDetail: Function,
  playerAliveAtPage: Object,
  archiveByGameId: Object,
  reviewByGameId: Object,
})
const emit = defineEmits([...])
</script>

<template>
  <section class="battle-log-page" aria-label="对战日志">
    <button v-if="returnToMatchAvailable" class="return-match-button" @click="emit('back-to-match')">
      <span>返回对局</span><i aria-hidden="true">▶</i>
    </button>
    <section class="battle-log-shell parchment-logbook">
      <HistoryGameList ... />
      <main class="history-detail-panel">
        <MultiAssess ... />
        <SeatLedger ... />
        <PhaseTabs ... />
        <section v-if="selectedHistoryGame && selectedHistoryPage" class="history-page-detail">
          <NightSection v-if="selectedHistoryPage.phase === 'night'" ... />
          <SpeechSection v-if="['speech', 'sheriff'].includes(selectedHistoryPage.phase)" ... />
          <VoteSection v-if="['vote', 'sheriff_vote'].includes(selectedHistoryPage.phase)" ... />
          <!-- last words、raw logs、archive/review 保留内联 -->
        </section>
      </main>
    </section>
    <ReplayControls v-if="isReplayMode" ... />
  </section>
</template>
```

- [ ] **Step 12: 在 App.vue 中引用 LogsPage**

- [ ] **Step 13: 验证**

```bash
npm run dev
```

重点测试：日志页面加载、历史对局列表、各阶段内容切换、夜间行动卡片点击、决策详情 tab、复盘流程。

- [ ] **Step 14: Commit**

```bash
git add ui/frontend/src/pages/LogsPage.vue ui/frontend/src/components/HistoryGameList.vue \
       ui/frontend/src/components/MultiAssess.vue ui/frontend/src/components/SeatLedger.vue \
       ui/frontend/src/components/PhaseTabs.vue ui/frontend/src/components/NightSection.vue \
       ui/frontend/src/components/SpeechSection.vue ui/frontend/src/components/VoteSection.vue \
       ui/frontend/src/components/NightActionCard.vue ui/frontend/src/components/DecisionDetail.vue \
       ui/frontend/src/components/ReplayControls.vue ui/frontend/src/App.vue
git commit -m "refactor: extract LogsPage and all sub-components"
```

---

### Task 11: 创建 EvolutionPage.vue

**Files:**
- Create: `ui/frontend/src/pages/EvolutionPage.vue`
- Modify: `ui/frontend/src/App.vue`

- [ ] **Step 1: 创建 EvolutionPage.vue**

从 App.vue template 中提取 `v-if="inEvolution"` 的自进化部分（原 main.js 第 2161 行起）。

Props: `returnToMatchAvailable`, `evolutionSelectedRoles`, `evolutionRoles`, `leaderboardData`。
Emit: `back-to-match`, `toggle-role`。

```vue
<script setup>
const props = defineProps({
  returnToMatchAvailable: Boolean,
  evolutionSelectedRoles: Array,
  evolutionRoles: Array,
  leaderboardData: Array,
})
const emit = defineEmits(['back-to-match', 'toggle-role'])
</script>

<template>
  <section class="evolution-page" aria-label="自进化">
    <button v-if="returnToMatchAvailable" class="return-match-button" @click="emit('back-to-match')">
      <span>返回对局</span><i aria-hidden="true">▶</i>
    </button>
    <section class="evolution-shell parchment-logbook">
      <!-- 原样搬移 evolution 模板内容 -->
    </section>
  </section>
</template>
```

- [ ] **Step 2: 在 App.vue 中引用**

- [ ] **Step 3: 验证**

```bash
npm run dev
```

验证自进化页面正常渲染、角色选择切换正常。

- [ ] **Step 4: Commit**

```bash
git add ui/frontend/src/pages/EvolutionPage.vue ui/frontend/src/App.vue
git commit -m "refactor: extract EvolutionPage component"
```

---

## Phase 4：清理 App.vue + CSS 迁移

### Task 12: 清理 App.vue，确认只剩路由逻辑

**Files:**
- Modify: `ui/frontend/src/App.vue`

- [ ] **Step 1: 检查 App.vue 剩余内容**

此时 App.vue 应该只剩：
- import composables 和 pages
- composable 调用
- `<template>` 中的路由 v-if/v-else-if 结构
- watchers 和 onMounted/onBeforeUnmount（可能还需要搬到 composables 中）

确认 App.vue < 300 行。如果仍有内联的模板片段（如 judge board 启动面板），决定是保留还是进一步拆分。

- [ ] **Step 2: 把剩余的 watchers 和 lifecycle 搬到合适的 composable**

如有需要，在 `useGameState` 或 `useGameActions` 中补充 `onMounted` 调用（如 `refreshHealth()`、`refreshHistoryList()`）。

- [ ] **Step 3: 验证**

```bash
npm run dev
```

完整测试所有功能路径。

- [ ] **Step 4: Commit**

```bash
git add ui/frontend/src/App.vue
git commit -m "refactor: clean up App.vue to routing-only"
```

---

### Task 13: CSS 迁移 — 标注和分离

**Files:**
- Modify: `ui/frontend/src/style.css`
- Modify: 各 `.vue` 文件的 `<style scoped>`

- [ ] **Step 1: 审计 style.css 中的选择器**

将 `style.css` 中的选择器分为三类：

1. **全局保留**（不动）：CSS 变量、reset、`.lycan-app` 基础样式、`.lycan-app.night`/`.day`/`.logbook`/`.evolution` 及其子选择器
2. **迁移至 scoped**：纯组件内部选择器（如 `.speaker-carousel`, `.chat-log`, `.judge-strip` 等）
3. **需要 `:deep()` 处理**：同时依赖父状态类和组件类的选择器

- [ ] **Step 2: 逐步迁移**

对每个已抽取的组件，把对应的选择器从 `style.css` 剪切到该 `.vue` 文件的 `<style scoped>`。

**注意：** 依赖 `.lycan-app.night` 等根状态类的选择器**必须保留在全局 style.css**。只有不依赖父级状态类的选择器才能迁移。

- [ ] **Step 3: 每迁移一个组件后验证**

```bash
npm run dev
```

确认该组件的样式没有丢失。

- [ ] **Step 4: Commit**

```bash
git add ui/frontend/src/style.css ui/frontend/src/components/*.vue ui/frontend/src/pages/*.vue
git commit -m "refactor: migrate component styles to scoped CSS"
```

---

### Task 14: 最终验证和清理

**Files:**
- Modify: `ui/frontend/src/main.js`（确认只有 ~10 行）
- Delete: 无（保留旧 main.js 中所有代码直到确认无误后再考虑删除备份）

- [ ] **Step 1: 检查 main.js 是否精简**

确认 `ui/frontend/src/main.js` 只有：

```js
import { createApp } from 'vue'
import App from './App.vue'
import './style.css'

createApp(App).mount('#app')
```

- [ ] **Step 2: 检查各文件行数**

```bash
wc -l ui/frontend/src/App.vue \
      ui/frontend/src/composables/*.js \
      ui/frontend/src/pages/*.vue \
      ui/frontend/src/components/*.vue
```

确认每个文件 < 300 行。如果超过，进一步拆分。

- [ ] **Step 3: 完整功能测试**

```bash
npm run dev
```

逐项验证：
- [ ] 大厅页面：模式选择、开始对局
- [ ] 对局页面：3D 场景、发言、投票、女巫/白狼王技能、法官开局
- [ ] 日志页面：历史对局列表、各阶段内容、夜间行动卡片、决策详情、多维测评
- [ ] 自进化页面：角色选择、排行榜
- [ ] 复盘模式：进入复盘、退出复盘、返回对局
- [ ] 观战模式：自动推进、EventSource
- [ ] 控制台无报错

- [ ] **Step 4: Commit**

```bash
git add -A ui/frontend/src/
git commit -m "refactor: complete frontend SFC migration — all views working"
```
