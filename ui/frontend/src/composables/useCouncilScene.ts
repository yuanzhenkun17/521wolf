import { nextTick, onBeforeUnmount, onMounted, watch } from 'vue'
import { createCouncilHallScene } from '../CouncilHallScene.ts'

type LooseRecord = Record<string, any>
type CouncilSceneApi = {
  update?: (payload: LooseRecord) => void
  preloadModels?: () => Promise<unknown> | unknown
  dispose?: () => void
}

function useCouncilScene(state: LooseRecord, utils: LooseRecord = {}, options: LooseRecord = {}) {
  const containerRef = options.containerRef || state.gameSceneRef
  let councilScene: CouncilSceneApi | null = null
  let syncRafId = 0
  let syncScheduled = false
  let actionApi = { chooseScenePlayer: options.chooseScenePlayer }

  function setActionApi(api: LooseRecord = {}) {
    actionApi = { ...actionApi, ...(api || {}) }
  }

  function playerLabel(player: LooseRecord | null | undefined) {
    return typeof utils.playerLabel === 'function' ? utils.playerLabel(player) : `${player?.seat || player?.id || ''}号`
  }

  function normalizePlayerText(text = '') {
    return typeof utils.normalizePlayerText === 'function' ? utils.normalizePlayerText(text) : String(text || '')
  }

  function roleIconImage(player: LooseRecord | null | undefined) {
    if (typeof utils.roleIconImage === 'function') return utils.roleIconImage(player)
    const hint = player?.role_hint || ''
    if (hint.includes('预言')) return '/role-icons/optimized/预言家.webp'
    if (hint.includes('女巫')) return '/role-icons/optimized/女巫.webp'
    if (hint.includes('猎人')) return '/role-icons/optimized/猎人.webp'
    if (hint.includes('守卫')) return '/role-icons/optimized/守卫.webp'
    if (hint.includes('白狼王')) return '/role-icons/optimized/白狼王.webp'
    if (hint.includes('狼人')) return '/role-icons/optimized/普通狼.webp'
    return '/role-icons/optimized/平民.webp'
  }

  async function scrollChatToBottom() {
    await nextTick()
    if (state.chatListRef.value) {
      state.chatListRef.value.scrollTop = state.chatListRef.value.scrollHeight
    }
  }

  async function scrollJudgeToBottom() {
    await nextTick()
    if (state.judgeListRef.value) {
      state.judgeListRef.value.scrollTop = state.judgeListRef.value.scrollHeight
    }
  }

  async function scrollJudgeStripToBottom() {
    await nextTick()
    if (state.judgeStripRef.value) {
      state.judgeStripRef.value.scrollTop = state.judgeStripRef.value.scrollHeight
    }
  }

  async function mountCouncilScene() {
    await nextTick()
    if (!state.inMatch.value || !containerRef.value) return
    if (!councilScene) {
      councilScene = createCouncilHallScene(containerRef.value)
    }
    containerRef.value.style.visibility = ''
    syncCouncilScene()
  }

  async function waitForCouncilModels() {
    await nextTick()
    await mountCouncilScene()
    await nextTick()
    syncCouncilScene()
    await councilScene?.preloadModels?.()
  }

  function hideCouncilScene() {
    if (containerRef.value) {
      containerRef.value.style.visibility = 'hidden'
    }
  }

  function syncCouncilScene() {
    const speechByPlayer: Record<string | number, { text: string; tone: string }> = {}
    const players = state.game.value?.players ?? []
    const recentPlayerLogs = (state.game.value?.logs ?? []).filter((log) =>
      state.canSeeLog(log) &&
      log.visibility !== 'system' &&
      log.actor_id &&
      log.speaker && log.speaker !== '法官' && log.speaker !== '系统'
    )
    const latestPlayerLog = recentPlayerLogs.at(-1)
    if (latestPlayerLog?.actor_id) {
      const player = players.find((item) => item.id === latestPlayerLog.actor_id)
      if (player) {
        speechByPlayer[player.id] = {
          text: `${playerLabel(player)}：${normalizePlayerText(latestPlayerLog.message)}`,
          tone: latestPlayerLog.phase === 'night' || latestPlayerLog.visibility === 'private' ? 'night' : 'day'
        }
      }
    }

    let effectiveSpeakerId = state.game.value?.current_speaker_id ?? null
    if (latestPlayerLog?.actor_id) {
      effectiveSpeakerId = latestPlayerLog.actor_id
    }
    const voteTally = state.sceneVoteTally.value
    councilScene?.update?.({
      players: state.visualSeatPlayers.value.map((player: LooseRecord) => {
        const masked = !state.isWatch.value && !player.is_human
        return {
          ...player,
          roleIcon: roleIconImage(player),
          role_hint: masked ? '未知' : player.role_hint
        }
      }),
      currentSpeakerId: effectiveSpeakerId,
      speechByPlayer,
      isNight: state.isNight.value,
      revealPlayers: state.roleAssignmentComplete.value || state.isReplayMode.value,
      humanId: state.isWatch.value ? null : state.game.value?.human_player_id ?? null,
      selectableIds: state.pendingActionType.value
        ? state.actionCandidates.value.map((player: LooseRecord) => player.id)
        : (state.game.value?.waiting_for === 'vote'
            ? state.canVotePlayers.value.map((player: LooseRecord) => player.id)
            : (state.burstArmed.value ? state.whiteWolfTargets.value.map((player: LooseRecord) => player.id) : [])),
      onPlayerSelect: actionApi.chooseScenePlayer || (() => {}),
      pageVoteTally: voteTally,
      voteTally
    })
  }

  function scheduleSyncCouncilScene() {
    if (syncScheduled) return
    syncScheduled = true
    syncRafId = requestAnimationFrame(() => {
      syncScheduled = false
      syncCouncilScene()
    })
  }

  function disposeCouncilScene() {
    if (syncRafId) {
      cancelAnimationFrame(syncRafId)
      syncRafId = 0
    }
    syncScheduled = false
    councilScene?.dispose?.()
    councilScene = null
  }

  function getCouncilScene() {
    return councilScene
  }

  if (options.installLifecycle !== false) {
    watch(() => state.chatLogs.value.length, scrollChatToBottom)
    watch(() => state.judgeLogs.value.length, scrollJudgeToBottom)
    watch(() => state.judgeStripMessage.value.length, scrollJudgeStripToBottom)
    watch(() => state.game.value?.logs?.length, scrollJudgeStripToBottom)
    watch(() => state.game.value?.current_speaker_id, scrollChatToBottom)
    watch(() => [
      state.game.value?.players?.map((p: LooseRecord) => `${p.id}:${p.role_hint}:${p.alive}`).join('|'),
      state.game.value?.current_speaker_id,
      state.game.value?.logs?.length,
      state.judgeBoardStarted.value,
      state.roleAssignmentComplete.value,
      state.pendingActionType.value,
      state.actionCandidates.value.map((p: LooseRecord) => p.id).join('|'),
      state.game.value?.waiting_for,
      state.burstArmed.value,
      state.sceneVoteTally.value.map((row: LooseRecord) => `${row.target_id}:${row.count}:${row.voters?.join(',')}`).join('|')
    ], scheduleSyncCouncilScene)
    watch(state.inMatch, (match) => {
      if (match) mountCouncilScene()
      else hideCouncilScene()
    })

    onMounted(() => {
      scrollJudgeToBottom()
      if (state.inMatch.value) mountCouncilScene()
    })

    onBeforeUnmount(() => {
      disposeCouncilScene()
    })
  }

  return {
    setActionApi,
    getCouncilScene,
    scrollChatToBottom,
    scrollJudgeToBottom,
    scrollJudgeStripToBottom,
    mountCouncilScene,
    waitForCouncilModels,
    hideCouncilScene,
    syncCouncilScene,
    scheduleSyncCouncilScene,
    disposeCouncilScene
  }
}

export { useCouncilScene }
