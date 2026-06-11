<script setup lang="ts">
import { computed, nextTick, onBeforeUnmount, onMounted, ref, watch } from 'vue'
import type { PropType } from 'vue'
import { createCouncilHallScene } from '../CouncilHallScene.ts'
import { displayActionLabel } from './history/historyDisplay.ts'

type IdValue = string | number
type NullableId = IdValue | null

interface PlayerLike {
  id?: NullableId
  name?: string | null
  displayName?: string | null
  displaySeat?: string | number | null
  role_hint?: string | null
  roleIcon?: string | null
  isSheriff?: boolean | null
  speaking?: boolean | null
  alive?: boolean | null
  [key: string]: unknown
}

interface LogPayload {
  message?: unknown
  text?: unknown
  target_id?: unknown
  protected_target?: unknown
  killed_target?: unknown
  poisoned_target?: unknown
  [key: string]: unknown
}

interface LogEntry {
  type?: unknown
  event_type?: unknown
  action?: unknown
  action_type?: unknown
  kind?: unknown
  _chatKind?: unknown
  phase?: unknown
  event_phase?: unknown
  stage?: unknown
  _message?: unknown
  message?: unknown
  content?: unknown
  text?: unknown
  public_summary?: unknown
  public_text?: unknown
  payload?: LogPayload | null
  actor_id?: unknown
  actor?: unknown
  player_id?: unknown
  playerId?: unknown
  speaker_id?: unknown
  speakerId?: unknown
  agent_id?: unknown
  seat?: unknown
  _seat?: unknown
  _speaker?: unknown
  speaker?: unknown
  actor_name?: unknown
  player_name?: unknown
  name?: unknown
  visibility?: unknown
  day?: unknown
  target_id?: unknown
  selected_target?: unknown
  target?: unknown
  [key: string]: unknown
}

interface PendingHumanAction {
  action_type?: unknown
  type?: unknown
  player_id?: unknown
  actor_id?: unknown
  speaker_id?: unknown
  seat?: unknown
  [key: string]: unknown
}

interface GameLike {
  day?: unknown
  phase?: unknown
  waiting_for?: unknown
  pending_human_action?: PendingHumanAction | null
  current_speaker_id?: unknown
  currentSpeakerId?: unknown
  speaker_id?: unknown
  speakerId?: unknown
  logs?: LogEntry[]
  events?: LogEntry[]
  decisions?: LogEntry[]
  game_id?: unknown
  id?: unknown
  human_player_id?: unknown
  [key: string]: unknown
}

interface SpeechPayload {
  text: string
  tone: string
  thinking?: boolean
}

type SpeechByPlayer = Record<string | number, string | SpeechPayload>

interface VoteTallyRow {
  target_id?: unknown
  targetId?: unknown
  count?: unknown
  voter_ids?: unknown[]
  voters?: unknown[]
  voter_labels?: unknown[]
  [key: string]: unknown
}

interface SceneEffect {
  id?: unknown
  type?: unknown
  actorId?: unknown
  targetId?: unknown
  day?: unknown
  sequence?: unknown
  [key: string]: unknown
}

interface LoadProgress {
  phase?: string
  label?: string
  loaded?: number
  total?: number
  progress?: number
  ready?: boolean
  [key: string]: unknown
}

interface ScenePayload {
  players: PlayerLike[]
  currentSpeakerId: number | null
  speechByPlayer: SpeechByPlayer
  isNight: boolean
  revealPlayers: boolean
  sceneKey: unknown
  humanId: unknown
  selectableIds: NullableId[]
  selectedTargetId?: NullableId
  hoveredTargetId?: NullableId
  onPlayerSelect: (id: IdValue) => void
  pageVoteTally: VoteTallyRow[]
  voteTally: VoteTallyRow[]
  sceneEffects: SceneEffect[]
  instantSpeech: boolean
  playInitialSceneEffects: boolean
  deferModelLoading: boolean
}

interface CouncilHallScene {
  setLoadProgressHandler?: (handler: ((progress: LoadProgress) => void) | null) => void
  update?: (payload: ScenePayload) => void
  preloadModels?: () => Promise<unknown> | unknown
  dispose?: () => void
}

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
  'seer_result',
  'witch_result'
])
const NIGHT_ACTION_REQUEST_TYPES = new Set(['guard_protect', 'werewolf_kill', 'seer_check', 'witch_act'])
const SPEECH_PROMPT_TYPE = 'speech_prompt'
const BUBBLE_ACTION_TYPES = new Set([
  ...SPEECH_EVENT_TYPES,
  ...NIGHT_ACTION_REQUEST_TYPES,
  'sheriff_run',
  'sheriff_withdraw',
  'speech_order',
  'hunter_shoot',
  'white_wolf_explode'
])

const props = defineProps({
  game: Object as PropType<GameLike | null>,
  isNight: Boolean,
  isWatch: Boolean,
  isReplayMode: Boolean,
  roleAssignmentComplete: Boolean,
  judgeBoardStarted: Boolean,
  players: { type: Array as PropType<PlayerLike[]>, default: () => [] },
  selectableIds: { type: Array as PropType<NullableId[]>, default: () => [] },
  selectedTargetId: [String, Number, null] as PropType<NullableId>,
  hoveredTargetId: [String, Number, null] as PropType<NullableId>,
  currentSpeakerId: [String, Number, null] as PropType<NullableId>,
  voteTally: { type: Array as PropType<VoteTallyRow[]>, default: () => [] },
  sceneEffects: { type: Array as PropType<SceneEffect[]>, default: () => [] },
  speakerMessage: { type: String, default: '' },
  deferModelLoading: Boolean
})

const emit = defineEmits(['ready', 'container-ready', 'player-select', 'loading-progress'])
const containerRef = ref<HTMLDivElement | null>(null)
let scene: CouncilHallScene | null = null
let rafId = 0
let sceneReadyPromise: Promise<CouncilHallScene | null> | null = null
let disposed = false
let lastSceneSignature = ''
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

function latestActiveSpeechPrompt(logs) {
  for (let index = logs.length - 1; index >= 0; index -= 1) {
    const log = logs[index]
    if (log?.visibility === 'private') continue
    if (normalizedLogType(log) === SPEECH_PROMPT_TYPE) return log
    if (isSpeechLog(log)) return null
  }
  return null
}

function isNightActionLog(log) {
  const phase = String(log?.phase || log?.event_phase || log?.stage || '').trim()
  const type = normalizedLogType(log)
  return NIGHT_ACTION_TYPES.has(type)
    && (phase === 'night' || props.isNight)
}

function isNightActionRequest(log) {
  const phase = String(log?.phase || log?.event_phase || log?.stage || '').trim()
  const actionType = String(log?.payload?.action_type || '').trim()
  return normalizedLogType(log) === 'action_request'
    && NIGHT_ACTION_REQUEST_TYPES.has(actionType)
    && (phase === 'night' || props.isNight)
}

function latestNightVisualEvent(logs) {
  if (!props.isWatch || !props.isNight) return null
  const currentDay = Number(props.game?.day)
  for (let index = logs.length - 1; index >= 0; index -= 1) {
    const log = logs[index]
    if (!isNightActionLog(log) && !isNightActionRequest(log)) continue
    if (Number.isFinite(currentDay) && log?.day != null && Number(log.day) !== currentDay) continue
    return log
  }
  return null
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
  const latestLog = latestNightVisualEvent(logs)
  if (!latestLog) return {}
  const latestPlayerId = nightActionPlayerId(latestLog)
  if (!latestPlayerId) return {}
  if (isNightActionRequest(latestLog)) {
    return {
      [latestPlayerId]: {
        text: '...',
        tone: 'night',
        thinking: true
      }
    }
  }
  const latestText = nightActionText(latestLog)
  if (!latestText) return {}
  const latestSeat = props.players.find((player) => Number(player?.id) === latestPlayerId)?.displaySeat ?? latestPlayerId
  return {
    [latestPlayerId]: {
      text: `${latestSeat}号：${latestText}`,
      tone: 'night'
    }
  }
}

function requestedActionType(log) {
  if (normalizedLogType(log) === SPEECH_PROMPT_TYPE) {
    return String(log?.payload?.action_type || '').trim()
  }
  if (normalizedLogType(log) !== 'action_request') return ''
  return String(log?.payload?.action_type || '').trim()
}

function canShowActionRequest(log) {
  const actionType = requestedActionType(log)
  if (!BUBBLE_ACTION_TYPES.has(actionType)) return false
  return props.isWatch || log?.visibility !== 'private' || normalizedLogType(log) === SPEECH_PROMPT_TYPE
}

function actionResultText(log, actionType) {
  const directText = normalizeSpeechText(
    log?.payload?.text
    ?? log?.text
    ?? log?.content
    ?? log?.public_summary
    ?? log?.public_text
    ?? log?.message
    ?? ''
  )
  if (directText) return directText

  const targetId = numericId(log?.target_id ?? log?.target ?? log?.payload?.target_id)
  const targetSeat = props.players.find((player) => Number(player?.id) === targetId)?.displaySeat ?? targetId
  const choice = String(log?.payload?.choice || log?.choice || '').trim()
  if (actionType === 'guard_protect') return targetSeat ? `守护了${targetSeat}号` : '选择本夜不守护'
  if (actionType === 'werewolf_kill') return targetSeat ? `选择袭击${targetSeat}号` : '选择本夜不袭击'
  if (actionType === 'seer_check') return targetSeat ? `查验了${targetSeat}号` : ''
  if (actionType === 'witch_act') {
    if (choice === 'save') return targetSeat ? `使用解药救了${targetSeat}号` : '使用了解药'
    if (choice === 'poison') return targetSeat ? `使用毒药毒了${targetSeat}号` : '使用了毒药'
    return '选择本夜不使用药剂'
  }
  return ''
}

function actionResultForRequest(logs, requestIndex, request) {
  const actionType = requestedActionType(request)
  const actorId = playerIdFromLog(request)
  if (!actionType || !actorId) return null

  for (let index = requestIndex + 1; index < logs.length; index += 1) {
    const log = logs[index]
    const type = normalizedLogType(log)
    const logActionType = String(log?.payload?.action_type || '').trim()
    if (canShowActionRequest(log)) break
    if (playerIdFromLog(log) !== actorId) continue
    if (type !== actionType && !(type === 'action_response' && logActionType === actionType)) continue
    const text = actionResultText(log, actionType)
    if (text) return { log, text }
  }
  return null
}

function latestActionBubble(logs) {
  for (let index = logs.length - 1; index >= 0; index -= 1) {
    const request = logs[index]
    if (!canShowActionRequest(request)) continue
    const playerId = playerIdFromLog(request)
    if (!playerId) continue
    const result = actionResultForRequest(logs, index, request)
    if (!result) {
      return {
        [playerId]: {
          text: '...',
          tone: props.isNight ? 'night' : '',
          thinking: true
        }
      }
    }
    return {
      [playerId]: speechPayload({ ...result.log, message: result.text }, playerId)
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

function isVotePhase() {
  const phase = String(props.game?.phase || '').trim()
  const waitingFor = String(props.game?.waiting_for || '').trim()
  const pendingType = String(
    props.game?.pending_human_action?.action_type
    || props.game?.pending_human_action?.type
    || ''
  ).trim()
  return waitingFor === 'vote'
    || ['vote', 'exile_vote', 'pk_vote', 'sheriff_vote'].includes(phase)
    || ['exile_vote', 'pk_vote', 'sheriff_vote'].includes(pendingType)
}

const rawSpeechByPlayer = computed(() => {
  if (isVotePhase()) return {}
  const eventLogs = [...(props.game?.logs || []), ...(props.game?.events || [])]
  const logs = eventLogs.length ? eventLogs : (props.game?.decisions || [])
  const actionBubble = latestActionBubble(logs)
  if (Object.keys(actionBubble).length) return actionBubble
  const nightActions = nightActionsByPlayer(logs)
  if (Object.keys(nightActions).length) return nightActions
  const latestLog = latestPublicLog(logs)
  if (!isSpeechWindow() && !isSpeechLog(latestLog)) return {}

  const prompt = latestActiveSpeechPrompt(logs)
  const promptSpeakerId = playerIdFromLog(prompt)
  const currentSpeakerId = promptSpeakerId || explicitCurrentSpeakerId() || pendingSpeakerId()
  const hasCurrentSpeaker = Boolean(currentSpeakerId)
  const currentSpeaker = hasCurrentSpeaker
    ? props.players.find((player) => Number(player?.id) === currentSpeakerId)
    : null

  if (hasCurrentSpeaker) {
    if (promptSpeakerId === currentSpeakerId) {
      return {
        [currentSpeakerId]: {
          text: '...',
          tone: props.isNight ? 'night' : '',
          thinking: true
        }
      }
    }
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

const speechByPlayer = ref<SpeechByPlayer>({})
let speechPresentationTimer: ReturnType<typeof setTimeout> | null = null
const pendingSpeechPresentations: SpeechByPlayer[] = []

function speechPresentationSignature(value: SpeechByPlayer = {}) {
  return Object.entries(value)
    .sort(([a], [b]) => Number(a) - Number(b))
    .map(([id, speech]) => {
      const text = typeof speech === 'string' ? speech : speech?.text
      const tone = typeof speech === 'string' ? '' : speech?.tone
      const thinking = typeof speech === 'string' ? false : speech?.thinking
      return `${id}:${tone || ''}:${thinking ? 1 : 0}:${text || ''}`
    })
    .join('|')
}

function presentationIsThinking(value: SpeechByPlayer = {}) {
  return Object.values(value).some((speech) => typeof speech !== 'string' && speech?.thinking)
}

function presentationText(value: SpeechByPlayer = {}) {
  const speech = Object.values(value)[0]
  return typeof speech === 'string' ? speech : String(speech?.text || '')
}

function resultDisplayDuration(value: SpeechByPlayer = {}) {
  const text = presentationText(value)
  const punctuationCount = Array.from(text).filter((char) => '，。？！；、,.?!;:'.includes(char)).length
  return Math.min(18000, 180 + Array.from(text).length * 86 + punctuationCount * 124 + 2000)
}

function clearSpeechPresentationTimer() {
  if (!speechPresentationTimer) return
  clearTimeout(speechPresentationTimer)
  speechPresentationTimer = null
}

function presentNextSpeechBubble() {
  clearSpeechPresentationTimer()
  const next = pendingSpeechPresentations.shift()
  if (!next) return
  speechByPlayer.value = next
  if (!presentationIsThinking(next) && pendingSpeechPresentations.length) {
    speechPresentationTimer = setTimeout(presentNextSpeechBubble, resultDisplayDuration(next))
  } else if (presentationIsThinking(next) && pendingSpeechPresentations.length) {
    speechPresentationTimer = setTimeout(presentNextSpeechBubble, 450)
  }
}

watch(rawSpeechByPlayer, (next) => {
  if (isVotePhase()) {
    clearSpeechPresentationTimer()
    pendingSpeechPresentations.length = 0
    speechByPlayer.value = {}
    return
  }
  const nextSignature = speechPresentationSignature(next)
  const currentSignature = speechPresentationSignature(speechByPlayer.value)
  if (nextSignature === currentSignature) return

  const queuedSignature = speechPresentationSignature(pendingSpeechPresentations.at(-1) || {})
  if (nextSignature === queuedSignature) return

  const currentIsThinking = presentationIsThinking(speechByPlayer.value)
  const nextIsThinking = presentationIsThinking(next)
  if (!currentSignature || (currentIsThinking && !nextIsThinking)) {
    clearSpeechPresentationTimer()
    speechByPlayer.value = next
    if (!nextIsThinking && pendingSpeechPresentations.length) {
      speechPresentationTimer = setTimeout(presentNextSpeechBubble, resultDisplayDuration(next))
    }
    return
  }

  pendingSpeechPresentations.push(next)
  if (!speechPresentationTimer) {
    speechPresentationTimer = setTimeout(
      presentNextSpeechBubble,
      currentIsThinking ? 450 : resultDisplayDuration(speechByPlayer.value)
    )
  }
}, { immediate: true, deep: true })

watch(() => [
  props.game?.phase,
  props.game?.waiting_for,
  props.game?.pending_human_action?.action_type,
  props.game?.pending_human_action?.type
], () => {
  if (!isVotePhase()) return
  clearSpeechPresentationTimer()
  pendingSpeechPresentations.length = 0
  speechByPlayer.value = {}
})

const effectiveCurrentSpeakerId = computed(() => {
  if (isVotePhase()) return null
  const logs = [...(props.game?.logs || []), ...(props.game?.events || [])]
  const currentSpeakerId = playerIdFromLog(latestActiveSpeechPrompt(logs)) || explicitCurrentSpeakerId() || pendingSpeakerId()
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
        scene = createCouncilHallScene(containerRef.value) as CouncilHallScene
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
    sceneEffects: [],
    instantSpeech: props.isReplayMode,
    playInitialSceneEffects: props.isReplayMode,
    deferModelLoading: props.deferModelLoading
  }
}

function valueListSignature(value) {
  return Array.isArray(value) ? value.map((item) => String(item ?? '')).join(',') : ''
}

function playerSceneSignature(players = []) {
  return players.map((player, index) => [
    player?.id ?? index,
    player?.alive === false ? 0 : 1,
    player?.role_hint ?? '',
    player?.roleIcon ?? '',
    player?.displaySeat ?? '',
    player?.isSheriff ? 1 : 0,
    player?.speaking ? 1 : 0
  ].join(':')).join('|')
}

function speechSceneSignature(value: SpeechByPlayer = {}) {
  return Object.entries(value)
    .sort(([a], [b]) => Number(a) - Number(b))
    .map(([id, speech]) => {
      const text = typeof speech === 'string' ? speech : speech?.text
      const tone = typeof speech === 'string' ? '' : speech?.tone
      const thinking = typeof speech === 'string' ? false : speech?.thinking
      return `${id}:${tone || ''}:${thinking ? 1 : 0}:${text || ''}`
    })
    .join('|')
}

function voteSceneSignature(rows = []) {
  return rows.map((row) => [
    row?.target_id ?? row?.targetId ?? '',
    row?.count ?? '',
    valueListSignature(row?.voter_ids),
    valueListSignature(row?.voters),
    valueListSignature(row?.voter_labels)
  ].join(':')).join('|')
}

function effectSceneSignature(effects = []) {
  return effects.map((effect) => [
    effect?.id ?? '',
    effect?.type ?? '',
    effect?.actorId ?? '',
    effect?.targetId ?? '',
    effect?.day ?? '',
    effect?.sequence ?? ''
  ].join(':')).join('|')
}

function buildSceneSignature(revealPlayers = props.roleAssignmentComplete || props.isReplayMode) {
  return [
    props.game?.game_id ?? props.game?.id ?? '',
    props.isNight ? 1 : 0,
    props.isWatch ? 1 : 0,
    props.isReplayMode ? 1 : 0,
    revealPlayers ? 1 : 0,
    props.isWatch ? '' : props.game?.human_player_id ?? '',
    effectiveCurrentSpeakerId.value ?? '',
    valueListSignature(props.selectableIds),
    props.selectedTargetId ?? '',
    props.hoveredTargetId ?? '',
    playerSceneSignature(props.players),
    speechSceneSignature(speechByPlayer.value),
    voteSceneSignature(props.voteTally),
    '',
    props.deferModelLoading ? 1 : 0
  ].join('||')
}

function updateScene({ force = false, revealPlayers = props.roleAssignmentComplete || props.isReplayMode } = {}) {
  if (!scene) return
  const signature = buildSceneSignature(revealPlayers)
  if (!force && signature === lastSceneSignature) return
  lastSceneSignature = signature
  scene.update?.(scenePayload(revealPlayers))
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
  updateScene({ force: true, revealPlayers: true })
  const preload = scene?.preloadModels?.()
  if (preload) await preload
  updateScene({ force: true })
}

onMounted(() => {
  ensureScene().then(() => updateScene())
})
watch(() => [props.players, props.currentSpeakerId, props.isNight, props.roleAssignmentComplete, props.isReplayMode, props.selectableIds, props.selectedTargetId, props.hoveredTargetId, props.voteTally, props.sceneEffects, props.speakerMessage, props.deferModelLoading, speechByPlayer.value, effectiveCurrentSpeakerId.value], scheduleSyncCouncilScene)

onBeforeUnmount(() => {
  disposed = true
  lastSceneSignature = ''
  clearSpeechPresentationTimer()
  pendingSpeechPresentations.length = 0
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
