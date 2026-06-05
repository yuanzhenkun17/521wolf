<script setup>
import { computed, defineAsyncComponent } from 'vue'
import ActionPanel from '../components/ActionPanel.vue'
import ChatLog from '../components/ChatLog.vue'
import JudgeStrip from '../components/JudgeStrip.vue'
import PlayerCarousel from '../components/PlayerCarousel.vue'
import RoleStats from '../components/RoleStats.vue'

const CouncilScene = defineAsyncComponent(() => import('../components/CouncilScene.vue'))

const props = defineProps({
  game: Object,
  loading: Boolean,
  backendMode: { type: String, default: 'mock' },
  isNight: Boolean,
  isWatch: Boolean,
  isReplayMode: Boolean,
  watchRunning: Boolean,
  roleAssignmentComplete: Boolean,
  judgeBoardStarted: Boolean,
  judgeBoardStarting: Boolean,
  promptText: { type: String, default: '' },
  judgeStripMessage: { type: Array, default: () => [] },
  playerIdentityList: { type: Array, default: () => [] },
  chatLogExpanded: Boolean,
  chatLogs: { type: Array, default: () => [] },
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
  'toggle-watch',
  'reset-game',
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

function phaseName(phase) {
  return props.historyPhaseName ? props.historyPhaseName(phase) : (phase || '')
}

function speaker(log) {
  return props.logSpeaker ? props.logSpeaker(log) : (log?.speaker || '')
}

function message(log) {
  return props.logMessage ? props.logMessage(log) : (log?.message || '')
}

const sceneSelectableIds = computed(() => {
  if (props.pendingActionType) return props.actionCandidates.map((player) => player.id)
  if (props.game?.waiting_for === 'vote') return props.canVotePlayers.map((player) => player.id)
  if (props.burstArmed) return props.whiteWolfTargets.map((player) => player.id)
  return []
})
const stepTitle = computed(() => props.backendMode === 'mock' ? '单步推进' : '刷新状态')
</script>

<template>
  <template v-if="game">
    <CouncilScene
      :game="game"
      :is-night="isNight"
      :is-watch="isWatch"
      :is-replay-mode="isReplayMode"
      :role-assignment-complete="roleAssignmentComplete"
      :judge-board-started="judgeBoardStarted"
      :players="playerIdentityList"
      :current-speaker-id="game.current_speaker_id"
      :vote-tally="sceneVoteTally"
      :selectable-ids="sceneSelectableIds"
      @player-select="props.chooseScenePlayer?.($event)"
      @ready="emit('council-ready', $event)"
    />

    <section class="match-control-strip">
      <div class="strip-top-row">
        <div class="strip-status">
          <strong>{{ isReplayMode ? '复盘' : 'DAY ' + game.day }}</strong>
          <span class="phase-icon" :title="phaseName(game.phase)">{{ isNight ? '☾' : '☀' }}</span>
          <Transition name="strip-text" mode="out-in">
            <em :key="promptText">
              {{ isReplayMode ? ('DAY ' + game.day + ' · ' + phaseName(game.phase)) : promptText }}
            </em>
          </Transition>
        </div>
        <div class="strip-controls" aria-label="观战控制">
          <button v-if="isReplayMode" class="icon-button primary" title="返回日志" @click="emit('return-to-history')">
            <svg viewBox="0 0 24 24" aria-hidden="true"><path d="M15.5 5.5 9 12l6.5 6.5V5.5z" /></svg>
          </button>
          <button v-if="isReplayMode" class="icon-button" title="退出复盘" @click="emit('exit-replay')">
            <svg viewBox="0 0 24 24" aria-hidden="true"><path d="M6.4 5 5 6.4l5.6 5.6L5 17.6 6.4 19l5.6-5.6 5.6 5.6 1.4-1.4-5.6-5.6L19 6.4 17.6 5 12 10.6z" /></svg>
          </button>
          <button v-if="!isReplayMode" class="icon-button primary" :disabled="!watchRunning && game.winner" :title="watchRunning ? '暂停' : '开始'" @click="emit('toggle-watch')">
            <svg v-if="watchRunning" viewBox="0 0 24 24" aria-hidden="true"><path d="M7 5h4v14H7zM13 5h4v14h-4z" /></svg>
            <svg v-else viewBox="0 0 24 24" aria-hidden="true"><path d="M8 5v14l11-7z" /></svg>
          </button>
          <button v-if="!isReplayMode" class="icon-button" :disabled="loading" title="重开" @click="emit('reset-game')">
            <svg viewBox="0 0 24 24" aria-hidden="true"><path d="M17.7 6.3A8 8 0 1 0 20 12h-2.2a5.8 5.8 0 1 1-1.7-4.1L13 11h8V3z" /></svg>
          </button>
          <button v-if="!isReplayMode" class="icon-button" :disabled="loading || watchRunning || game.winner" :title="stepTitle" @click="emit('step-game')">
            <svg viewBox="0 0 24 24" aria-hidden="true"><path d="M5 5v14l8-7zM13 5v14l8-7z" /></svg>
          </button>
        </div>
      </div>
      <JudgeStrip
        :messages="judgeStripMessage"
        :judge-board-started="judgeBoardStarted"
        :judge-board-starting="judgeBoardStarting"
        @start="emit('start-from-judge-board')"
      />
    </section>

    <section class="match-layout">
      <Transition name="role-grid-in">
        <aside v-if="roleAssignmentComplete" class="role-grid-panel" aria-label="玩家身份列">
          <div class="role-grid">
            <article
              v-for="(player, index) in playerIdentityList"
              :key="player.id"
              :class="{ speaking: player.speaking, dead: !player.alive }"
              :style="{ '--i': index }"
            >
              <img v-show="player.isSheriff" class="sheriff-badge-sm" src="/ui/sheriff-badge.png" alt="警长" />
              <div class="role-icon-wrap" :class="{ dead: !player.alive }">
                <img :src="player.roleIcon" :alt="player.role_hint" />
              </div>
              <div class="role-grid-seat">
                <b>{{ player.displaySeat }}</b>
              </div>
            </article>
          </div>
        </aside>
      </Transition>

      <Transition name="role-grid-in">
        <ChatLog
          v-if="roleAssignmentComplete"
          :logs="chatLogs"
          :expanded="chatLogExpanded"
          :log-speaker="props.logSpeaker"
          :log-message="props.logMessage"
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

      <Transition name="role-grid-in">
        <aside v-if="roleAssignmentComplete" class="info-stack">
          <section class="judge-panel match-panel">
            <header>
              <span>法官日志</span>
              <strong>{{ displayPhase }}</strong>
            </header>
            <div class="judge-list">
              <div v-for="group in groupedJudgeLogs" :key="group.key" class="log-group">
                <div class="log-group-header">
                  <span class="log-day">DAY {{ group.day }}</span>
                  <span class="log-phase">{{ group.phaseLabel }}</span>
                  <span class="log-phase-icon">{{ group.phase === 'night' ? '☾' : '☀' }}</span>
                </div>
                <article v-for="(log, index) in group.logs" :key="index" class="log-entry">
                  <span class="log-speaker">{{ speaker(log) }}</span>
                  <p class="log-message">{{ message(log) }}</p>
                </article>
              </div>
            </div>
          </section>
          <RoleStats
            :stats="roleStats"
            :living-count="livingPlayers.length"
            :total-count="game.player_count"
          />
        </aside>
      </Transition>
    </section>
  </template>
</template>
