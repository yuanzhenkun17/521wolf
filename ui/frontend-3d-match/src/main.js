import { createApp, computed, nextTick, onBeforeUnmount, onMounted, ref, watch } from 'vue/dist/vue.esm-bundler.js'
import './style.css'
import { createCouncilHallScene } from './CouncilHallScene.js'

const API = import.meta.env.VITE_API_BASE || 'http://127.0.0.1:8000/api'

const phaseText = {
  lobby: 'LOBBY',
  setup: 'SETUP',
  night: 'NIGHT {day}',
  sheriff: 'DAY {day} · SHERIFF',
  sheriff_result: 'DAY {day} · SHERIFF RESULT',
  speech: 'DAY {day} · SPEECH',
  vote: 'DAY {day} · VOTE',
  result: 'DAY {day} · RESULT',
  ended: 'GAME OVER'
}

const phaseLabel = {
  lobby: '选择模式',
  setup: '开局配置',
  night: '黑夜行动',
  sheriff: '警长竞选',
  sheriff_result: '警长结果',
  speech: '白天发言',
  vote: '公投放逐',
  result: '结算',
  ended: '终局'
}

const roleIconSpecs = [
  { key: 'whiteWolfKing', role: '白狼王', tokens: ['白狼王'], image: '/role-crops/white-wolf-king.png' },
  { key: 'werewolf', role: '狼人', tokens: ['狼人'], image: '/role-crops/werewolf.png' },
  { key: 'villager', role: '村民', tokens: ['村民'], image: '/role-crops/villager.png' },
  { key: 'seer', role: '预言家', tokens: ['预言'], image: '/role-crops/seer.png' },
  { key: 'witch', role: '女巫', tokens: ['女巫'], image: '/role-crops/witch.png' },
  { key: 'hunter', role: '猎人', tokens: ['猎人'], image: '/role-crops/hunter.png' },
  { key: 'guard', role: '守卫', tokens: ['守卫'], image: '/role-crops/guard.png' }
]

function roleMatches(role = '', tokens = []) {
  return tokens.some((token) => role.includes(token))
}

createApp({
  setup() {
    const game = ref(null)
    const loading = ref(false)
    const error = ref('')
    const speech = ref('我先报一下自己的视角：目前重点听发言逻辑和票型。')
    const speechRemaining = ref(180)
    const voteTarget = ref(1)
    const actionTarget = ref(null)
    const witchChoice = ref('skip')
    const burstArmed = ref(false)
    const playerCount = ref(12)
    const watchRunning = ref(false)
    const backendMode = ref('mock')
    const externalStatus = ref(null)
    const archiveByGameId = ref({})
    const reviewByGameId = ref({})
    const archiveLoading = ref(false)
    const reviewLoading = ref(false)
    const judgeBoardStarted = ref(false)
    const judgeBoardStarting = ref(false)
    const roleAssignmentComplete = ref(false)
    const roleAssignmentCompleteNotice = ref(false)
    const initialHash = window.location.hash
    const currentView = ref(initialHash === '#logs' ? 'logs' : 'lobby')
    const gameHistory = ref([])
    const selectedHistoryGameId = ref(null)
    const selectedHistoryGame = ref(null)
    const historyLoading = ref(false)
    const historyPhase = ref('all')
    const selectedHistoryPageKey = ref('')
    const isReplayMode = ref(false)
    const replaySourceGameId = ref(null)
    const replayPageKey = ref('')
    const lastLiveGame = ref(null)
    const visualSeatSalt = ref(Math.random().toString(36).slice(2))
    const chatLogExpanded = ref(false)
    const chatListRef = ref(null)
    const judgeListRef = ref(null)
    const judgeStripRef = ref(null)
    const gameSceneRef = ref(null)
    let timer = null
    let speechTimer = null
    let eventSource = null
    let councilScene = null

    const isNight = computed(() => game.value?.phase === 'night')
    const inLogs = computed(() => currentView.value === 'logs')
    const inLobby = computed(() => currentView.value === 'lobby' || (!game.value && !inLogs.value))
    const inMatch = computed(() => currentView.value === 'match' && Boolean(game.value))
    const isWatch = computed(() => game.value?.mode === 'watch')
    const humanPlayer = computed(() => game.value?.players?.find((p) => p.id === game.value.human_player_id))
    const livingPlayers = computed(() => game.value?.players?.filter((p) => p.alive) ?? [])
    const canVotePlayers = computed(() => livingPlayers.value.filter((p) => p.id !== game.value?.human_player_id))
    function canSeeLog(log) {
      return log.visibility !== 'private' && (log.visibility !== 'god' || isWatch.value)
    }
    const publicLogs = computed(() => (game.value?.logs ?? []).filter(canSeeLog).slice(-10))
    const judgeVisibleTypes = new Set([
      'action_prompt',
      'guard_protect',
      'werewolf_kill',
      'seer_check',
      'witch_act',
      'hunter_shoot',
      'white_wolf_explode',
      'sheriff_run',
      'sheriff_pass',
      'sheriff_withdraw',
      'sheriff_stay',
      'sheriff_vote',
      'exile_vote',
      'pk_vote',
      'sheriff_badge'
    ])
    const chatLogs = computed(() =>
      (game.value?.logs ?? [])
        .filter((log) => canSeeLog(log) && !['法官', '系统', '狼人团队'].includes(log.speaker))
        .slice(-80)
    )
    const judgeLogs = computed(() =>
      (game.value?.logs ?? [])
        .filter((log) =>
          log.visibility === 'system'
          || (canSeeLog(log) && ['法官', '系统', '狼人团队'].includes(log.speaker))
          || (canSeeLog(log) && judgeVisibleTypes.has(log.type))
          || (isWatch.value && log.phase === 'night' && log.visibility !== 'private')
        )
        .slice(-80)
    )
    const groupedJudgeLogs = computed(() => {
      const groups = []
      let currentGroup = null

      judgeLogs.value.forEach((log) => {
        const day = log.day || 0
        const phase = log.phase || 'unknown'
        const groupKey = `${day}-${phase}`

        if (!currentGroup || currentGroup.key !== groupKey) {
          currentGroup = {
            key: groupKey,
            day: day,
            phase: phase,
            phaseLabel: phaseText[phase] || phase,
            logs: []
          }
          groups.push(currentGroup)
        }
        currentGroup.logs.push(log)
      })

      return groups.slice(-10) // 只显示最近10个分组
    })
    const speakingPlayer = computed(() => {
      if (!game.value?.current_speaker_id) return null
      return game.value.players.find((p) => p.id === game.value.current_speaker_id)
    })
    const displayPhase = computed(() => {
      if (!game.value) return 'LOBBY'
      return (phaseText[game.value.phase] || '').replace('{day}', game.value.day)
    })
    const visualSeatById = computed(() => new Map(visualSeatPlayers.value.map((player, index) => [player.id, index + 1])))
    function playerNumber(player) {
      if (!player) return ''
      return visualSeatById.value.get(player.id) || player.seat || player.id
    }
    function playerNumberById(id) {
      const player = game.value?.players?.find((item) => item.id === id)
      return player ? playerNumber(player) : id
    }
    function playerLabel(player) {
      const number = playerNumber(player)
      return number ? `${number}号` : ''
    }
    function normalizePlayerText(text = '') {
      let value = String(text || '')
      const players = [...(game.value?.players ?? [])].sort((a, b) => String(b.name || '').length - String(a.name || '').length)
      for (const player of players) {
        const visual = playerLabel(player)
        if (!visual) continue
        const escapedName = String(player.name || '').replace(/[.*+?^${}()|[\]\\]/g, '\\$&')
        const realSeat = `${player.seat}号`
        value = value.replaceAll(`${realSeat} ${player.name}`, visual)
        value = value.replaceAll(`${realSeat}${player.name}`, visual)
        if (escapedName) value = value.replace(new RegExp(escapedName, 'g'), visual)
        value = value.replace(new RegExp(`${player.seat}\\s*号`, 'g'), visual)
      }
      return value
    }
    function logSpeaker(log) {
      const player = game.value?.players?.find((item) => item.id === log?.actor_id || item.name === log?.speaker)
      if (!player) return normalizePlayerText(log?.speaker || '')
      const roleSuffix = String(log?.speaker || '').replace(new RegExp(`^${player.seat}\\s*号`), '')
      return roleSuffix && roleSuffix !== player.name ? `${playerLabel(player)}${roleSuffix}` : playerLabel(player)
    }
    function logMessage(log) {
      return normalizePlayerText(log?.message || '')
    }
    const promptText = computed(() => {
      if (!game.value) return '选择模式开始游戏'
      if (game.value.winner) return game.value.winner
      if (game.value.waiting_for === 'speech') return '轮到你发言，所有智能体正在等待'
      if (game.value.waiting_for === 'vote') return '轮到你投票，提交后智能体继续行动'
      if (speakingPlayer.value) return `${playerLabel(speakingPlayer.value)} 正在发言`
      return phaseLabel[game.value.phase]
    })
    const speakerMessage = computed(() => {
      const speaker = speakingPlayer.value
      if (!speaker) return game.value?.winner || promptText.value
      const logs = (game.value?.logs ?? [])
        .filter((log) => log.visibility !== 'private' && (log.actor_id === speaker.id || log.speaker === speaker.name))
      return normalizePlayerText(logs.at(-1)?.message || promptText.value)
    })
    const speakerCarousel = computed(() => {
      const players = game.value?.players ?? []
      const current = speakingPlayer.value
      if (!players.length || !current) {
        return [
          { key: 'speaker-judge', label: '法官', image: '/cards/judge.png', tone: 'current' }
        ]
      }
      const order = players.filter((p) => p.alive)
      const index = order.findIndex((p) => p.id === current.id)
      const prev = order[(index - 1 + order.length) % order.length]
      const next = order[(index + 1) % order.length]
      return [
        { key: `speaker-${prev.id}`, label: playerLabel(prev), image: cardImage(prev), tone: 'prev' },
        { key: `speaker-${current.id}`, label: playerLabel(current), image: cardImage(current), tone: 'current' },
        { key: `speaker-${next.id}`, label: playerLabel(next), image: cardImage(next), tone: 'next' }
      ]
    })
    const inferredSheriffId = computed(() => {
      if (game.value?.sheriff_id) return game.value.sheriff_id
      const rows = game.value?.decisions ?? []
      for (let i = rows.length - 1; i >= 0; i--) {
        const decision = rows[i]
        if (decision.action === 'sheriff_destroy') return null
        if (decision.action === 'sheriff_transfer') return decision.target_id
        if (decision.action === 'sheriff_elect') return decision.target_id || decision.actor_id
      }
      return null
    })
    const sheriffElection = computed(() => {
      const rows = game.value?.decisions ?? []
      const electIndex = rows.findLastIndex?.((row) => row.action === 'sheriff_elect') ?? -1
      const fallbackIndex = electIndex >= 0 ? electIndex : rows.length
      const runs = rows
        .slice(Math.max(0, fallbackIndex - 8), electIndex >= 0 ? electIndex : rows.length)
        .filter((row) => row.action === 'sheriff_run')
        .map((row) => `${playerNumberById(row.actor_id)}号`)
      const winner = inferredSheriffId.value ? `${playerNumberById(inferredSheriffId.value)}号` : ''
      if (!runs.length && !winner) return null
      return {
        candidates: [...new Set(runs)],
        winner
      }
    })
    const roleName = computed(() => humanPlayer.value?.role_hint || (isWatch.value ? '观战者' : '未知身份'))
    const pendingAction = computed(() => game.value?.pending_action || { type: '', prompt: '', candidate_ids: [], options: {} })
    const pendingActionType = computed(() => pendingAction.value?.type || '')
    const skillState = computed(() => game.value?.skill_state || {})
    const isHumanWitch = computed(() => roleName.value.includes('女巫'))
    const isHumanWhiteWolf = computed(() => roleName.value.includes('白狼王'))
    const canUseWitchAntidote = computed(() => pendingActionType.value === 'witch_act' && !skillState.value.witch_antidote_used)
    const canUseWitchPoison = computed(() => pendingActionType.value === 'witch_act' && !skillState.value.witch_poison_used && pendingAction.value.options?.poison_available)
    const actionCandidates = computed(() => {
      const ids = new Set(pendingAction.value?.candidate_ids || [])
      return livingPlayers.value.filter((player) => ids.has(player.id))
    })
    const whiteWolfTargets = computed(() => {
      if (!humanPlayer.value?.alive || !isHumanWhiteWolf.value || skillState.value.white_wolf_burst_used) return []
      return livingPlayers.value.filter((player) => player.id !== game.value?.human_player_id)
    })
    const canWhiteWolfBurst = computed(() => whiteWolfTargets.value.length > 0 && !isReplayMode.value && !isWatch.value)
    const needsTarget = computed(() => {
      if (pendingActionType.value === 'witch_act') return ['poison', 'antidote'].includes(witchChoice.value)
      return Boolean(pendingActionType.value)
    })
    const actionInstruction = computed(() => {
      if (pendingActionType.value === 'witch_act' && witchChoice.value === 'poison') return '法官提醒：点击一名玩家的 3D 模型使用毒药。'
      if (pendingActionType.value === 'witch_act' && witchChoice.value === 'antidote') return '法官提醒：点击一名玩家的 3D 模型使用解药。'
      if (pendingActionType.value === 'witch_act') return pendingAction.value.prompt || '女巫请选择是否发动技能。'
      if (pendingActionType.value) return pendingAction.value.prompt || '法官提醒：点击一名玩家的 3D 模型选择目标。'
      if (game.value?.waiting_for === 'vote') return '投票环节，点击你要投票的玩家模型。'
      if (burstArmed.value) return '白狼王自爆已准备，点击要带走的玩家模型。'
      return ''
    })
    const speechCountdownText = computed(() => {
      const value = Math.max(0, speechRemaining.value)
      const minutes = String(Math.floor(value / 60)).padStart(1, '0')
      const seconds = String(value % 60).padStart(2, '0')
      return `${minutes}:${seconds}`
    })
    const voteTally = computed(() => game.value?.vote_tally ?? [])
    const sceneVoteTally = computed(() => voteTally.value.map((row) => ({
      ...row,
      voters: (row.voter_ids || []).map((id) => `${playerNumberById(id)}号`)
    })))
    const roleStats = computed(() => {
      const players = game.value?.players ?? []
      const counts = game.value?.role_counts ?? {}
      return roleIconSpecs
        .map((spec) => {
          const rolePlayers = players.filter((player) => roleMatches(player.role_hint ?? '', spec.tokens))
          const configured = Object.entries(counts).find(([role]) => roleMatches(role, spec.tokens))?.[1] ?? 0
          const total = rolePlayers.length || Number(configured) || 0
          const alive = rolePlayers.length ? rolePlayers.filter((player) => player.alive).length : total
          return { ...spec, alive, total }
        })
        .filter((item) => item.total > 0)
    })
    function seatHash(value) {
      let hash = 2166136261
      for (let i = 0; i < value.length; i++) {
        hash ^= value.charCodeAt(i)
        hash = Math.imul(hash, 16777619)
      }
      return hash >>> 0
    }
    const visualSeatPlayers = computed(() => {
      const players = (game.value?.players ?? []).slice(0, 12)
      if (backendMode.value === 'external' || isWatch.value) {
        return players
          .map((player, index) => ({ player, index }))
          .sort((a, b) => (Number(a.player?.seat || a.player?.id || a.index) - Number(b.player?.seat || b.player?.id || b.index)) || a.index - b.index)
          .map((item) => item.player)
      }
      const signature = players.map((player, index) => `${player?.id ?? index}:${player?.role_hint ?? ''}`).join('|')

      // 玩家模式：自己是1号，其他玩家按逆时针（向左）排序
      if (!isWatch.value) {
        const human = players.find((p) => p.is_human)
        if (human) {
          // 先算出随机排序
          const shuffled = players
            .map((player, index) => ({
              player,
              index,
              order: seatHash(`${visualSeatSalt.value}:${signature}:${player?.id ?? index}`)
            }))
            .sort((a, b) => a.order - b.order || a.index - b.index)
            .map((item) => item.player)

          const humanIdx = shuffled.indexOf(human)
          const others = shuffled.filter((p) => p.id !== human.id)
          const sorted = others.map((p) => {
            const idx = shuffled.indexOf(p)
            return { player: p, idx }
          }).sort((a, b) => {
            const aOffset = (a.idx - humanIdx + 12) % 12
            const bOffset = (b.idx - humanIdx + 12) % 12
            return aOffset - bOffset
          }).map((item) => item.player)

          return [human, ...sorted]
        }
      }

      return players
        .map((player, index) => ({
          player,
          index,
          order: seatHash(`${visualSeatSalt.value}:${signature}:${player?.id ?? index}`)
        }))
        .sort((a, b) => a.order - b.order || a.index - b.index)
        .map((item) => item.player)
    })
    const playerIdentityList = computed(() =>
      visualSeatPlayers.value
        .map((player) => ({
          ...player,
          displaySeat: visualSeatPlayers.value.indexOf(player) + 1,
          roleIcon: isWatch.value ? roleIconImage(player) : (player.is_human ? roleIconImage(player) : '/role-icons/未知.png'),
          isSheriff: player.is_sheriff || player.id === inferredSheriffId.value,
          speaking: player.id === game.value?.current_speaker_id
        }))
    )
    const judgeBoardMessage = computed(() => {
      if (!judgeBoardStarted.value) return '你好，我是本局的法官，点击下方的开始按钮开启对局。'
      if (!roleAssignmentComplete.value) return '正在分配角色...'
      if (roleAssignmentCompleteNotice.value) return '角色分配完成，开始使用技能。'
      return ''
    })

    const decisionActionText = {
      speak: '发言',
      vote: '投票',
      kill: '狼人袭击',
      inspect: '预言查验',
      poison: '女巫毒药',
      antidote: '女巫解药',
      guard: '守卫守护',
      shoot: '猎人开枪',
      sheriff_run: '上警',
      sheriff_pass: '不上警',
      sheriff_speak: '警上发言',
      sheriff_withdraw: '退水',
      sheriff_stay: '留警上',
      sheriff_vote: '警长投票',
      sheriff_elect: '警长当选',
      sheriff_election_end: '警长结果',
      sheriff_transfer: '移交警徽',
      sheriff_destroy: '撕毁警徽',
      white_wolf_burst: '白狼王自爆',
      white_wolf_explode: '白狼王自爆',
      guard_protect: '守卫守护',
      werewolf_kill: '狼人夜刀',
      seer_check: '预言查验',
      witch_act: '女巫行动',
      last_word: '遗言',
      pk_speak: 'PK发言',
      pk_vote: 'PK投票',
      hunter_shoot: '猎人开枪',
      speech_order: '发言顺序',
      sheriff_badge: '警徽处理',
      sheriff_badge_transfer: '移交警徽',
      sheriff_badge_destroy: '撕毁警徽'
    }
    const historyPhaseTabs = [
      { key: 'all', label: '全部' },
      { key: 'setup', label: '配置' },
      { key: 'night', label: '黑夜' },
      { key: 'sheriff', label: '警长竞选' },
      { key: 'sheriff_result', label: '警长结果' },
      { key: 'speech', label: '发言' },
      { key: 'vote', label: '投票' },
      { key: 'result', label: '结算' },
      { key: 'ended', label: '终局' }
    ]
    const decisionRows = computed(() => {
      return (game.value?.decisions ?? []).map((decision, index) => ({
        ...decision,
        index: index + 1,
        actorName: `${playerNumberById(decision.actor_id)}号`,
        targetName: decision.target_id ? `${playerNumberById(decision.target_id)}号` : '无目标',
        reason: normalizePlayerText(decision.reason),
        public_summary: normalizePlayerText(decision.public_summary),
        actionName: decisionActionText[decision.action] || decision.action
      }))
    })
    function historyPlayerById(id) {
      return selectedHistoryGame.value?.players?.find((item) => item.id === id)
    }
    function historyPlayerLabelById(id) {
      const player = historyPlayerById(id)
      return player?.seat ? `${player.seat}号` : `${id}号`
    }
    function historyLogSpeaker(log) {
      const player = selectedHistoryGame.value?.players?.find((item) => item.id === log?.actor_id || item.name === log?.speaker)
      return player?.seat ? `${player.seat}号` : (log?.speaker || '')
    }
    function historyPhaseName(phase) {
      return phaseLabel[phase] || phase || '未知阶段'
    }
    function historyPageKeyFor(log) {
      return `day-${log?.day ?? 1}-${log?.phase || 'setup'}`
    }
    function historyPageTitle(page) {
      return `DAY ${page.day} · ${historyPhaseName(page.phase)}`
    }
    function historyNormalizeText(text = '') {
      let value = String(text || '')
      for (const player of selectedHistoryGame.value?.players ?? []) {
        value = value.replace(new RegExp(`${player.seat}\\s*号`, 'g'), `${player.seat}号`)
        if (player.name) value = value.replaceAll(player.name, `${player.seat}号`)
      }
      return value
    }
    function historyDecisionMatchesPage(decision, page) {
      if (!page) return true
      return Number(decision.day || page.day) === Number(page.day) && String(decision.phase || page.phase) === String(page.phase)
    }
    const historyPages = computed(() => {
      const logs = selectedHistoryGame.value?.logs ?? []
      const map = new Map()
      logs.forEach((log) => {
        const key = historyPageKeyFor(log)
        if (!map.has(key)) {
          map.set(key, { key, day: log.day || 1, phase: log.phase || 'setup', logs: [], decisions: [] })
        }
        map.get(key).logs.push(log)
      })
      const pages = [...map.values()]
      const decisions = selectedHistoryGame.value?.decisions ?? []
      pages.forEach((page) => {
        page.decisions = decisions.filter((decision) => historyDecisionMatchesPage(decision, page))
      })
      if (!selectedHistoryPageKey.value && pages.length) selectedHistoryPageKey.value = pages[0].key
      if (historyPhase.value === 'all') return pages
      return pages.filter((page) => page.phase === historyPhase.value)
    })
    const selectedHistoryPage = computed(() => {
      const pages = historyPages.value
      return pages.find((page) => page.key === selectedHistoryPageKey.value) || pages[0] || null
    })
    const historyLogs = computed(() => selectedHistoryPage.value?.logs ?? [])
    const historyDecisionRows = computed(() => {
      return (selectedHistoryGame.value?.decisions ?? []).map((decision, index) => ({
        ...decision,
        index: index + 1,
        actorName: decision.actor_name || historyPlayerLabelById(decision.actor_id),
        targetName: decision.target_name || (decision.target_id ? historyPlayerLabelById(decision.target_id) : '无目标'),
        reason: historyNormalizeText(decision.reason || ''),
        public_summary: historyNormalizeText(decision.public_summary || ''),
        private_reasoning: historyNormalizeText(decision.private_reasoning || ''),
        actionName: decisionActionText[decision.action] || decision.action,
        roleName: decision.role || historyPlayerById(decision.actor_id)?.role_hint || '未知身份',
        selected_skill: decision.selected_skill || '',
        memory_summary: decision.memory_summary || [],
        memory_refs: decision.memory_refs || [],
        belief_snapshot: decision.belief_snapshot || null,
        raw_output: decision.raw_output || '',
        errors: decision.errors || [],
        policy_adjustments: decision.policy_adjustments || []
      }))
    })
    const filteredHistoryDecisionRows = computed(() => {
      const page = selectedHistoryPage.value
      return historyDecisionRows.value.filter((decision) => historyDecisionMatchesPage(decision, page))
    })
    const pageNightActions = computed(() => {
      const page = selectedHistoryPage.value
      if (!page || page.phase !== 'night') return []
      return filteredHistoryDecisionRows.value.filter((d) =>
        ['kill', 'guard', 'inspect', 'poison', 'antidote', 'shoot',
          'guard_protect', 'werewolf_kill', 'seer_check', 'witch_act', 'hunter_shoot'].includes(d.action)
      )
    })
    const pageVoteResults = computed(() => {
      const page = selectedHistoryPage.value
      if (!page || !['vote', 'sheriff_vote'].includes(page.phase)) return []
      const votes = filteredHistoryDecisionRows.value.filter((d) =>
        ['vote', 'sheriff_vote'].includes(d.action)
      )
      const grouped = new Map()
      for (const vote of votes) {
        const key = vote.target_id || 'unknown'
        if (!grouped.has(key)) {
          grouped.set(key, { targetId: vote.target_id, targetName: vote.targetName, votes: [] })
        }
        grouped.get(key).votes.push(vote)
      }
      return [...grouped.values()].sort((a, b) => b.votes.length - a.votes.length)
    })
    const pageLastWords = computed(() => {
      return filteredHistoryDecisionRows.value.filter((d) => d.action === 'last_word')
    })
    function nightActionDetail(action) {
      const actor = action.actorName
      const target = action.targetName
      const a = action.action
      if (a === 'kill' || a === 'werewolf_kill') return `狼人选择击杀 ${target}`
      if (a === 'guard' || a === 'guard_protect') return `${actor}守护 ${target}`
      if (a === 'inspect' || a === 'seer_check') return `${actor}查验 ${target}`
      if (a === 'poison' || a === 'witch_act') return `${actor}使用毒药 ${target}`
      if (a === 'antidote') return `${actor}使用解药 ${target}`
      if (a === 'shoot' || a === 'hunter_shoot') return `${actor}开枪 ${target}`
      return `${actor}行动 ${target}`
    }
    const pageSpeechDecisions = computed(() => {
      const page = selectedHistoryPage.value
      if (!page || !['speech', 'sheriff'].includes(page.phase)) return []
      return filteredHistoryDecisionRows.value.filter((d) =>
        ['speak', 'sheriff_speak'].includes(d.action)
      )
    })
    const historyStats = computed(() => {
      const source = selectedHistoryGame.value
      return {
        logs: source?.logs?.length ?? 0,
        decisions: source?.decisions?.length ?? 0,
        alive: source?.players?.filter((player) => player.alive).length ?? 0,
        total: source?.players?.length ?? 0
      }
    })

    const judgeStripMessage = computed(() => {
      if (judgeBoardMessage.value) {
        return [{ speaker: '法官', message: judgeBoardMessage.value }]
      }

      const latestDecision = decisionRows.value.at(-1)
      if (latestDecision?.action?.startsWith('sheriff_')) {
        if (latestDecision.action === 'sheriff_run') {
          return [{ speaker: '法官', message: `${latestDecision.actorName}参与警长竞选。` }]
        }
        if (latestDecision.action === 'sheriff_elect') {
          const winner = latestDecision.targetName !== '无目标' ? latestDecision.targetName : latestDecision.actorName
          return [{ speaker: '法官', message: `警长竞选结束，${winner}当选警长。` }]
        }
        if (latestDecision.action === 'sheriff_transfer') {
          return [{ speaker: '法官', message: `警徽移交给${latestDecision.targetName}。` }]
        }
        if (latestDecision.action === 'sheriff_destroy') {
          return [{ speaker: '法官', message: '警徽被撕毁，本局不再移交警徽。' }]
        }
      }

      const rows = judgeLogs.value.map((log) => ({
        speaker: logSpeaker(log),
        message: logMessage(log)
      }))
      if (rows.length) return rows

      return [{ speaker: '法官', message: '等待法官记录。' }]
    })

    async function apiFetch(path, options = {}) {
      const response = await fetch(`${API}${path}`, {
        headers: { 'Content-Type': 'application/json' },
        ...options
      })
      if (!response.ok) {
        const detail = await response.text().catch(() => '')
        throw new Error(detail || `HTTP ${response.status}`)
      }
      return response.json()
    }

    function formatJson(value) {
      if (!value) return ''
      if (typeof value === 'string') return value
      try { return JSON.stringify(value, null, 2) } catch { return String(value) }
    }

    function compactList(value) {
      if (!value) return []
      return Array.isArray(value) ? value : [value]
    }

    async function refreshHealth() {
      try {
        const health = await apiFetch('/health')
        backendMode.value = health.mode || 'mock'
        externalStatus.value = health.external || null
      } catch {
        backendMode.value = 'mock'
        externalStatus.value = null
      }
    }

    async function request(path, options = {}) {
      loading.value = true
      error.value = ''
      try {
        game.value = await apiFetch(path, options)
        currentView.value = 'match'
        if (canVotePlayers.value.length && !canVotePlayers.value.some((p) => p.id === Number(voteTarget.value))) {
          voteTarget.value = canVotePlayers.value[0].id
        }
        if (game.value.winner) stopWatch()
        refreshHistoryList({ silent: true })
      } catch {
        error.value = '后端未连接或接口异常，请确认 FastAPI 服务正在运行。'
        stopWatch()
      } finally {
        loading.value = false
      }
    }

    async function refreshHistoryList({ silent = false } = {}) {
      if (!silent) historyLoading.value = true
      try {
        const data = await apiFetch('/games')
        gameHistory.value = data.games ?? []
        if (!selectedHistoryGameId.value && gameHistory.value.length) {
          selectedHistoryGameId.value = gameHistory.value[0].game_id
        }
      } catch {
        if (!silent) error.value = '历史对局读取失败，请确认后端服务正在运行。'
      } finally {
        if (!silent) historyLoading.value = false
      }
    }

    async function selectHistoryGame(gameId) {
      if (!gameId) return
      selectedHistoryGameId.value = gameId
      historyPhase.value = 'all'
      selectedHistoryPageKey.value = ''
      historyLoading.value = true
      error.value = ''
      try {
        selectedHistoryGame.value = await apiFetch(`/games/${gameId}`)
      } catch {
        error.value = '历史对局详情读取失败。'
      } finally {
        historyLoading.value = false
      }
    }

    async function openLogPage(gameId = selectedHistoryGameId.value) {
      stopWatch()
      currentView.value = 'logs'
      window.location.hash = 'logs'
      await refreshHistoryList()
      await selectHistoryGame(gameId || gameHistory.value[0]?.game_id)
    }

    function goLobby() {
      stopWatch()
      currentView.value = 'lobby'
      window.location.hash = ''
      game.value = null
    }

    function backToMatch() {
      window.location.hash = ''
      if (game.value) {
        currentView.value = 'match'
        // Restart watch if game is still running
        if (isWatch.value && !game.value.winner) {
          watchRunning.value = false
          startWatch()
        }
      } else {
        currentView.value = 'lobby'
      }
    }

    function buildReplaySnapshot(source, page) {
      if (!source || !page) return null
      const endSequence = Math.max(...page.logs.map((log) => Number(log.sequence || 0)), 0)
      const logs = (source.logs ?? []).filter((log) => Number(log.sequence || 0) <= endSequence)
      const decisions = (source.decisions ?? []).filter((decision) => {
        const decisionDay = Number(decision.day || 0)
        const sameEarlierDay = decisionDay && decisionDay < Number(page.day)
        const samePage = decisionDay === Number(page.day) && String(decision.phase || '') === String(page.phase)
        return sameEarlierDay || samePage
      })
      const players = (source.players ?? []).map((player) => ({ ...player, alive: true, is_sheriff: false }))
      let sheriffId = null
      let currentSpeakerId = null
      const playerById = (id) => players.find((player) => player.id === id)
      for (const log of logs) {
        const type = log.event_type || ''
        if (['death', 'exile', 'white_wolf_burst_kill', 'white_wolf_burst_death'].includes(type)) {
          const dead = playerById(log.target_id || log.actor_id)
          if (dead) dead.alive = false
        }
        if (type === 'sheriff_election_end') sheriffId = log.payload?.winner || log.target_id || log.actor_id || sheriffId
        if (type === 'sheriff_transfer') sheriffId = log.target_id || sheriffId
        if (type === 'sheriff_destroy') sheriffId = null
        if (['speech', 'sheriff_speak'].includes(type)) currentSpeakerId = log.actor_id || currentSpeakerId
      }
      players.forEach((player) => { player.is_sheriff = player.id === sheriffId })
      return {
        ...source,
        players,
        logs,
        decisions,
        day: page.day,
        phase: page.phase,
        current_speaker_id: currentSpeakerId,
        sheriff_id: sheriffId,
        winner: source.winner && ['ended', 'result'].includes(page.phase) ? source.winner : null,
        waiting_for: 'none'
      }
    }

    function enterReplayPage(page = selectedHistoryPage.value) {
      const snapshot = buildReplaySnapshot(selectedHistoryGame.value, page)
      if (!snapshot) return
      stopWatch()
      if (!isReplayMode.value) lastLiveGame.value = game.value
      isReplayMode.value = true
      replaySourceGameId.value = selectedHistoryGame.value?.game_id || null
      replayPageKey.value = page.key
      game.value = snapshot
      judgeBoardStarted.value = true
      roleAssignmentComplete.value = true
      currentView.value = 'match'
      window.location.hash = 'match'
      nextTick(syncCouncilScene)
    }

    function returnToHistoryFromReplay() {
      currentView.value = 'logs'
      window.location.hash = 'logs'
    }

    function exitReplayMode() {
      if (!isReplayMode.value) return
      isReplayMode.value = false
      replaySourceGameId.value = null
      replayPageKey.value = ''
      if (lastLiveGame.value) game.value = lastLiveGame.value
      else game.value = null
      currentView.value = game.value ? 'match' : 'lobby'
      window.location.hash = game.value ? 'match' : ''
      // Restart watch if returning to a live game
      if (game.value && isWatch.value && !game.value.winner) {
        watchRunning.value = false
        startWatch()
      }
    }

    function startMode(mode, testRole = null) {
      stopWatch()
      if (backendMode.value === 'external' && mode === 'play') {
        error.value = '外部智能体后端暂不支持人类加入，请使用观战模式。'
        return Promise.resolve()
      }
      isReplayMode.value = false
      lastLiveGame.value = null
      visualSeatSalt.value = Math.random().toString(36).slice(2)
      judgeBoardStarted.value = false
      judgeBoardStarting.value = false
      roleAssignmentComplete.value = false
      roleAssignmentCompleteNotice.value = false
      return request('/game/start', {
        method: 'POST',
        body: JSON.stringify({ mode, player_count: 12, test_role: testRole })
      })
    }

    async function startVoteTest() {
      await startMode('play')
      judgeBoardStarted.value = true
      judgeBoardStarting.value = false
      roleAssignmentComplete.value = true
      await submitSpeech('')
    }

    function resetGame() {
      stopWatch()
      isReplayMode.value = false
      lastLiveGame.value = null
      visualSeatSalt.value = Math.random().toString(36).slice(2)
      judgeBoardStarted.value = false
      judgeBoardStarting.value = false
      roleAssignmentComplete.value = false
      roleAssignmentCompleteNotice.value = false
      return request('/game/reset', { method: 'POST' })
    }

    function stepGame() {
      if (isReplayMode.value) return Promise.resolve()
      return request('/game/step', { method: 'POST' })
    }

    function startWatch() {
      if (isReplayMode.value || !isWatch.value || watchRunning.value) return
      judgeBoardStarted.value = true
      roleAssignmentComplete.value = true
      watchRunning.value = true
      if (backendMode.value === 'external') {
        stepGame()
        eventSource?.close?.()
        eventSource = new EventSource(`${API}/game/events`)
        eventSource.addEventListener('log', () => stepGame())
        eventSource.addEventListener('done', () => {
          stepGame().finally(() => stopWatch())
        })
        eventSource.addEventListener('error', () => {
          eventSource?.close?.()
          eventSource = null
          if (!timer) {
            timer = window.setInterval(() => {
              if (!loading.value && !game.value?.winner) stepGame()
            }, 2200)
          }
        })
        return
      }
      stepGame()
      timer = window.setInterval(() => {
        if (!loading.value && !game.value?.winner) stepGame()
      }, 1500)
    }

    function startFromJudgeBoard() {
      if (judgeBoardStarting.value || watchRunning.value) return
      judgeBoardStarting.value = true
      judgeBoardStarted.value = true
      roleAssignmentComplete.value = false
      roleAssignmentCompleteNotice.value = false
      const finishAssignment = () => {
        roleAssignmentComplete.value = true
        roleAssignmentCompleteNotice.value = true
        judgeBoardStarting.value = false
        syncCouncilScene()
        window.setTimeout(() => {
          roleAssignmentCompleteNotice.value = false
        }, 1400)
        if (isWatch.value) startWatch()
        else stepGame()
      }
      waitForCouncilModels()
        .then(() => new Promise((resolve) => window.setTimeout(resolve, 260)))
        .then(finishAssignment)
        .catch(finishAssignment)
        .finally(() => {
          judgeBoardStarting.value = false
        })
    }

    function stopWatch() {
      watchRunning.value = false
      eventSource?.close?.()
      eventSource = null
      if (timer) {
        window.clearInterval(timer)
        timer = null
      }
    }

    function toggleWatch() {
      if (watchRunning.value) {
        stopWatch()
        return
      }
      startWatch()
    }

    function clearSpeechTimer() {
      if (speechTimer) {
        window.clearInterval(speechTimer)
        speechTimer = null
      }
    }

    function startSpeechTimer() {
      clearSpeechTimer()
      speechRemaining.value = 180
      speechTimer = window.setInterval(() => {
        speechRemaining.value -= 1
        if (speechRemaining.value <= 0) {
          clearSpeechTimer()
          submitSpeech('')
        }
      }, 1000)
    }

    function submitSpeech(textOverride = null) {
      if (isReplayMode.value || backendMode.value === 'external') return Promise.resolve()
      clearSpeechTimer()
      return request('/game/speech', {
        method: 'POST',
        body: JSON.stringify({ text: textOverride == null ? speech.value : textOverride })
      })
    }

    function submitVote() {
      if (isReplayMode.value || backendMode.value === 'external') return Promise.resolve()
      return request('/game/vote', {
        method: 'POST',
        body: JSON.stringify({ target_id: Number(voteTarget.value) })
      })
    }

    function submitAction(action = pendingActionType.value, targetId = actionTarget.value, choice = witchChoice.value) {
      if (isReplayMode.value || backendMode.value === 'external' || !action) return Promise.resolve()
      return request('/game/action', {
        method: 'POST',
        body: JSON.stringify({ action, target_id: targetId ? Number(targetId) : null, choice })
      }).then(() => {
        actionTarget.value = null
        witchChoice.value = 'skip'
      })
    }

    function submitWhiteWolfBurst(targetId = actionTarget.value) {
      if (!targetId) return Promise.resolve()
      return submitAction('white_wolf_burst', targetId, 'burst').finally(() => {
        burstArmed.value = false
      })
    }

    function chooseScenePlayer(playerId) {
      const id = Number(playerId)
      if (!id) return
      if (burstArmed.value && whiteWolfTargets.value.some((player) => player.id === id)) {
        actionTarget.value = id
        submitWhiteWolfBurst(id)
        return
      }
      if (pendingActionType.value) {
        if (actionCandidates.value.some((player) => player.id === id)) {
          actionTarget.value = id
          if (pendingActionType.value !== 'witch_act' || ['poison', 'antidote'].includes(witchChoice.value)) submitAction(pendingActionType.value, id, witchChoice.value)
        }
        return
      }
      if (game.value?.waiting_for === 'vote' && canVotePlayers.value.some((player) => player.id === id)) {
        voteTarget.value = id
        submitVote()
      }
    }

    function squareSeatStyle(index, total) {
      const layouts = {
        6: [
          [30, 5], [70, 5],
          [96, 50],
          [70, 95], [30, 95],
          [4, 50]
        ],
        9: [
          [25, 5], [50, 5], [75, 5],
          [96, 34], [96, 66],
          [66, 95], [34, 95],
          [4, 66], [4, 34]
        ],
        10: [
          [24, 5], [50, 5], [76, 5],
          [96, 30], [96, 70],
          [76, 95], [50, 95], [24, 95],
          [4, 70], [4, 30]
        ],
        12: [
          [22, 1], [50, 5], [75, 5],
          [96, 25], [96, 50], [96, 75],
          [75, 95], [50, 95], [25, 95],
          [4, 75], [4, 50], [0, 22]
        ]
      }
      const layout = layouts[total]
      if (layout?.[index]) {
        const [x, y] = layout[index]
        return { left: `${x}%`, top: `${y}%` }
      }

      const t = (index / total) * 4
      let x = 50
      let y = 50
      if (t < 1) {
        x = 8 + t * 84
        y = 4
      } else if (t < 2) {
        x = 96
        y = 8 + (t - 1) * 84
      } else if (t < 3) {
        x = 92 - (t - 2) * 84
        y = 96
      } else {
        x = 4
        y = 92 - (t - 3) * 84
      }
      return { left: `${x}%`, top: `${y}%` }
    }

    function cardImage(player) {
      if (!isWatch.value && player && !player.is_human) return '/cards/card-back.png'
      const hint = player?.role_hint || ''
      if (hint.includes('预言')) return '/cards/seer.png'
      if (hint.includes('女巫')) return '/cards/witch.png'
      if (hint.includes('猎人')) return '/cards/hunter.png'
      if (hint.includes('守卫')) return '/cards/guard.png'
      if (hint.includes('白狼王')) return '/cards/white-wolf-king.png'
      if (hint.includes('狼人')) return '/cards/wolf.png'
      return '/cards/villager.png'
    }

    function roleIconImage(player) {
      const hint = player?.role_hint || ''
      if (hint.includes('预言')) return '/role-icons/预言家.png'
      if (hint.includes('女巫')) return '/role-icons/女巫.png'
      if (hint.includes('猎人')) return '/role-icons/猎人.png'
      if (hint.includes('守卫')) return '/role-icons/守卫.png'
      if (hint.includes('白狼王')) return '/role-icons/白狼王.png'
      if (hint.includes('狼人')) return '/role-icons/普通狼.png'
      return '/role-icons/平民.png'
    }

    function speakerImage(player) {
      return player ? cardImage(player) : '/cards/judge.png'
    }

    async function loadArchive(gameId = selectedHistoryGameId.value) {
      if (!gameId || archiveByGameId.value[gameId]) return
      archiveLoading.value = true
      try {
        archiveByGameId.value = { ...archiveByGameId.value, [gameId]: await apiFetch(`/games/${gameId}/archive`) }
      } catch (err) {
        archiveByGameId.value = { ...archiveByGameId.value, [gameId]: { error: err.message || '档案读取失败' } }
      } finally {
        archiveLoading.value = false
      }
    }

    async function loadReview(gameId = selectedHistoryGameId.value) {
      if (!gameId || reviewByGameId.value[gameId]) return
      reviewLoading.value = true
      try {
        reviewByGameId.value = { ...reviewByGameId.value, [gameId]: await apiFetch(`/games/${gameId}/review`) }
      } catch (err) {
        reviewByGameId.value = { ...reviewByGameId.value, [gameId]: { error: err.message || '复盘报告读取失败' } }
      } finally {
        reviewLoading.value = false
      }
    }

    async function scrollChatToBottom() {
      await nextTick()
      if (chatListRef.value) {
        chatListRef.value.scrollTop = chatListRef.value.scrollHeight
      }
    }

    async function scrollJudgeToBottom() {
      await nextTick()
      if (judgeListRef.value) {
        judgeListRef.value.scrollTop = judgeListRef.value.scrollHeight
      }
    }

    async function scrollJudgeStripToBottom() {
      await nextTick()
      if (judgeStripRef.value) {
        judgeStripRef.value.scrollTop = judgeStripRef.value.scrollHeight
      }
    }

    async function mountCouncilScene() {
      await nextTick()
      if (!inMatch.value || !gameSceneRef.value) return
      if (!councilScene) {
        councilScene = createCouncilHallScene(gameSceneRef.value)
      }
      gameSceneRef.value.style.visibility = ''
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
      if (gameSceneRef.value) {
        gameSceneRef.value.style.visibility = 'hidden'
      }
    }

    function syncCouncilScene() {
      const speechByPlayer = {}
      const players = game.value?.players ?? []
      const recentPlayerLogs = (game.value?.logs ?? []).filter((log) =>
        canSeeLog(log) &&
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
            tone: latestPlayerLog.phase === 'night' || latestPlayerLog.visibility === 'god' ? 'night' : 'day'
          }
        }
      }

      // Infer current speaker from the latest visible player log when backend returns null
      let effectiveSpeakerId = game.value?.current_speaker_id ?? null
      if (latestPlayerLog?.actor_id) {
        effectiveSpeakerId = latestPlayerLog.actor_id
      }
      councilScene?.update?.({
        players: visualSeatPlayers.value.map((player) => {
          // 玩家模式下非自己的玩家隐藏身份，用平民模型
          const masked = !isWatch.value && !player.is_human
          return {
            ...player,
            roleIcon: roleIconImage(player),
            role_hint: masked ? '未知' : player.role_hint
          }
        }),
        currentSpeakerId: effectiveSpeakerId,
        speechByPlayer,
        isNight: isNight.value,
        revealPlayers: roleAssignmentComplete.value || isReplayMode.value,
        humanId: isWatch.value ? null : game.value?.human_player_id ?? null,
        selectableIds: pendingActionType.value
          ? actionCandidates.value.map((player) => player.id)
          : (game.value?.waiting_for === 'vote'
              ? canVotePlayers.value.map((player) => player.id)
              : (burstArmed.value ? whiteWolfTargets.value.map((player) => player.id) : [])),
        onPlayerSelect: chooseScenePlayer,
        voteTally: sceneVoteTally.value
      })
    }

    watch(() => chatLogs.value.length, scrollChatToBottom)
    watch(() => judgeLogs.value.length, scrollJudgeToBottom)
    watch(() => judgeStripMessage.value.length, scrollJudgeStripToBottom)
    watch(() => game.value?.logs?.length, scrollJudgeStripToBottom)
    watch(() => game.value?.current_speaker_id, scrollChatToBottom)
    watch(() => [
      game.value?.players?.map((p) => `${p.id}:${p.role_hint}:${p.alive}`).join('|'),
      game.value?.current_speaker_id,
      game.value?.logs?.length,
      judgeBoardStarted.value,
      roleAssignmentComplete.value,
      pendingActionType.value,
      actionCandidates.value.map((p) => p.id).join('|'),
      game.value?.waiting_for,
      burstArmed.value,
      sceneVoteTally.value.map((row) => `${row.target_id}:${row.count}:${row.voters?.join(',')}`).join('|')
    ], syncCouncilScene)
    watch(() => game.value?.waiting_for, (waiting) => {
      if (!isWatch.value && !isReplayMode.value && waiting === 'speech') startSpeechTimer()
      else clearSpeechTimer()
    }, { immediate: true })
    watch(inMatch, (match) => {
      if (match) mountCouncilScene()
      else hideCouncilScene()
    })

    onMounted(() => {
      refreshHealth()
      refreshHistoryList({ silent: true })
      if (currentView.value === 'logs') openLogPage()
      scrollJudgeToBottom()
    })
    onBeforeUnmount(() => {
      stopWatch()
      clearSpeechTimer()
      councilScene?.dispose?.()
      councilScene = null
    })

    return {
      game,
      loading,
      error,
      currentView,
      inLogs,
      inMatch,
      gameHistory,
      selectedHistoryGameId,
      selectedHistoryGame,
      historyLoading,
      historyPhase,
      historyPhaseTabs,
      selectedHistoryPageKey,
      selectedHistoryPage,
      historyPages,
      historyPageTitle,
      historyLogs,
      historyDecisionRows,
      filteredHistoryDecisionRows,
      pageNightActions,
      pageVoteResults,
      pageLastWords,
      pageSpeechDecisions,
      nightActionDetail,
      historyStats,
      isReplayMode,
      backendMode,
      externalStatus,
      archiveByGameId,
      reviewByGameId,
      archiveLoading,
      reviewLoading,
      chatListRef,
      judgeListRef,
      judgeStripRef,
      gameSceneRef,
      speech,
      voteTarget,
      playerCount,
      watchRunning,
      isNight,
      inLobby,
      isWatch,
      livingPlayers,
      humanPlayer,
      canVotePlayers,
      publicLogs,
      chatLogs,
      judgeLogs,
      groupedJudgeLogs,
      judgeBoardStarted,
      judgeBoardStarting,
      roleAssignmentComplete,
      roleAssignmentCompleteNotice,
      chatLogExpanded,
      judgeBoardMessage,
      judgeStripMessage,
      decisionRows,
      speakingPlayer,
      speakerMessage,
      speakerCarousel,
      sheriffElection,
      roleStats,
      playerIdentityList,
      displayPhase,
      promptText,
      roleName,
      pendingAction,
      pendingActionType,
      skillState,
      isHumanWitch,
      isHumanWhiteWolf,
      canUseWitchAntidote,
      canUseWitchPoison,
      actionCandidates,
      actionTarget,
      witchChoice,
      burstArmed,
      actionInstruction,
      speechCountdownText,
      needsTarget,
      voteTally,
      whiteWolfTargets,
      canWhiteWolfBurst,
      logSpeaker,
      logMessage,
      historyLogSpeaker,
      historyPhaseName,
      historyPlayerById,
      formatJson,
      compactList,
      loadArchive,
      loadReview,
      enterReplayPage,
      returnToHistoryFromReplay,
      exitReplayMode,
      normalizePlayerText,
      playerLabel,
      openLogPage,
      selectHistoryGame,
      goLobby,
      backToMatch,
      startMode,
      startVoteTest,
      resetGame,
      stepGame,
      startWatch,
      startFromJudgeBoard,
      stopWatch,
      toggleWatch,
      submitSpeech,
      submitVote,
      submitAction,
      submitWhiteWolfBurst,
      squareSeatStyle,
      cardImage,
      roleIconImage,
      speakerImage
    }
  },
  template: `
    <main :class="['lycan-app', { night: isNight, day: !isNight, lobbying: inLobby && !inLogs, logbook: inLogs }]">
      <div class="atmosphere"></div>
      <div class="noise"></div>

      <header class="topbar">
        <div class="brand">
          <img src="/topbar-characters.png" alt="NightCouncil" />
          <strong>NightCouncil</strong>
        </div>
        <nav>
          <button @click="goLobby">大厅</button>
          <button @click="openLogPage()">日志</button>
        </nav>
      </header>

      <div class="council-scene" ref="gameSceneRef" aria-hidden="true"></div>

      <section v-if="inLogs" class="battle-log-page" aria-label="对战日志">
        <section class="battle-log-shell parchment-logbook">
          <aside class="history-games-panel">
            <button v-if="game" class="history-back-button" @click="backToMatch">
              <svg viewBox="0 0 24 24" aria-hidden="true"><path d="M15.5 5.5 9 12l6.5 6.5V5.5z" /></svg>
              <span>返回对局</span>
            </button>
            <header>
              <span>历史对局</span>
              <strong>{{ gameHistory.length }} 局</strong>
            </header>
            <div class="history-games-list">
              <div
                v-for="item in gameHistory"
                :key="item.game_id"
                :class="{ active: item.game_id === selectedHistoryGameId }"
                class="history-game-item"
              >
                <button class="history-game-select" @click="selectHistoryGame(item.game_id)">
                  <span>{{ item.log_name }}</span>
                  <small>DAY {{ item.day }} · {{ item.event_count }} 条记录</small>
                </button>
                <button class="history-game-replay" @click="selectHistoryGame(item.game_id); $nextTick(() => { selectedHistoryPageKey = historyPages[0]?.key; enterReplayPage(historyPages[0]) })">现场复盘</button>
              </div>
            </div>
            <p v-if="!gameHistory.length && !historyLoading" class="empty-log">暂无历史对局</p>
          </aside>

          <main class="history-detail-panel">
            <section v-if="selectedHistoryGame" class="history-seat-ledger" aria-label="玩家席位">
              <article v-for="player in selectedHistoryGame.players" :key="'history-seat-' + player.id" :class="{ dead: !player.alive, sheriff: player.is_sheriff || player.id === selectedHistoryGame.sheriff_id }">
                <img :src="roleIconImage(player)" :alt="player.role_hint" />
                <b>{{ player.seat }}号</b>
                <span>{{ player.role_hint }}</span>
              </article>
            </section>

            <nav v-if="selectedHistoryGame" class="history-phase-tabs" aria-label="日志阶段筛选">
              <button
                v-for="page in historyPages"
                :key="page.key"
                :class="{ active: selectedHistoryPage?.key === page.key }"
                @click="selectedHistoryPageKey = page.key"
              >
                {{ historyPageTitle(page) }}
              </button>
            </nav>

            <section v-if="selectedHistoryGame && selectedHistoryPage" class="history-page-detail">

                <!-- Night action cards -->
                <section v-if="selectedHistoryPage.phase === 'night' && pageNightActions.length" class="history-night-section">
                  <div class="night-banner">
                    <div class="night-banner-icon">☾</div>
                    <div>
                      <h3>天黑请闭眼</h3>
                      <p>守卫、狼人、预言家、女巫正在行动</p>
                    </div>
                  </div>
                  <div class="night-action-grid">
                    <div v-for="(action, index) in pageNightActions" :key="'night-action-' + index" class="night-action-card">
                      <span class="night-action-type">{{ action.actionName }}</span>
                      <p class="night-action-detail">{{ nightActionDetail(action) }}</p>
                      <details class="night-action-decision">
                        <summary>决策过程{{ action.candidates?.length ? ' (' + action.candidates.length + ')' : '' }}</summary>
                        <small v-if="action.private_reasoning || action.reason">{{ action.private_reasoning || action.reason }}</small>
                        <small v-if="action.candidates?.length">候选：{{ action.candidates.map((item) => item.seat + '号' + item.role).join('、') }}</small>
                        <small v-if="action.alternatives?.length">备选：{{ action.alternatives.join('、') }}</small>
                        <small v-if="action.confidence != null">置信度：{{ Math.round(action.confidence * 100) }}%</small>
                        <small v-if="compactList(action.memory_summary).length">记忆摘要：{{ compactList(action.memory_summary).join('；') }}</small>
                      </details>
                    </div>
                  </div>
                </section>

                <!-- Speech cards -->
                <section v-if="['speech', 'sheriff'].includes(selectedHistoryPage?.phase) && pageSpeechDecisions.length" class="history-speech-section">
                  <div v-for="(decision, index) in pageSpeechDecisions" :key="'speech-' + index" class="speech-card">
                    <header>
                      <span class="speech-actor-badge">{{ decision.actorName }}玩家</span>
                      <span class="speech-role-badge">{{ decision.roleName }}</span>
                      <span class="speech-type-label">白天发言</span>
                    </header>
                    <p class="speech-message">{{ decision.public_summary || decision.reason || '先过。' }}</p>
                    <details class="speech-decision">
                      <summary>决策过程</summary>
                      <div class="decision-detail-grid">
                        <div class="decision-detail-item">
                          <span>选择：</span><span>{{ decision.targetName || '-' }}</span>
                        </div>
                        <div class="decision-detail-item">
                          <span>候选：</span><span>{{ decision.candidates?.length ? decision.candidates.map(c => c.seat + '号').join('、') : '-' }}</span>
                        </div>
                        <div class="decision-detail-item">
                          <span>备选：</span><span>{{ decision.alternatives?.length ? decision.alternatives.join('、') : '-' }}</span>
                        </div>
                        <div class="decision-detail-item">
                          <span>置信度：</span><span>{{ decision.confidence != null ? Math.round(decision.confidence * 100) + '%' : '-' }}</span>
                        </div>
                        <div class="decision-detail-item">
                          <span>记忆事件：</span><span>{{ compactList(decision.memory_summary).join('；') || '-' }}</span>
                        </div>
                        <div class="decision-detail-item">
                          <span>记忆引用：</span><span>{{ compactList(decision.memory_refs).join('、') || '-' }}</span>
                        </div>
                      </div>
                      <small v-if="decision.private_reasoning || decision.reason">{{ decision.private_reasoning || decision.reason }}</small>
                      <small v-if="compactList(decision.errors).length" class="decision-error">错误：{{ compactList(decision.errors).join('；') }}</small>
                      <small v-if="compactList(decision.policy_adjustments).length" class="decision-policy">策略修正：{{ compactList(decision.policy_adjustments).join('；') }}</small>
                    </details>
                  </div>
                </section>

                <!-- Vote result cards -->
                <section v-if="['vote', 'sheriff_vote'].includes(selectedHistoryPage?.phase) && pageVoteResults.length" class="history-vote-section">
                  <div class="vote-result-grid">
                    <div v-for="(result, index) in pageVoteResults" :key="'vote-result-' + index" class="vote-result-card">
                      <header>
                        <span class="vote-target-number">{{ result.targetName }}</span>
                        <span class="vote-target-role">{{ historyPlayerById(result.targetId)?.role_hint || '' }}</span>
                      </header>
                      <div class="vote-entry-list">
                        <div v-for="(vote, vIndex) in result.votes" :key="'vote-' + vIndex" class="vote-entry">
                          <span class="vote-badge">{{ vote.actorName }}投票</span>
                          <details class="vote-decision">
                            <summary>决策过程</summary>
                            <small v-if="vote.private_reasoning || vote.reason">{{ vote.private_reasoning || vote.reason }}</small>
                            <small v-if="vote.candidates?.length">候选：{{ vote.candidates.map((item) => item.seat + '号' + item.role).join('、') }}</small>
                            <small v-if="vote.confidence != null">置信度：{{ Math.round(vote.confidence * 100) }}%</small>
                          </details>
                        </div>
                      </div>
                      <span class="vote-count">{{ result.votes.length }} 票</span>
                    </div>
                  </div>
                </section>

                <!-- Last words section -->
                <section v-if="pageLastWords.length" class="history-lastwords-section">
                  <div v-for="(word, index) in pageLastWords" :key="'last-word-' + index" class="last-word-card">
                    <header>
                      <span class="last-word-actor">{{ word.actorName }}玩家</span>
                      <span class="last-word-role">{{ word.roleName }}</span>
                      <span class="last-word-label">遗言</span>
                    </header>
                    <p class="last-word-message">{{ word.public_summary || word.reason }}</p>
                    <details class="last-word-decision">
                      <summary>决策过程</summary>
                      <small v-if="word.private_reasoning || word.reason">{{ word.private_reasoning || word.reason }}</small>
                      <small v-if="word.candidates?.length">候选：{{ word.candidates.map((item) => item.seat + '号' + item.role).join('、') }}</small>
                    </details>
                  </div>
                </section>

                <section v-if="reviewByGameId[selectedHistoryGame.game_id]" class="archive-review-panel">
                  <h3>复盘报告</h3>
                  <pre>{{ formatJson(reviewByGameId[selectedHistoryGame.game_id]) }}</pre>
                </section>
                <section v-if="archiveByGameId[selectedHistoryGame.game_id]" class="archive-review-panel">
                  <h3>智能体档案</h3>
                  <pre>{{ formatJson(archiveByGameId[selectedHistoryGame.game_id]) }}</pre>
                </section>
              </section>

            <p v-if="!selectedHistoryGame && !historyLoading" class="empty-log">选择一局历史对局查看详情</p>
            <p v-if="historyLoading" class="empty-log">正在读取历史卷宗…</p>
          </main>
        </section>
      </section>
      <section v-if="inLobby" class="lobby">
        <section class="lobby-hero">
          <span class="hero-mark"></span>
          <h1>The Night Approaches</h1>
          <p>Gather the council. Trust no one.</p>
        </section>

        <section class="card-fan" aria-label="NightCouncil roles">
          <figure class="role-card-art werewolf" aria-label="狼人角色牌">
            <img class="lobby-card-image" src="/lobby-cards/werewolf.png" alt="" />
            <img class="lobby-card-frame" src="/lobby-cards/frame.png" alt="" />
          </figure>
          <figure class="role-card-art villager" aria-label="村民角色牌">
            <img class="lobby-card-image" src="/lobby-cards/villager.png" alt="" />
            <img class="lobby-card-frame" src="/lobby-cards/frame.png" alt="" />
          </figure>
          <figure class="role-card-art judge" aria-label="法官角色牌">
            <img class="lobby-card-image" src="/lobby-cards/judge.png" alt="" />
            <img class="lobby-card-frame" src="/lobby-cards/frame.png" alt="" />
          </figure>
          <figure class="role-card-art hunter" aria-label="猎人角色牌">
            <img class="lobby-card-image" src="/lobby-cards/hunter.png" alt="" />
            <img class="lobby-card-frame" src="/lobby-cards/frame.png" alt="" />
          </figure>
          <figure class="role-card-art witch" aria-label="女巫角色牌">
            <img class="lobby-card-image" src="/lobby-cards/witch.png" alt="" />
            <img class="lobby-card-frame" src="/lobby-cards/frame.png" alt="" />
          </figure>
        </section>

        <section class="lobby-actions">
          <button class="mode-card watch" @click="startMode('watch')">
            <span>{{ backendMode === 'external' ? '外部智能体' : '观战模式' }}</span>
            <strong>{{ backendMode === 'external' ? '连接真实后端对局' : '观看智能体对局' }}</strong>
          </button>
          <button class="mode-card play" @click="startMode('play')" :disabled="backendMode === 'external'">
            <span>玩家模式</span>
            <strong>{{ backendMode === 'external' ? '外部后端暂不支持加入' : '加入智能体对局' }}</strong>
          </button>
        </section>
        <section class="test-role-strip" v-if="backendMode !== 'external'">
          <button @click="startMode('play', 'werewolf')">测狼人</button>
          <button @click="startVoteTest">测投票</button>
          <button @click="startMode('play', 'seer')">测预言家</button>
          <button @click="startMode('play', 'hunter')">测猎人</button>
          <button @click="startMode('play', 'guard')">测守卫</button>
          <button @click="startMode('play', 'white_wolf_king')">测白狼王</button>
          <button @click="startMode('play', 'witch')">测女巫</button>
        </section>
      </section>

      <template v-if="inMatch">
        <section class="match-control-strip">
          <div class="strip-top-row">
            <div class="strip-status">
              <strong>{{ isReplayMode ? '复盘' : 'DAY ' + game.day }}</strong>
              <span class="phase-icon" :title="historyPhaseName(game.phase)">{{ isNight ? '☾' : '☀' }}</span>
              <Transition name="strip-text" mode="out-in">
                <em :key="promptText">{{ isReplayMode ? ('DAY ' + game.day + ' · ' + historyPhaseName(game.phase)) : promptText }}</em>
              </Transition>
            </div>
            <div class="strip-controls" aria-label="观战控制">
              <button v-if="isReplayMode" class="icon-button primary" @click="returnToHistoryFromReplay" title="返回日志">
                <svg viewBox="0 0 24 24" aria-hidden="true"><path d="M15.5 5.5 9 12l6.5 6.5V5.5z" /></svg>
              </button>
              <button v-if="isReplayMode" class="icon-button" @click="exitReplayMode" title="退出复盘">
                <svg viewBox="0 0 24 24" aria-hidden="true"><path d="M6.4 5 5 6.4l5.6 5.6L5 17.6 6.4 19l5.6-5.6 5.6 5.6 1.4-1.4-5.6-5.6L19 6.4 17.6 5 12 10.6z" /></svg>
              </button>
              <button v-if="!isReplayMode" class="icon-button primary" @click="toggleWatch" :disabled="!watchRunning && game.winner" :title="watchRunning ? '暂停' : '开始'">
                <svg v-if="watchRunning" viewBox="0 0 24 24" aria-hidden="true"><path d="M7 5h4v14H7zM13 5h4v14h-4z" /></svg>
                <svg v-else viewBox="0 0 24 24" aria-hidden="true"><path d="M8 5v14l11-7z" /></svg>
              </button>
              <button v-if="!isReplayMode" class="icon-button" @click="resetGame" :disabled="loading" title="重开">
                <svg viewBox="0 0 24 24" aria-hidden="true"><path d="M17.7 6.3A8 8 0 1 0 20 12h-2.2a5.8 5.8 0 1 1-1.7-4.1L13 11h8V3z" /></svg>
              </button>
              <button v-if="!isReplayMode" class="icon-button" @click="stepGame" :disabled="loading || watchRunning || game.winner" title="单步推进">
                <svg viewBox="0 0 24 24" aria-hidden="true"><path d="M5 5v14l8-7zM13 5v14l8-7z" /></svg>
              </button>
            </div>
          </div>
          <div class="strip-judge-log" aria-label="法官日志">
            <img class="strip-judge-avatar" src="/livehall-assets/props/judge-avatar.png" alt="法官" />
            <div class="strip-judge-copy" :class="{ 'has-start': !judgeBoardStarted }">
              <div class="strip-judge-scroll" ref="judgeStripRef">
                <p v-for="(line, index) in judgeStripMessage" :key="'judge-strip-' + index">
                  {{ line.message }}
                </p>
              </div>
              <button
                v-if="!judgeBoardStarted"
                class="strip-judge-start"
                :class="{ fading: judgeBoardStarting }"
                @click="startFromJudgeBoard"
                :disabled="judgeBoardStarting"
              >
                开始对局
              </button>
            </div>
          </div>
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
            <aside v-if="roleAssignmentComplete" class="chat-log-panel" :class="{ expanded: chatLogExpanded }" aria-label="聊天记录">
              <div class="chat-log-top">
                <span>聊天记录</span>
                <button class="chat-log-toggle" @click="chatLogExpanded = !chatLogExpanded" :title="chatLogExpanded ? '收起' : '展开'">
                  <svg viewBox="0 0 24 24"><path v-if="!chatLogExpanded" d="M7 10l5 5 5-5z"/><path v-else d="M7 14l5-5 5 5z"/></svg>
                </button>
              </div>
              <div class="chat-log-body">
                <div class="chat-log-scroll" ref="chatListRef">
                  <p v-for="(log, index) in chatLogs" :key="index" class="chat-log-line">
                    <b>{{ logSpeaker(log) }}</b>：{{ logMessage(log) }}
                  </p>
                </div>
              </div>
            </aside>
          </Transition>
          <aside class="chat-panel match-panel" style="display:none;">
            <header>
              <span>聊天内容</span>
              <strong>{{ game.player_count }}人{{ isWatch ? '观战局' : '人机局' }}</strong>
            </header>
            <div class="chat-list" ref="chatListRef">
              <article v-for="(log, index) in chatLogs" :key="index" class="chat-bubble">
                <span>DAY {{ log.day }} · {{ log.phase }}</span>
                <p><b>{{ logSpeaker(log) }}</b>{{ logMessage(log) }}</p>
              </article>
            </div>
            <section v-if="!isWatch && !isReplayMode" class="player-actions">
                <input v-if="game.waiting_for === 'speech'" v-model="speech" :disabled="loading" placeholder="输入你的发言..." />
                <button v-if="game.waiting_for === 'speech'" class="primary" @click="submitSpeech" :disabled="loading">提交发言</button>
                <select v-if="game.waiting_for === 'vote'" v-model="voteTarget">
              <option v-for="p in canVotePlayers" :key="p.id" :value="p.id">{{ playerLabel(p) }}</option>
                </select>
                <button v-if="game.waiting_for === 'vote'" class="primary" @click="submitVote" :disabled="loading">提交投票</button>
                <button v-if="game.waiting_for === 'none'" class="primary" @click="stepGame" :disabled="loading || game.winner">继续</button>
            </section>
          </aside>

          <main class="board-stage">
            <Transition name="player-command-in">
              <section v-if="roleAssignmentComplete && !isWatch && !isReplayMode" class="player-command-panel">
                <div class="player-skill-bar">
                  <span class="player-seat-chip">
                    <img v-if="humanPlayer" :src="roleIconImage(humanPlayer)" :alt="roleName" />
                    <b>{{ humanPlayer ? playerLabel(humanPlayer) : '玩家' }}</b>
                    <em>{{ roleName }}</em>
                  </span>
                  <div class="skill-card-stage">
                    <div v-if="isHumanWitch" class="skill-card-row">
                      <button class="skill-card image-card witch-antidote-card" :class="{ active: witchChoice === 'antidote', used: skillState.witch_antidote_used }" :disabled="loading || !canUseWitchAntidote" @click="witchChoice = 'antidote'" title="使用解药" aria-label="使用解药"></button>
                      <button class="skill-card image-card witch-poison-card" :class="{ active: witchChoice === 'poison', used: skillState.witch_poison_used }" :disabled="loading || !canUseWitchPoison" @click="witchChoice = 'poison'" title="使用毒药" aria-label="使用毒药"></button>
                      <button v-if="pendingActionType === 'witch_act'" class="skip-skill-link" :class="{ active: witchChoice === 'skip' }" @click="witchChoice = 'skip'; submitAction('witch_act', null, 'skip')" :disabled="loading">跳过</button>
                    </div>
                    <button v-if="isHumanWhiteWolf" class="skill-card image-card white-wolf-card" :class="{ active: burstArmed, used: skillState.white_wolf_burst_used }" @click="burstArmed = !burstArmed" :disabled="loading || !canWhiteWolfBurst" title="白狼王自爆" aria-label="白狼王自爆"></button>
                  </div>
                  <div class="skill-status-side">
                    <time v-if="game.waiting_for === 'speech'" class="speech-countdown">{{ speechCountdownText }}</time>
                  </div>
                </div>
                <form class="player-chat-box" @submit.prevent="submitSpeech()">
                  <textarea v-model="speech" :disabled="loading" placeholder="输入你的发言..."></textarea>
                  <button class="primary" :disabled="loading || game.waiting_for !== 'speech'">发送</button>
                </form>
              </section>
            </Transition>
            <section v-if="roleAssignmentComplete" class="square-board">
              <section class="speaker-core">
                <header>
                  <span>DAY {{ game.day }}</span>
                  <i>{{ isNight ? '☾' : '☀' }}</i>
                  <b>{{ isNight ? '黑夜' : '白天' }}</b>
                </header>
                <div class="speaker-carousel">
                  <article v-for="item in speakerCarousel" :key="item.key" :class="['speaker-avatar', item.tone]">
                    <img :src="item.image" alt="发言者" />
                    <strong>{{ item.label }}</strong>
                  </article>
                </div>
                <div class="speaker-message-slot">
                  <Transition name="message-slide">
                    <p :key="'message-' + (game.current_speaker_id || game.phase)">{{ speakerMessage }}</p>
                  </Transition>
                </div>
              </section>
            </section>
          </main>

          <Transition name="role-grid-in">
          <aside v-if="roleAssignmentComplete" class="info-stack">
            <section class="judge-panel match-panel">
              <header>
                <span>法官日志</span>
                <strong>{{ displayPhase }}</strong>
              </header>
              <div class="judge-list" ref="judgeListRef">
                <div v-for="group in groupedJudgeLogs" :key="group.key" class="log-group">
                  <div class="log-group-header">
                    <span class="log-day">DAY {{ group.day }}</span>
                    <span class="log-phase">{{ group.phaseLabel }}</span>
                    <span class="log-phase-icon">{{ group.phase === 'night' ? '☾' : '☀' }}</span>
                  </div>
                  <article v-for="(log, index) in group.logs" :key="index" class="log-entry">
                    <span class="log-speaker">{{ logSpeaker(log) }}</span>
                    <p class="log-message">{{ logMessage(log) }}</p>
                  </article>
                </div>
              </div>
            </section>
            <section class="identity-panel match-panel">
              <header>
                <span>本局身份</span>
                <strong>{{ livingPlayers.length }} / {{ game.player_count }} 存活</strong>
              </header>
              <div class="identity-list">
                <article v-for="item in roleStats" :key="item.role">
                  <b>{{ item.role }}</b>
                  <span>{{ item.alive }}/{{ item.total }}</span>
                </article>
              </div>
            </section>
          </aside>
          </Transition>
        </section>
      </template>

      <div v-if="error" class="toast">{{ error }}</div>
    </main>
  `
}).mount('#app')
