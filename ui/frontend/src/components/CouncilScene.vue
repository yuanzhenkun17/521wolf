<script setup>
import { computed, nextTick, onBeforeUnmount, onMounted, ref, watch } from 'vue'
import { createCouncilHallScene } from '../CouncilHallScene.js'
import { displayActionLabel } from './history/historyDisplay.js'

const SPEECH_EVENT_TYPES = new Set([
  'speech',
  'speak',
  'talk',
  'message',
  'chat',
  'statement',
  'discussion',
  'day_speech',
  'player_speech',
  'sheriff_run',
  'sheriff_speak',
  'sheriff_speech',
  'pk_speak',
  'pk_speech',
  'last_word'
])
const NON_PLAYER_LOG_TYPES = new Set(['system', 'judge', 'announcement', 'phase', 'phase_change'])
const NIGHT_ACTION_TYPES = new Set([
  'guard_result',
  'werewolf_result',
  'witch_result'
])

const props = defineProps({
  game: Object,
  isNight: Boolean,
  isWatch: Boolean,
  isReplayMode: Boolean,
  roleAssignmentComplete: Boolean,
  judgeBoardStarted: Boolean,
  players: { type: Array, default: () => [] },
  selectableIds: { type: Array, default: () => [] },
  selectedTargetId: [String, Number, null],
  hoveredTargetId: [String, Number, null],
  currentSpeakerId: [String, Number, null],
  voteTally: { type: Array, default: () => [] },
  sceneEffects: { type: Array, default: () => [] },
  speakerMessage: { type: String, default: '' }
})

const emit = defineEmits(['ready', 'container-ready', 'player-select', 'loading-progress'])
const containerRef = ref(null)
let scene = null
let rafId = 0
let sceneReadyPromise = null
let disposed = false
const sceneApi = { waitForCouncilModels, syncCouncilScene, scheduleSyncCouncilScene }

function normalizeSpeechText(value) {
  return String(value ?? '').trim()
}

function logTypeCandidates(log) {
  return [
    log?.type,
    log?.event_type,
    log?.action,
    log?.action_type,
    log?.kind,
    log?._chatKind,
    log?.phase,
    log?.event_phase,
    log?.stage
  ]
    .map((value) => String(value || '').trim())
    .filter(Boolean)
}

function normalizedLogType(log) {
  return logTypeCandidates(log)[0] || ''
}

function speechLogText(log) {
  return normalizeSpeechText(
    log?._message
    ?? log?.message
    ?? log?.content
    ?? log?.text
    ?? log?.public_summary
    ?? log?.public_text
    ?? log?.payload?.message
    ?? log?.payload?.text
    ?? ''
  )
}

function numericId(value) {
  const id = Number(value)
  return Number.isFinite(id) && id > 0 ? id : null
}

function logActorId(log) {
  const value = log?.actor_id
    ?? log?.actor
    ?? log?.player_id
    ?? log?.playerId
    ?? log?.speaker_id
    ?? log?.speakerId
    ?? log?.agent_id
    ?? log?.seat
    ?? log?._seat
  return numericId(value)
}

function logSpeakerName(log) {
  return String(log?._speaker || log?.speaker || log?.actor_name || log?.player_name || log?.name || '').trim()
}

function playerIdFromLog(log) {
  const actorId = logActorId(log)
  if (actorId) return actorId
  const name = logSpeakerName(log)
  if (!name) return null
  const player = props.players.find((item) => {
    const id = Number(item?.id)
    return String(item?.name || '').trim() === name
      || String(item?.displayName || '').trim() === name
      || String(item?.displaySeat || '').trim() === name
      || (Number.isFinite(id) && `${id}号` === name)
  })
  const id = Number(player?.id)
  return Number.isFinite(id) && id > 0 ? id : null
}

function logMatchesSpeaker(log, speakerId, speaker) {
  if (playerIdFromLog(log) === speakerId) return true
  const name = logSpeakerName(log)
  return Boolean(
    name
    && (
      String(speaker?.name || '') === name
      || String(speaker?.displayName || '') === name
      || String(speaker?.displaySeat || '') === name
      || `${speakerId}号` === name
    )
  )
}

function isPublicPlayerLog(log) {
  const type = normalizedLogType(log)
  return log?.visibility !== 'private' && !NON_PLAYER_LOG_TYPES.has(type)
}

function isSpeechLog(log) {
  return logTypeCandidates(log).some((type) => SPEECH_EVENT_TYPES.has(type))
}

function isNightActionLog(log) {
  const phase = String(log?.phase || log?.event_phase || log?.stage || '').trim()
  const type = normalizedLogType(log)
  return NIGHT_ACTION_TYPES.has(type)
    && (phase === 'night' || props.isNight)
}

function nightActionText(log) {
  const rawAction = normalizedLogType(log)
  const targetId = numericId(
    log?.target_id
    ?? log?.selected_target
    ?? log?.target
    ?? log?.payload?.target_id
    ?? log?.payload?.protected_target
    ?? log?.payload?.killed_target
    ?? log?.payload?.poisoned_target
  )
  const target = props.players.find((player) => Number(player?.id) === targetId)
  const targetSeat = target?.displaySeat ?? targetId
  if (rawAction === 'guard_result') return targetSeat ? `守护了${targetSeat}号` : '本夜未守护'
  if (rawAction === 'werewolf_result') return targetSeat ? `刀了${targetSeat}号` : '本夜未落刀'
  if (rawAction === 'witch_result') {
    const message = speechLogText(log)
    if (/解药|救/.test(message)) return targetSeat ? `救了${targetSeat}号` : '使用了解药'
    if (/毒/.test(message)) return targetSeat ? `毒了${targetSeat}号` : '使用了毒药'
    return '本夜未使用药剂'
  }
  return ''
}

function nightActionPlayerId(log) {
  const actorId = playerIdFromLog(log)
  if (actorId) return actorId
  if (normalizedLogType(log) === 'werewolf_result') {
    return numericId(props.players.find((player) => /狼/.test(String(player?.role_hint || '')))?.id)
  }
  return null
}

function nightActionsByPlayer(logs) {
  if (!props.isWatch || !props.isNight) return {}
  const currentDay = Number(props.game?.day)
  for (let index = logs.length - 1; index >= 0; index -= 1) {
    const log = logs[index]
    if (!isNightActionLog(log)) continue
    if (Number.isFinite(currentDay) && log?.day != null && Number(log.day) !== currentDay) continue
    const playerId = nightActionPlayerId(log)
    if (!playerId) continue
    const text = nightActionText(log)
    if (!text) continue
    const seat = props.players.find((player) => Number(player?.id) === playerId)?.displaySeat ?? playerId
    return {
      [playerId]: {
        text: `${seat}号：${text}`,
        tone: 'night'
      }
    }
  }
  return {}
}

function isPublicLog(log) {
  return log?.visibility !== 'private' && speechLogText(log)
}

function isSpeechWindow() {
  const phase = String(props.game?.phase || '').trim()
  const waitingFor = String(props.game?.waiting_for || '').trim()
  const pendingType = String(
    props.game?.pending_human_action?.action_type
    || props.game?.pending_human_action?.type
    || ''
  ).trim()
  return waitingFor === 'speech'
    || waitingFor === 'speak'
    || waitingFor === 'day_speech'
    || phase === 'speech'
    || phase === 'day_speech'
    || phase === 'discussion'
    || phase === 'sheriff'
    || phase === 'sheriff_speak'
    || phase === 'pk_speak'
    || phase === 'last_word'
    || SPEECH_EVENT_TYPES.has(pendingType)
}

function latestPublicLog(logs) {
  for (let index = logs.length - 1; index >= 0; index -= 1) {
    const log = logs[index]
    if (isPublicLog(log)) return log
  }
  return null
}

function speechPayload(log, speakerId = playerIdFromLog(log)) {
  const text = speechLogText(log)
  const seat = props.players.find((player) => Number(player?.id) === Number(speakerId))?.displaySeat ?? speakerId
  return {
    text: seat && text && !new RegExp(`^${seat}\\s*号?\\s*[：:]`).test(text)
      ? `${seat}号：${text}`
      : text,
    tone: props.isNight || log?.phase === 'night' ? 'night' : ''
  }
}

function fallbackSpeakerText(speakerId) {
  const speaker = props.players.find((player) => Number(player?.id) === speakerId)
  const label = speaker?.displaySeat ? `${speaker.displaySeat}号` : (speaker?.name || '当前玩家')
  return `${label}：正在发言...`
}

function pendingSpeakerId() {
  const pending = props.game?.pending_human_action
  if (!pending) return null
  const type = String(pending.action_type || pending.type || '').trim()
  if (!SPEECH_EVENT_TYPES.has(type)) return null
  return numericId(pending.player_id ?? pending.actor_id ?? pending.speaker_id ?? pending.seat)
}

function explicitCurrentSpeakerId() {
  return numericId(
    props.currentSpeakerId
    ?? props.game?.current_speaker_id
    ?? props.game?.currentSpeakerId
    ?? props.game?.speaker_id
    ?? props.game?.speakerId
  )
}

const speechByPlayer = computed(() => {
  const eventLogs = [...(props.game?.logs || []), ...(props.game?.events || [])]
  const logs = eventLogs.length ? eventLogs : (props.game?.decisions || [])
  const nightActions = nightActionsByPlayer(logs)
  if (Object.keys(nightActions).length) return nightActions
  const latestLog = latestPublicLog(logs)
  if (!isSpeechWindow() && !isSpeechLog(latestLog)) return {}

  const currentSpeakerId = explicitCurrentSpeakerId() || pendingSpeakerId()
  const hasCurrentSpeaker = Boolean(currentSpeakerId)
  const currentSpeaker = hasCurrentSpeaker
    ? props.players.find((player) => Number(player?.id) === currentSpeakerId)
    : null

  if (hasCurrentSpeaker) {
    for (let index = logs.length - 1; index >= 0; index -= 1) {
      const log = logs[index]
      if (!logMatchesSpeaker(log, currentSpeakerId, currentSpeaker) || !isPublicPlayerLog(log) || !isSpeechLog(log)) continue
      const payload = speechPayload(log, currentSpeakerId)
      if (!payload.text) continue
      return { [currentSpeakerId]: payload }
    }

    if (isSpeechWindow()) {
      const text = normalizeSpeechText(props.speakerMessage) || fallbackSpeakerText(currentSpeakerId)
      return {
        [currentSpeakerId]: {
          text,
          tone: props.isNight ? 'night' : ''
        }
      }
    }
  }

  if (props.isReplayMode) return {}

  for (let index = logs.length - 1; index >= 0; index -= 1) {
    const log = logs[index]
    if (!isPublicPlayerLog(log) || !isSpeechLog(log)) continue
    const speakerId = playerIdFromLog(log)
    if (!speakerId) continue
    const payload = speechPayload(log, speakerId)
    if (!payload.text) continue
    return { [speakerId]: payload }
  }
  return {}
})

const effectiveCurrentSpeakerId = computed(() => {
  const currentSpeakerId = explicitCurrentSpeakerId() || pendingSpeakerId()
  if (currentSpeakerId) return currentSpeakerId
  const [speakerId] = Object.keys(speechByPlayer.value)
  const id = Number(speakerId)
  return Number.isFinite(id) && id > 0 ? id : null
})

function handleLoadingProgress(progress) {
  emit('loading-progress', progress)
}

function publishContainer() {
  if (containerRef.value) {
    emit('ready', sceneApi)
    emit('container-ready', containerRef)
  }
}

async function ensureScene() {
  await nextTick()
  if (disposed || !containerRef.value) return null
  if (!scene && !sceneReadyPromise) {
    sceneReadyPromise = (async () => {
      if (disposed || !containerRef.value) return null
      if (!scene) {
        scene = createCouncilHallScene(containerRef.value)
        scene.setLoadProgressHandler?.(handleLoadingProgress)
      }
      return scene
    })().finally(() => {
      sceneReadyPromise = null
    })
  }
  if (sceneReadyPromise) await sceneReadyPromise
  if (disposed || !containerRef.value || !scene) return null
  containerRef.value.style.visibility = ''
  publishContainer()
  return scene
}

function scenePayload(revealPlayers = props.roleAssignmentComplete || props.isReplayMode) {
  return {
    players: props.players,
    currentSpeakerId: effectiveCurrentSpeakerId.value,
    speechByPlayer: speechByPlayer.value,
    isNight: props.isNight,
    revealPlayers,
    sceneKey: props.game?.game_id ?? props.game?.id ?? '',
    humanId: props.isWatch ? null : props.game?.human_player_id ?? null,
    selectableIds: props.selectableIds,
    selectedTargetId: props.selectedTargetId,
    hoveredTargetId: props.hoveredTargetId,
    onPlayerSelect: (id) => emit('player-select', id),
    pageVoteTally: props.voteTally,
    voteTally: props.voteTally,
    sceneEffects: props.sceneEffects,
    instantSpeech: props.isReplayMode,
    playInitialSceneEffects: props.isReplayMode
  }
}

function updateScene() {
  if (!scene) return
  scene.update?.(scenePayload())
}

function scheduleSyncCouncilScene() {
  if (rafId) cancelAnimationFrame(rafId)
  rafId = requestAnimationFrame(async () => {
    rafId = 0
    await ensureScene()
    updateScene()
  })
}

function syncCouncilScene() {
  updateScene()
}

async function waitForCouncilModels() {
  await ensureScene()
  scene?.update?.(scenePayload(true))
  const preload = scene?.preloadModels?.()
  if (preload) await preload
  updateScene()
}

onMounted(() => {
  ensureScene().then(updateScene)
})
watch(() => [props.players, props.currentSpeakerId, props.isNight, props.roleAssignmentComplete, props.isReplayMode, props.selectableIds, props.selectedTargetId, props.hoveredTargetId, props.voteTally, props.sceneEffects, props.speakerMessage, speechByPlayer.value, effectiveCurrentSpeakerId.value], scheduleSyncCouncilScene, { deep: true })

onBeforeUnmount(() => {
  disposed = true
  if (rafId) cancelAnimationFrame(rafId)
  scene?.setLoadProgressHandler?.(null)
  scene?.dispose?.()
  scene = null
})

defineExpose({ containerRef, waitForCouncilModels, syncCouncilScene, scheduleSyncCouncilScene })
</script>

<template>
  <div ref="containerRef" class="council-scene" aria-hidden="true"></div>
</template>
