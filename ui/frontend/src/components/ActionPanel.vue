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
  'submit-speech',
  'submit-action'
])

const waitingFor = computed(() => props.game?.waiting_for || '')
const targetOptions = computed(() => (props.burstArmed ? props.whiteWolfTargets : props.actionCandidates))
const hasPanelAction = computed(() => Boolean(props.pendingActionType || props.burstArmed))
const needsChoice = computed(() => props.pendingChoiceOptions.length > 0 && props.pendingActionType !== 'witch_act')
const panelNeedsTarget = computed(() => props.burstArmed || props.needsTarget)
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

function skipWitchAction() {
  emit('update:witchChoice', 'skip')
  emit('update:actionTarget', null)
  emit('submit-action', { action: 'witch_act', targetId: null, choice: 'skip' })
}

function submitTargetAction() {
  if (props.burstArmed) {
    emit('submit-action', { action: 'white_wolf_burst', targetId: props.actionTarget, choice: 'burst' })
    return
  }
  emit('submit-action', {
    action: props.pendingActionType,
    targetId: props.actionTarget,
    choice: props.actionChoice || props.witchChoice
  })
}
</script>

<template>
  <Transition name="player-command-in">
    <section v-if="roleAssignmentComplete && !isWatch && !isReplayMode" class="player-command-panel">
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
            v-if="isHumanWhiteWolf"
            class="skill-card image-card white-wolf-card"
            :class="{ active: burstArmed, used: skillState.white_wolf_burst_used }"
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

      <div v-if="hasPanelAction" class="player-action-box">
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
          <select :value="actionTarget ?? ''" :disabled="loading || !targetOptions.length" @change="setActionTarget($event.target.value)">
            <option value="">{{ targetOptions.length ? '选择目标' : '暂无目标' }}</option>
            <option v-for="player in targetOptions" :key="player.id" :value="player.id">
              {{ label(player) }}
            </option>
          </select>
        </div>
        <button class="primary action-submit" :disabled="!canSubmitPanelAction" @click="submitTargetAction">
          确认
        </button>
      </div>

      <form v-else class="player-chat-box" @submit.prevent="emit('submit-speech')">
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
