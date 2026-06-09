<script lang="ts">
// @ts-nocheck
const settledIntroGameIds = new Set()
</script>

<script setup lang="ts">
// @ts-nocheck
import { computed, onBeforeUnmount, ref, watch } from 'vue'
import ActionPanel from '../components/ActionPanel.vue'
import ApiErrorPanel from '../components/ApiErrorPanel.vue'
import ChatLog from '../components/ChatLog.vue'
import CouncilScene from '../components/CouncilScene.vue'
import GameOverBoard from '../components/GameOverBoard.vue'
import MatchControlStrip from '../components/MatchControlStrip.vue'
import MobileTaskShell from '../components/MobileTaskShell.vue'
import PlayerCarousel from '../components/PlayerCarousel.vue'
import PlayerIdentityBoard from '../components/PlayerIdentityBoard.vue'
import ReplayControls from '../components/ReplayControls.vue'
import { displayPhaseLabel } from '../components/history/historyDisplay.ts'
import { inlineNoticeForDisplay, noticeErrorForPanel } from '../composables/apiErrorDisplay.ts'

const props = defineProps({
  game: Object,
  loading: Boolean,
  matchNotice: { type: Object, default: () => ({}) },
  backendMode: { type: String, default: 'mock' },
  isNight: Boolean,
  isWatch: Boolean,
  isReplayMode: Boolean,
  replayCursor: { type: Number, default: 0 },
  replayPlaying: Boolean,
  replaySpeed: { type: Number, default: 1 },
  replayTotal: { type: Number, default: 0 },
  replayEventLabel: { type: String, default: '' },
  watchRunning: Boolean,
  skipIntroGameId: { type: [String, Number, null], default: null },
  roleAssignmentComplete: Boolean,
  judgeBoardStarted: Boolean,
  judgeBoardStarting: Boolean,
  promptText: { type: String, default: '' },
  judgeStripMessage: { type: Array, default: () => [] },
  playerIdentityList: { type: Array, default: () => [] },
  chatLogExpanded: Boolean,
  chatLogs: { type: Array, default: () => [] },
  matchRecordLogs: { type: Array, default: () => [] },
  groupedJudgeLogs: { type: Array, default: () => [] },
  displayPhase: { type: String, default: '' },
  livingPlayers: { type: Array, default: () => [] },
  roleStats: { type: Array, default: () => [] },
  speakerCarousel: { type: Array, default: () => [] },
  speakerMessage: { type: String, default: '' },
  humanPlayer: Object,
  roleName: { type: String, default: '' },
  skillState: { type: Object, default: () => ({}) },
  isHumanWitch: Boolean,
  isHumanWhiteWolf: Boolean,
  canUseWitchAntidote: Boolean,
  canUseWitchPoison: Boolean,
  canWhiteWolfBurst: Boolean,
  pendingActionType: { type: String, default: '' },
  pendingChoiceOptions: { type: Array, default: () => [] },
  actionInstruction: { type: String, default: '' },
  speechCountdownText: { type: String, default: '' },
  canVotePlayers: { type: Array, default: () => [] },
  sceneEffects: { type: Array, default: () => [] },
  actionCandidates: { type: Array, default: () => [] },
  whiteWolfTargets: { type: Array, default: () => [] },
  needsTarget: Boolean,
  speech: { type: String, default: '' },
  witchChoice: { type: String, default: 'skip' },
  actionChoice: { type: String, default: '' },
  burstArmed: Boolean,
  actionTarget: [String, Number, null],
  sceneVoteTally: { type: Array, default: () => [] },
  playerLabel: Function,
  roleIconImage: Function,
  logSpeaker: Function,
  logMessage: Function,
  historyPhaseName: Function,
  chooseScenePlayer: Function
})

const emit = defineEmits([
  'council-ready',
  'return-to-history',
  'exit-replay',
  'play-replay',
  'pause-replay',
  'step-replay',
  'seek-replay',
  'set-replay-speed',
  'toggle-watch',
  'reset-game',
  'exit-game',
  'step-game',
  'start-from-judge-board',
  'update:chatLogExpanded',
  'update:speech',
  'update:witchChoice',
  'update:actionChoice',
  'update:burstArmed',
  'update:actionTarget',
  'submit-speech',
  'submit-action'
])

const sceneApi = ref(null)
const compactHudHeight = ref(146)
const introMounted = ref(true)
const introLeaving = ref(false)
const hoveredTargetId = ref(null)
const sceneLoadProgress = ref({
  phase: 'scene',
  label: '搭建议事厅',
  loaded: 0,
  total: 1,
  progress: 0.08,
  ready: false
})
const INTRO_MIN_VISIBLE_MS = 1800
let introRunId = 0
let introTimer = 0
let introRemoveTimer = 0
let introSettledGameId = null
const introWaitTimers = new Set()

function phaseName(phase) {
  return props.historyPhaseName ? props.historyPhaseName(phase) : displayPhaseLabel(phase)
}

const hasPendingHumanAction = computed(() => {
  const pending = props.game?.pending_human_action
  if (!pending) return false
  const pendingPlayerId = Number(pending.player_id)
  const humanPlayerId = Number(props.humanPlayer?.id || props.game?.human_player_id)
  return !pendingPlayerId || !humanPlayerId || pendingPlayerId === humanPlayerId
})
const sceneSelectableIds = computed(() => {
  if (!hasPendingHumanAction.value) return []
  if (props.burstArmed) return props.whiteWolfTargets.map((player) => player.id)
  if (props.pendingActionType) return props.needsTarget ? props.actionCandidates.map((player) => player.id) : []
  if (props.game?.waiting_for === 'vote') return props.canVotePlayers.map((player) => player.id)
  return []
})
const selectedSceneTargetId = computed(() => props.actionTarget ?? null)
const dismissedGameOverKey = ref('')
const gameOverKey = computed(() => {
  if (!props.game?.winner) return ''
  return `${props.game?.game_id || ''}:${props.game.winner}:${props.game?.day || ''}`
})
const showGameOverModal = computed(() =>
  Boolean(gameOverKey.value) &&
  !props.isReplayMode &&
  dismissedGameOverKey.value !== gameOverKey.value
)
const introStage = computed(() => {
  if (!props.game) return '创建房间'
  if (!sceneApi.value) return '点亮议事厅'
  if (!props.roleAssignmentComplete && !props.isReplayMode) return '分配身份'
  return '召集玩家'
})
const introStageText = computed(() => sceneLoadProgress.value?.label || introStage.value)
const introProgressPercent = computed(() => {
  const progress = Number(sceneLoadProgress.value?.progress)
  return `${Math.max(6, Math.min(100, Math.round((Number.isFinite(progress) ? progress : 0.08) * 100)))}%`
})
const activeSeatLabel = computed(() => {
  const player = props.playerIdentityList.find((item) => item?.speaking)
  return player?.displaySeat == null ? '' : String(player.displaySeat)
})
const introReady = computed(() =>
  Boolean(props.game)
  && Boolean(sceneApi.value)
  && (props.roleAssignmentComplete || props.isReplayMode)
)
const showIntro = computed(() => !props.isReplayMode && introMounted.value)
const replayPhaseText = computed(() => `第${props.game?.day ?? '-'}天 · ${phaseName(props.game?.phase)}`)
const replayJudgeStripMessage = computed(() => [
  { message: props.replayEventLabel || '准备回放' }
])
function matchPanelErrorForNotice(notice) {
  const error = noticeErrorForPanel(notice)
  if (!error || error instanceof Error || typeof error !== 'object' || Array.isArray(error)) return error
  if (error.requestId || !error.request_id) return error
  return {
    ...error,
    requestId: error.request_id
  }
}

const inlineMatchNotice = computed(() => inlineNoticeForDisplay(props.matchNotice))
const matchErrorNotice = computed(() => matchPanelErrorForNotice(props.matchNotice))
const matchNoticeMessage = computed(() => String(inlineMatchNotice.value?.message || '').trim())
const matchNoticeType = computed(() => inlineMatchNotice.value?.type || 'info')
const hasMobileTask = computed(() => (
  props.roleAssignmentComplete &&
  !props.isWatch &&
  !props.isReplayMode &&
  hasPendingHumanAction.value &&
  (props.game?.waiting_for === 'speech' || Boolean(props.pendingActionType) || props.game?.waiting_for === 'vote')
))

function handleCouncilReady(api) {
  sceneApi.value = api
  emit('council-ready', api)
}

function handleCouncilLoadingProgress(progress) {
  sceneLoadProgress.value = {
    ...sceneLoadProgress.value,
    ...(progress || {})
  }
}

function handleScenePlayerSelect(playerId) {
  props.chooseScenePlayer?.(playerId)
}

function handleTargetHover(playerId) {
  if (playerId == null || playerId === '') {
    hoveredTargetId.value = null
    return
  }
  const numeric = Number(playerId)
  hoveredTargetId.value = Number.isFinite(numeric) ? numeric : playerId
}

function closeGameOverModal() {
  dismissedGameOverKey.value = gameOverKey.value
}

function wait(ms, runId = introRunId) {
  if (typeof window === 'undefined') return Promise.resolve()
  return new Promise((resolve) => {
    const entry = { timer: 0, resolve: null, runId }
    entry.resolve = () => {
      introWaitTimers.delete(entry)
      resolve()
    }
    entry.timer = window.setTimeout(entry.resolve, ms)
    introWaitTimers.add(entry)
  })
}

function clearIntroWaitTimers(runId = null) {
  introWaitTimers.forEach((entry) => {
    if (runId != null && entry.runId !== runId) return
    window.clearTimeout(entry.timer)
    entry.resolve?.()
  })
}

function clearIntroTimers() {
  if (introTimer) {
    window.clearTimeout(introTimer)
    introTimer = 0
  }
  if (introRemoveTimer) {
    window.clearTimeout(introRemoveTimer)
    introRemoveTimer = 0
  }
  clearIntroWaitTimers()
}

function clearIntroDelayTimer() {
  if (introTimer) {
    window.clearTimeout(introTimer)
    introTimer = 0
  }
}

function forceHideIntroOverlay() {
  clearIntroTimers()
  introMounted.value = false
  introLeaving.value = false
}

function showIntroOverlay() {
  clearIntroTimers()
  introMounted.value = true
  introLeaving.value = false
}

function hideIntroOverlay() {
  if (introRemoveTimer) window.clearTimeout(introRemoveTimer)
  introLeaving.value = true
  introRemoveTimer = window.setTimeout(() => {
    introMounted.value = false
    introLeaving.value = false
    introRemoveTimer = 0
  }, 380)
}

async function settleIntro() {
  const gameId = props.game?.game_id ?? null
  const runId = ++introRunId
  clearIntroDelayTimer()
  if (props.isReplayMode) {
    forceHideIntroOverlay()
    return
  }
  if (gameId && String(props.skipIntroGameId || '') === String(gameId)) {
    settledIntroGameIds.add(gameId)
    forceHideIntroOverlay()
    return
  }
  if (gameId && (introSettledGameId === gameId || settledIntroGameIds.has(gameId))) {
    forceHideIntroOverlay()
    return
  }
  showIntroOverlay()
  if (!introReady.value) return
  const models = sceneApi.value?.waitForCouncilModels?.()
  await Promise.all([
    models || Promise.resolve(),
    wait(INTRO_MIN_VISIBLE_MS, runId)
  ]).finally(() => clearIntroWaitTimers(runId))
  if (runId !== introRunId) return
  introSettledGameId = gameId
  if (gameId) settledIntroGameIds.add(gameId)
  introTimer = window.setTimeout(() => {
    if (runId === introRunId) hideIntroOverlay()
  }, 180)
}

watch(
  [
    () => props.game?.game_id ?? null,
    () => props.skipIntroGameId,
    () => props.roleAssignmentComplete,
    () => props.isReplayMode,
    () => sceneApi.value
  ],
  settleIntro,
  { immediate: true }
)

onBeforeUnmount(() => {
  introRunId += 1
  clearIntroTimers()
})
</script>

<template>
  <MobileTaskShell mode="match" :has-task="hasMobileTask" :replay="isReplayMode">
    <CouncilScene
      :game="game"
      :is-night="isNight"
      :is-watch="isWatch"
      :is-replay-mode="isReplayMode"
      :role-assignment-complete="roleAssignmentComplete"
      :judge-board-started="judgeBoardStarted"
      :players="playerIdentityList"
      :current-speaker-id="game?.current_speaker_id ?? null"
      :speaker-message="speakerMessage"
      :vote-tally="sceneVoteTally"
      :scene-effects="sceneEffects"
      :selectable-ids="sceneSelectableIds"
      :selected-target-id="selectedSceneTargetId"
      :hovered-target-id="hoveredTargetId"
      @player-select="handleScenePlayerSelect"
      @loading-progress="handleCouncilLoadingProgress"
      @ready="handleCouncilReady"
    />

    <section
      v-if="showIntro"
      :class="['match-intro-overlay', { leaving: introLeaving }]"
      aria-live="polite"
    >
      <div class="intro-ring" aria-hidden="true">
        <span></span>
        <i></i>
      </div>
      <div class="intro-copy">
        <b>夜幕议事厅</b>
        <strong>议事厅入场</strong>
        <em>{{ introStageText }}</em>
      </div>
      <div class="intro-progress" aria-hidden="true"><span :style="{ width: introProgressPercent }"></span></div>
      <div class="intro-steps" aria-hidden="true">
        <span :class="{ active: Boolean(game) }"></span>
        <span :class="{ active: Boolean(sceneApi) }"></span>
        <span :class="{ active: roleAssignmentComplete || isReplayMode }"></span>
      </div>
    </section>

    <Transition name="match-notice">
      <ApiErrorPanel
        v-if="matchErrorNotice"
        class="match-error-notice"
        :error="matchErrorNotice"
        title="对局操作失败"
        compact
      />
    </Transition>

    <Transition name="match-notice">
      <aside
        v-if="matchNoticeMessage"
        :class="['match-action-notice', matchNoticeType]"
        role="status"
        aria-live="polite"
      >
        <span></span>
        <b>{{ matchNoticeMessage }}</b>
      </aside>
    </Transition>

    <template v-if="game">
      <MatchControlStrip
        :game="game"
        :loading="loading"
        :backend-mode="backendMode"
        :is-night="isNight"
        :is-replay-mode="isReplayMode"
        :watch-running="watchRunning"
        :prompt-text="isReplayMode ? replayPhaseText : promptText"
        :judge-strip-message="isReplayMode ? replayJudgeStripMessage : judgeStripMessage"
        :judge-board-started="isReplayMode ? true : judgeBoardStarted"
        :judge-board-starting="isReplayMode ? false : judgeBoardStarting"
        :history-phase-name="props.historyPhaseName"
        @toggle-watch="emit('toggle-watch')"
        @reset-game="emit('reset-game')"
        @exit-game="emit('exit-game')"
        @start-from-judge-board="emit('start-from-judge-board')"
      />

      <ReplayControls
        v-if="isReplayMode"
        class="match-replay-controls"
        :is-replay-mode="isReplayMode"
        :cursor="replayCursor"
        :total="replayTotal"
        :playing="replayPlaying"
        :speed="replaySpeed"
        :event-label="replayEventLabel"
        @play="emit('play-replay')"
        @pause="emit('pause-replay')"
        @step="emit('step-replay', $event)"
        @seek="emit('seek-replay', $event)"
        @speed="emit('set-replay-speed', $event)"
        @return-to-history="emit('return-to-history')"
        @exit-replay="emit('exit-replay')"
      />

      <section class="match-layout">
        <Transition name="role-grid-in">
          <PlayerIdentityBoard
            v-if="roleAssignmentComplete"
            :players="playerIdentityList"
            :active-seat="activeSeatLabel"
            :selected-target-id="selectedSceneTargetId"
            :panel-height="compactHudHeight"
          />
        </Transition>

        <Transition name="role-grid-in">
          <ChatLog
            v-if="roleAssignmentComplete"
            :logs="matchRecordLogs"
            :expanded="chatLogExpanded"
            :active-seat="activeSeatLabel"
            :log-speaker="props.logSpeaker"
            :log-message="props.logMessage"
            @compact-height="compactHudHeight = $event"
            @update:expanded="emit('update:chatLogExpanded', $event)"
          />
        </Transition>

        <main class="board-stage">
          <ActionPanel
            :game="game"
            :loading="loading"
            :is-watch="isWatch"
            :is-replay-mode="isReplayMode"
            :role-assignment-complete="roleAssignmentComplete"
            :human-player="humanPlayer"
            :role-name="roleName"
            :skill-state="skillState"
            :is-human-witch="isHumanWitch"
            :is-human-white-wolf="isHumanWhiteWolf"
            :can-use-witch-antidote="canUseWitchAntidote"
            :can-use-witch-poison="canUseWitchPoison"
            :can-white-wolf-burst="canWhiteWolfBurst"
            :pending-action-type="pendingActionType"
            :pending-choice-options="pendingChoiceOptions"
            :action-instruction="actionInstruction"
            :speech-countdown-text="speechCountdownText"
            :can-vote-players="canVotePlayers"
            :action-candidates="actionCandidates"
            :white-wolf-targets="whiteWolfTargets"
            :needs-target="needsTarget"
            :player-label="props.playerLabel"
            :role-icon-image="props.roleIconImage"
            :speech="speech"
            :witch-choice="witchChoice"
            :action-choice="actionChoice"
            :burst-armed="burstArmed"
            :action-target="actionTarget"
            @update:speech="emit('update:speech', $event)"
            @update:witchChoice="emit('update:witchChoice', $event)"
            @update:actionChoice="emit('update:actionChoice', $event)"
            @update:burstArmed="emit('update:burstArmed', $event)"
            @update:actionTarget="emit('update:actionTarget', $event)"
            @target-hover="handleTargetHover"
            @submit-speech="emit('submit-speech')"
            @submit-action="emit('submit-action', $event)"
          />
          <section v-if="roleAssignmentComplete" class="square-board">
            <PlayerCarousel
              :game="game"
              :is-night="isNight"
              :carousel="speakerCarousel"
              :message="speakerMessage"
            />
          </section>
        </main>

      </section>

      <Transition name="game-over-board">
        <GameOverBoard
          v-if="showGameOverModal"
          :game="game"
          :loading="loading"
          :living-count="livingPlayers.length"
          @reset-game="emit('reset-game')"
          @exit-game="emit('exit-game')"
          @close="closeGameOverModal"
        />
      </Transition>
    </template>
  </MobileTaskShell>
</template>

<style scoped>
.match-intro-overlay {
  position: fixed;
  inset: 0;
  z-index: 91;
  display: grid;
  place-items: center;
  align-content: center;
  gap: 18px;
  background:
    radial-gradient(circle at 50% 42%, rgba(242, 202, 80, 0.14), transparent 26%),
    radial-gradient(circle at 50% 56%, rgba(115, 26, 22, 0.24), transparent 34%),
    linear-gradient(180deg, rgba(2, 1, 2, 0.96), rgba(6, 4, 3, 0.88));
  color: #fff0c6;
  opacity: 1;
  pointer-events: auto;
  transition: opacity 360ms ease;
}

.match-intro-overlay.leaving {
  opacity: 0;
  pointer-events: none;
}

.match-intro-overlay::before,
.match-intro-overlay::after {
  content: "";
  position: absolute;
  inset: 0;
  pointer-events: none;
}

.match-intro-overlay::before {
  opacity: 0.22;
  background:
    linear-gradient(90deg, transparent 0 47%, rgba(242, 202, 80, 0.34) 49% 51%, transparent 53%),
    repeating-linear-gradient(90deg, rgba(255, 232, 176, 0.1) 0 1px, transparent 1px 58px);
  mask-image: radial-gradient(ellipse at center, black 0 44%, transparent 72%);
}

.match-intro-overlay::after {
  background:
    radial-gradient(circle at 50% 50%, transparent 0 28%, rgba(0, 0, 0, 0.42) 62%, rgba(0, 0, 0, 0.84) 100%),
    linear-gradient(0deg, rgba(0, 0, 0, 0.28), transparent 28%, transparent 70%, rgba(0, 0, 0, 0.32));
}

.intro-ring,
.intro-copy,
.intro-progress,
.intro-steps {
  position: relative;
  z-index: 1;
}

.intro-ring {
  display: grid;
  width: 116px;
  height: 116px;
  place-items: center;
  border: 1px solid rgba(242, 202, 80, 0.28);
  border-radius: 50%;
  background: radial-gradient(circle, rgba(242, 202, 80, 0.2), rgba(9, 6, 4, 0.52) 58%, transparent 62%);
  box-shadow: 0 0 52px rgba(242, 202, 80, 0.18);
}

.intro-ring span,
.intro-ring i {
  position: absolute;
  border-radius: 50%;
}

.intro-ring span {
  inset: 12px;
  border: 2px solid transparent;
  border-top-color: #f2ca50;
  border-right-color: rgba(242, 202, 80, 0.34);
  animation: introSpin 1600ms linear infinite;
}

.intro-ring i {
  width: 38px;
  height: 38px;
  background:
    radial-gradient(circle at 58% 44%, #fff7d8 0 6px, transparent 7px),
    radial-gradient(circle, #f2ca50 0 8px, rgba(242, 202, 80, 0.12) 9px 100%);
  box-shadow: 0 0 32px rgba(242, 202, 80, 0.54);
}

.intro-copy {
  display: grid;
  gap: 5px;
  text-align: center;
}

.intro-copy b {
  color: rgba(255, 235, 181, 0.58);
  font-size: 12px;
  font-weight: 950;
  letter-spacing: 0;
  text-transform: uppercase;
}

.intro-copy strong {
  color: #fff0c6;
  font-size: 30px;
  font-weight: 1000;
  line-height: 1.05;
  text-shadow: 0 0 24px rgba(242, 202, 80, 0.28);
}

.intro-copy em {
  color: rgba(255, 238, 196, 0.72);
  font-size: 13px;
  font-style: normal;
  font-weight: 900;
}

.intro-progress {
  width: 240px;
  height: 4px;
  overflow: hidden;
  border-radius: 999px;
  background: rgba(255, 238, 196, 0.14);
}

.intro-progress span {
  display: block;
  width: 8%;
  height: 100%;
  border-radius: inherit;
  background: linear-gradient(90deg, #8a5428, #f2ca50 72%, #fff0b8);
  box-shadow: 0 0 18px rgba(242, 202, 80, 0.34);
  transition: width 220ms ease;
}

.intro-steps {
  display: flex;
  align-items: center;
  gap: 9px;
}

.intro-steps span {
  width: 8px;
  height: 8px;
  border-radius: 50%;
  background: rgba(255, 238, 196, 0.2);
  transition: background 220ms ease, box-shadow 220ms ease;
}

.intro-steps span.active {
  background: #f2ca50;
  box-shadow: 0 0 18px rgba(242, 202, 80, 0.58);
}

@keyframes introSpin {
  to { transform: rotate(360deg); }
}

@keyframes introLoad {
  from { transform: translateX(-100%); }
  to { transform: translateX(240%); }
}

.match-action-notice {
  position: fixed;
  top: var(--match-toast-top, 158px);
  left: 50%;
  z-index: 92;
  display: inline-grid;
  grid-template-columns: 9px minmax(0, 1fr);
  align-items: center;
  gap: 8px;
  box-sizing: border-box;
  width: min(420px, calc(100vw - var(--match-toast-gutter, 32px) - var(--match-safe-left, 0px) - var(--match-safe-right, 0px)));
  min-height: 34px;
  padding: 7px 14px 7px 12px;
  border: 2px solid rgba(100, 55, 25, 0.62);
  border-radius: 0;
  color: #3f2714;
  background:
    linear-gradient(180deg, rgba(255, 239, 194, 0.96), rgba(230, 190, 117, 0.96)),
    repeating-linear-gradient(90deg, rgba(88, 42, 14, 0.08) 0 1px, transparent 1px 18px);
  box-shadow:
    0 10px 24px rgba(0, 0, 0, 0.34),
    inset 0 0 0 1px rgba(255, 250, 218, 0.48);
  transform: translateX(-50%);
  pointer-events: none;
}

.match-error-notice {
  --status-danger: #9a2e21;
  --text-main: #3f2714;
  --text-muted: rgba(63, 39, 20, 0.72);
  --match-error-bottom-clearance: calc(288px + var(--match-safe-bottom, 0px));
  position: fixed;
  top: var(--match-toast-top, calc(158px + var(--match-safe-top, 0px)));
  left: 50%;
  z-index: 92;
  box-sizing: border-box;
  width: min(520px, calc(100vw - var(--match-toast-gutter, 32px) - var(--match-safe-left, 0px) - var(--match-safe-right, 0px)));
  max-height: clamp(144px, calc(100dvh - var(--match-toast-top, 158px) - var(--match-error-bottom-clearance)), 340px);
  overflow-y: auto;
  border-width: 2px;
  background:
    linear-gradient(180deg, rgba(255, 239, 194, 0.98), rgba(245, 218, 164, 0.98)),
    repeating-linear-gradient(90deg, rgba(88, 42, 14, 0.08) 0 1px, transparent 1px 18px);
  box-shadow:
    0 14px 30px rgba(0, 0, 0, 0.36),
    inset 0 0 0 1px rgba(255, 250, 218, 0.48);
  transform: translateX(-50%);
  pointer-events: auto;
  scrollbar-gutter: stable;
}

.match-error-notice :deep(details) {
  min-width: 0;
}

.match-action-notice span {
  display: block;
  width: 9px;
  height: 9px;
  border-radius: 50%;
  background: #7c8b43;
  box-shadow: 0 0 0 3px rgba(124, 139, 67, 0.18);
}

.match-action-notice b {
  min-width: 0;
  color: inherit;
  font-size: 13px;
  font-weight: 900;
  line-height: 1.25;
  overflow-wrap: anywhere;
}

.match-action-notice.warning span {
  background: #b9802d;
  box-shadow: 0 0 0 3px rgba(185, 128, 45, 0.2);
}

.match-notice-enter-active,
.match-notice-leave-active {
  transition: opacity 160ms ease, transform 160ms ease;
}

.match-notice-enter-from,
.match-notice-leave-to {
  opacity: 0;
  transform: translate(-50%, -6px);
}

.match-replay-controls {
  position: fixed;
  right: auto;
  bottom: var(--match-replay-bottom, 24px);
  left: 50%;
  z-index: 24;
  width: min(740px, calc(100vw - var(--match-replay-gutter, 52px) - var(--match-safe-left, 0px) - var(--match-safe-right, 0px)));
  transform: translateX(-50%);
  pointer-events: auto;
}

:deep(.player-command-panel) {
  bottom: var(--match-action-bottom, clamp(18px, 4vh, 42px));
  width: min(720px, calc(100vw - var(--match-action-gutter, 64px) - var(--match-safe-left, 0px) - var(--match-safe-right, 0px)));
  max-height: min(224px, var(--match-action-max-height, calc(100vh - 112px)));
}

@supports not (height: 100dvh) {
  .match-error-notice {
    max-height: clamp(144px, calc(100vh - var(--match-toast-top, 158px) - var(--match-error-bottom-clearance)), 340px);
  }
}

@media (max-width: 760px) {
  .match-replay-controls {
    bottom: var(--match-replay-bottom, 12px);
    width: calc(100vw - var(--match-replay-gutter, 18px) - var(--match-safe-left, 0px) - var(--match-safe-right, 0px));
  }

  .match-action-notice {
    top: var(--match-toast-top, 146px);
    width: calc(100vw - var(--match-toast-gutter, 22px) - var(--match-safe-left, 0px) - var(--match-safe-right, 0px));
    padding-inline: 10px;
  }

  .match-error-notice {
    --match-error-bottom-clearance: calc(306px + var(--match-safe-bottom, 0px));
    top: var(--match-toast-top, calc(146px + var(--match-safe-top, 0px)));
    width: calc(100vw - var(--match-toast-gutter, 22px) - var(--match-safe-left, 0px) - var(--match-safe-right, 0px));
    max-height: clamp(144px, calc(100dvh - var(--match-toast-top, 146px) - var(--match-error-bottom-clearance)), 260px);
    padding: 10px 11px;
  }

  :deep(.player-command-panel) {
    bottom: var(--match-action-bottom, 12px);
    width: calc(100vw - var(--match-action-gutter, 18px) - var(--match-safe-left, 0px) - var(--match-safe-right, 0px));
    max-height: min(260px, var(--match-action-max-height, calc(100vh - 96px)));
  }
}

@supports not (height: 100dvh) {
  @media (max-width: 760px) {
    .match-error-notice {
      max-height: clamp(144px, calc(100vh - var(--match-toast-top, 146px) - var(--match-error-bottom-clearance)), 260px);
    }
  }
}
</style>
