<script setup>
import { computed } from 'vue'

const props = defineProps({
  game: Object,
  loading: Boolean,
  isWatch: Boolean,
  isReplayMode: Boolean,
  roleAssignmentComplete: Boolean,
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
  playerLabel: Function,
  roleIconImage: Function,
  speech: { type: String, default: '' },
  witchChoice: { type: String, default: 'skip' },
  actionChoice: { type: String, default: '' },
  burstArmed: Boolean,
  actionTarget: [String, Number, null]
})

const emit = defineEmits([
  'update:speech',
  'update:witchChoice',
  'update:actionChoice',
  'update:burstArmed',
  'update:actionTarget',
  'target-hover',
  'submit-speech',
  'submit-action'
])

const waitingFor = computed(() => props.game?.waiting_for || '')
const pendingHumanAction = computed(() => props.game?.pending_human_action || null)
const isPendingForHuman = computed(() => {
  if (!pendingHumanAction.value) return false
  const pendingPlayerId = Number(pendingHumanAction.value.player_id)
  const humanPlayerId = Number(props.humanPlayer?.id || props.game?.human_player_id)
  return !pendingPlayerId || !humanPlayerId || pendingPlayerId === humanPlayerId
})
const isVoteWaiting = computed(() => waitingFor.value === 'vote')
const isWhiteWolfExplodePending = computed(() => props.pendingActionType === 'white_wolf_explode')
const activeBurstArmed = computed(() => props.burstArmed && isWhiteWolfExplodePending.value && props.canWhiteWolfBurst)
const targetOptions = computed(() => {
  if (activeBurstArmed.value) return props.whiteWolfTargets
  if (isVoteWaiting.value && !props.actionCandidates.length) return props.canVotePlayers
  return props.actionCandidates
})
const hasPanelAction = computed(() => Boolean(props.pendingActionType || activeBurstArmed.value || isVoteWaiting.value))
const hasHumanTurnContent = computed(() => waitingFor.value === 'speech' || hasPanelAction.value)
const shouldShowPanel = computed(() =>
  props.roleAssignmentComplete &&
  !props.isWatch &&
  !props.isReplayMode &&
  isPendingForHuman.value &&
  hasHumanTurnContent.value
)
const needsChoice = computed(() => props.pendingChoiceOptions.length > 0 && props.pendingActionType !== 'witch_act' && !activeBurstArmed.value)
const panelNeedsTarget = computed(() => activeBurstArmed.value || props.needsTarget || isVoteWaiting.value)
const selectedTargetPlayer = computed(() => targetOptions.value.find((player) => Number(player?.id) === Number(props.actionTarget)))
const selectedTargetLabel = computed(() => selectedTargetPlayer.value ? targetLabel(selectedTargetPlayer.value) : '')
const canSubmitPanelAction = computed(() => {
  if (props.loading) return false
  if (needsChoice.value && !props.actionChoice) return false
  if (panelNeedsTarget.value && props.actionTarget == null) return false
  return true
})

function optionValue(value) {
  if (value === '' || value == null) return null
  const numeric = Number(value)
  return Number.isNaN(numeric) ? value : numeric
}

function label(player) {
  return props.playerLabel ? props.playerLabel(player) : `${player?.seat || player?.id || ''}号`
}

function targetLabel(player) {
  const fallback = player?.displaySeat ?? player?.seat ?? player?.id
  const raw = props.playerLabel ? props.playerLabel(player) : (fallback == null || fallback === '' ? '玩家' : `${fallback}号`)
  const text = String(raw || '').trim()
  const seatMatch = text.match(/^\s*(\d+)\s*号/)
  if (seatMatch) return `${seatMatch[1]}号`
  return fallback == null || fallback === '' ? '玩家' : `${fallback}号`
}

function roleImage(player) {
  return props.roleIconImage ? props.roleIconImage(player) : ''
}

function setWitchChoice(choice) {
  emit('update:witchChoice', choice)
  if (choice !== 'poison') emit('update:actionTarget', null)
}

function setActionChoice(choice) {
  emit('update:actionChoice', choice)
  const option = props.pendingChoiceOptions.find((item) => item.value === choice)
  if (!option?.requiresTarget) emit('update:actionTarget', null)
}

function setActionTarget(value) {
  emit('update:actionTarget', optionValue(value))
}

function hoverTarget(value) {
  emit('target-hover', value == null ? null : optionValue(value))
}

function skipWitchAction() {
  emit('update:witchChoice', 'skip')
  emit('update:actionTarget', null)
  emit('submit-action', { action: 'witch_act', targetId: null, choice: 'skip' })
}

function submitTargetAction() {
  if (activeBurstArmed.value) {
    emit('submit-action', { action: 'white_wolf_burst', targetId: props.actionTarget, choice: 'burst' })
    return
  }
  emit('submit-action', {
    action: props.pendingActionType || 'exile_vote',
    targetId: props.actionTarget,
    choice: props.pendingActionType === 'witch_act' ? props.witchChoice : (props.actionChoice || null)
  })
}
</script>

<template>
  <Transition name="player-command-in">
    <section
      v-if="shouldShowPanel"
      class="player-command-panel"
      :class="{ 'has-panel-action': hasPanelAction, 'has-action-instruction': Boolean(actionInstruction) }"
    >
      <div class="player-skill-bar">
        <span class="player-seat-chip">
          <img v-if="humanPlayer" :src="roleImage(humanPlayer)" :alt="roleName" />
          <b>{{ humanPlayer ? label(humanPlayer) : '玩家' }}</b>
          <em>{{ roleName }}</em>
        </span>
        <div class="skill-card-stage">
          <div v-if="isHumanWitch" class="skill-card-row">
            <button
              class="skill-card image-card witch-antidote-card"
              :class="{ active: witchChoice === 'antidote', used: skillState.witch_antidote_used }"
              :disabled="loading || !canUseWitchAntidote"
              title="使用解药"
              aria-label="使用解药"
              @click="setWitchChoice('antidote')"
            ></button>
            <button
              class="skill-card image-card witch-poison-card"
              :class="{ active: witchChoice === 'poison', used: skillState.witch_poison_used }"
              :disabled="loading || !canUseWitchPoison"
              title="使用毒药"
              aria-label="使用毒药"
              @click="setWitchChoice('poison')"
            ></button>
            <button
              v-if="pendingActionType === 'witch_act'"
              class="skip-skill-link"
              :class="{ active: witchChoice === 'skip' }"
              :disabled="loading"
              @click="skipWitchAction"
            >
              跳过
            </button>
          </div>
          <button
            v-if="isHumanWhiteWolf && isWhiteWolfExplodePending"
            class="skill-card image-card white-wolf-card"
            :class="{ active: activeBurstArmed, used: skillState.white_wolf_burst_used }"
            :disabled="loading || !canWhiteWolfBurst"
            title="白狼王自爆"
            aria-label="白狼王自爆"
            @click="emit('update:burstArmed', !burstArmed)"
          ></button>
        </div>
        <div class="skill-status-side">
          <time v-if="waitingFor === 'speech'" class="speech-countdown">{{ speechCountdownText }}</time>
        </div>
      </div>

      <div v-if="actionInstruction" class="action-instruction">
        {{ actionInstruction }}
      </div>

      <div v-if="hasPanelAction" class="player-action-box" :class="{ 'has-choice': needsChoice, 'has-target': panelNeedsTarget }">
        <div v-if="needsChoice" class="choice-action-row">
          <button
            v-for="option in pendingChoiceOptions"
            :key="option.value"
            :class="{ active: actionChoice === option.value }"
            :disabled="loading"
            @click="setActionChoice(option.value)"
          >
            {{ option.label }}
          </button>
        </div>
        <div v-if="panelNeedsTarget" class="target-action-row">
          <div class="target-action-head">
            <span>目标</span>
            <b>{{ selectedTargetLabel || (targetOptions.length ? '未选择' : '暂无目标') }}</b>
          </div>
          <div class="target-choice-strip" role="listbox" aria-label="选择目标">
            <button
              v-for="player in targetOptions"
              :key="player.id"
              type="button"
              class="target-choice"
              :class="{ active: Number(actionTarget) === Number(player.id), dead: player.alive === false }"
              :disabled="loading"
              :aria-selected="Number(actionTarget) === Number(player.id)"
              role="option"
              @mouseenter="hoverTarget(player.id)"
              @mouseleave="hoverTarget(null)"
              @focus="hoverTarget(player.id)"
              @blur="hoverTarget(null)"
              @click="setActionTarget(player.id)"
            >
              <span>{{ targetLabel(player) }}</span>
            </button>
          </div>
        </div>
        <button class="primary action-submit" :disabled="!canSubmitPanelAction" @click="submitTargetAction">
          确认
        </button>
      </div>

      <form v-else-if="waitingFor === 'speech'" class="player-chat-box" @submit.prevent="emit('submit-speech')">
        <textarea
          :value="speech"
          :disabled="loading"
          placeholder="输入你的发言..."
          @input="emit('update:speech', $event.target.value)"
        ></textarea>
        <button class="primary" :disabled="loading || waitingFor !== 'speech'">发送</button>
      </form>

    </section>
  </Transition>

</template>
