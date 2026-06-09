<script setup>
import { computed, defineAsyncComponent, isRef } from 'vue'
import TopNav from './components/TopNav.vue'
import { useGameState } from './composables/useGameState.js'
import { useMatchUtils } from './composables/useMatchUtils.js'
import { useGameActions } from './composables/useGameActions.js'
import { useGameAudio } from './composables/useGameAudio.js'
import { useGameHistory } from './composables/useGameHistory.js'
import { isReturnableGame } from './composables/gameSession.js'

const LogsPage = defineAsyncComponent(() => import('./pages/LogsPage.vue'))
const BenchmarkPage = defineAsyncComponent(() => import('./pages/BenchmarkPage.vue'))
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
const audio = useGameAudio({ ...state, apiBase: actions.apiBase })
const runtime = { ...state, ...utils, ...actions, ...history, ...audio }

function registerCouncilScene(sceneApi) {
  actions.setSceneApi?.(sceneApi)
  history.setSceneApi?.(sceneApi)
}

function bindValue(value) {
  return isRef(value) ? value.value : value
}

function readRuntime(key) {
  return bindValue(runtime[key])
}

function pickRuntime(keys) {
  return Object.fromEntries(keys.map((key) => [key, readRuntime(key)]))
}

const logsPropKeys = [
  'returnToMatchAvailable',
  'gameHistory',
  'selectedHistoryGameId',
  'selectedHistoryGame',
  'historyLoading',
  'historyPagination',
  'historyLoadingMore',
  'historySourceFilter',
  'historyStatusFilter',
  'historyCounts',
  'historyFacets',
  'historyNotice',
  'historyHasMore',
  'historyCurrentPage',
  'historyTotalPages',
  'historyPages',
  'selectedHistoryPageKey',
  'historyWorkspaceTab',
  'selectedHistoryPage',
  'phaseLoadingByKey',
  'historyLogs',
  'pageNightActions',
  'pageSpeechDecisions',
  'sheriffVotes',
  'voteDecisions',
  'currentVoteTally',
  'sheriffVoteTally',
  'pageLastWords',
  'nightResult',
  'sheriffResult',
  'isReplayMode',
  'replayCursor',
  'replayPlaying',
  'replaySpeed',
  'replayTotal',
  'replayEventLabel',
  'assessDimension',
  'playerAssessmentScores',
  'activeAssessScores',
  'selectedDecision',
  'detailTab',
  'roleIconImage',
  'historyPageTitle',
  'historyPhaseName',
  'historyLogSpeaker',
  'historyNormalizeText',
  'nightActionDetail',
  'playerAliveAtPage',
  'archiveByGameId',
  'reviewByGameId',
  'flowDataByGameId',
  'flowLoadingByGameId',
  'archiveLoading',
  'reviewLoading',
  'loadMoreHistory',
  'loadMoreHistoryPhaseDetail',
  'goHistoryPage',
  'setHistorySourceFilter',
  'setHistoryStatusFilter',
  'deleteHistoryGame',
  'loadArchive',
  'loadReview',
  'loadFlowData',
  'formatJson'
]

const matchPropKeys = [
  'game',
  'loading',
  'matchNotice',
  'backendMode',
  'isNight',
  'isWatch',
  'isReplayMode',
  'replayCursor',
  'replayPlaying',
  'replaySpeed',
  'replayTotal',
  'replayEventLabel',
  'watchRunning',
  'skipIntroGameId',
  'roleAssignmentComplete',
  'judgeBoardStarted',
  'judgeBoardStarting',
  'promptText',
  'judgeStripMessage',
  'playerIdentityList',
  'chatLogExpanded',
  'chatLogs',
  'matchRecordLogs',
  'groupedJudgeLogs',
  'displayPhase',
  'livingPlayers',
  'roleStats',
  'speakerCarousel',
  'speakerMessage',
  'humanPlayer',
  'roleName',
  'skillState',
  'isHumanWitch',
  'isHumanWhiteWolf',
  'canUseWitchAntidote',
  'canUseWitchPoison',
  'canWhiteWolfBurst',
  'pendingActionType',
  'pendingChoiceOptions',
  'actionInstruction',
  'speechCountdownText',
  'canVotePlayers',
  'actionCandidates',
  'whiteWolfTargets',
  'needsTarget',
  'speech',
  'witchChoice',
  'actionChoice',
  'burstArmed',
  'actionTarget',
  'sceneVoteTally',
  'sceneEffects',
  'playerLabel',
  'roleIconImage',
  'logSpeaker',
  'logMessage',
  'historyPhaseName',
  'chooseScenePlayer'
]

const logsProps = computed(() => pickRuntime(logsPropKeys))
const benchmarkProps = computed(() => pickRuntime(['returnToMatchAvailable']))
const evolutionProps = computed(() => pickRuntime(['returnToMatchAvailable']))
const lobbyProps = computed(() => pickRuntime(['backendMode', 'externalStatus', 'loading', 'playerCount', 'apiFetch']))
const matchProps = computed(() => pickRuntime(matchPropKeys))
const activeSession = computed(() => readRuntime('activeSession'))
const audioEnabled = computed(() => readRuntime('audioEnabled'))
const ttsEnabled = computed(() => readRuntime('ttsEnabled'))
const ttsAvailable = computed(() => readRuntime('ttsAvailable'))
const topNavActiveView = computed(() => readRuntime('isReplayMode') ? 'logs' : readRuntime('currentView'))
const showActiveGamePill = computed(() => {
  if (readRuntime('isReplayMode')) return false
  if (readRuntime('currentView') === 'match') return false
  return isReturnableGame(readRuntime('liveGame'))
})
const showMatchBoot = computed(() => {
  return readRuntime('currentView') === 'match'
    && !readRuntime('isReplayMode')
    && (
      !readRuntime('game')
      || (
        !readRuntime('roleAssignmentComplete')
        && (readRuntime('judgeBoardStarted') || readRuntime('judgeBoardStarting'))
      )
    )
})
const matchBootStatus = computed(() => {
  if (!readRuntime('game')) return '创建房间'
  if (!readRuntime('roleAssignmentComplete')) return '分配身份'
  return '进入议事厅'
})
const showTopbarExitGame = computed(() => {
  return readRuntime('currentView') === 'match' && !readRuntime('isReplayMode') && Boolean(readRuntime('game'))
})
const topbarExitDisabled = computed(() => false)

const {
  actionTarget,
  actionChoice,
  assessDimension,
  backToMatch,
  burstArmed,
  chatLogExpanded,
  detailTab,
  error,
  exitGame,
  exitReplayMode,
  goLobby,
  inBenchmark,
  inEvolution,
  inLobby,
  inLogs,
  inMatch,
  isNight,
  openBenchmarkPage,
  openEvolutionPage,
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
  speech,
  startFromJudgeBoard,
  startMode,
  setReplaySpeed,
  stepReplay,
  stepGame,
  submitAction,
  submitSpeech,
  toggleWatch,
  toggleAudio,
  toggleTts,
  witchChoice
} = runtime
</script>

<template>
<main :class="['lycan-app', { night: isNight, day: !isNight, lobbying: inLobby && !inLogs && !inBenchmark, logbook: inLogs, benchmark: inBenchmark, evolution: inEvolution }]">
      <div class="atmosphere"></div>
      <div class="noise"></div>

      <TopNav
        :variant="inMatch ? 'match' : (inLobby ? 'lobby' : 'section')"
        :active-view="topNavActiveView"
        :class="{ 'night-mode': isNight }"
        :active-session="activeSession"
        :has-active-game="showActiveGamePill"
        :audio-enabled="audioEnabled"
        :tts-enabled="ttsEnabled"
        :tts-available="ttsAvailable"
        :show-exit-game="showTopbarExitGame"
        :exit-disabled="topbarExitDisabled"
        @go-lobby="goLobby"
        @open-logs="openLogPage()"
        @open-benchmark="openBenchmarkPage"
        @open-evolution="openEvolutionPage"
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
        v-bind="benchmarkProps"
        @back-to-match="backToMatch"
      />
      <EvolutionPage
        v-if="inEvolution"
        v-bind="evolutionProps"
        @back-to-match="backToMatch"
        @open-sample-log="openLogPage($event)"
        @replay-sample-game="replayHistoryGame($event)"
      />
      <LobbyPage
        v-if="inLobby"
        v-bind="lobbyProps"
        @start-mode="startMode"
      />

      <MatchPage
        v-if="inMatch"
        v-bind="matchProps"
        v-model:speech="speech"
        v-model:witch-choice="witchChoice"
        v-model:action-choice="actionChoice"
        v-model:burst-armed="burstArmed"
        v-model:action-target="actionTarget"
        v-model:chat-log-expanded="chatLogExpanded"
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
        @submit-speech="submitSpeech()"
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
      <div v-if="error" class="toast">{{ error }}</div>
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
