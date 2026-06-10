<script setup lang="ts">
import { computed, defineAsyncComponent, watchEffect } from 'vue'
import { useRoute } from 'vue-router'
import TopNav from './components/TopNav.vue'
import { useGameState } from './composables/useGameState.ts'
import { useMatchUtils } from './composables/useMatchUtils.ts'
import { useGameActions } from './composables/useGameActions.ts'
import { useGameAudio } from './composables/useGameAudio.ts'
import { useGameHistory } from './composables/useGameHistory.ts'
import { useAppRuntimeProps } from './composables/appRuntimeProps'
import { appViewFromRouteSource } from './router/appViews'
import {
  createIncrementalRuntimeHydrator,
  useGameStore,
  useHistoryStore,
  useReplayStore,
  useSessionStore,
  useUiStore
} from './stores'

type RuntimeRecord = Record<string, any>

const LogsPage = defineAsyncComponent(() => import('./pages/LogsPage.vue'))
const BenchmarkPage = defineAsyncComponent(() => import('./pages/BenchmarkPage.vue'))
const EvolutionPage = defineAsyncComponent(() => import('./pages/EvolutionPage.vue'))
const TasksPage = defineAsyncComponent(() => import('./pages/TasksPage.vue'))
const SettingsPage = defineAsyncComponent(() => import('./pages/SettingsPage.vue'))
const LobbyPage = defineAsyncComponent(() => import('./pages/LobbyPage.vue'))
const MatchPage = defineAsyncComponent(() => import('./pages/MatchPage.vue'))

const state = useGameState()
const route = useRoute()
const utils = useMatchUtils(state)
state.setGameStateUtils?.(utils)
const actions = useGameActions(state)
const history = useGameHistory(state, { apiFetch: actions.apiFetch, actionApi: actions, route })
actions.setHistoryApi?.(history)
history.setActionApi?.(actions)
const audio = useGameAudio({ ...state, apiBase: actions.apiBase })
const runtime = { ...state, ...utils, ...actions, ...history, ...audio } as RuntimeRecord
const sessionStore = useSessionStore()
const gameStore = useGameStore()
const historyStore = useHistoryStore()
const replayStore = useReplayStore()
const uiStore = useUiStore()
historyStore.bindRuntimeActions(history)
const runtimeHydrator = createIncrementalRuntimeHydrator({
  session: sessionStore,
  game: gameStore,
  history: historyStore,
  replay: replayStore,
  ui: uiStore
})

function registerCouncilScene(sceneApi: RuntimeRecord) {
  actions.setSceneApi?.(sceneApi)
  history.setSceneApi?.(sceneApi)
}

watchEffect(() => {
  runtimeHydrator.hydrate(runtime)
})

const {
  logsProps,
  matchProps
} = useAppRuntimeProps(runtime)
const routeAppView = computed(() => appViewFromRouteSource(route))
const activeAppView = computed(() => routeAppView.value || 'lobby')
const inLobby = computed(() => activeAppView.value === 'lobby')
const inMatch = computed(() => activeAppView.value === 'match')
const inLogs = computed(() => activeAppView.value === 'logs')
const inBenchmark = computed(() => activeAppView.value === 'benchmark')
const inEvolution = computed(() => activeAppView.value === 'evolution')
const inTasks = computed(() => activeAppView.value === 'tasks')
const inSettings = computed(() => activeAppView.value === 'settings')
const isNight = computed(() => gameStore.isNight)
const toastError = computed(() => uiStore.errorMessage)
const showMatchBoot = computed(() => {
  return activeAppView.value === 'match'
    && !replayStore.isReplayMode
    && (
      !gameStore.liveGame
      || (
        !gameStore.roleAssignmentComplete
        && (gameStore.judgeBoardStarted || gameStore.judgeBoardStarting)
      )
    )
})
const matchBootStatus = computed(() => {
  if (!gameStore.liveGame) return '创建房间'
  if (!gameStore.roleAssignmentComplete) return '分配身份'
  return '进入议事厅'
})

const {
  assessDimension,
  backToMatch,
  detailTab,
  exitGame,
  exitReplayMode,
  goLobby,
  openBenchmarkPage,
  openEvolutionPage,
  openTasksPage,
  openSettingsPage,
  openLogPage,
  pauseReplay,
  playReplay,
  replayHistoryGame,
  resetGame,
  returnToHistoryFromReplay,
  selectHistoryGame,
  selectedDecision,
  selectedHistoryPageKey,
  historyWorkspaceTab,
  seekReplay,
  startFromJudgeBoard,
  startMode,
  setReplaySpeed,
  stepReplay,
  stepGame,
  submitAction,
  submitSpeech,
  toggleWatch,
  toggleAudio,
  toggleTts
} = runtime
</script>

<template>
<main :class="['lycan-app', { night: isNight, day: !isNight, lobbying: inLobby && !inLogs && !inBenchmark && !inEvolution && !inTasks && !inSettings, logbook: inLogs, benchmark: inBenchmark, evolution: inEvolution, tasks: inTasks, settings: inSettings }]">
      <div class="atmosphere"></div>
      <div class="noise"></div>

      <TopNav
        :variant="inMatch ? 'match' : (inLobby ? 'lobby' : 'section')"
        :class="{ 'night-mode': isNight }"
        @go-lobby="goLobby"
        @open-logs="openLogPage()"
        @open-benchmark="openBenchmarkPage"
        @open-evolution="openEvolutionPage"
        @open-tasks="openTasksPage"
        @open-settings="openSettingsPage"
        @back-to-match="backToMatch"
        @toggle-audio="toggleAudio"
        @toggle-tts="toggleTts"
        @exit-game="exitGame"
      />

      <LogsPage
        v-if="inLogs"
        v-bind="logsProps"
        v-model:selected-history-page-key="selectedHistoryPageKey"
        v-model:history-workspace-tab="historyWorkspaceTab"
        v-model:assess-dimension="assessDimension"
        v-model:selected-decision="selectedDecision"
        v-model:detail-tab="detailTab"
        @back-to-match="backToMatch"
        @select-history-game="selectHistoryGame"
        @replay-game="replayHistoryGame"
        @return-to-history="returnToHistoryFromReplay"
        @exit-replay="exitReplayMode"
        @play-replay="playReplay"
        @pause-replay="pauseReplay"
        @step-replay="stepReplay"
        @seek-replay="seekReplay"
        @set-replay-speed="setReplaySpeed"
      />
      <BenchmarkPage
        v-if="inBenchmark"
        @back-to-match="backToMatch"
      />
      <EvolutionPage
        v-if="inEvolution"
        @back-to-match="backToMatch"
        @open-sample-log="openLogPage($event)"
        @replay-sample-game="replayHistoryGame($event)"
      />
      <TasksPage
        v-if="inTasks"
      />
      <SettingsPage
        v-if="inSettings"
      />
      <LobbyPage
        v-if="inLobby"
        :external-status="state.externalStatus.value"
        :player-count="state.playerCount.value"
        :api-fetch="actions.apiFetch"
        @start-mode="startMode"
      />

      <MatchPage
        v-if="inMatch"
        v-bind="matchProps"
        @return-to-history="returnToHistoryFromReplay"
        @exit-replay="exitReplayMode"
        @play-replay="playReplay"
        @pause-replay="pauseReplay"
        @step-replay="stepReplay"
        @seek-replay="seekReplay"
        @set-replay-speed="setReplaySpeed"
        @toggle-watch="toggleWatch"
        @reset-game="resetGame"
        @exit-game="exitGame"
        @step-game="stepGame"
        @council-ready="registerCouncilScene"
        @start-from-judge-board="startFromJudgeBoard"
        @submit-speech="submitSpeech(gameStore.speech)"
        @submit-action="submitAction($event?.action, $event?.targetId, $event?.choice)"
      />
      <section v-if="showMatchBoot" class="match-boot-overlay" aria-live="polite">
        <div class="match-boot-ring" aria-hidden="true">
          <span></span>
          <i></i>
        </div>
        <div class="match-boot-copy">
          <b>夜议会</b>
          <strong>议事厅入场</strong>
          <em>{{ matchBootStatus }}</em>
        </div>
        <div class="match-boot-progress" aria-hidden="true"><span></span></div>
      </section>
      <div v-if="toastError" class="toast">{{ toastError }}</div>
    </main>
</template>

<style scoped>
.match-boot-overlay {
  position: fixed;
  inset: 0;
  z-index: 90;
  display: grid;
  place-items: center;
  align-content: center;
  gap: 18px;
  background:
    radial-gradient(circle at 50% 42%, rgba(242, 202, 80, 0.14), transparent 26%),
    radial-gradient(circle at 50% 56%, rgba(115, 26, 22, 0.24), transparent 34%),
    linear-gradient(180deg, rgba(2, 1, 2, 0.96), rgba(6, 4, 3, 0.9));
  color: #fff0c6;
  pointer-events: none;
}

.match-boot-overlay::before,
.match-boot-overlay::after {
  content: "";
  position: absolute;
  inset: 0;
  pointer-events: none;
}

.match-boot-overlay::before {
  opacity: 0.22;
  background:
    linear-gradient(90deg, transparent 0 47%, rgba(242, 202, 80, 0.34) 49% 51%, transparent 53%),
    repeating-linear-gradient(90deg, rgba(255, 232, 176, 0.1) 0 1px, transparent 1px 58px);
  mask-image: radial-gradient(ellipse at center, black 0 44%, transparent 72%);
}

.match-boot-overlay::after {
  background:
    radial-gradient(circle at 50% 50%, transparent 0 28%, rgba(0, 0, 0, 0.42) 62%, rgba(0, 0, 0, 0.84) 100%),
    linear-gradient(0deg, rgba(0, 0, 0, 0.28), transparent 28%, transparent 70%, rgba(0, 0, 0, 0.32));
}

.match-boot-ring,
.match-boot-copy,
.match-boot-progress {
  position: relative;
  z-index: 1;
}

.match-boot-ring {
  display: grid;
  width: 116px;
  height: 116px;
  place-items: center;
  border: 1px solid rgba(242, 202, 80, 0.28);
  border-radius: 50%;
  background: radial-gradient(circle, rgba(242, 202, 80, 0.2), rgba(9, 6, 4, 0.52) 58%, transparent 62%);
  box-shadow: 0 0 52px rgba(242, 202, 80, 0.18);
}

.match-boot-ring span,
.match-boot-ring i {
  position: absolute;
  border-radius: 50%;
}

.match-boot-ring span {
  inset: 12px;
  border: 2px solid transparent;
  border-top-color: #f2ca50;
  border-right-color: rgba(242, 202, 80, 0.34);
  animation: matchBootSpin 1600ms linear infinite;
}

.match-boot-ring i {
  width: 38px;
  height: 38px;
  background:
    radial-gradient(circle at 58% 44%, #fff7d8 0 6px, transparent 7px),
    radial-gradient(circle, #f2ca50 0 8px, rgba(242, 202, 80, 0.12) 9px 100%);
  box-shadow: 0 0 32px rgba(242, 202, 80, 0.54);
}

.match-boot-copy {
  display: grid;
  gap: 5px;
  text-align: center;
}

.match-boot-copy b {
  color: rgba(255, 235, 181, 0.58);
  font-size: 12px;
  font-weight: 950;
  letter-spacing: 0;
  text-transform: uppercase;
}

.match-boot-copy strong {
  color: #fff0c6;
  font-size: 30px;
  font-weight: 1000;
  line-height: 1.05;
  text-shadow: 0 0 24px rgba(242, 202, 80, 0.28);
}

.match-boot-copy em {
  color: rgba(255, 238, 196, 0.72);
  font-size: 13px;
  font-style: normal;
  font-weight: 900;
}

.match-boot-progress {
  width: 240px;
  height: 4px;
  overflow: hidden;
  border-radius: 999px;
  background: rgba(255, 238, 196, 0.14);
}

.match-boot-progress span {
  display: block;
  width: 42%;
  height: 100%;
  border-radius: inherit;
  background: linear-gradient(90deg, transparent, #f2ca50, transparent);
  animation: matchBootLoad 1300ms ease-in-out infinite;
}

@keyframes matchBootSpin {
  to { transform: rotate(360deg); }
}

@keyframes matchBootLoad {
  from { transform: translateX(-100%); }
  to { transform: translateX(240%); }
}
</style>
