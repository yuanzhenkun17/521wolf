<script setup>
import { computed, defineAsyncComponent, isRef } from 'vue'
import TopNav from './components/TopNav.vue'
import { useGameState } from './composables/useGameState.js'
import { useMatchUtils } from './composables/useMatchUtils.js'
import { useGameActions } from './composables/useGameActions.js'
import { useGameHistory } from './composables/useGameHistory.js'

const LogsPage = defineAsyncComponent(() => import('./pages/LogsPage.vue'))
const EvolutionPage = defineAsyncComponent(() => import('./pages/EvolutionPage.vue'))
const LobbyPage = defineAsyncComponent(() => import('./pages/LobbyPage.vue'))
const MatchPage = defineAsyncComponent(() => import('./pages/MatchPage.vue'))

const state = useGameState()
const utils = useMatchUtils(state)
state.setGameStateUtils?.(utils)
const actions = useGameActions(state)
const history = useGameHistory(state, { apiFetch: actions.apiFetch, actionApi: actions })
actions.setHistoryApi?.(history)
history.setActionApi?.(actions)
const runtime = { ...state, ...utils, ...actions, ...history }

function registerCouncilScene(sceneApi) {
  actions.setSceneApi?.(sceneApi)
  history.setSceneApi?.(sceneApi)
}

function bindValue(value) {
  return isRef(value) ? value.value : value
}

const pageBindings = computed(() =>
  Object.fromEntries(Object.entries(runtime).map(([key, value]) => [key, bindValue(value)]))
)

const {
  actionTarget,
  actionChoice,
  assessDimension,
  backToMatch,
  burstArmed,
  chatLogExpanded,
  detailTab,
  error,
  exitReplayMode,
  goLobby,
  inEvolution,
  inLobby,
  inLogs,
  inMatch,
  isNight,
  openEvolutionPage,
  openLogPage,
  replayHistoryGame,
  resetGame,
  returnToHistoryFromReplay,
  selectHistoryGame,
  selectedDecision,
  selectedHistoryPageKey,
  speech,
  startFromJudgeBoard,
  startMode,
  stepGame,
  submitAction,
  submitSpeech,
  toggleWatch,
  witchChoice
} = runtime
</script>

<template>
<main :class="['lycan-app', { night: isNight, day: !isNight, lobbying: inLobby && !inLogs, logbook: inLogs, evolution: inEvolution }]">
      <div class="atmosphere"></div>
      <div class="noise"></div>

      <TopNav
        @go-lobby="goLobby"
        @open-logs="openLogPage()"
        @open-evolution="openEvolutionPage"
      />

      <LogsPage
        v-if="inLogs"
        v-bind="pageBindings"
        v-model:selected-history-page-key="selectedHistoryPageKey"
        v-model:assess-dimension="assessDimension"
        v-model:selected-decision="selectedDecision"
        v-model:detail-tab="detailTab"
        @back-to-match="backToMatch"
        @select-history-game="selectHistoryGame"
        @replay-game="replayHistoryGame"
        @return-to-history="returnToHistoryFromReplay"
        @exit-replay="exitReplayMode"
      />
      <EvolutionPage
        v-if="inEvolution"
        v-bind="pageBindings"
        @back-to-match="backToMatch"
      />
      <LobbyPage
        v-if="inLobby"
        v-bind="pageBindings"
        @start-mode="startMode"
      />

      <MatchPage
        v-if="inMatch"
        v-bind="pageBindings"
        v-model:speech="speech"
        v-model:witch-choice="witchChoice"
        v-model:action-choice="actionChoice"
        v-model:burst-armed="burstArmed"
        v-model:action-target="actionTarget"
        v-model:chat-log-expanded="chatLogExpanded"
        @return-to-history="returnToHistoryFromReplay"
        @exit-replay="exitReplayMode"
        @toggle-watch="toggleWatch"
        @reset-game="resetGame"
        @step-game="stepGame"
        @council-ready="registerCouncilScene"
        @start-from-judge-board="startFromJudgeBoard"
        @submit-speech="submitSpeech()"
        @submit-action="submitAction($event?.action, $event?.targetId, $event?.choice)"
      />
      <div v-if="error" class="toast">{{ error }}</div>
    </main>
</template>
