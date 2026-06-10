import { defineStore } from 'pinia'
import { computed, ref } from 'vue'
import { choiceOptionsForAction, targetRequiredForAction } from '../domain/game/normalizers'
import type { Game } from '../types/game'

type LooseRecord = Record<string, unknown>
type IdValue = string | number
type NullableId = IdValue | null

const DEFAULT_SPEECH = '我先报一下自己的视角：目前重点听发言逻辑和票型。'

export interface GameRuntimeHydration {
  liveGame?: Game | null
  game?: Game | null
  loading?: boolean | null
  error?: string | null
  watchRunning?: boolean | null
  roleAssignmentComplete?: boolean | null
  judgeBoardStarted?: boolean | null
  judgeBoardStarting?: boolean | null
  promptText?: string | null
  judgeStripMessage?: LooseRecord[] | null
  playerIdentityList?: LooseRecord[] | null
  matchRecordLogs?: LooseRecord[] | null
  livingPlayers?: LooseRecord[] | null
  speakerCarousel?: LooseRecord[] | null
  speakerMessage?: string | null
  sceneVoteTally?: LooseRecord[] | null
  sceneEffects?: LooseRecord[] | null
  skipIntroGameId?: NullableId
  speechRemaining?: number | null
}

export const useGameStore = defineStore('game', () => {
  const liveGame = ref<Game | null>(null)
  const loading = ref(false)
  const error = ref('')
  const watchRunning = ref(false)
  const roleAssignmentComplete = ref(false)
  const judgeBoardStarted = ref(false)
  const judgeBoardStarting = ref(false)
  const promptText = ref('')
  const judgeStripMessage = ref<LooseRecord[]>([])
  const playerIdentityList = ref<LooseRecord[]>([])
  const matchRecordLogs = ref<LooseRecord[]>([])
  const livingPlayers = ref<LooseRecord[]>([])
  const speakerCarousel = ref<LooseRecord[]>([])
  const speakerMessage = ref('')
  const sceneVoteTally = ref<LooseRecord[]>([])
  const sceneEffects = ref<LooseRecord[]>([])
  const skipIntroGameId = ref<NullableId>(null)
  const chatLogExpanded = ref(false)
  const speech = ref(DEFAULT_SPEECH)
  const speechRemaining = ref(180)
  const witchChoice = ref('skip')
  const actionChoice = ref('')
  const burstArmed = ref(false)
  const actionTarget = ref<NullableId>(null)
  let lastPendingKey = ''

  const isNight = computed(() => liveGame.value?.phase === 'night')
  const isWatch = computed(() => liveGame.value?.mode === 'watch')
  const humanPlayer = computed<LooseRecord | null>(() => {
    const humanId = liveGame.value?.human_player_id
    if (humanId == null) return null
    return (liveGame.value?.players || []).find((player) => Number(player.id) === Number(humanId)) as LooseRecord || null
  })
  const roleName = computed(() => String(humanPlayer.value?.role_hint || (isWatch.value ? '观战者' : '未知身份')))
  const skillState = computed<LooseRecord>(() => liveGame.value?.skill_state as LooseRecord || {})
  const pendingAction = computed<LooseRecord>(() => liveGame.value?.pending_action as LooseRecord || { type: '', prompt: '', candidate_ids: [], options: {} })
  const pendingActionType = computed(() => String(pendingAction.value?.type || ''))
  const pendingChoiceOptions = computed(() => {
    const options = pendingAction.value?.options as LooseRecord | undefined
    return Array.isArray(options?.choices)
      ? options.choices
      : choiceOptionsForAction(pendingActionType.value, options || {})
  })
  const effectiveLivingPlayers = computed<LooseRecord[]>(() => (
    livingPlayers.value.length
      ? livingPlayers.value
      : (liveGame.value?.players || []).filter((player) => player.alive) as LooseRecord[]
  ))
  const canVotePlayers = computed(() => effectiveLivingPlayers.value.filter((player) => Number(player.id) !== Number(liveGame.value?.human_player_id)))
  const isHumanWitch = computed(() => roleName.value.includes('女巫'))
  const isHumanWhiteWolf = computed(() => roleName.value.includes('白狼王'))
  const canUseWitchAntidote = computed(() => (
    pendingActionType.value === 'witch_act'
    && !skillState.value.witch_antidote_used
    && (pendingAction.value.options as LooseRecord | undefined)?.antidote_available !== false
  ))
  const canUseWitchPoison = computed(() => (
    pendingActionType.value === 'witch_act'
    && !skillState.value.witch_poison_used
    && Boolean((pendingAction.value.options as LooseRecord | undefined)?.poison_available)
  ))
  const actionCandidates = computed(() => {
    const ids = new Set(Array.isArray(pendingAction.value?.candidate_ids) ? pendingAction.value.candidate_ids : [])
    return effectiveLivingPlayers.value.filter((player) => ids.has(player.id))
  })
  const whiteWolfTargets = computed(() => {
    if (
      pendingActionType.value !== 'white_wolf_explode'
      || !humanPlayer.value?.alive
      || !isHumanWhiteWolf.value
      || skillState.value.white_wolf_burst_used
    ) return []
    const ids = new Set(Array.isArray(pendingAction.value?.candidate_ids) ? pendingAction.value.candidate_ids : [])
    const candidates = ids.size
      ? effectiveLivingPlayers.value.filter((player) => ids.has(player.id))
      : effectiveLivingPlayers.value
    return candidates.filter((player) => Number(player.id) !== Number(liveGame.value?.human_player_id))
  })
  const canWhiteWolfBurst = computed(() => whiteWolfTargets.value.length > 0 && !isWatch.value)
  const needsTarget = computed(() => {
    if (pendingActionType.value === 'witch_act') return witchChoice.value === 'poison'
    const selectedChoiceOption = pendingChoiceOptions.value.find((option: LooseRecord) => option.value === actionChoice.value)
    if (selectedChoiceOption?.requiresTarget) return true
    if (pendingChoiceOptions.value.length) return false
    const options = pendingAction.value?.options as LooseRecord | undefined
    return targetRequiredForAction(pendingActionType.value, {
      ...(options || {}),
      target_required: pendingAction.value.target_required ?? options?.target_required,
      allow_no_target: pendingAction.value.allow_no_target ?? options?.allow_no_target
    })
  })
  const actionInstruction = computed(() => {
    if (pendingActionType.value === 'witch_act' && witchChoice.value === 'poison') return '法官提醒：点击一名玩家模型使用毒药。'
    if (pendingActionType.value === 'witch_act' && witchChoice.value === 'antidote') {
      const attacked = (pendingAction.value.options as LooseRecord | undefined)?.attacked_player
      return attacked ? `法官提醒：确认使用解药救 ${attacked} 号。` : '法官提醒：确认使用解药。'
    }
    if (pendingActionType.value === 'witch_act') return String(pendingAction.value.prompt || '女巫请选择是否发动技能。')
    if (pendingActionType.value === 'white_wolf_explode' && burstArmed.value) return '白狼王自爆已准备，点击要带走的玩家模型。'
    if (pendingChoiceOptions.value.length) return String(pendingAction.value.prompt || '请选择本轮行动。')
    if (pendingActionType.value) return String(pendingAction.value.prompt || '法官提醒：点击一名玩家模型选择目标。')
    if (liveGame.value?.waiting_for === 'vote') return '投票环节，点击你要投票的玩家模型。'
    return ''
  })
  const speechCountdownText = computed(() => {
    const value = Math.max(0, Number(speechRemaining.value) || 0)
    const minutes = String(Math.floor(value / 60)).padStart(1, '0')
    const seconds = String(value % 60).padStart(2, '0')
    return `${minutes}:${seconds}`
  })

  function setGame(game: Game | null): void {
    liveGame.value = game
    syncPendingControls(game)
  }

  function setLoading(isLoading: boolean): void {
    loading.value = isLoading
  }

  function setError(message: string | null): void {
    error.value = message ?? ''
  }

  function setWatchRunning(running: boolean): void {
    watchRunning.value = running
  }

  function clearGame(): void {
    liveGame.value = null
    lastPendingKey = ''
    watchRunning.value = false
    roleAssignmentComplete.value = false
    judgeBoardStarted.value = false
    judgeBoardStarting.value = false
    promptText.value = ''
    judgeStripMessage.value = []
    playerIdentityList.value = []
    matchRecordLogs.value = []
    livingPlayers.value = []
    speakerCarousel.value = []
    speakerMessage.value = ''
    sceneVoteTally.value = []
    sceneEffects.value = []
    skipIntroGameId.value = null
    chatLogExpanded.value = false
    speech.value = DEFAULT_SPEECH
    speechRemaining.value = 180
    witchChoice.value = 'skip'
    actionChoice.value = ''
    burstArmed.value = false
    actionTarget.value = null
  }

  function hydrateFromRuntime(runtime: GameRuntimeHydration): void {
    liveGame.value = runtime.liveGame ?? runtime.game ?? null
    loading.value = Boolean(runtime.loading)
    error.value = runtime.error ?? ''
    watchRunning.value = Boolean(runtime.watchRunning)
    roleAssignmentComplete.value = Boolean(runtime.roleAssignmentComplete)
    judgeBoardStarted.value = Boolean(runtime.judgeBoardStarted)
    judgeBoardStarting.value = Boolean(runtime.judgeBoardStarting)
    promptText.value = runtime.promptText ?? ''
    judgeStripMessage.value = runtime.judgeStripMessage ?? []
    playerIdentityList.value = runtime.playerIdentityList ?? []
    matchRecordLogs.value = runtime.matchRecordLogs ?? []
    livingPlayers.value = runtime.livingPlayers ?? []
    speakerCarousel.value = runtime.speakerCarousel ?? []
    speakerMessage.value = runtime.speakerMessage ?? ''
    sceneVoteTally.value = runtime.sceneVoteTally ?? []
    sceneEffects.value = runtime.sceneEffects ?? []
    skipIntroGameId.value = runtime.skipIntroGameId ?? null
    speechRemaining.value = Number(runtime.speechRemaining ?? 180)
    syncPendingControls(liveGame.value)
  }

  function setChatLogExpanded(expanded: boolean): void {
    chatLogExpanded.value = expanded
  }

  function setSpeech(value: string): void {
    speech.value = value
  }

  function setWitchChoice(value: string): void {
    witchChoice.value = value || 'skip'
  }

  function setActionChoice(value: string): void {
    actionChoice.value = value || ''
  }

  function setBurstArmed(armed: boolean): void {
    burstArmed.value = armed
  }

  function setActionTarget(value: NullableId): void {
    actionTarget.value = value == null || value === '' ? null : value
  }

  function pendingControlKey(game: Game | null): string {
    if (!game) return ''
    const pending = game.pending_human_action as LooseRecord | null | undefined
    const action = pending?.action_type || game.pending_action?.type || game.waiting_for || ''
    const candidates = Array.isArray(game.pending_action?.candidate_ids)
      ? game.pending_action.candidate_ids
      : (Array.isArray(pending?.candidates) ? pending.candidates : [])
    return `${action}:${game.day ?? ''}:${game.phase}:${pending?.retry_count ?? ''}:${candidates.join(',')}`
  }

  function syncPendingControls(game: Game | null): void {
    const key = pendingControlKey(game)
    if (key !== lastPendingKey) {
      actionTarget.value = null
      actionChoice.value = ''
      if (game?.pending_action?.type !== 'witch_act') witchChoice.value = 'skip'
      burstArmed.value = false
      lastPendingKey = key
    }

    const candidates = game?.pending_action?.candidate_ids || []
    if (
      candidates.length
      && actionTarget.value != null
      && !candidates.includes(Number(actionTarget.value))
    ) {
      actionTarget.value = null
    }
  }

  function selectScenePlayer(playerId: unknown): void {
    const id = Number(playerId)
    if (!id) return
    if (burstArmed.value && whiteWolfTargets.value.some((player) => Number(player.id) === id)) {
      actionTarget.value = id
      return
    }
    if (pendingActionType.value) {
      if (actionCandidates.value.some((player) => Number(player.id) === id)) actionTarget.value = id
      return
    }
    if (
      liveGame.value?.waiting_for === 'vote'
      && canVotePlayers.value.some((player) => Number(player.id) === id)
    ) {
      actionTarget.value = id
    }
  }

  return {
    liveGame,
    loading,
    error,
    watchRunning,
    roleAssignmentComplete,
    judgeBoardStarted,
    judgeBoardStarting,
    promptText,
    judgeStripMessage,
    playerIdentityList,
    matchRecordLogs,
    livingPlayers,
    speakerCarousel,
    speakerMessage,
    sceneVoteTally,
    sceneEffects,
    skipIntroGameId,
    chatLogExpanded,
    speech,
    speechRemaining,
    witchChoice,
    actionChoice,
    burstArmed,
    actionTarget,
    isNight,
    isWatch,
    humanPlayer,
    roleName,
    skillState,
    pendingActionType,
    pendingChoiceOptions,
    canVotePlayers,
    isHumanWitch,
    isHumanWhiteWolf,
    canUseWitchAntidote,
    canUseWitchPoison,
    actionCandidates,
    whiteWolfTargets,
    canWhiteWolfBurst,
    needsTarget,
    actionInstruction,
    speechCountdownText,
    setGame,
    setLoading,
    setError,
    setWatchRunning,
    clearGame,
    hydrateFromRuntime,
    setChatLogExpanded,
    setSpeech,
    setWitchChoice,
    setActionChoice,
    setBurstArmed,
    setActionTarget,
    syncPendingControls,
    selectScenePlayer
  }
})
