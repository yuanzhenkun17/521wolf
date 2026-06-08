const MOCK_STEP_DELAY_MS = {
  setup: 420,
  night: 950,
  result: 760,
  speech: 1450,
  vote: 1050,
  ended: 520
}

const BASE_PLAYERS = [
  { id: 1, seat: 1, name: '沈临川' },
  { id: 2, seat: 2, name: '林祈' },
  { id: 3, seat: 3, name: '周止' },
  { id: 4, seat: 4, name: '顾砚' },
  { id: 5, seat: 5, name: '许望' },
  { id: 6, seat: 6, name: '唐棠' },
  { id: 7, seat: 7, name: '秦越' },
  { id: 8, seat: 8, name: '叶知秋' },
  { id: 9, seat: 9, name: '陆青' },
  { id: 10, seat: 10, name: '韩霜' },
  { id: 11, seat: 11, name: '苏眠' },
  { id: 12, seat: 12, name: '程野' }
]

const ROLE_DECK = [
  '平民', '平民', '平民', '平民',
  '狼人', '狼人', '狼人',
  '白狼王',
  '守卫',
  '女巫',
  '预言家',
  '猎人'
]

export const MOCK_LEADERBOARD = [
  { role: '预言家', version: 'v3', winRate: 72.5, color: '#4a9eff' },
  { role: '女巫', version: 'v1', winRate: 68.2, color: '#9b59b6' },
  { role: '猎人', version: 'v2', winRate: 65.8, color: '#e74c3c' },
  { role: '守卫', version: 'v1', winRate: 62.3, color: '#2ecc71' },
  { role: '白狼王', version: 'v1', winRate: 58.1, color: '#e67e22' },
  { role: '狼人', version: 'v2', winRate: 54.6, color: '#c0392b' },
  { role: '平民', version: 'v1', winRate: 48.9, color: '#7f8c8d' },
  { role: '预言家', version: 'v1', winRate: 52.3, color: '#3498db' },
  { role: '预言家', version: 'v2', winRate: 64.8, color: '#5dade2' }
]

export const MOCK_ROLE_COUNTS = {
  平民: 4,
  狼人: 3,
  白狼王: 1,
  守卫: 1,
  女巫: 1,
  预言家: 1,
  猎人: 1
}

const MOCK_EVOLUTION_ROLES = [
  'white_wolf_king',
  'werewolf',
  'villager',
  'seer',
  'witch',
  'hunter',
  'guard'
]

const MOCK_EVOLUTION_LABELS = {
  white_wolf_king: '白狼王',
  werewolf: '狼人',
  villager: '村民',
  seer: '预言家',
  witch: '女巫',
  hunter: '猎人',
  guard: '守卫'
}

const mockEvolutionVersions = Object.fromEntries(MOCK_EVOLUTION_ROLES.map((role, index) => [
  role,
  [
    {
      version_id: `base-${role}-20260604`,
      role,
      source: 'baseline',
      created_at: `2026-06-04T0${index % 4}:12:00`,
      is_baseline: true
    },
    {
      version_id: `cand-${role}-review-a${index + 1}`,
      role,
      source: 'evolution',
      created_at: `2026-06-05T1${index % 4}:24:00`,
      is_baseline: false
    }
  ]
]))

let mockEvolutionCounter = 3

const mockEvolutionRuns = [
  {
    kind: 'role_evolution_run',
    schema_version: 1,
    run_id: 'mock-evo-seer-review',
    role: 'seer',
    status: 'reviewing',
    stage: 'reviewing',
    current_stage: 'reviewing',
    started_at: '2026-06-05T08:20:00',
    parent_hash: 'base-seer-20260604',
    candidate_hash: 'cand-seer-review-a4',
    config: { roles: ['seer'], training_games: 5, battle_games: 4, max_days: 5, auto_promote: true },
    training_games: 5,
    battle_games: 4,
    training_completed: 5,
    battle_completed: 8,
    battle_result: {
      target_team: 'villagers',
      candidate: { target_win_rate: 0.64 },
      baseline: { target_win_rate: 0.55 },
      candidate_win_rate: 0.64,
      baseline_win_rate: 0.55,
      win_rate_delta: 0.09,
      significant: false,
      recommendation: 'promote'
    },
    combined_battle_result: {
      target_team: 'villagers',
      candidate: { target_win_rate: 0.64 },
      baseline: { target_win_rate: 0.55 },
      candidate_win_rate: 0.64,
      baseline_win_rate: 0.55,
      win_rate_delta: 0.09,
      significant: false,
      recommendation: 'promote'
    }
  },
  {
    kind: 'role_evolution_run',
    schema_version: 1,
    run_id: 'mock-evo-witch-active',
    role: 'witch',
    status: 'battling',
    stage: 'battling',
    current_stage: 'battling',
    started_at: '2026-06-05T07:35:00',
    parent_hash: 'base-witch-20260604',
    candidate_hash: 'cand-witch-review-a5',
    config: { roles: ['witch'], training_games: 5, battle_games: 4, max_days: 5, auto_promote: true },
    training_games: 5,
    battle_games: 4,
    training_completed: 5,
    battle_completed: 4,
    battle_result: {
      candidate: { avg_role_weighted_score: 0.61, target_side_win_rate: 0.59 },
      baseline: { avg_role_weighted_score: 0.57, target_side_win_rate: 0.53 },
      recommendation: 'pending'
    }
  }
]

const mockEvolutionBatches = [
  {
    kind: 'role_evolution_batch',
    schema_version: 1,
    batch_id: 'mock-batch-all-roles',
    roles: MOCK_EVOLUTION_ROLES,
    status: 'combined_battling',
    stage: 'combined_battling',
    current_stage: 'combined_battling',
    started_at: '2026-06-05T06:10:00',
    config: { roles: MOCK_EVOLUTION_ROLES, training_games: 5, battle_games: 4, max_days: 5, auto_promote: true },
    training_games: 5,
    battle_games: 4,
    training_completed: 35,
    battle_completed: 28,
    runs: ['mock-evo-seer-review', 'mock-evo-witch-active']
  }
]

let mockBenchmarkCounter = 1

const mockBenchmarkBatches = [
  {
    kind: 'benchmark_batch',
    schema_version: 1,
    batch_id: 'mock-bench-model-villager',
    roles: ['villager'],
    status: 'completed',
    started_at: '2026-06-05T09:20:00',
    finished_at: '2026-06-05T09:24:00',
    config: { roles: ['villager'], battle_games: 10, max_days: 5 },
    result: {
      batch_id: 'mock-bench-model-villager',
      game_count: 10,
      completed: 10,
      errored: 0,
      score_summary: {
        game_count: 10,
        decision_judge_aggregate: {
          status: 'ok',
          game_count: 10,
          reported_games: 10,
          judged_decisions: 10,
          failed_decisions: 0,
          avg_score: 7.4,
          bad_rate: 0.2,
          unknown_rate: 0.1,
          quality_counts: { good: 5, ok: 3, bad: 2 },
          top_mistake_tags: [
            { tag: 'low_information_gain', count: 2 },
            { tag: 'vote_alignment', count: 1 }
          ],
          by_role: { villager: { count: 10, avg_score: 7.4, bad_rate: 0.2, unknown_rate: 0.1 } },
          by_action_type: { exile_vote: { count: 6, avg_score: 7.0, bad_rate: 0.17, unknown_rate: 0 } },
          lowest_decisions: []
        }
      },
      fairness: { is_fair: true, reason: 'mock' },
      rankable: true,
      rankable_reason: ''
    }
  }
]

const mockEvolutionDiffs = {
  'mock-evo-seer-review': [
    { filename: 'speech.md', action: 'rewrite', proposal_ref: 'mock-proposal-seer-1' },
    { filename: 'claim.md', action: 'tighten', proposal_ref: 'mock-proposal-seer-2' },
    { filename: 'vote.md', action: 'append', proposal_ref: 'mock-proposal-seer-3' }
  ],
  'mock-evo-witch-active': [
    { filename: 'night.md', action: 'append', proposal_ref: 'mock-proposal-witch-1' },
    { filename: 'poison.md', action: 'rewrite', proposal_ref: 'mock-proposal-witch-2' }
  ],
  'mock-batch-all-roles': [
    { filename: 'batch_summary.md', action: 'merge', proposal_ref: 'mock-proposal-batch-1' }
  ]
}

const mockBattleLeaderboardEntries = [
  { role: 'seer', label: '预言家 baseline', version_id: 'base-seer-20260604', score: 0.61, win_rate: 0.58, total_games: 40, source: 'battle' },
  { role: 'seer', label: '预言家 candidate', version_id: 'cand-seer-review-a4', score: 0.67, win_rate: 0.64, total_games: 40, source: 'battle' },
  { role: 'witch', label: '女巫 baseline', version_id: 'base-witch-20260604', score: 0.57, win_rate: 0.53, total_games: 36, source: 'battle' },
  { role: 'guard', label: '守卫 candidate', version_id: 'cand-guard-review-a7', score: 0.62, win_rate: 0.59, total_games: 28, source: 'battle' }
]

let mockSelfplayCounter = 2

const mockSelfplayRuns = [
  {
    run_id: 'mock-selfplay-eval-a',
    status: 'completed',
    progress: { completed: 12, total: 12 },
    num_games: 12,
    completed_games: 12,
    label: 'baseline-eval',
    agent_version: 'agent',
    skill_dir: '',
    max_days: 20,
    enable_sheriff: true,
    enable_batch_dream: false,
    created_at: '2026-06-05T08:40:00',
    started_at: '2026-06-05T08:40:00',
    artifact_run_id: 'mock-selfplay-eval-a',
    summary: { good: 7, werewolves: 5 }
  },
  {
    run_id: 'mock-selfplay-live-b',
    status: 'running',
    progress: { completed: 3, total: 10 },
    num_games: 10,
    completed_games: 3,
    label: 'candidate-smoke',
    agent_version: 'cand-seer-review-a4',
    skill_dir: 'skills/candidates/seer',
    max_days: 20,
    enable_sheriff: true,
    enable_batch_dream: true,
    created_at: '2026-06-05T10:10:00',
    started_at: '2026-06-05T10:10:00',
    artifact_run_id: 'mock-selfplay-live-b'
  }
]

function clone(value) {
  return JSON.parse(JSON.stringify(value))
}

function cloneSelfplayRun(run) {
  const copy = clone(run)
  delete copy._leaderboard_published
  return copy
}

function sleep(ms) {
  return new Promise((resolve) => globalThis.setTimeout(resolve, ms))
}

function shuffle(items) {
  const next = items.slice()
  for (let i = next.length - 1; i > 0; i--) {
    const j = Math.floor(Math.random() * (i + 1))
    ;[next[i], next[j]] = [next[j], next[i]]
  }
  return next
}

function label(player) {
  return `${player?.seat ?? player?.id ?? '?'}号`
}

function findRole(game, role) {
  return game.players.find((player) => player.role_hint === role)
}

function findRoles(game, role) {
  return game.players.filter((player) => player.role_hint === role)
}

function goodPlayers(game) {
  return game.players.filter((player) => !['狼人', '白狼王'].includes(player.role_hint))
}

function wolfPlayers(game) {
  return game.players.filter((player) => ['狼人', '白狼王'].includes(player.role_hint))
}

function makeLog(game, patch) {
  return {
    sequence: ++game.sequence,
    day: game.day,
    phase: game.phase,
    visibility: 'public',
    type: patch.action || patch.type || 'info',
    event_type: patch.action || patch.type || 'info',
    source: patch.source || 'mock',
    ...patch
  }
}

function makeDecision(game, patch) {
  const actor = game.players.find((player) => player.id === patch.actor_id)
  const target = game.players.find((player) => player.id === patch.target_id)
  return {
    id: game.decisions.length + 1,
    day: game.day,
    phase: game.phase,
    actor_id: patch.actor_id,
    actor_name: actor ? label(actor) : '系统',
    target_id: patch.target_id ?? null,
    target_name: target ? label(target) : '无目标',
    role: actor?.role_hint || '',
    action: patch.action,
    reason: patch.reason || patch.message || '',
    public_summary: patch.public_summary || patch.message || '',
    private_reasoning: patch.private_reasoning || patch.reason || '',
    confidence: patch.confidence ?? 0.72,
    source: patch.source || 'mock',
    selected_skill: patch.selected_skill || '',
    memory_summary: patch.memory_summary || [
      '记录首夜技能行动与预言家报验信息。',
      '持续追踪警徽流、站边关系和狼队互保可能。',
      '投票阶段优先观察跟票轻重和临场改票。'
    ],
    candidates: patch.candidates || game.players
      .filter((player) => player.alive && player.id !== patch.actor_id)
      .slice(0, 5)
      .map((player) => ({ id: player.id, seat: player.seat, role: player.role_hint })),
    alternatives: patch.alternatives || [],
    policy_adjustments: patch.source === 'policy_adjusted' ? ['只展示公开可见的 agent 决策摘要。'] : [],
    errors: []
  }
}

function assignRandomRoles(mode = 'watch') {
  const roles = shuffle(ROLE_DECK)
  return BASE_PLAYERS.map((player, index) => ({
    ...player,
    role_hint: roles[index],
    alive: true,
    is_human: mode === 'play' && player.id === 1
  }))
}

function buildContext(game) {
  const seer = findRole(game, '预言家')
  const witch = findRole(game, '女巫')
  const guard = findRole(game, '守卫')
  const hunter = findRole(game, '猎人')
  const whiteWolf = findRole(game, '白狼王')
  const wolves = findRoles(game, '狼人')
  const villagers = findRoles(game, '平民')
  const gold = goodPlayers(game).find((player) => player.id !== seer?.id) || villagers[0] || hunter || witch || guard
  const mainTarget = whiteWolf || wolves[0] || game.players.find((player) => player.id !== seer?.id)
  const secondTarget = wolves.find((player) => player.id !== mainTarget?.id) || villagers.find((player) => player.id !== gold?.id) || game.players.find((player) => player.id !== mainTarget?.id)
  return { seer, witch, guard, hunter, whiteWolf, wolves, villagers, gold, mainTarget, secondTarget }
}

function createNightDecisions(game) {
  const ctx = game.mockContext
  const wolf = ctx.wolves[0] || ctx.whiteWolf
  return [
    {
      actor_id: ctx.guard?.id,
      action: 'guard_protect',
      target_id: ctx.seer?.id,
      reason: `${label(ctx.guard)}守卫首夜优先保护${label(ctx.seer)}，防止关键查验位被狼队直接压掉。`,
      public_summary: '守卫完成守护选择。',
      source: 'tot',
      confidence: 0.77
    },
    {
      actor_id: wolf?.id,
      action: 'werewolf_kill',
      target_id: ctx.seer?.id,
      reason: `狼队决定袭击${label(ctx.seer)}，目标是尽早切断预言家信息源。`,
      public_summary: '狼人团队完成夜间袭击选择。',
      source: 'got',
      confidence: 0.84
    },
    {
      actor_id: ctx.seer?.id,
      action: 'seer_check',
      target_id: ctx.gold?.id,
      reason: `${label(ctx.seer)}查验${label(ctx.gold)}，希望在白天建立一个可归票的好人支点。`,
      public_summary: `预言家查验${label(ctx.gold)}为好人。`,
      source: 'llm',
      confidence: 0.9
    },
    {
      actor_id: ctx.witch?.id,
      action: 'witch_act',
      target_id: null,
      selected_skill: 'skip',
      reason: `${label(ctx.witch)}女巫判断首夜信息不足，选择保留解药和毒药，等待白天发言形成更清晰的狼坑。`,
      public_summary: '女巫选择不使用药剂。',
      source: 'policy_adjusted',
      confidence: 0.72
    }
  ].filter((decision) => decision.actor_id)
}

function speechForPlayer(game, player, index) {
  const ctx = game.mockContext
  const seerNo = label(ctx.seer)
  const goldNo = label(ctx.gold)
  const targetNo = label(ctx.mainTarget)
  const secondNo = label(ctx.secondTarget)
  const selfNo = label(player)
  const source = ['got', 'tot', 'llm', 'policy_adjusted', 'fallback'][index % 5]

  if (player.id === ctx.seer?.id) {
    return {
      actor_id: player.id,
      action: 'speak',
      source,
      confidence: 0.88,
      message: `我是${selfNo}，预言家。昨晚查验${goldNo}，结果是好人。我的第一警徽流压${targetNo}，第二警徽流压${secondNo}：${targetNo}在夜间收益上最像狼队核心，${secondNo}的站边空间也需要被压缩。女巫和守卫先不要急着交身份，今天重点听${targetNo}、${secondNo}以及后置位对我查验的反馈。如果有人只打我“报验太快”却不给完整狼坑，我会把他放进明天的优先验人或放逐池。`
    }
  }

  if (player.id === ctx.gold?.id) {
    return {
      actor_id: player.id,
      action: 'speak',
      source,
      confidence: 0.84,
      message: `${selfNo}接${seerNo}的金水。我暂时不替${seerNo}无条件背书，但这个查验对好人有用。今天我会帮大家看三件事：第一，${targetNo}是不是在拆信息源；第二，${secondNo}有没有只打状态不打逻辑；第三，狼队有没有借我的金水身份来制造“金水带队”的假安全感。我的建议是先把票型集中到${targetNo}附近，别让散票给狼队藏刀。`
    }
  }

  if (player.role_hint === '白狼王') {
    return {
      actor_id: player.id,
      action: 'speak',
      source,
      confidence: 0.82,
      message: `${selfNo}发言。我不认${seerNo}一定是真预，因为他一上来就把${targetNo}和${secondNo}框进警徽流，像是提前写好了抗推路线。真正的好人视角应该先看发言反馈，而不是只靠首夜一张金水牌压全场。今天如果大家只因为我是焦点位就跟票，我会认为狼队在借${seerNo}的力度推简单局。我更想听${secondNo}给完整站边，再决定票往哪里走。`
    }
  }

  if (player.role_hint === '狼人') {
    return {
      actor_id: player.id,
      action: 'speak',
      source,
      confidence: 0.76,
      message: `${selfNo}这里先不急着站死边。${seerNo}有验人信息，这是加分点，但他对${targetNo}的压制太早，也可能是在找方便归票的位置。我觉得${secondNo}比${targetNo}更需要解释，因为${secondNo}一直在评价别人，却没有承担自己的投票成本。今天我不会散票，我会在${targetNo}和${secondNo}之间选一个更像狼的点，但希望大家别被单一信息源完全带走。`
    }
  }

  if (player.role_hint === '女巫') {
    return {
      actor_id: player.id,
      action: 'speak',
      source,
      confidence: 0.79,
      message: `${selfNo}女巫视角先不聊夜里细节。${seerNo}报${goldNo}金水，我先接住，但我更关注${targetNo}的防御姿态和${secondNo}的跟票轻重。好人今天不要逼神职交太多信息，狼队最希望把技能牌提前压出来。我的票目前偏向${targetNo}，但如果后置位出现强行保${targetNo}、同时踩${seerNo}的人，我会把那个人一起放进狼坑。`
    }
  }

  if (player.role_hint === '守卫') {
    return {
      actor_id: player.id,
      action: 'speak',
      source,
      confidence: 0.78,
      message: `${selfNo}是一张偏防守的好人牌。${seerNo}的发言至少给了查验、警徽流和后续验人路线，信息完整度够高。${targetNo}如果是好人，应该解释自己视角里的狼队结构，而不是只说自己被抗推。${secondNo}也不能只做旁观评价。今天我希望大家集中票型，先让一个核心焦点位出局，再根据明天查验和票型继续推进。`
    }
  }

  if (player.role_hint === '猎人') {
    return {
      actor_id: player.id,
      action: 'speak',
      source,
      confidence: 0.8,
      message: `${selfNo}猎人牌，先给态度：我暂时站${seerNo}边，但不把${goldNo}当绝对指挥。${targetNo}最像狼的地方是防御比找狼更重，${secondNo}的问题是一直保留退路。今天如果归${targetNo}，我能跟；如果临场有人把票硬转到低存在感平民位，我会认为那是狼队在救核心。我的枪口视角也会优先盯这些临场改票的人。`
    }
  }

  return {
    actor_id: player.id,
    action: 'speak',
    source,
    confidence: 0.73,
    message: `${selfNo}平民视角。我没有夜间信息，只看发言链。${seerNo}目前像真预的点是敢报${goldNo}金水并给出${targetNo}、${secondNo}两段警徽流；可疑点是压力给得很早。${targetNo}的回应如果只停留在“我被打了”，没有给出反向狼坑，那就很像狼。${secondNo}如果继续两边都留余地，也要进票池。我的倾向是先跟主票型，不给狼队散票操作空间。`
  }
}

function createDialogues(game) {
  return game.players.map((player, index) => speechForPlayer(game, player, index))
}

function createVoteRows(game) {
  const ctx = game.mockContext
  const target = ctx.mainTarget
  const second = ctx.secondTarget
  const third = game.players.find((player) => player.id !== target?.id && player.id !== second?.id && player.id !== ctx.seer?.id) || ctx.gold
  const votersForTarget = game.players.filter((player) => player.id !== target?.id).slice(0, 8).map((player) => player.id)
  const rest = game.players.map((player) => player.id).filter((id) => !votersForTarget.includes(id))
  return {
    target,
    second,
    third,
    tally: [
      { target_id: target?.id, count: votersForTarget.length, voter_ids: votersForTarget },
      { target_id: second?.id, count: Math.min(2, rest.length), voter_ids: rest.slice(0, 2) },
      { target_id: third?.id, count: Math.max(0, rest.length - 2), voter_ids: rest.slice(2) }
    ].filter((row) => row.target_id && row.count > 0)
  }
}

function createVoteEvents(game, voteRows) {
  const rowsByVoter = []
  voteRows.tally.forEach((row) => {
    row.voter_ids.forEach((voterId) => {
      rowsByVoter.push({ voterId, targetId: row.target_id })
    })
  })
  return rowsByVoter.map(({ voterId, targetId }, index) => {
    const voter = game.players.find((player) => player.id === voterId)
    const target = game.players.find((player) => player.id === targetId)
    const source = ['got', 'tot', 'llm', 'policy_adjusted'][index % 4]
    const message = `${label(voter)}投票给${label(target)}。理由：结合白天发言、预言家视角和票型收益，这一票优先压缩${label(target)}的生存空间。`
    return {
      phase: 'vote',
      decision: {
        actor_id: voterId,
        action: 'vote',
        target_id: targetId,
        reason: message,
        public_summary: message,
        source,
        confidence: 0.68 + (index % 4) * 0.05
      },
      log: {
        speaker: label(voter),
        actor_id: voterId,
        target_id: targetId,
        message,
        visibility: 'public',
        type: 'vote',
        source
      }
    }
  })
}

function baseGame(mode = 'watch', scenario = 'good_win') {
  const game = {
    game_id: `mock-agent-${Date.now()}`,
    log_name: 'Mock 多 Agent 狼人杀测试局',
    mode,
    scenario,
    day: 1,
    phase: 'setup',
    seed: null,
    max_days: 20,
    enable_sheriff: true,
    skill_dir: '',
    role_skill_dirs: {},
    config: {},
    player_count: 12,
    players: assignRandomRoles(mode),
    role_counts: clone(MOCK_ROLE_COUNTS),
    logs: [],
    decisions: [],
    current_speaker_id: null,
    human_player_id: mode === 'play' ? 1 : null,
    waiting_for: 'none',
    pending_action: null,
    pending_human_action: null,
    skill_state: {
      witch_antidote_used: false,
      witch_poison_used: false,
      white_wolf_burst_used: false
    },
    sheriff_id: null,
    vote_tally: [],
    winner: null,
    sequence: 0,
    timelineIndex: 0,
    timeline: []
  }
  applyStartConfig(game)
  game.mockContext = buildContext(game)
  game.timeline = scenario === 'wolf_win' ? createWolfWinTimeline(game)
    : scenario === 'long_game' ? createLongGameTimeline(game)
    : createTimeline(game)
  return game
}

function applyStartConfig(game, body = {}) {
  const roleSkillDirs = body.role_skill_dirs || body.role_versions || game.role_skill_dirs || {}
  const humanPlayerId = body.human_player_id === undefined ? game.human_player_id : body.human_player_id
  game.seed = body.seed ?? game.seed ?? null
  game.max_days = Number(body.max_days || game.max_days || 20)
  game.enable_sheriff = body.enable_sheriff === undefined ? game.enable_sheriff !== false : body.enable_sheriff !== false
  game.skill_dir = body.skill_dir || game.skill_dir || ''
  game.role_skill_dirs = { ...roleSkillDirs }
  game.player_count = Number(body.player_count || game.player_count || 12)
  game.human_player_id = humanPlayerId == null ? null : Number(humanPlayerId)
  game.players.forEach((player) => {
    player.is_human = game.human_player_id != null && player.id === game.human_player_id
  })
  game.config = {
    seed: game.seed,
    max_days: game.max_days,
    enable_sheriff: game.enable_sheriff,
    skill_dir: game.skill_dir,
    role_skill_dirs: { ...game.role_skill_dirs },
    player_count: game.player_count,
    human_player_id: game.human_player_id
  }
  return game
}

// === 新增辅助函数 ===

function createVoteRowsForPhase(alivePlayers, targetPlayer, secondPlayer) {
  const votersForTarget = alivePlayers
    .filter(p => p.id !== targetPlayer?.id)
    .slice(0, Math.max(1, Math.ceil(alivePlayers.length * 0.75)))
    .map(p => p.id)
  const votersForSecond = alivePlayers
    .filter(p => p.id !== targetPlayer?.id && !votersForTarget.includes(p.id))
    .map(p => p.id)
  return {
    target: targetPlayer,
    second: secondPlayer,
    tally: [
      { target_id: targetPlayer?.id, count: votersForTarget.length, voter_ids: votersForTarget },
      { target_id: secondPlayer?.id, count: votersForSecond.length, voter_ids: votersForSecond }
    ].filter(row => row.target_id && row.count > 0)
  }
}

function speechForDay2(game, player, ctx) {
  const selfNo = label(player)
  const seerNo = label(ctx.seer)
  const w1No = label(ctx.wolves[1])
  const w0No = label(ctx.wolves[0])
  const goldNo = label(ctx.gold)
  const source = ['got', 'tot', 'llm', 'policy_adjusted'][game.players.indexOf(player) % 4]

  if (player.id === ctx.seer?.id) {
    return {
      actor_id: player.id, action: 'speak', source,
      confidence: 0.92,
      message: `${selfNo}预言家报验：昨晚查验${w1No}，结果是狼人。第一天归了白狼王，今天必须归${w1No}。我的警徽流先压${w0No}，如果今天${w1No}出局，明天继续追${w0No}。所有人跟票，不要散。`
    }
  }
  if (player.id === ctx.wolves[1]?.id) {
    return {
      actor_id: player.id, action: 'speak', source,
      confidence: 0.74,
      message: `${selfNo}不认${seerNo}的查验。第一天归白狼王已经损失一个队友，今天再归我就是好人碾压局。${seerNo}可能是假预或者被对跳操控，我请求大家再听一轮完整发言再做决定。`
    }
  }
  if (player.id === ctx.wolves[0]?.id) {
    return {
      actor_id: player.id, action: 'speak', source,
      confidence: 0.72,
      message: `${selfNo}发言。${seerNo}报${w1No}查验，力度够，但我不完全站死边。${w1No}的回应如果能给出完整反向狼坑，还有翻盘空间。我暂时保留投票方向，听完后置位再做决定。`
    }
  }
  if (player.role_hint === '女巫') {
    return {
      actor_id: player.id, action: 'speak', source,
      confidence: 0.85,
      message: `${selfNo}女巫发言。昨夜有人出局，同时也有人非正常死亡。今天我站${seerNo}边，归${w1No}。场上狼队空间已经很窄，不能给狼队任何翻盘机会。`
    }
  }
  if (player.role_hint === '守卫') {
    return {
      actor_id: player.id, action: 'speak', source,
      confidence: 0.82,
      message: `${selfNo}守卫发言。${seerNo}两夜查验结果一致指向狼队，可信度很高。今天归${w1No}是合理选择，我也跟票。如果有人试图把票型转到低存在感好人位，那很可能是狼队在保核心。`
    }
  }
  if (player.id === ctx.gold?.id) {
    return {
      actor_id: player.id, action: 'speak', source,
      confidence: 0.83,
      message: `${selfNo}金水发言。${seerNo}第一天给我金水，第二天查${w1No}出狼，信息链完整。今天归${w1No}，明天追${w0No}，好人阵营可以收尾了。`
    }
  }
  return {
    actor_id: player.id, action: 'speak', source,
    confidence: 0.78,
    message: `${selfNo}平民视角。${seerNo}两夜查验指向明确，今天归${w1No}是最优选择。跟票，不散。`
  }
}

function speechForDay3(game, player, ctx) {
  const selfNo = label(player)
  const seerNo = label(ctx.seer)
  const w0No = label(ctx.wolves[0])
  const source = ['got', 'tot', 'llm'][game.players.indexOf(player) % 3]

  if (player.id === ctx.seer?.id) {
    return {
      actor_id: player.id, action: 'speak', source,
      confidence: 0.95,
      message: `${selfNo}预言家最后报验：昨晚查验${w0No}，结果是狼人。场上只剩这一匹狼，今天归${w0No}，游戏结束。所有人必须跟票，这是最后的机会。`
    }
  }
  if (['狼人', '白狼王'].includes(player.role_hint)) {
    return {
      actor_id: player.id, action: 'speak', source,
      confidence: 0.65,
      message: `${selfNo}发言。我不认${seerNo}的查验，场上还有变数。不要被单一信息源完全带走，最后一票要慎重。`
    }
  }
  if (player.role_hint === '女巫') {
    return {
      actor_id: player.id, action: 'speak', source,
      confidence: 0.88,
      message: `${selfNo}女巫发言。场上只剩一匹狼，今天必须归${w0No}。好人阵营已经锁定了狼坑，没有任何犹豫的空间。`
    }
  }
  if (player.role_hint === '守卫') {
    return {
      actor_id: player.id, action: 'speak', source,
      confidence: 0.86,
      message: `${selfNo}守卫发言。${seerNo}三夜查验全部指向狼队，信息链完整无缺。今天归${w0No}，结束战斗。`
    }
  }
  if (player.id === ctx.gold?.id) {
    return {
      actor_id: player.id, action: 'speak', source,
      confidence: 0.87,
      message: `${selfNo}金水发言。三天信息链完整，今天归${w0No}收尾。不要散票，不要犹豫。`
    }
  }
  return {
    actor_id: player.id, action: 'speak', source,
    confidence: 0.80,
    message: `${selfNo}平民发言。跟票${seerNo}，归${w0No}，结束游戏。`
  }
}

// === 重写 createTimeline ===

function createTimeline(game) {
  const ctx = game.mockContext
  const night1Decisions = createNightDecisions(game)
  const day1Dialogues = createDialogues(game)
  const day1VoteRows = createVoteRows(game)

  // ========== 死亡时间表（预先计算） ==========
  // Day1 放逐：白狼王（mainTarget 一定是 whiteWolf）
  const day1Exiled = ctx.whiteWolf || ctx.wolves[0]
  // Night2 狼刀：猎人；女巫毒：wolves[2]
  const night2WolfKill = ctx.hunter
  const night2Poisoned = ctx.wolves[2]
  // Day2 放逐：wolves[1]
  const day2Exiled = ctx.wolves[1]

  // 计算各阶段的存活玩家集合
  const deadAfterDay1 = new Set([day1Exiled?.id].filter(id => id != null))
  const deadAfterNight2 = new Set([day1Exiled?.id, night2WolfKill?.id, night2Poisoned?.id].filter(id => id != null))
  const deadAfterDay2 = new Set([...deadAfterNight2, day2Exiled?.id].filter(id => id != null))

  const aliveForDay2 = game.players.filter(p => !deadAfterNight2.has(p.id))
  const aliveForDay2Vote = aliveForDay2 // 投票在放逐之前

  // Night3 狼刀目标：找一个存活的平民
  const aliveGoodAfterDay2 = game.players.filter(p => !['狼人', '白狼王'].includes(p.role_hint) && !deadAfterDay2.has(p.id))
  const night3WolfKill = aliveGoodAfterDay2.find(p => p.role_hint === '平民') || aliveGoodAfterDay2[0]

  const deadAfterNight3 = new Set([...deadAfterDay2, night3WolfKill?.id].filter(id => id != null))
  const aliveForDay3 = game.players.filter(p => !deadAfterNight3.has(p.id))
  const aliveForDay3Vote = aliveForDay3

  // Day3 放逐目标：最后一匹活着的狼
  const day3Exiled = wolfPlayers(game).filter(p => !deadAfterNight3.has(p.id))[0] || ctx.wolves[0]

  // Night2/3 的狼刀行动者（第一匹存活狼）
  const night2WolfActor = wolfPlayers(game).filter(p => !deadAfterDay1.has(p.id))[0] || ctx.wolves[0]
  const night3WolfActor = wolfPlayers(game).filter(p => !deadAfterDay2.has(p.id))[0] || ctx.wolves[0]

  // Day2/3 的投票行和发言
  const day2SecondTarget = aliveForDay2.find(p => p.id !== day2Exiled?.id && p.id !== ctx.gold?.id && !['狼人', '白狼王'].includes(p.role_hint)) || ctx.gold
  const day2VoteRows = createVoteRowsForPhase(aliveForDay2Vote, day2Exiled, day2SecondTarget)
  const day2Speeches = aliveForDay2.map(p => speechForDay2(game, p, ctx))

  const day3SecondTarget = aliveForDay3.find(p => p.id !== day3Exiled?.id && !['狼人', '白狼王'].includes(p.role_hint)) || aliveForDay3.find(p => p.id !== day3Exiled?.id)
  const day3VoteRows = createVoteRowsForPhase(aliveForDay3Vote, day3Exiled, day3SecondTarget)
  const day3Speeches = aliveForDay3.map(p => speechForDay3(game, p, ctx))

  return [
    // === 准备阶段 ===
    {
      phase: 'setup',
      log: {
        speaker: '法官',
        message: '12名智能体入座完毕，座位身份已随机分配。',
        visibility: 'system',
        type: 'setup',
        role_assignments: game.players.map((p) => ({ seat: p.seat, name: p.name, role: p.role_hint }))
      }
    },

    // === 第1夜 ===
    ...night1Decisions.map((decision) => ({
      phase: 'night',
      day: 1,
      decision,
      log: {
        speaker: decision.action === 'werewolf_kill' ? '狼人团队' : label(game.players.find((player) => player.id === decision.actor_id)),
        actor_id: decision.actor_id,
        target_id: decision.target_id,
        message: decision.public_summary,
        visibility: decision.action === 'werewolf_kill' ? 'god' : 'public',
        type: decision.action,
        source: decision.source
      }
    })),
    {
      phase: 'result',
      day: 1,
      log: { speaker: '法官', message: '昨夜平安夜，没有玩家出局。白天发言开始。', visibility: 'system', type: 'night_result' }
    },

    // === 警长竞选 ===
    {
      phase: 'sheriff',
      day: 1,
      log: {
        speaker: '法官',
        message: '警长竞选开始。参与竞选的玩家请举手示意。',
        visibility: 'system',
        type: 'sheriff_start'
      }
    },
    ...game.players.slice(0, 4).map((player, index) => ({
      phase: 'sheriff',
      day: 1,
      decision: {
        actor_id: player.id,
        action: 'sheriff_speak',
        reason: `${label(player)}参与警长竞选，发表竞选宣言。${label(player)}表示愿意带领好人阵营走向胜利，承诺合理使用警徽流。`,
        public_summary: `${label(player)}参与警长竞选。`,
        source: ['got', 'tot', 'llm'][index % 3],
        confidence: 0.75 + index * 0.05
      },
      log: {
        speaker: label(player),
        actor_id: player.id,
        message: `${label(player)}参与警长竞选，希望大家支持。`,
        visibility: 'public',
        type: 'sheriff_speak',
        source: 'got'
      }
    })),
    {
      phase: 'sheriff',
      day: 1,
      decision: {
        actor_id: game.players[2]?.id,
        action: 'sheriff_withdraw',
        reason: `${label(game.players[2])}听完发言后选择退水，认为当前局势不适合自己担任警长。`,
        public_summary: `${label(game.players[2])}退水。`,
        source: 'tot',
        confidence: 0.65
      },
      log: {
        speaker: label(game.players[2]),
        actor_id: game.players[2]?.id,
        message: `${label(game.players[2])}选择退水。`,
        visibility: 'public',
        type: 'sheriff_withdraw',
        source: 'tot'
      }
    },

    // === 警长投票 ===
    ...game.players.slice(4, 9).map((player, index) => ({
      phase: 'sheriff_result',
      day: 1,
      decision: {
        actor_id: player.id,
        action: 'sheriff_vote',
        target_id: index < 3 ? ctx.seer?.id : ctx.hunter?.id,
        reason: index < 3
          ? `${label(player)}投票给${label(ctx.seer)}，认可其查验信息和警徽流规划。`
          : `${label(player)}投票给${label(ctx.hunter)}，认为猎人身份明确更适合带队。`,
        public_summary: `${label(player)}投票给${index < 3 ? label(ctx.seer) : label(ctx.hunter)}。`,
        source: ['got', 'tot', 'llm'][index % 3],
        confidence: 0.68 + (index % 4) * 0.06
      },
      log: {
        speaker: label(player),
        actor_id: player.id,
        target_id: index < 3 ? ctx.seer?.id : ctx.hunter?.id,
        message: `${label(player)}投票给${index < 3 ? label(ctx.seer) : label(ctx.hunter)}。`,
        visibility: 'public',
        type: 'sheriff_vote',
        source: 'got'
      }
    })),
    {
      phase: 'sheriff_result',
      day: 1,
      log: {
        speaker: '法官',
        message: `警长竞选结束，${label(ctx.seer)}当选警长。`,
        visibility: 'system',
        type: 'sheriff_result'
      },
      apply(nextGame) {
        nextGame.sheriff_id = ctx.seer?.id
      }
    },

    // === 第1天发言 ===
    ...day1Dialogues.map((dialogue) => ({
      phase: 'speech',
      day: 1,
      decision: {
        ...dialogue,
        reason: dialogue.message,
        public_summary: dialogue.message
      },
      log: {
        speaker: label(game.players.find((player) => player.id === dialogue.actor_id)),
        actor_id: dialogue.actor_id,
        message: dialogue.message,
        visibility: 'public',
        type: 'speech',
        source: dialogue.source
      }
    })),

    // === 第1天投票 ===
    {
      phase: 'vote',
      day: 1,
      log: {
        speaker: '法官',
        message: `发言结束，进入公投。当前主票型围绕${label(day1VoteRows.target)}、${label(day1VoteRows.second)}展开，所有 agent 开始独立计算投票收益。`,
        visibility: 'system',
        type: 'vote_prompt'
      }
    },
    ...createVoteEvents(game, day1VoteRows),
    {
      phase: 'vote',
      day: 1,
      decision: {
        actor_id: ctx.seer?.id,
        action: 'vote',
        target_id: day1VoteRows.target?.id,
        reason: `${label(ctx.seer)}按警徽流和白天发言强度投给${label(day1VoteRows.target)}。`,
        public_summary: `${label(ctx.seer)}投票给${label(day1VoteRows.target)}。`,
        source: 'got',
        confidence: 0.86
      },
      log: {
        speaker: label(ctx.seer),
        actor_id: ctx.seer?.id,
        target_id: day1VoteRows.target?.id,
        message: `我投${label(day1VoteRows.target)}，理由是这个位置持续拆信息源，却没有交出足够完整的反向狼坑。`,
        visibility: 'public',
        type: 'vote',
        source: 'got'
      }
    },
    {
      phase: 'vote',
      day: 1,
      log: {
        speaker: '法官',
        message: `公投结束：${label(day1VoteRows.target)}获得${day1VoteRows.tally[0]?.count || 0}票，被放逐出局。`,
        visibility: 'system',
        type: 'exile',
        target_id: day1VoteRows.target?.id
      },
      apply(nextGame) {
        const target = nextGame.players.find((player) => player.id === day1VoteRows.target?.id)
        if (target) target.alive = false
        nextGame.vote_tally = day1VoteRows.tally
      }
    },

    // === 第2夜 ===
    {
      phase: 'night',
      day: 2,
      log: {
        speaker: '法官',
        message: '天黑请闭眼。守卫、狼人、预言家、女巫正在行动。',
        visibility: 'system',
        type: 'night_start'
      }
    },
    // 守卫守护
    {
      phase: 'night',
      day: 2,
      decision: {
        actor_id: ctx.guard?.id,
        action: 'guard_protect',
        target_id: ctx.gold?.id,
        reason: `${label(ctx.guard)}守卫第二夜选择守护${label(ctx.gold)}，保护金水位不被狼队二次袭击。`,
        public_summary: '守卫完成守护选择。',
        source: 'tot',
        confidence: 0.79
      },
      log: {
        speaker: label(ctx.guard),
        actor_id: ctx.guard?.id,
        target_id: ctx.gold?.id,
        message: '守卫完成守护选择。',
        visibility: 'public',
        type: 'guard_protect',
        source: 'tot'
      }
    },
    // 狼人袭击猎人
    {
      phase: 'night',
      day: 2,
      decision: {
        actor_id: night2WolfActor?.id,
        action: 'werewolf_kill',
        target_id: ctx.hunter?.id,
        reason: `狼队决定袭击${label(ctx.hunter)}，削弱好人阵营的输出能力。`,
        public_summary: '狼人团队完成夜间袭击选择。',
        source: 'got',
        confidence: 0.82
      },
      log: {
        speaker: '狼人团队',
        actor_id: night2WolfActor?.id,
        target_id: ctx.hunter?.id,
        message: '狼人团队完成夜间袭击选择。',
        visibility: 'god',
        type: 'werewolf_kill',
        source: 'got'
      }
    },
    // 预言家查验wolves[1]
    {
      phase: 'night',
      day: 2,
      decision: {
        actor_id: ctx.seer?.id,
        action: 'seer_check',
        target_id: ctx.wolves[1]?.id,
        reason: `${label(ctx.seer)}查验${label(ctx.wolves[1])}，结果是狼人。`,
        public_summary: `预言家查验${label(ctx.wolves[1])}为狼人。`,
        source: 'llm',
        confidence: 0.92
      },
      log: {
        speaker: label(ctx.seer),
        actor_id: ctx.seer?.id,
        target_id: ctx.wolves[1]?.id,
        message: `预言家查验${label(ctx.wolves[1])}为狼人。`,
        visibility: 'public',
        type: 'seer_check',
        source: 'llm'
      }
    },
    // 女巫毒杀wolves[2]（新增！）
    {
      phase: 'night',
      day: 2,
      decision: {
        actor_id: ctx.witch?.id,
        action: 'witch_act',
        target_id: ctx.wolves[2]?.id,
        selected_skill: 'poison',
        reason: `${label(ctx.witch)}女巫判断${label(ctx.wolves[2])}是狼队成员，使用毒药将其带走。白天发言链和票型都指向狼队方向，毒杀${label(ctx.wolves[2])}可以加速好人收局。`,
        public_summary: '女巫使用毒药。',
        source: 'policy_adjusted',
        confidence: 0.82
      },
      log: {
        speaker: label(ctx.witch),
        actor_id: ctx.witch?.id,
        target_id: ctx.wolves[2]?.id,
        message: '女巫使用毒药。',
        visibility: 'public',
        type: 'witch_act',
        source: 'policy_adjusted'
      }
    },
    // Night2 结果：猎人和wolves[2]双双出局
    {
      phase: 'result',
      day: 2,
      log: {
        speaker: '法官',
        message: `昨夜${label(ctx.hunter)}号和${label(ctx.wolves[2])}号双双出局。`,
        visibility: 'system',
        type: 'night_result'
      },
      apply(nextGame) {
        const hunter = nextGame.players.find((player) => player.id === ctx.hunter?.id)
        if (hunter) hunter.alive = false
        const poisonedWolf = nextGame.players.find((player) => player.id === ctx.wolves[2]?.id)
        if (poisonedWolf) poisonedWolf.alive = false
      }
    },
    // 猎人遗言
    {
      phase: 'speech',
      day: 2,
      decision: {
        actor_id: ctx.hunter?.id,
        action: 'last_word',
        reason: `${label(ctx.hunter)}发表遗言：我是猎人，昨晚被刀了。我开枪带走${label(ctx.wolves[2])}。`,
        public_summary: `${label(ctx.hunter)}发表遗言：我是猎人，昨晚被刀了。我开枪带走${label(ctx.wolves[2])}。`,
        source: 'human',
        confidence: 1
      },
      log: {
        speaker: label(ctx.hunter),
        actor_id: ctx.hunter?.id,
        message: `${label(ctx.hunter)}发表遗言：我是猎人，昨晚被刀了。我开枪带走${label(ctx.wolves[2])}。`,
        visibility: 'public',
        type: 'last_word',
        source: 'human'
      }
    },

    // === 第2天发言（仅存活玩家） ===
    ...day2Speeches.map((speech) => ({
      phase: 'speech',
      day: 2,
      decision: {
        ...speech,
        reason: speech.message,
        public_summary: speech.message
      },
      log: {
        speaker: label(game.players.find((player) => player.id === speech.actor_id)),
        actor_id: speech.actor_id,
        message: speech.message,
        visibility: 'public',
        type: 'speech',
        source: speech.source
      }
    })),

    // === 第2天投票（全体存活玩家） ===
    {
      phase: 'vote',
      day: 2,
      log: {
        speaker: '法官',
        message: `发言结束，进入公投。当前主票型围绕${label(day2VoteRows.target)}展开。`,
        visibility: 'system',
        type: 'vote_prompt'
      }
    },
    ...createVoteEvents(game, day2VoteRows),
    {
      phase: 'vote',
      day: 2,
      log: {
        speaker: '法官',
        message: `公投结束：${label(day2VoteRows.target)}获得${day2VoteRows.tally[0]?.count || 0}票，被放逐出局。`,
        visibility: 'system',
        type: 'exile',
        target_id: day2VoteRows.target?.id
      },
      apply(nextGame) {
        const wolf = nextGame.players.find((player) => player.id === day2VoteRows.target?.id)
        if (wolf) wolf.alive = false
        nextGame.vote_tally = day2VoteRows.tally
      }
    },

    // === 第3夜 ===
    {
      phase: 'night',
      day: 3,
      log: {
        speaker: '法官',
        message: '天黑请闭眼。守卫、狼人、预言家正在行动。',
        visibility: 'system',
        type: 'night_start'
      }
    },
    // 守卫守护预言家
    {
      phase: 'night',
      day: 3,
      decision: {
        actor_id: ctx.guard?.id,
        action: 'guard_protect',
        target_id: ctx.seer?.id,
        reason: `${label(ctx.guard)}守卫第三夜守护${label(ctx.seer)}，确保预言家最后一夜查验顺利。`,
        public_summary: '守卫完成守护选择。',
        source: 'tot',
        confidence: 0.80
      },
      log: {
        speaker: label(ctx.guard),
        actor_id: ctx.guard?.id,
        target_id: ctx.seer?.id,
        message: '守卫完成守护选择。',
        visibility: 'public',
        type: 'guard_protect',
        source: 'tot'
      }
    },
    // 狼人袭击平民
    {
      phase: 'night',
      day: 3,
      decision: {
        actor_id: night3WolfActor?.id,
        action: 'werewolf_kill',
        target_id: night3WolfKill?.id,
        reason: `狼队决定袭击${label(night3WolfKill)}，最后一搏。`,
        public_summary: '狼人团队完成夜间袭击选择。',
        source: 'got',
        confidence: 0.85
      },
      log: {
        speaker: '狼人团队',
        actor_id: night3WolfActor?.id,
        target_id: night3WolfKill?.id,
        message: '狼人团队完成夜间袭击选择。',
        visibility: 'god',
        type: 'werewolf_kill',
        source: 'got'
      }
    },
    // 预言家查验wolves[0]
    {
      phase: 'night',
      day: 3,
      decision: {
        actor_id: ctx.seer?.id,
        action: 'seer_check',
        target_id: ctx.wolves[0]?.id,
        reason: `${label(ctx.seer)}查验${label(ctx.wolves[0])}，确认最后狼人身份。`,
        public_summary: `预言家查验${label(ctx.wolves[0])}为狼人。`,
        source: 'llm',
        confidence: 0.93
      },
      log: {
        speaker: label(ctx.seer),
        actor_id: ctx.seer?.id,
        target_id: ctx.wolves[0]?.id,
        message: `预言家查验${label(ctx.wolves[0])}为狼人。`,
        visibility: 'public',
        type: 'seer_check',
        source: 'llm'
      }
    },
    // 女巫不使用药剂
    {
      phase: 'night',
      day: 3,
      decision: {
        actor_id: ctx.witch?.id,
        action: 'witch_act',
        target_id: null,
        selected_skill: 'skip',
        reason: `${label(ctx.witch)}女巫判断场上只剩一匹狼，明天必定归票出局，不需要浪费解药。`,
        public_summary: '女巫选择不使用药剂。',
        source: 'policy_adjusted',
        confidence: 0.72
      },
      log: {
        speaker: label(ctx.witch),
        actor_id: ctx.witch?.id,
        message: '女巫选择不使用药剂。',
        visibility: 'public',
        type: 'witch_act',
        source: 'policy_adjusted'
      }
    },
    // Night3 结果：平民出局
    {
      phase: 'result',
      day: 3,
      log: {
        speaker: '法官',
        message: `昨夜${label(night3WolfKill)}被狼人袭击出局。`,
        visibility: 'system',
        type: 'night_result'
      },
      apply(nextGame) {
        const victim = nextGame.players.find((player) => player.id === night3WolfKill?.id)
        if (victim) victim.alive = false
      }
    },

    // === 第3天发言（仅存活玩家） ===
    ...day3Speeches.map((speech) => ({
      phase: 'speech',
      day: 3,
      decision: {
        ...speech,
        reason: speech.message,
        public_summary: speech.message
      },
      log: {
        speaker: label(game.players.find((player) => player.id === speech.actor_id)),
        actor_id: speech.actor_id,
        message: speech.message,
        visibility: 'public',
        type: 'speech',
        source: speech.source
      }
    })),

    // === 第3天投票（全体存活玩家） ===
    {
      phase: 'vote',
      day: 3,
      log: {
        speaker: '法官',
        message: `发言结束，进入公投。这是关键的一票，归${label(day3VoteRows.target)}游戏结束。`,
        visibility: 'system',
        type: 'vote_prompt'
      }
    },
    ...createVoteEvents(game, day3VoteRows),
    {
      phase: 'vote',
      day: 3,
      log: {
        speaker: '法官',
        message: `公投结束：${label(day3VoteRows.target)}获得${day3VoteRows.tally[0]?.count || 0}票，被放逐出局。`,
        visibility: 'system',
        type: 'exile',
        target_id: day3VoteRows.target?.id
      },
      apply(nextGame) {
        const wolf = nextGame.players.find((player) => player.id === day3VoteRows.target?.id)
        if (wolf) wolf.alive = false
        nextGame.vote_tally = day3VoteRows.tally
      }
    },

    // === 结果 ===
    {
      phase: 'ended',
      day: 3,
      log: {
        speaker: '系统',
        message: '好人阵营获胜！狼人全部出局。本局游戏结束。',
        visibility: 'system',
        type: 'game_over'
      },
      apply(nextGame) {
        nextGame.winner = '好人阵营获胜'
      }
    }
  ]
}

// === 狼人翻盘胜时间线 ===

function createWolfWinTimeline(game) {
  const ctx = game.mockContext
  const deadIds = new Set()

  // 死亡时间表
  // Night1: 狼刀平民(守卫保护了gold没保护seer方向), seer查wolves[0]出狼, 女巫跳过
  // → 平民死亡
  const night1WolfKill = ctx.villagers[0] || ctx.gold
  deadIds.add(night1WolfKill?.id)

  // Day1: 放逐白狼王（好人拿到一狼）
  const day1Exiled = ctx.whiteWolf
  deadIds.add(day1Exiled?.id)

  // Night2: 狼刀预言家, seer查wolves[1]出狼（查完即死）
  const night2WolfKill = ctx.seer
  const aliveAfterDay1 = () => game.players.filter(p => !deadIds.has(p.id))
  const aliveWolfAfterDay1 = wolfPlayers(game).filter(p => !deadIds.has(p.id))
  const night2WolfActor = aliveWolfAfterDay1[0] || ctx.wolves[0]
  deadIds.add(night2WolfKill?.id)

  // Day2: 好人混乱, 放逐一个平民（狼队操控票型）
  const aliveForDay2 = aliveAfterDay1()
  const day2ExiledCandidate = aliveForDay2.filter(p =>
    p.role_hint === '平民' && p.id !== ctx.gold?.id
  )[0] || aliveForDay2.find(p => p.role_hint === '平民')
  const day2Exiled = day2ExiledCandidate
  deadIds.add(day2Exiled?.id)

  // Night3: 狼刀女巫, guard保护gold
  const night3WolfKill = ctx.witch
  const aliveWolfAfterDay2 = wolfPlayers(game).filter(p => !deadIds.has(p.id))
  const night3WolfActor = aliveWolfAfterDay2[0] || ctx.wolves[0]
  deadIds.add(night3WolfKill?.id)

  // Day3: 再放逐一个平民 → 好人3 狼人3 → 狼人胜利
  const aliveForDay3Pre = aliveAfterDay1()
  const aliveForDay3Vote = aliveForDay3Pre
  const day3ExiledCandidate = aliveForDay3Vote.filter(p =>
    p.role_hint === '平民' && p.id !== ctx.gold?.id && p.id !== day2Exiled?.id
  )[0] || aliveForDay3Vote.find(p => !['狼人', '白狼王'].includes(p.role_hint) && p.id !== day2Exiled?.id)
  const day3Exiled = day3ExiledCandidate

  // 投票行
  const day1SecondTarget = ctx.wolves[0]
  const day1VoteRows = createVoteRowsForPhase(game.players.filter(p => p.id !== night1WolfKill?.id), day1Exiled, day1SecondTarget)

  const day2SecondTarget = aliveForDay2.find(p => ['狼人', '白狼王'].includes(p.role_hint) && p.id !== day1Exiled?.id) || aliveForDay2[0]
  const day2VoteRows = createVoteRowsForPhase(aliveForDay2, day2Exiled, ctx.gold)

  const day3SecondTarget = aliveForDay3Vote.find(p => ['狼人', '白狼王'].includes(p.role_hint) && !deadIds.has(p.id)) || aliveForDay3Vote[0]
  const day3VoteRows = createVoteRowsForPhase(aliveForDay3Vote, day3Exiled, day3SecondTarget)

  // Day2 发言（存活玩家）
  const aliveD2 = game.players.filter(p => !deadIds.has(p.id) || p.id === night2WolfKill?.id)
  // 注意：seer在Night2死亡但在Day2可以发表遗言
  const day2Speeches = game.players.filter(p => !new Set([night1WolfKill?.id, day1Exiled?.id]).has(p.id)).map(p => {
    const selfNo = label(p)
    const src = ['got', 'tot', 'llm', 'policy_adjusted'][game.players.indexOf(p) % 4]
    if (p.id === ctx.seer?.id) {
      return { actor_id: p.id, action: 'speak', source: src, confidence: 0.90,
        message: `${selfNo}遗言：昨晚查验${label(ctx.wolves[1])}是狼人。我虽然出局了，但这个查验信息必须传下去。今天归${label(ctx.wolves[1])}，不能让狼队继续操控票型。` }
    }
    if (p.id === ctx.wolves[1]?.id) {
      return { actor_id: p.id, action: 'speak', source: src, confidence: 0.70,
        message: `${selfNo}不认${label(ctx.seer)}的遗言查验。${label(ctx.seer)}已经出局，信息链断裂，我们不能盲目跟票。我请求大家重新审视场上局势。` }
    }
    if (p.id === ctx.wolves[0]?.id) {
      return { actor_id: p.id, action: 'speak', source: src, confidence: 0.68,
        message: `${selfNo}发言。${label(ctx.seer)}的遗言查验有参考价值，但场上形势比单纯的查验更复杂。我保留投票方向。` }
    }
    if (p.role_hint === '女巫') {
      return { actor_id: p.id, action: 'speak', source: src, confidence: 0.80,
        message: `${selfNo}女巫发言。${label(ctx.seer)}遗言报${label(ctx.wolves[1])}狼，信息可信。但狼队可能有对跳或反制策略，大家要谨慎投票。` }
    }
    if (p.role_hint === '守卫') {
      return { actor_id: p.id, action: 'speak', source: src, confidence: 0.78,
        message: `${selfNo}守卫发言。我承认昨晚守护方向可能有误。${label(ctx.seer)}的遗言需要重视，但今天票型不要被情绪驱动。` }
    }
    return { actor_id: p.id, action: 'speak', source: src, confidence: 0.75,
      message: `${selfNo}平民发言。${label(ctx.seer)}的遗言给了方向，但场上混乱，我需要更多信息才能确定站边。` }
  })

  // Day3 发言
  const aliveD3 = game.players.filter(p => !new Set([night1WolfKill?.id, day1Exiled?.id, night2WolfKill?.id, day2Exiled?.id, night3WolfKill?.id]).has(p.id))
  const day3Speeches = aliveD3.map(p => {
    const selfNo = label(p)
    const src = ['got', 'tot', 'llm'][game.players.indexOf(p) % 3]
    if (['狼人', '白狼王'].includes(p.role_hint) && !deadIds.has(p.id)) {
      return { actor_id: p.id, action: 'speak', source: src, confidence: 0.60,
        message: `${selfNo}发言。场上好人数量已经不占优势了，我们需要重新审视每一个人的立场。不要被情绪和信息残留误导。` }
    }
    if (p.role_hint === '守卫') {
      return { actor_id: p.id, action: 'speak', source: src, confidence: 0.70,
        message: `${selfNo}守卫发言。场上形势严峻，今天每一票都决定胜负。我站好人边，但具体归谁需要听完整发言链。` }
    }
    if (p.id === ctx.gold?.id) {
      return { actor_id: p.id, action: 'speak', source: src, confidence: 0.72,
        message: `${selfNo}金水发言。${label(ctx.seer)}已经出局，但查验信息还有效。今天必须精确归票，不能散。` }
    }
    return { actor_id: p.id, action: 'speak', source: src, confidence: 0.65,
      message: `${selfNo}平民发言。场上局势紧张，每一票都很关键。我会跟主票型走。` }
  })

  return [
    // === Setup ===
    { phase: 'setup', log: { speaker: '法官', message: '12名智能体入座完毕，座位身份已随机分配。', visibility: 'system', type: 'setup',
      role_assignments: game.players.map(p => ({ seat: p.seat, name: p.name, role: p.role_hint }))
    }},

    // === Night1: 狼刀平民, guard守gold, seer查wolves[0], witch跳过 ===
    { phase: 'night', day: 1, decision: { actor_id: ctx.guard?.id, action: 'guard_protect', target_id: ctx.gold?.id,
      reason: `${label(ctx.guard)}守卫首夜守护${label(ctx.gold)}，判断金水位更需要保护。`,
      public_summary: '守卫完成守护选择。', source: 'tot', confidence: 0.72 },
      log: { speaker: label(ctx.guard), actor_id: ctx.guard?.id, target_id: ctx.gold?.id,
        message: '守卫完成守护选择。', visibility: 'public', type: 'guard_protect', source: 'tot' }
    },
    { phase: 'night', day: 1, decision: { actor_id: ctx.wolves[0]?.id, action: 'werewolf_kill', target_id: night1WolfKill?.id,
      reason: `狼队决定袭击${label(night1WolfKill)}，削弱好人阵营基础。`,
      public_summary: '狼人团队完成夜间袭击选择。', source: 'got', confidence: 0.84 },
      log: { speaker: '狼人团队', actor_id: ctx.wolves[0]?.id, target_id: night1WolfKill?.id,
        message: '狼人团队完成夜间袭击选择。', visibility: 'god', type: 'werewolf_kill', source: 'got' }
    },
    { phase: 'night', day: 1, decision: { actor_id: ctx.seer?.id, action: 'seer_check', target_id: ctx.wolves[0]?.id,
      reason: `${label(ctx.seer)}查验${label(ctx.wolves[0])}，确认狼人身份。`,
      public_summary: `预言家查验${label(ctx.wolves[0])}为狼人。`, source: 'llm', confidence: 0.88 },
      log: { speaker: label(ctx.seer), actor_id: ctx.seer?.id, target_id: ctx.wolves[0]?.id,
        message: `预言家查验${label(ctx.wolves[0])}为狼人。`, visibility: 'public', type: 'seer_check', source: 'llm' }
    },
    { phase: 'night', day: 1, decision: { actor_id: ctx.witch?.id, action: 'witch_act', target_id: null, selected_skill: 'skip',
      reason: `${label(ctx.witch)}女巫判断首夜信息不足，选择保留药剂。`,
      public_summary: '女巫选择不使用药剂。', source: 'policy_adjusted', confidence: 0.72 },
      log: { speaker: label(ctx.witch), actor_id: ctx.witch?.id,
        message: '女巫选择不使用药剂。', visibility: 'public', type: 'witch_act', source: 'policy_adjusted' }
    },
    // Night1 结果
    { phase: 'result', day: 1, log: { speaker: '法官', message: `昨夜${label(night1WolfKill)}被狼人袭击出局。白天发言开始。`, visibility: 'system', type: 'night_result' },
      apply(nextGame) { const v = nextGame.players.find(p => p.id === night1WolfKill?.id); if (v) v.alive = false }
    },

    // === Sheriff ===
    { phase: 'sheriff', day: 1, log: { speaker: '法官', message: '警长竞选开始。', visibility: 'system', type: 'sheriff_start' }},
    ...game.players.slice(0, 4).map((player, i) => ({
      phase: 'sheriff', day: 1,
      decision: { actor_id: player.id, action: 'sheriff_speak',
        reason: `${label(player)}参与警长竞选。`, public_summary: `${label(player)}参与警长竞选。`,
        source: ['got', 'tot', 'llm'][i % 3], confidence: 0.75 + i * 0.05 },
      log: { speaker: label(player), actor_id: player.id, message: `${label(player)}参与警长竞选。`,
        visibility: 'public', type: 'sheriff_speak', source: 'got' }
    })),
    { phase: 'sheriff', day: 1, decision: { actor_id: game.players[2]?.id, action: 'sheriff_withdraw',
      reason: `${label(game.players[2])}选择退水。`, public_summary: `${label(game.players[2])}退水。`,
      source: 'tot', confidence: 0.65 },
      log: { speaker: label(game.players[2]), actor_id: game.players[2]?.id,
        message: `${label(game.players[2])}选择退水。`, visibility: 'public', type: 'sheriff_withdraw', source: 'tot' }
    },
    ...game.players.slice(4, 9).map((player, i) => ({
      phase: 'sheriff_result', day: 1,
      decision: { actor_id: player.id, action: 'sheriff_vote', target_id: i < 3 ? ctx.seer?.id : ctx.hunter?.id,
        reason: `${label(player)}投票给${i < 3 ? label(ctx.seer) : label(ctx.hunter)}。`,
        public_summary: `${label(player)}投票给${i < 3 ? label(ctx.seer) : label(ctx.hunter)}。`,
        source: ['got', 'tot', 'llm'][i % 3], confidence: 0.68 + (i % 4) * 0.06 },
      log: { speaker: label(player), actor_id: player.id, target_id: i < 3 ? ctx.seer?.id : ctx.hunter?.id,
        message: `${label(player)}投票给${i < 3 ? label(ctx.seer) : label(ctx.hunter)}。`,
        visibility: 'public', type: 'sheriff_vote', source: 'got' }
    })),
    { phase: 'sheriff_result', day: 1, log: { speaker: '法官', message: `警长竞选结束，${label(ctx.seer)}当选警长。`, visibility: 'system', type: 'sheriff_result' },
      apply(nextGame) { nextGame.sheriff_id = ctx.seer?.id }
    },

    // === Day1 发言 ===
    ...createDialogues(game).map(d => ({
      phase: 'speech', day: 1,
      decision: { ...d, reason: d.message, public_summary: d.message },
      log: { speaker: label(game.players.find(p => p.id === d.actor_id)), actor_id: d.actor_id,
        message: d.message, visibility: 'public', type: 'speech', source: d.source }
    })),

    // === Day1 投票 → 放逐白狼王 ===
    { phase: 'vote', day: 1, log: { speaker: '法官', message: `发言结束，进入公投。`, visibility: 'system', type: 'vote_prompt' }},
    ...createVoteEvents(game, day1VoteRows),
    { phase: 'vote', day: 1, log: { speaker: '法官',
      message: `公投结束：${label(day1VoteRows.target)}获得${day1VoteRows.tally[0]?.count || 0}票，被放逐出局。`,
      visibility: 'system', type: 'exile', target_id: day1VoteRows.target?.id },
      apply(nextGame) { const t = nextGame.players.find(p => p.id === day1VoteRows.target?.id); if (t) t.alive = false; nextGame.vote_tally = day1VoteRows.tally }
    },

    // === Night2: 狼刀预言家, guard守gold, seer查wolves[1] ===
    { phase: 'night', day: 2, log: { speaker: '法官', message: '天黑请闭眼。守卫、狼人、预言家正在行动。', visibility: 'system', type: 'night_start' }},
    { phase: 'night', day: 2, decision: { actor_id: ctx.guard?.id, action: 'guard_protect', target_id: ctx.gold?.id,
      reason: `${label(ctx.guard)}守护${label(ctx.gold)}。`, public_summary: '守卫完成守护选择。',
      source: 'tot', confidence: 0.76 },
      log: { speaker: label(ctx.guard), actor_id: ctx.guard?.id, target_id: ctx.gold?.id,
        message: '守卫完成守护选择。', visibility: 'public', type: 'guard_protect', source: 'tot' }
    },
    { phase: 'night', day: 2, decision: { actor_id: night2WolfActor?.id, action: 'werewolf_kill', target_id: ctx.seer?.id,
      reason: `狼队袭击${label(ctx.seer)}，切断预言家信息源。`, public_summary: '狼人团队完成夜间袭击选择。',
      source: 'got', confidence: 0.83 },
      log: { speaker: '狼人团队', actor_id: night2WolfActor?.id, target_id: ctx.seer?.id,
        message: '狼人团队完成夜间袭击选择。', visibility: 'god', type: 'werewolf_kill', source: 'got' }
    },
    { phase: 'night', day: 2, decision: { actor_id: ctx.seer?.id, action: 'seer_check', target_id: ctx.wolves[1]?.id,
      reason: `${label(ctx.seer)}查验${label(ctx.wolves[1])}，确认狼人身份。`,
      public_summary: `预言家查验${label(ctx.wolves[1])}为狼人。`, source: 'llm', confidence: 0.90 },
      log: { speaker: label(ctx.seer), actor_id: ctx.seer?.id, target_id: ctx.wolves[1]?.id,
        message: `预言家查验${label(ctx.wolves[1])}为狼人。`, visibility: 'public', type: 'seer_check', source: 'llm' }
    },
    { phase: 'night', day: 2, decision: { actor_id: ctx.witch?.id, action: 'witch_act', target_id: null, selected_skill: 'skip',
      reason: `${label(ctx.witch)}判断局势不明，保留药剂。`, public_summary: '女巫选择不使用药剂。',
      source: 'policy_adjusted', confidence: 0.70 },
      log: { speaker: label(ctx.witch), actor_id: ctx.witch?.id,
        message: '女巫选择不使用药剂。', visibility: 'public', type: 'witch_act', source: 'policy_adjusted' }
    },
    // Night2 结果: 预言家出局
    { phase: 'result', day: 2, log: { speaker: '法官', message: `昨夜${label(ctx.seer)}被狼人袭击出局。请发表遗言。`, visibility: 'system', type: 'night_result' },
      apply(nextGame) { const s = nextGame.players.find(p => p.id === ctx.seer?.id); if (s) s.alive = false }
    },
    // Seer遗言
    { phase: 'speech', day: 2, decision: { actor_id: ctx.seer?.id, action: 'last_word',
      reason: `${label(ctx.seer)}遗言：查验${label(ctx.wolves[1])}是狼人。`, 
      public_summary: `${label(ctx.seer)}遗言：查验${label(ctx.wolves[1])}是狼人。`,
      source: 'human', confidence: 1 },
      log: { speaker: label(ctx.seer), actor_id: ctx.seer?.id,
        message: `${label(ctx.seer)}遗言：查验${label(ctx.wolves[1])}是狼人，今天必须归${label(ctx.wolves[1])}。`,
        visibility: 'public', type: 'last_word', source: 'human' }
    },

    // === Day2 发言 ===
    ...day2Speeches.map(s => ({
      phase: 'speech', day: 2,
      decision: { ...s, reason: s.message, public_summary: s.message },
      log: { speaker: label(game.players.find(p => p.id === s.actor_id)), actor_id: s.actor_id,
        message: s.message, visibility: 'public', type: 'speech', source: s.source }
    })),

    // === Day2 投票 → 放逐平民 ===
    { phase: 'vote', day: 2, log: { speaker: '法官', message: `发言结束，进入公投。`, visibility: 'system', type: 'vote_prompt' }},
    ...createVoteEvents(game, day2VoteRows),
    { phase: 'vote', day: 2, log: { speaker: '法官',
      message: `公投结束：${label(day2VoteRows.target)}获得${day2VoteRows.tally[0]?.count || 0}票，被放逐出局。`,
      visibility: 'system', type: 'exile', target_id: day2VoteRows.target?.id },
      apply(nextGame) { const t = nextGame.players.find(p => p.id === day2VoteRows.target?.id); if (t) t.alive = false; nextGame.vote_tally = day2VoteRows.tally }
    },

    // === Night3: 狼刀女巫, guard守gold ===
    { phase: 'night', day: 3, log: { speaker: '法官', message: '天黑请闭眼。', visibility: 'system', type: 'night_start' }},
    { phase: 'night', day: 3, decision: { actor_id: ctx.guard?.id, action: 'guard_protect', target_id: ctx.gold?.id,
      reason: `${label(ctx.guard)}守护${label(ctx.gold)}。`, public_summary: '守卫完成守护选择。',
      source: 'tot', confidence: 0.75 },
      log: { speaker: label(ctx.guard), actor_id: ctx.guard?.id, target_id: ctx.gold?.id,
        message: '守卫完成守护选择。', visibility: 'public', type: 'guard_protect', source: 'tot' }
    },
    { phase: 'night', day: 3, decision: { actor_id: night3WolfActor?.id, action: 'werewolf_kill', target_id: ctx.witch?.id,
      reason: `狼队袭击${label(ctx.witch)}，带走关键神职。`, public_summary: '狼人团队完成夜间袭击选择。',
      source: 'got', confidence: 0.85 },
      log: { speaker: '狼人团队', actor_id: night3WolfActor?.id, target_id: ctx.witch?.id,
        message: '狼人团队完成夜间袭击选择。', visibility: 'god', type: 'werewolf_kill', source: 'got' }
    },
    // Night3 结果: 女巫出局
    { phase: 'result', day: 3, log: { speaker: '法官', message: `昨夜${label(ctx.witch)}被狼人袭击出局。`, visibility: 'system', type: 'night_result' },
      apply(nextGame) { const w = nextGame.players.find(p => p.id === ctx.witch?.id); if (w) w.alive = false }
    },

    // === Day3 发言 ===
    ...day3Speeches.map(s => ({
      phase: 'speech', day: 3,
      decision: { ...s, reason: s.message, public_summary: s.message },
      log: { speaker: label(game.players.find(p => p.id === s.actor_id)), actor_id: s.actor_id,
        message: s.message, visibility: 'public', type: 'speech', source: s.source }
    })),

    // === Day3 投票 → 放逐平民 → 狼人胜利 ===
    { phase: 'vote', day: 3, log: { speaker: '法官', message: `发言结束，进入公投。这是决定胜负的关键投票。`, visibility: 'system', type: 'vote_prompt' }},
    ...createVoteEvents(game, day3VoteRows),
    { phase: 'vote', day: 3, log: { speaker: '法官',
      message: `公投结束：${label(day3VoteRows.target)}获得${day3VoteRows.tally[0]?.count || 0}票，被放逐出局。`,
      visibility: 'system', type: 'exile', target_id: day3VoteRows.target?.id },
      apply(nextGame) { const t = nextGame.players.find(p => p.id === day3VoteRows.target?.id); if (t) t.alive = false; nextGame.vote_tally = day3VoteRows.tally }
    },

    // === 结果: 狼人胜利 ===
    { phase: 'ended', day: 3, log: { speaker: '系统', message: '狼人阵营获胜！好人阵营已被瓦解。本局游戏结束。', visibility: 'system', type: 'game_over' },
      apply(nextGame) { nextGame.winner = '狼人阵营获胜' }
    }
  ]
}

// === 四天持久战时间线（好人险胜） ===

function createLongGameTimeline(game) {
  const ctx = game.mockContext

  // 死亡时间表
  // Night1: 平安夜 (guard守seer, wolf刀seer被挡)
  // Day1: 放逐白狼王
  // Night2: 狼刀hunter, witch毒wolves[2]
  // Day2: 放逐wolves[1]
  // Night3: 狼刀平民, seer查wolves[0]出狼, witch跳过
  // Day3: 好人混乱 → 放逐一个平民(wolves[0]逃脱)
  // Night4: 狼刀guard, seer查wolves[0]确认
  // Day4: 放逐wolves[0] → 好人险胜

  const day1Exiled = ctx.whiteWolf
  const night2WolfKill = ctx.hunter
  const night2Poisoned = ctx.wolves[2]

  const deadAfterNight2 = new Set([day1Exiled?.id, night2WolfKill?.id, night2Poisoned?.id].filter(id => id != null))
  const aliveForDay2 = game.players.filter(p => !deadAfterNight2.has(p.id))

  const day2Exiled = ctx.wolves[1]
  const deadAfterDay2 = new Set([...deadAfterNight2, day2Exiled?.id].filter(id => id != null))

  // Night3: 狼刀平民
  const aliveGoodAfterDay2 = game.players.filter(p => !['狼人', '白狼王'].includes(p.role_hint) && !deadAfterDay2.has(p.id))
  const night3WolfKill = aliveGoodAfterDay2.find(p => p.role_hint === '平民' && p.id !== ctx.gold?.id) || aliveGoodAfterDay2.find(p => p.role_hint === '平民')

  const deadAfterNight3 = new Set([...deadAfterDay2, night3WolfKill?.id].filter(id => id != null))

  // Day3: 放逐另一个平民（狼队逃脱）
  const aliveForDay3 = game.players.filter(p => !deadAfterNight3.has(p.id))
  const day3MisdirectTarget = aliveForDay3.filter(p =>
    p.role_hint === '平民' && p.id !== ctx.gold?.id && p.id !== night3WolfKill?.id
  )[0] || aliveForDay3.find(p => p.role_hint === '平民')

  const deadAfterDay3 = new Set([...deadAfterNight3, day3MisdirectTarget?.id].filter(id => id != null))

  // Night4: 狼刀guard
  const aliveGoodAfterDay3 = game.players.filter(p => !['狼人', '白狼王'].includes(p.role_hint) && !deadAfterDay3.has(p.id))
  const night4WolfKill = ctx.guard && !deadAfterDay3.has(ctx.guard.id) ? ctx.guard : aliveGoodAfterDay3[0]
  const aliveWolfAfterDay3 = wolfPlayers(game).filter(p => !deadAfterDay3.has(p.id))
  const night4WolfActor = aliveWolfAfterDay3[0] || ctx.wolves[0]

  const deadAfterNight4 = new Set([...deadAfterDay3, night4WolfKill?.id].filter(id => id != null))

  // Day4: 放逐wolves[0]
  const aliveForDay4 = game.players.filter(p => !deadAfterNight4.has(p.id))
  const day4Exiled = aliveWolfAfterDay3[0] || ctx.wolves[0]

  // 投票行
  const day1VoteRows = createVoteRows(game) // reuse original
  const day2SecondTarget = aliveForDay2.find(p => p.id !== day2Exiled?.id && !['狼人', '白狼王'].includes(p.role_hint)) || ctx.gold
  const day2VoteRows = createVoteRowsForPhase(aliveForDay2, day2Exiled, day2SecondTarget)
  const day3SecondTarget = aliveForDay3.find(p => ['狼人', '白狼王'].includes(p.role_hint) && !deadAfterNight3.has(p.id)) || ctx.wolves[0]
  const day3VoteRows = createVoteRowsForPhase(aliveForDay3, day3MisdirectTarget, day3SecondTarget)
  const day4VoteRows = createVoteRowsForPhase(aliveForDay4, day4Exiled, aliveForDay4.find(p => p.id !== day4Exiled?.id))

  // Day2 发言
  const day2Speeches = aliveForDay2.map(p => {
    const selfNo = label(p)
    const src = ['got', 'tot', 'llm', 'policy_adjusted'][game.players.indexOf(p) % 4]
    if (p.id === ctx.seer?.id) return { actor_id: p.id, action: 'speak', source: src, confidence: 0.90,
      message: `${selfNo}报验：昨晚查验${label(ctx.wolves[1])}是狼人。归${label(ctx.wolves[1])}。` }
    if (p.role_hint === '女巫') return { actor_id: p.id, action: 'speak', source: src, confidence: 0.85,
      message: `${selfNo}女巫发言。昨夜我使用了毒药，有人非正常死亡。站${label(ctx.seer)}边，归${label(ctx.wolves[1])}。` }
    if (p.id === ctx.wolves[1]?.id) return { actor_id: p.id, action: 'speak', source: src, confidence: 0.70,
      message: `${selfNo}不认查验，请求完整发言链再做决定。` }
    if (['狼人', '白狼王'].includes(p.role_hint)) return { actor_id: p.id, action: 'speak', source: src, confidence: 0.68,
      message: `${selfNo}发言。保留投票方向，听完后置位。` }
    return { actor_id: p.id, action: 'speak', source: src, confidence: 0.78,
      message: `${selfNo}站${label(ctx.seer)}边，归${label(ctx.wolves[1])}。` }
  })

  // Day3 发言（混乱局势）
  const aliveForDay3List = aliveForDay3
  const day3Speeches = aliveForDay3List.map(p => {
    const selfNo = label(p)
    const src = ['got', 'tot', 'llm'][game.players.indexOf(p) % 3]
    if (p.id === ctx.seer?.id) return { actor_id: p.id, action: 'speak', source: src, confidence: 0.93,
      message: `${selfNo}报验：昨晚查验${label(ctx.wolves[0])}是狼人。今天必须归${label(ctx.wolves[0])}。` }
    if (p.id === ctx.wolves[0]?.id) return { actor_id: p.id, action: 'speak', source: src, confidence: 0.62,
      message: `${selfNo}发言。${label(ctx.seer)}的查验有争议，场上形势复杂，不要盲目跟票。` }
    if (p.role_hint === '女巫') return { actor_id: p.id, action: 'speak', source: src, confidence: 0.82,
      message: `${selfNo}女巫发言。${label(ctx.seer)}三夜查验一致指向狼队，归${label(ctx.wolves[0])}。` }
    if (p.role_hint === '守卫') return { actor_id: p.id, action: 'speak', source: src, confidence: 0.80,
      message: `${selfNo}守卫发言。站${label(ctx.seer)}边，归${label(ctx.wolves[0])}。` }
    if (p.id === ctx.gold?.id) return { actor_id: p.id, action: 'speak', source: src, confidence: 0.84,
      message: `${selfNo}金水发言。三夜信息链完整，归${label(ctx.wolves[0])}收尾。` }
    return { actor_id: p.id, action: 'speak', source: src, confidence: 0.75,
      message: `${selfNo}平民发言。场上形势混乱，我需要更多信息才能确定站边。` }
  })

  // Day4 发言
  const aliveForDay4List = aliveForDay4
  const day4Speeches = aliveForDay4List.map(p => {
    const selfNo = label(p)
    const src = ['got', 'tot', 'llm'][game.players.indexOf(p) % 3]
    if (p.id === ctx.seer?.id) return { actor_id: p.id, action: 'speak', source: src, confidence: 0.95,
      message: `${selfNo}预言家最终报验：昨晚再次确认${label(ctx.wolves[0])}是狼人。今天是最后机会，必须归${label(ctx.wolves[0])}。` }
    if (['狼人', '白狼王'].includes(p.role_hint) && p.id === day4Exiled?.id) return { actor_id: p.id, action: 'speak', source: src, confidence: 0.55,
      message: `${selfNo}最后发言。我不认查验，但已经无力反驳。希望大家做出正确判断。` }
    return { actor_id: p.id, action: 'speak', source: src, confidence: 0.82,
      message: `${selfNo}发言。今天是决胜票，归${label(day4Exiled)}，结束游戏。` }
  })

  // Night2/3/4 狼刀行动者
  const n2WolfActor = wolfPlayers(game).filter(p => !new Set([day1Exiled?.id]).has(p.id))[0] || ctx.wolves[0]
  const n3WolfActor = wolfPlayers(game).filter(p => !deadAfterDay2.has(p.id))[0] || ctx.wolves[0]
  const n4WolfActor = aliveWolfAfterDay3[0] || ctx.wolves[0]

  const night1Decisions = createNightDecisions(game)

  return [
    // === Setup ===
    { phase: 'setup', log: { speaker: '法官', message: '12名智能体入座完毕。', visibility: 'system', type: 'setup',
      role_assignments: game.players.map(p => ({ seat: p.seat, name: p.name, role: p.role_hint }))
    }},

    // === Night1: 平安夜 ===
    ...night1Decisions.map(d => ({
      phase: 'night', day: 1, decision: d,
      log: { speaker: d.action === 'werewolf_kill' ? '狼人团队' : label(game.players.find(p => p.id === d.actor_id)),
        actor_id: d.actor_id, target_id: d.target_id, message: d.public_summary,
        visibility: d.action === 'werewolf_kill' ? 'god' : 'public', type: d.action, source: d.source }
    })),
    { phase: 'result', day: 1, log: { speaker: '法官', message: '昨夜平安夜，没有玩家出局。', visibility: 'system', type: 'night_result' }},

    // === Sheriff ===
    { phase: 'sheriff', day: 1, log: { speaker: '法官', message: '警长竞选开始。', visibility: 'system', type: 'sheriff_start' }},
    ...game.players.slice(0, 4).map((player, i) => ({
      phase: 'sheriff', day: 1,
      decision: { actor_id: player.id, action: 'sheriff_speak', reason: `${label(player)}参与竞选。`,
        public_summary: `${label(player)}参与竞选。`, source: ['got', 'tot', 'llm'][i % 3], confidence: 0.75 + i * 0.05 },
      log: { speaker: label(player), actor_id: player.id, message: `${label(player)}参与警长竞选。`,
        visibility: 'public', type: 'sheriff_speak', source: 'got' }
    })),
    { phase: 'sheriff', day: 1, decision: { actor_id: game.players[2]?.id, action: 'sheriff_withdraw',
      reason: `${label(game.players[2])}退水。`, public_summary: `${label(game.players[2])}退水。`,
      source: 'tot', confidence: 0.65 },
      log: { speaker: label(game.players[2]), actor_id: game.players[2]?.id,
        message: `${label(game.players[2])}退水。`, visibility: 'public', type: 'sheriff_withdraw', source: 'tot' }
    },
    ...game.players.slice(4, 9).map((player, i) => ({
      phase: 'sheriff_result', day: 1,
      decision: { actor_id: player.id, action: 'sheriff_vote', target_id: i < 3 ? ctx.seer?.id : ctx.hunter?.id,
        reason: `${label(player)}投票给${i < 3 ? label(ctx.seer) : label(ctx.hunter)}。`,
        public_summary: `${label(player)}投票给${i < 3 ? label(ctx.seer) : label(ctx.hunter)}。`,
        source: ['got', 'tot', 'llm'][i % 3], confidence: 0.68 + (i % 4) * 0.06 },
      log: { speaker: label(player), actor_id: player.id, target_id: i < 3 ? ctx.seer?.id : ctx.hunter?.id,
        message: `${label(player)}投票给${i < 3 ? label(ctx.seer) : label(ctx.hunter)}。`,
        visibility: 'public', type: 'sheriff_vote', source: 'got' }
    })),
    { phase: 'sheriff_result', day: 1, log: { speaker: '法官', message: `警长竞选结束，${label(ctx.seer)}当选警长。`, visibility: 'system', type: 'sheriff_result' },
      apply(nextGame) { nextGame.sheriff_id = ctx.seer?.id }
    },

    // === Day1 发言 ===
    ...createDialogues(game).map(d => ({
      phase: 'speech', day: 1,
      decision: { ...d, reason: d.message, public_summary: d.message },
      log: { speaker: label(game.players.find(p => p.id === d.actor_id)), actor_id: d.actor_id,
        message: d.message, visibility: 'public', type: 'speech', source: d.source }
    })),

    // === Day1 投票 → 放逐白狼王 ===
    { phase: 'vote', day: 1, log: { speaker: '法官', message: `发言结束，进入公投。`, visibility: 'system', type: 'vote_prompt' }},
    ...createVoteEvents(game, day1VoteRows),
    { phase: 'vote', day: 1, decision: { actor_id: ctx.seer?.id, action: 'vote', target_id: day1VoteRows.target?.id,
      reason: `${label(ctx.seer)}投给${label(day1VoteRows.target)}。`,
      public_summary: `${label(ctx.seer)}投票给${label(day1VoteRows.target)}。`, source: 'got', confidence: 0.86 },
      log: { speaker: label(ctx.seer), actor_id: ctx.seer?.id, target_id: day1VoteRows.target?.id,
        message: `我投${label(day1VoteRows.target)}。`, visibility: 'public', type: 'vote', source: 'got' }
    },
    { phase: 'vote', day: 1, log: { speaker: '法官',
      message: `公投结束：${label(day1VoteRows.target)}获得多数票，被放逐出局。`, visibility: 'system', type: 'exile', target_id: day1VoteRows.target?.id },
      apply(nextGame) { const t = nextGame.players.find(p => p.id === day1VoteRows.target?.id); if (t) t.alive = false; nextGame.vote_tally = day1VoteRows.tally }
    },

    // === Night2: 狼刀hunter, witch毒wolves[2] ===
    { phase: 'night', day: 2, log: { speaker: '法官', message: '天黑请闭眼。', visibility: 'system', type: 'night_start' }},
    { phase: 'night', day: 2, decision: { actor_id: ctx.guard?.id, action: 'guard_protect', target_id: ctx.gold?.id,
      reason: `${label(ctx.guard)}守护${label(ctx.gold)}。`, public_summary: '守卫完成守护选择。',
      source: 'tot', confidence: 0.79 },
      log: { speaker: label(ctx.guard), actor_id: ctx.guard?.id, target_id: ctx.gold?.id,
        message: '守卫完成守护选择。', visibility: 'public', type: 'guard_protect', source: 'tot' }
    },
    { phase: 'night', day: 2, decision: { actor_id: n2WolfActor?.id, action: 'werewolf_kill', target_id: ctx.hunter?.id,
      reason: `狼队袭击${label(ctx.hunter)}。`, public_summary: '狼人团队完成夜间袭击选择。',
      source: 'got', confidence: 0.82 },
      log: { speaker: '狼人团队', actor_id: n2WolfActor?.id, target_id: ctx.hunter?.id,
        message: '狼人团队完成夜间袭击选择。', visibility: 'god', type: 'werewolf_kill', source: 'got' }
    },
    { phase: 'night', day: 2, decision: { actor_id: ctx.seer?.id, action: 'seer_check', target_id: ctx.wolves[1]?.id,
      reason: `${label(ctx.seer)}查验${label(ctx.wolves[1])}出狼。`,
      public_summary: `预言家查验${label(ctx.wolves[1])}为狼人。`, source: 'llm', confidence: 0.92 },
      log: { speaker: label(ctx.seer), actor_id: ctx.seer?.id, target_id: ctx.wolves[1]?.id,
        message: `预言家查验${label(ctx.wolves[1])}为狼人。`, visibility: 'public', type: 'seer_check', source: 'llm' }
    },
    { phase: 'night', day: 2, decision: { actor_id: ctx.witch?.id, action: 'witch_act', target_id: ctx.wolves[2]?.id, selected_skill: 'poison',
      reason: `${label(ctx.witch)}毒杀${label(ctx.wolves[2])}。`, public_summary: '女巫使用毒药。',
      source: 'policy_adjusted', confidence: 0.82 },
      log: { speaker: label(ctx.witch), actor_id: ctx.witch?.id, target_id: ctx.wolves[2]?.id,
        message: '女巫使用毒药。', visibility: 'public', type: 'witch_act', source: 'policy_adjusted' }
    },
    { phase: 'result', day: 2, log: { speaker: '法官',
      message: `昨夜${label(ctx.hunter)}号和${label(ctx.wolves[2])}号双双出局。`, visibility: 'system', type: 'night_result' },
      apply(nextGame) { const h = nextGame.players.find(p => p.id === ctx.hunter?.id); if (h) h.alive = false;
        const pw = nextGame.players.find(p => p.id === ctx.wolves[2]?.id); if (pw) pw.alive = false }
    },
    // Hunter遗言
    { phase: 'speech', day: 2, decision: { actor_id: ctx.hunter?.id, action: 'last_word',
      reason: `${label(ctx.hunter)}遗言：猎人开枪带走${label(ctx.wolves[2])}。`,
      public_summary: `${label(ctx.hunter)}遗言：猎人开枪带走${label(ctx.wolves[2])}。`,
      source: 'human', confidence: 1 },
      log: { speaker: label(ctx.hunter), actor_id: ctx.hunter?.id,
        message: `${label(ctx.hunter)}遗言：猎人开枪带走${label(ctx.wolves[2])}。`, visibility: 'public', type: 'last_word', source: 'human' }
    },

    // === Day2 发言 + 投票 → 放逐wolves[1] ===
    ...day2Speeches.map(s => ({
      phase: 'speech', day: 2,
      decision: { ...s, reason: s.message, public_summary: s.message },
      log: { speaker: label(game.players.find(p => p.id === s.actor_id)), actor_id: s.actor_id,
        message: s.message, visibility: 'public', type: 'speech', source: s.source }
    })),
    { phase: 'vote', day: 2, log: { speaker: '法官', message: `发言结束，进入公投。`, visibility: 'system', type: 'vote_prompt' }},
    ...createVoteEvents(game, day2VoteRows),
    { phase: 'vote', day: 2, log: { speaker: '法官',
      message: `公投结束：${label(day2VoteRows.target)}获得多数票，被放逐出局。`, visibility: 'system', type: 'exile', target_id: day2VoteRows.target?.id },
      apply(nextGame) { const t = nextGame.players.find(p => p.id === day2VoteRows.target?.id); if (t) t.alive = false; nextGame.vote_tally = day2VoteRows.tally }
    },

    // === Night3: 狼刀平民, seer查wolves[0], witch跳过 ===
    { phase: 'night', day: 3, log: { speaker: '法官', message: '天黑请闭眼。', visibility: 'system', type: 'night_start' }},
    { phase: 'night', day: 3, decision: { actor_id: ctx.guard?.id, action: 'guard_protect', target_id: ctx.seer?.id,
      reason: `${label(ctx.guard)}守护${label(ctx.seer)}。`, public_summary: '守卫完成守护选择。',
      source: 'tot', confidence: 0.80 },
      log: { speaker: label(ctx.guard), actor_id: ctx.guard?.id, target_id: ctx.seer?.id,
        message: '守卫完成守护选择。', visibility: 'public', type: 'guard_protect', source: 'tot' }
    },
    { phase: 'night', day: 3, decision: { actor_id: n3WolfActor?.id, action: 'werewolf_kill', target_id: night3WolfKill?.id,
      reason: `狼队袭击${label(night3WolfKill)}。`, public_summary: '狼人团队完成夜间袭击选择。',
      source: 'got', confidence: 0.84 },
      log: { speaker: '狼人团队', actor_id: n3WolfActor?.id, target_id: night3WolfKill?.id,
        message: '狼人团队完成夜间袭击选择。', visibility: 'god', type: 'werewolf_kill', source: 'got' }
    },
    { phase: 'night', day: 3, decision: { actor_id: ctx.seer?.id, action: 'seer_check', target_id: ctx.wolves[0]?.id,
      reason: `${label(ctx.seer)}查验${label(ctx.wolves[0])}出狼。`,
      public_summary: `预言家查验${label(ctx.wolves[0])}为狼人。`, source: 'llm', confidence: 0.93 },
      log: { speaker: label(ctx.seer), actor_id: ctx.seer?.id, target_id: ctx.wolves[0]?.id,
        message: `预言家查验${label(ctx.wolves[0])}为狼人。`, visibility: 'public', type: 'seer_check', source: 'llm' }
    },
    { phase: 'night', day: 3, decision: { actor_id: ctx.witch?.id, action: 'witch_act', target_id: null, selected_skill: 'skip',
      reason: `${label(ctx.witch)}跳过。`, public_summary: '女巫选择不使用药剂。',
      source: 'policy_adjusted', confidence: 0.72 },
      log: { speaker: label(ctx.witch), actor_id: ctx.witch?.id,
        message: '女巫选择不使用药剂。', visibility: 'public', type: 'witch_act', source: 'policy_adjusted' }
    },
    { phase: 'result', day: 3, log: { speaker: '法官',
      message: `昨夜${label(night3WolfKill)}被狼人袭击出局。`, visibility: 'system', type: 'night_result' },
      apply(nextGame) { const v = nextGame.players.find(p => p.id === night3WolfKill?.id); if (v) v.alive = false }
    },

    // === Day3 发言 + 投票 → 放逐平民（狼队逃脱） ===
    ...day3Speeches.map(s => ({
      phase: 'speech', day: 3,
      decision: { ...s, reason: s.message, public_summary: s.message },
      log: { speaker: label(game.players.find(p => p.id === s.actor_id)), actor_id: s.actor_id,
        message: s.message, visibility: 'public', type: 'speech', source: s.source }
    })),
    { phase: 'vote', day: 3, log: { speaker: '法官', message: `发言结束，进入公投。`, visibility: 'system', type: 'vote_prompt' }},
    ...createVoteEvents(game, day3VoteRows),
    { phase: 'vote', day: 3, log: { speaker: '法官',
      message: `公投结束：${label(day3VoteRows.target)}获得多数票，被放逐出局。`, visibility: 'system', type: 'exile', target_id: day3VoteRows.target?.id },
      apply(nextGame) { const t = nextGame.players.find(p => p.id === day3VoteRows.target?.id); if (t) t.alive = false; nextGame.vote_tally = day3VoteRows.tally }
    },

    // === Night4: 狼刀守卫, seer再查wolves[0] ===
    { phase: 'night', day: 4, log: { speaker: '法官', message: '天黑请闭眼。最后一夜。', visibility: 'system', type: 'night_start' }},
    { phase: 'night', day: 4, decision: { actor_id: n4WolfActor?.id, action: 'werewolf_kill', target_id: night4WolfKill?.id,
      reason: `狼队袭击${label(night4WolfKill)}，最后一搏。`, public_summary: '狼人团队完成夜间袭击选择。',
      source: 'got', confidence: 0.86 },
      log: { speaker: '狼人团队', actor_id: n4WolfActor?.id, target_id: night4WolfKill?.id,
        message: '狼人团队完成夜间袭击选择。', visibility: 'god', type: 'werewolf_kill', source: 'got' }
    },
    { phase: 'night', day: 4, decision: { actor_id: ctx.seer?.id, action: 'seer_check', target_id: ctx.wolves[0]?.id,
      reason: `${label(ctx.seer)}再次确认${label(ctx.wolves[0])}是狼人。`,
      public_summary: `预言家确认${label(ctx.wolves[0])}为狼人。`, source: 'llm', confidence: 0.95 },
      log: { speaker: label(ctx.seer), actor_id: ctx.seer?.id, target_id: ctx.wolves[0]?.id,
        message: `预言家确认${label(ctx.wolves[0])}为狼人。`, visibility: 'public', type: 'seer_check', source: 'llm' }
    },
    { phase: 'result', day: 4, log: { speaker: '法官',
      message: `昨夜${label(night4WolfKill)}被狼人袭击出局。`, visibility: 'system', type: 'night_result' },
      apply(nextGame) { const v = nextGame.players.find(p => p.id === night4WolfKill?.id); if (v) v.alive = false }
    },

    // === Day4 发言 + 投票 → 放逐wolves[0] → 好人险胜 ===
    ...day4Speeches.map(s => ({
      phase: 'speech', day: 4,
      decision: { ...s, reason: s.message, public_summary: s.message },
      log: { speaker: label(game.players.find(p => p.id === s.actor_id)), actor_id: s.actor_id,
        message: s.message, visibility: 'public', type: 'speech', source: s.source }
    })),
    { phase: 'vote', day: 4, log: { speaker: '法官', message: `发言结束，进入公投。今天归${label(day4VoteRows.target)}游戏结束。`, visibility: 'system', type: 'vote_prompt' }},
    ...createVoteEvents(game, day4VoteRows),
    { phase: 'vote', day: 4, log: { speaker: '法官',
      message: `公投结束：${label(day4VoteRows.target)}获得多数票，被放逐出局。`, visibility: 'system', type: 'exile', target_id: day4VoteRows.target?.id },
      apply(nextGame) { const t = nextGame.players.find(p => p.id === day4VoteRows.target?.id); if (t) t.alive = false; nextGame.vote_tally = day4VoteRows.tally }
    },

    // === 结果: 好人险胜 ===
    { phase: 'ended', day: 4, log: { speaker: '系统', message: '好人阵营险胜！最后一匹狼人出局。本局游戏结束。', visibility: 'system', type: 'game_over' },
      apply(nextGame) { nextGame.winner = '好人阵营险胜' }
    }
  ]
}

const MOCK_HISTORY_STORAGE_KEY = 'nightcouncil.mock.history.v12'

function readStoredHistory() {
  try {
    const raw = globalThis.localStorage?.getItem(MOCK_HISTORY_STORAGE_KEY)
    const parsed = raw ? JSON.parse(raw) : []
    return Array.isArray(parsed) ? parsed : []
  } catch {
    return []
  }
}

function writeStoredHistory(games) {
  try {
    globalThis.localStorage?.setItem(MOCK_HISTORY_STORAGE_KEY, JSON.stringify(games))
  } catch {
    // Storage can be unavailable in tests or private browsing; in-memory history still works.
  }
}

let activeGame = null
let archivedGames = readStoredHistory()

function snapshot(game = activeGame) {
  if (!game) return null
  const data = clone(game)
  delete data.timeline
  delete data.mockContext
  return data
}

function archiveActiveGame() {
  if (!activeGame) return
  const data = snapshot(activeGame)
  const existingIndex = archivedGames.findIndex((item) => item.game_id === data.game_id)
  if (existingIndex >= 0) archivedGames[existingIndex] = data
  else archivedGames.unshift(data)
  archivedGames = archivedGames.slice(0, 12)
  writeStoredHistory(archivedGames)
}

const SCENARIO_NAMES = {
  good_win: '好人带队·预言家锁狼胜',
  wolf_win: '狼人翻盘·预言家出局败',
  long_game: '持久战·四天好人险胜'
}

function buildCompletedMockGame(index = 0, scenario = 'good_win') {
  const game = baseGame('watch', scenario)
  applyStartConfig(game, {
    seed: 4100 + index,
    max_days: scenario === 'long_game' ? 30 : 20,
    skill_dir: index % 3 === 1 ? 'skills/candidates/seer' : '',
    role_versions: index % 3 === 2 ? { seer: 'base-seer-20260604' } : {}
  })
  game.game_id = `mock-seed-${index + 1}`
  game.log_name = `记录${index + 1} · ${SCENARIO_NAMES[scenario] || '多Agent复盘局'}`
  while (game.timelineIndex < game.timeline.length) {
    const event = game.timeline[game.timelineIndex]
    game.phase = event.phase
    game.day = event.day || 1
    game.current_speaker_id = event.log?.actor_id || null
    if (event.decision?.actor_id) {
      game.decisions.push(makeDecision(game, event.decision))
    }
    if (event.log) {
      game.logs.push(makeLog(game, event.log))
    }
    event.apply?.(game)
    game.timelineIndex += 1
  }
  game.current_speaker_id = null
  game.waiting_for = 'none'
  return snapshot(game)
}

function ensureSeedHistory() {
  const existingIds = new Set(archivedGames.map((game) => game.game_id))

  // 观战局种子：3种场景各2局
  const scenarios = [
    { scenario: 'good_win', indices: [0, 1] },
    { scenario: 'wolf_win', indices: [2, 3] },
    { scenario: 'long_game', indices: [4, 5] }
  ]

  const watchSeeds = scenarios.flatMap(({ scenario, indices }) =>
    indices.map((index) => {
      const game = buildCompletedMockGame(index, scenario)
      game.mode = 'watch'
      return game
    })
  ).filter((game) => !existingIds.has(game.game_id))

  // 玩家局种子
  const playSeeds = [6, 7, 8]
    .map((index) => {
      const scenario = index === 6 ? 'good_win' : index === 7 ? 'wolf_win' : 'long_game'
      const game = buildCompletedMockGame(index, scenario)
      game.mode = 'play'
      game.game_id = `mock-play-${index - 5}`
      return game
    })
    .filter((game) => !existingIds.has(game.game_id))

  const seeds = [...watchSeeds, ...playSeeds]
  if (archivedGames.length >= 9 && !seeds.length) return
  archivedGames = [...archivedGames, ...seeds].slice(0, 12)
  writeStoredHistory(archivedGames)
}

const MOCK_SPEECH_ACTIONS = new Set(['speak', 'speech', 'sheriff_speak', 'pk_speak', 'last_word'])
const MOCK_VOTE_ACTIONS = new Set(['vote', 'exile_vote', 'pk_vote', 'sheriff_vote'])
const MOCK_NO_TARGET_ACTIONS = new Set(['sheriff_run', 'sheriff_withdraw', 'speech_order'])

function isWolfRoleName(role = '') {
  return String(role || '').includes('狼人') || String(role || '').includes('白狼王')
}

function canonicalMockAction(actionType = '') {
  if (actionType === 'speech') return 'speak'
  if (actionType === 'vote') return 'exile_vote'
  if (actionType === 'white_wolf_burst' || actionType === 'white_wolf_explosion') return 'white_wolf_explode'
  return actionType || ''
}

function mockWaitingFor(actionType) {
  if (MOCK_SPEECH_ACTIONS.has(actionType)) return 'speech'
  if (MOCK_VOTE_ACTIONS.has(actionType)) return 'vote'
  return 'action'
}

function mockPromptForAction(actionType) {
  const prompts = {
    sheriff_speak: '轮到你发表警长竞选发言。',
    last_word: '轮到你发表遗言。',
    exile_vote: '请选择放逐投票目标。',
    pk_vote: '请选择 PK 投票目标。',
    sheriff_vote: '请选择警长投票目标。',
    guard_protect: '请选择守护目标。',
    werewolf_kill: '请选择狼队夜刀目标。',
    seer_check: '请选择查验目标。',
    witch_act: '请选择女巫行动。',
    hunter_shoot: '请选择开枪目标。',
    white_wolf_explode: '请选择白狼王自爆目标。'
  }
  return prompts[actionType] || '请选择本轮行动。'
}

function mockCandidateIds(game, actionType) {
  const humanId = Number(game.human_player_id)
  const alive = game.players.filter((player) => player.alive)
  if (MOCK_SPEECH_ACTIONS.has(actionType) || MOCK_NO_TARGET_ACTIONS.has(actionType)) return []
  if (actionType === 'guard_protect') return alive.map((player) => player.id)
  if (actionType === 'werewolf_kill') {
    return alive
      .filter((player) => player.id !== humanId && !isWolfRoleName(player.role_hint))
      .map((player) => player.id)
  }
  return alive
    .filter((player) => player.id !== humanId)
    .map((player) => player.id)
}

function mockPendingMetadata(game, actionType, event = {}) {
  if (actionType === 'witch_act') {
    return {
      can_save: !game.skill_state?.witch_antidote_used,
      can_poison: !game.skill_state?.witch_poison_used,
      antidote_available: !game.skill_state?.witch_antidote_used,
      poison_available: !game.skill_state?.witch_poison_used,
      attacked_player: event.decision?.target_id ?? event.log?.target_id ?? null
    }
  }
  if (actionType === 'speech_order') return { choices: ['forward', 'reverse'] }
  return {}
}

function mockPendingForEvent(game, event = {}) {
  if (!game || game.mode !== 'play' || !game.human_player_id || game.winner) return null
  const humanId = Number(game.human_player_id)
  const actorId = Number(event.decision?.actor_id ?? event.log?.actor_id ?? 0)
  if (!actorId || actorId !== humanId) return null

  const actionType = canonicalMockAction(event.decision?.action || event.log?.type || event.log?.event_type || 'speak')
  if (!actionType) return null
  const human = game.players.find((player) => player.id === humanId)
  if (!human?.alive && actionType !== 'last_word') return null

  const candidateIds = mockCandidateIds(game, actionType)
  return {
    game_id: game.game_id,
    player_id: humanId,
    action_type: actionType,
    day: event.day || game.day || 1,
    phase: event.phase || game.phase,
    prompt: mockPromptForAction(actionType),
    candidate_ids: candidateIds,
    metadata: mockPendingMetadata(game, actionType, event),
    observation: {
      role: human?.role_hint || '',
      role_state: {
        antidote_available: !game.skill_state?.witch_antidote_used,
        poison_available: !game.skill_state?.witch_poison_used,
        has_exploded: Boolean(game.skill_state?.white_wolf_burst_used)
      }
    }
  }
}

function setPendingHumanEvent(game, event, pending) {
  const actionType = canonicalMockAction(pending.action_type)
  const waitingFor = mockWaitingFor(actionType)
  game.phase = event.phase || game.phase
  game.day = event.day || game.day || 1
  game.current_speaker_id = waitingFor === 'speech' ? Number(game.human_player_id) : null
  game.waiting_for = waitingFor
  game.pending_human_action = pending
  game.pending_action = waitingFor === 'speech'
    ? null
    : {
        type: actionType,
        prompt: pending.prompt,
        candidate_ids: pending.candidate_ids || [],
        options: pending.metadata || {}
      }
}

function clearPendingHumanAction(game) {
  game.pending_human_action = null
  game.pending_action = null
  game.waiting_for = 'none'
}

function consumePendingTimelineEvent(game, hadPending) {
  if (!hadPending) return
  game.timelineIndex = Math.min(game.timeline.length, game.timelineIndex + 1)
}

function applyHumanSkillState(game, actionType, choice) {
  const action = canonicalMockAction(actionType)
  const selected = choice === 'antidote' ? 'save' : (['skip', 'none', 'pass'].includes(choice) ? 'none' : choice)
  if (action === 'witch_act') {
    if (selected === 'save') game.skill_state.witch_antidote_used = true
    if (selected === 'poison') game.skill_state.witch_poison_used = true
  }
  if (action === 'white_wolf_explode') {
    game.skill_state.white_wolf_burst_used = true
  }
}

function stepActiveGame() {
  if (!activeGame) activeGame = baseGame('watch', 'good_win')
  if (activeGame.pending_human_action) {
    return { game: activeGame, delay: MOCK_STEP_DELAY_MS[activeGame.phase] || 300 }
  }
  const event = activeGame.timeline[activeGame.timelineIndex]
  if (!event) return { game: activeGame, delay: MOCK_STEP_DELAY_MS.ended }

  const pending = mockPendingForEvent(activeGame, event)
  if (pending) {
    setPendingHumanEvent(activeGame, event, pending)
    archiveActiveGame()
    return { game: activeGame, delay: 220 }
  }

  activeGame.phase = event.phase
  activeGame.day = event.day || activeGame.day || 1
  activeGame.current_speaker_id = event.log?.actor_id || null
  activeGame.waiting_for = 'none'
  activeGame.pending_action = null
  activeGame.pending_human_action = null

  if (event.decision?.actor_id) {
    activeGame.decisions.push(makeDecision(activeGame, event.decision))
  }
  if (event.log) {
    activeGame.logs.push(makeLog(activeGame, event.log))
  }
  event.apply?.(activeGame)
  activeGame.timelineIndex += 1
  archiveActiveGame()
  return { game: activeGame, delay: MOCK_STEP_DELAY_MS[event.phase] || 900 }
}

function startGame(body = {}) {
  activeGame = baseGame(body.mode || 'watch', body.scenario || 'good_win')
  applyStartConfig(activeGame, body)
  archivedGames = archivedGames.filter((game) => game.game_id !== activeGame.game_id)
  writeStoredHistory(archivedGames)
  return activeGame
}

function addHumanSpeech(text = '') {
  if (!activeGame) startGame({ mode: 'play' })
  const pending = activeGame.pending_human_action
  const hadPending = Boolean(pending)
  const actionType = canonicalMockAction(pending?.action_type || 'speak')
  activeGame.phase = pending?.phase || 'speech'
  activeGame.day = pending?.day || activeGame.day || 1
  clearPendingHumanAction(activeGame)
  activeGame.current_speaker_id = activeGame.human_player_id || 1
  const message = text || `${activeGame.current_speaker_id}号玩家选择过麦，交给后置位继续分析。`
  activeGame.decisions.push(makeDecision(activeGame, {
    actor_id: activeGame.current_speaker_id,
    action: actionType,
    reason: message,
    public_summary: message,
    source: 'human',
    confidence: 1
  }))
  activeGame.logs.push(makeLog(activeGame, {
    speaker: `${activeGame.current_speaker_id}号`,
    actor_id: activeGame.current_speaker_id,
    message,
    visibility: 'public',
    type: actionType === 'speak' ? 'speech' : actionType,
    source: 'human'
  }))
  consumePendingTimelineEvent(activeGame, hadPending)
  archiveActiveGame()
  return activeGame
}

function addHumanVote(targetId, actionType = 'vote') {
  if (!activeGame) startGame({ mode: 'play' })
  const pending = activeGame.pending_human_action
  const hadPending = Boolean(pending)
  const actorId = activeGame.human_player_id || 1
  const action = canonicalMockAction(actionType || pending?.action_type || 'vote')
  activeGame.phase = pending?.phase || 'vote'
  activeGame.day = pending?.day || activeGame.day || 1
  clearPendingHumanAction(activeGame)
  activeGame.current_speaker_id = actorId
  activeGame.decisions.push(makeDecision(activeGame, {
    actor_id: actorId,
    action,
    target_id: targetId,
    reason: `${actorId}号玩家投票给${targetId}号。`,
    public_summary: `${actorId}号投票给${targetId}号。`,
    source: 'human',
    confidence: 1
  }))
  activeGame.logs.push(makeLog(activeGame, {
    speaker: `${actorId}号`,
    actor_id: actorId,
    target_id: targetId,
    message: `我投${targetId}号。`,
    visibility: 'public',
    type: action,
    source: 'human'
  }))
  consumePendingTimelineEvent(activeGame, hadPending)
  archiveActiveGame()
  return activeGame
}

function addHumanGenericAction(actionType, targetId = null, choice = null, text = '') {
  if (!activeGame) startGame({ mode: 'play' })
  const pending = activeGame.pending_human_action
  const hadPending = Boolean(pending)
  const actorId = activeGame.human_player_id || 1
  const action = canonicalMockAction(actionType || pending?.action_type || 'action')
  activeGame.phase = pending?.phase || activeGame.phase
  activeGame.day = pending?.day || activeGame.day || 1
  clearPendingHumanAction(activeGame)
  activeGame.current_speaker_id = actorId
  const targetText = targetId ? `，目标 ${targetId} 号` : ''
  const choiceText = choice ? `，选择 ${choice}` : ''
  const message = text || `${actorId}号提交 ${action}${choiceText}${targetText}`
  applyHumanSkillState(activeGame, action, choice)
  activeGame.decisions.push(makeDecision(activeGame, {
    actor_id: actorId,
    action,
    target_id: targetId,
    selected_skill: choice || '',
    reason: message,
    public_summary: message,
    source: 'human',
    confidence: 1
  }))
  activeGame.logs.push(makeLog(activeGame, {
    speaker: `${actorId}号`,
    actor_id: actorId,
    target_id: targetId,
    message,
    visibility: 'public',
    type: action,
    source: 'human'
  }))
  consumePendingTimelineEvent(activeGame, hadPending)
  archiveActiveGame()
  return activeGame
}

function parseBody(options = {}) {
  if (!options.body) return {}
  try {
    return typeof options.body === 'string' ? JSON.parse(options.body) : options.body
  } catch {
    return {}
  }
}

function mockRoleLabel(role) {
  return MOCK_EVOLUTION_LABELS[role] || role || '未知角色'
}

function mockRoleVersions(role) {
  return clone(mockEvolutionVersions[role] || [])
}

function mockRoleVersionDetail(role, versionId) {
  const version = (mockEvolutionVersions[role] || []).find((item) => item.version_id === versionId)
  if (!version) throw new Error('Mock version not found')
  const leaderboard = mockRoleLeaderboard(role).find((item) => item.hash === versionId)
  return {
    kind: 'knowledge_package',
    schema_version: 2,
    version_id: version.version_id,
    role,
    parent_id: version.parent_id || null,
    created_at: version.created_at,
    skills: [
      { path: `${mockRoleLabel(role)}-speech.md`, content_hash: `${versionId}-speech-hash` },
      { path: `${mockRoleLabel(role)}-vote.md`, content_hash: `${versionId}-vote-hash` }
    ],
    patterns: [
      { pattern_id: `${versionId}-p1`, summary: `${mockRoleLabel(role)}优先复用高置信度发言线索。` },
      { pattern_id: `${versionId}-p2`, summary: '投票前对齐警徽流、死亡信息和团队目标。' }
    ],
    provenance: {
      source: version.source || 'mock',
      run_id: version.run_id || null,
      proposal_ids: [],
      evidence_game_ids: [],
      rejected_pattern_ids: []
    },
    metrics: {
      win_rate: leaderboard?.target_side_win_rate || 0,
      score: leaderboard?.target_role_role_weighted_score || 0,
      speech_score: 0.64,
      vote_score: 0.61,
      skill_score: 0.58,
      games_played: leaderboard?.total_games || 0,
      confidence_interval: leaderboard?.target_side_win_rate_ci || null
    }
  }
}

function mockRoleLeaderboard(role) {
  const roleIndex = Math.max(0, MOCK_EVOLUTION_ROLES.indexOf(role))
  const baselineScore = 0.5 + (roleIndex % 5) * 0.035
  return (mockEvolutionVersions[role] || []).map((version, index) => {
    const score = Math.min(0.88, baselineScore + (version.is_baseline ? 0 : 0.07 - index * 0.01))
    const winRate = Math.min(0.82, score - 0.04)
    return {
      hash: version.version_id,
      role,
      source: version.source,
      battle_record: {
        wins: Math.round(winRate * 20),
        losses: Math.max(0, 20 - Math.round(winRate * 20))
      },
      recommendation: version.is_baseline ? 'baseline' : score >= baselineScore + 0.04 ? 'promote' : 'hold',
      is_baseline: version.is_baseline,
      total_games: 20,
      target_role_role_weighted_score: score,
      target_side_win_rate: winRate,
      target_side_win_rate_ci: [Math.max(0, winRate - 0.08), Math.min(1, winRate + 0.08)],
      target_role_fallback_rate: version.is_baseline ? 0.02 : 0.04,
      delta_vs_baseline: {
        target_role_role_weighted_score: version.is_baseline ? 0 : score - baselineScore,
        target_side_win_rate: version.is_baseline ? 0 : winRate - Math.max(0, baselineScore - 0.04)
      },
      data_sufficient: true
    }
  }).sort((a, b) => Number(b.is_baseline) - Number(a.is_baseline) || b.target_role_role_weighted_score - a.target_role_role_weighted_score)
}

function findMockEvolutionEntity(id) {
  return mockEvolutionRuns.find((run) => run.run_id === id)
    || mockEvolutionBatches.find((batch) => batch.batch_id === id)
}

function mockEvolutionBaseline(role) {
  return (mockEvolutionVersions[role] || []).find((version) => version.is_baseline)
    || (mockEvolutionVersions[role] || [])[0]
}

function createMockEvolutionRun(body = {}) {
  const role = body.roles?.[0] || MOCK_EVOLUTION_ROLES[0]
  const baseline = mockEvolutionBaseline(role)
  const id = `mock-evo-${role}-${++mockEvolutionCounter}`
  const candidate = `cand-${role}-mock-${mockEvolutionCounter}`
  if (!mockEvolutionVersions[role]) mockEvolutionVersions[role] = []
  mockEvolutionVersions[role].unshift({
    version_id: candidate,
    role,
    source: 'evolution',
    created_at: new Date().toISOString(),
    is_baseline: false
  })
  mockEvolutionDiffs[id] = [
    { filename: `${mockRoleLabel(role)}-speech.md`, action: 'rewrite', proposal_ref: `${id}-speech` },
    { filename: `${mockRoleLabel(role)}-vote.md`, action: 'append', proposal_ref: `${id}-vote` }
  ]
  const run = {
    kind: 'role_evolution_run',
    schema_version: 1,
    run_id: id,
    role,
    status: 'queued',
    stage: 'queued',
    current_stage: 'queued',
    started_at: new Date().toISOString(),
    parent_hash: baseline?.version_id || `base-${role}`,
    candidate_hash: candidate,
    config: {
      roles: [role],
      training_games: Number(body.training_games ?? 5),
      battle_games: Number(body.battle_games ?? 4),
      max_days: Number(body.max_days || 5),
      auto_promote: true
    },
    training_games: Number(body.training_games ?? 5),
    battle_games: Number(body.battle_games ?? 4),
    training_completed: 0,
    battle_completed: 0,
    battle_result: {
      candidate: { avg_role_weighted_score: 0, target_side_win_rate: 0 },
      baseline: { avg_role_weighted_score: 0, target_side_win_rate: 0 },
      recommendation: 'pending'
    }
  }
  mockEvolutionRuns.unshift(run)
  return clone(run)
}

function createMockEvolutionBatch(body = {}) {
  const roles = Array.isArray(body.roles) && body.roles.length ? body.roles : MOCK_EVOLUTION_ROLES
  const id = `mock-batch-${++mockEvolutionCounter}`
  const batch = {
    kind: 'role_evolution_batch',
    schema_version: 1,
    batch_id: id,
    roles,
    status: 'queued',
    stage: 'queued',
    current_stage: 'queued',
    started_at: new Date().toISOString(),
    config: {
      roles,
      training_games: Number(body.training_games ?? 5),
      battle_games: Number(body.battle_games ?? 4),
      max_days: Number(body.max_days || 5),
      auto_promote: true
    },
    training_games: Number(body.training_games ?? 5),
    battle_games: Number(body.battle_games ?? 4),
    training_completed: 0,
    battle_completed: 0,
    runs: []
  }
  mockEvolutionBatches.unshift(batch)
  mockEvolutionDiffs[id] = roles.slice(0, 4).map((role) => ({
    filename: `${mockRoleLabel(role)}-batch.md`,
    action: 'schedule',
    proposal_ref: `${id}-${role}`
  }))
  return clone(batch)
}

function createMockBenchmarkBatch(body = {}) {
  const roles = Array.isArray(body.roles) && body.roles.length ? body.roles : [MOCK_EVOLUTION_ROLES[0]]
  const battleGames = Number(body.battle_games || 10)
  const maxDays = Number(body.max_days || 5)
  const id = `mock-bench-${++mockBenchmarkCounter}`
  const batch = {
    kind: 'benchmark_batch',
    schema_version: 1,
    batch_id: id,
    roles,
    status: 'completed',
    started_at: new Date().toISOString(),
    finished_at: new Date().toISOString(),
    config: { roles, battle_games: battleGames, max_days: maxDays },
    result: {
      batch_id: id,
      game_count: battleGames,
      completed: battleGames,
      errored: 0,
      score_summary: {
        game_count: battleGames,
        decision_judge_aggregate: {
          status: battleGames > 0 ? 'ok' : 'skipped',
          game_count: battleGames,
          reported_games: battleGames,
          judged_decisions: battleGames,
          failed_decisions: 0,
          avg_score: battleGames > 0 ? 7.1 : null,
          bad_rate: battleGames > 0 ? 0.1 : null,
          unknown_rate: battleGames > 0 ? 0 : null,
          quality_counts: battleGames > 0 ? { good: Math.max(0, battleGames - 2), ok: 1, bad: 1 } : {},
          top_mistake_tags: battleGames > 0 ? [{ tag: 'target_priority', count: 1 }] : [],
          by_role: {},
          by_action_type: {},
          lowest_decisions: []
        }
      },
      fairness: { is_fair: true, reason: 'mock' },
      rankable: battleGames > 0,
      rankable_reason: battleGames > 0 ? '' : 'No games in batch'
    }
  }
  mockBenchmarkBatches.unshift(batch)
  return clone(batch)
}

function stopMockBenchmarkBatch(batchId) {
  const batch = mockBenchmarkBatches.find((item) => item.batch_id === batchId)
  if (!batch) throw new Error('Mock benchmark batch not found')
  batch.status = 'failed'
  batch.stop_requested = true
  batch.finished_at = batch.finished_at || new Date().toISOString()
  batch.error = batch.error || 'stopped'
  return clone(batch)
}

function applyMockEvolutionAction(id, action) {
  const entity = findMockEvolutionEntity(id)
  if (!entity) throw new Error('Mock evolution run not found')

  if (action === 'promote') {
    entity.status = 'promoted'
    entity.stage = 'promoted'
    entity.current_stage = 'promoted'
    entity.completed_at = new Date().toISOString()
    if (entity.role && entity.candidate_hash) {
      const versions = mockEvolutionVersions[entity.role] || []
      let candidate = versions.find((version) => version.version_id === entity.candidate_hash)
      if (!candidate) {
        candidate = {
          version_id: entity.candidate_hash,
          role: entity.role,
          source: 'evolution',
          created_at: new Date().toISOString(),
          is_baseline: false
        }
        versions.unshift(candidate)
        mockEvolutionVersions[entity.role] = versions
      }
      versions.forEach((version) => {
        version.is_baseline = version.version_id === entity.candidate_hash
      })
    }
  } else if (action === 'reject') {
    entity.status = 'rejected'
    entity.stage = 'rejected'
    entity.current_stage = 'rejected'
    entity.completed_at = new Date().toISOString()
  } else if (action === 'stop') {
    entity.status = 'paused'
    entity.stage = 'paused'
    entity.current_stage = 'paused'
  } else if (action === 'resume') {
    entity.status = 'queued'
    entity.stage = 'queued'
    entity.current_stage = 'queued'
  } else if (action === 'rerun_consolidation') {
    entity.status = 'consolidating'
    entity.stage = 'consolidating'
    entity.current_stage = 'consolidating'
  } else if (action === 'terminate') {
    entity.status = 'failed'
    entity.stage = 'failed'
    entity.current_stage = 'failed'
    entity.completed_at = new Date().toISOString()
  }

  return clone(entity)
}

function rollbackMockRole(role, versionId) {
  const versions = mockEvolutionVersions[role] || []
  const target = versions.find((version) => version.version_id === versionId)
  if (!target) throw new Error('Mock version not found')
  versions.forEach((version) => {
    version.is_baseline = version.version_id === versionId
  })
  return {
    kind: 'role_rollback',
    schema_version: 2,
    role,
    new_baseline: versionId
  }
}

function mockEvolutionGames(runId, phase = 'training', side = '') {
  const count = phase === 'training' ? 4 : 3
  return Array.from({ length: count }, (_, index) => ({
    game_id: `${runId}-${phase || 'game'}-${side || 'all'}-${index + 1}`,
    phase,
    side: side || null,
    event_count: 38 + index * 7,
    winner: index % 2 === 0 ? 'good' : 'werewolves',
    day: 2 + (index % 3),
    summary: `${phase === 'training' ? '训练' : '对战'}样本局 ${index + 1}`
  }))
}

function mockEvolutionGameArchive(runId, gameId, phase = 'training', side = '') {
  const sideLabel = side === 'baseline' ? '基线' : side === 'candidate' ? '候选' : '训练'
  return {
    title: `${sideLabel}样本局 · ${gameId}`,
    summary: `${runId} 的${sideLabel}样本局，用于核对候选技能在发言、投票和夜间行动中的实际行为。`,
    verdict: gameId.includes('-2') ? '狼人胜利' : '好人胜利',
    highlights: [
      '预言家发言是否清晰给出查验链路。',
      '关键轮次投票是否贴合站边与狼坑收敛。',
      '夜间技能行动是否减少无效目标和重复信息。'
    ],
    phase,
    side: side || null
  }
}

function mockEvolutionGameDecisions(runId, gameId, phase = 'training', side = '') {
  return {
    run_id: runId,
    game_id: gameId,
    side: side || null,
    decisions: [
      {
        id: `${gameId}-decision-1`,
        day: 1,
        phase,
        actor_name: '预言家',
        action: 'speak',
        confidence: 0.82,
        public_summary: '明确报出首验金水，并给出两轮警徽流。',
        private_reasoning: '候选策略优先降低模糊发言，避免被狼队利用身份摇摆。'
      },
      {
        id: `${gameId}-decision-2`,
        day: 2,
        phase: 'vote',
        actor_name: '预言家',
        action: 'vote',
        confidence: 0.76,
        public_summary: '按发言矛盾和跟票关系归票焦点位。',
        private_reasoning: '对比 baseline，候选更早锁定悍跳狼同伴的互保路径。'
      }
    ]
  }
}

function mockEvolutionGameEvents(runId, gameId, phase = 'training', side = '') {
  return {
    run_id: runId,
    game_id: gameId,
    side: side || null,
    events: [
      { sequence: 1, day: 1, phase: 'night', event_type: 'seer_check', message: '预言家完成首夜查验。' },
      { sequence: 2, day: 1, phase: 'speech', event_type: 'speech', message: '候选技能生成更短的身份声明。' },
      { sequence: 3, day: 2, phase: 'vote', event_type: 'vote', message: '归票落在主要狼坑位。' }
    ]
  }
}

function findMockSelfplayRun(runId) {
  return mockSelfplayRuns.find((run) => run.run_id === runId)
}

function publishMockSelfplayLeaderboard(run) {
  if (run._leaderboard_published) return

  const totalGames = Number(run.completed_games || run.num_games || 0)
  const score = 0.56 + Math.min(0.18, totalGames / Math.max(20, Number(run.num_games || 1)))
  const winRate = 0.5 + Math.min(0.16, totalGames / Math.max(24, Number(run.num_games || 1)))

  mockBattleLeaderboardEntries.unshift({
    role: 'selfplay',
    label: run.label || run.agent_version || run.run_id,
    version_id: run.agent_version || run.run_id,
    score: Math.round(score * 100) / 100,
    win_rate: Math.round(winRate * 100) / 100,
    total_games: totalGames,
    source: 'selfplay',
    run_id: run.run_id
  })
  run._leaderboard_published = true
}

function advanceMockSelfplayRuns() {
  mockSelfplayRuns.forEach((run) => {
    if (run.status !== 'running') return

    const total = Number(run.num_games || run.progress?.total || 0)
    const current = Number(run.completed_games || run.progress?.completed || 0)
    const next = Math.min(total, current + 1)
    run.completed_games = next
    run.progress = { completed: next, total }

    if (total > 0 && next >= total) {
      run.status = 'completed'
      run.completed_at = new Date().toISOString()
      run.summary = {
        good: Math.ceil(total * 0.58),
        werewolves: Math.floor(total * 0.42)
      }
      publishMockSelfplayLeaderboard(run)
    }
  })
}

function mockSelfplayGames(runId) {
  const run = findMockSelfplayRun(runId)
  const completed = Math.max(1, Number(run?.completed_games || run?.progress?.completed || 3))
  return Array.from({ length: Math.min(completed, 8) }, (_, index) => ({
    game_id: `${runId}-game-${index + 1}`,
    event_count: 42 + index * 6,
    winner: index % 3 === 1 ? 'werewolves' : 'good',
    day: 2 + (index % 4),
    phase: index % 2 === 0 ? 'ended' : 'vote',
    in_progress: run?.status === 'running' && index === completed - 1
  }))
}

function mockSelfplayGameArchive(runId, gameId) {
  return {
    title: `评测对局 · ${gameId}`,
    summary: `${runId} 的 selfplay 对局，用于评估当前 agent 版本在完整 12 人局中的胜负、发言、投票和技能决策质量。`,
    verdict: gameId.includes('-2') ? '狼人胜利' : '好人胜利',
    highlights: [
      '首日发言是否能形成可复盘的站边依据。',
      '关键夜晚技能目标是否符合局势收益。',
      '投票轮是否能从历史发言和票型中收束焦点。'
    ]
  }
}

function mockSelfplayGameDecisions(runId, gameId) {
  return {
    run_id: runId,
    game_id: gameId,
    decisions: [
      {
        id: `${gameId}-d1`,
        day: 1,
        phase: 'speech',
        actor_name: '预言家',
        action: 'speak',
        confidence: 0.78,
        public_summary: '报出查验信息，并提出下一轮警徽流。'
      },
      {
        id: `${gameId}-d2`,
        day: 2,
        phase: 'vote',
        actor_name: '村民',
        action: 'vote',
        confidence: 0.71,
        public_summary: '根据警上对跳和警下票型投出焦点位。'
      }
    ]
  }
}

function mockSelfplayGameEvents(runId, gameId) {
  return {
    run_id: runId,
    game_id: gameId,
    events: [
      { sequence: 1, day: 1, phase: 'night', event_type: 'start', message: '夜晚开始，法官分发行动请求。' },
      { sequence: 2, day: 1, phase: 'speech', event_type: 'speech', message: '预言家公开首验信息。' },
      { sequence: 3, day: 2, phase: 'vote', event_type: 'vote', message: '白天投票形成主要放逐目标。' }
    ]
  }
}

function createMockSelfplayRun(body = {}) {
  const id = `mock-selfplay-${++mockSelfplayCounter}`
  const total = Number(body.num_games || 10)
  const run = {
    run_id: id,
    status: 'running',
    progress: { completed: 0, total },
    num_games: total,
    completed_games: 0,
    label: body.label || 'battle-eval',
    agent_version: body.agent_version || 'agent',
    skill_dir: body.skill_dir || '',
    max_days: Number(body.max_days || 20),
    enable_sheriff: body.enable_sheriff !== false,
    enable_batch_dream: Boolean(body.enable_batch_dream),
    created_at: new Date().toISOString(),
    started_at: new Date().toISOString(),
    artifact_run_id: id
  }
  mockSelfplayRuns.unshift(run)
  return cloneSelfplayRun(run)
}

function applyMockSelfplayAction(runId, action) {
  const run = findMockSelfplayRun(runId)
  if (!run) throw new Error('Mock selfplay run not found')
  if (action === 'stop') run.status = 'paused'
  if (action === 'resume') run.status = 'running'
  if (action === 'terminate') {
    run.status = 'failed'
    run.error = '用户终止'
  }
  return cloneSelfplayRun(run)
}

export async function mockApiFetch(path, options = {}) {
  const body = parseBody(options)
  const method = String(options.method || 'GET').toUpperCase()
  const [routePath, queryString = ''] = String(path).split('?')

  if (path === '/health') {
    return {
      ok: true,
      mode: 'mock',
      external: {
        provider: 'frontend-mock',
        latency: 'simulated',
        agents: BASE_PLAYERS.length
      }
    }
  }

  if (routePath === '/leaderboards') {
    return {
      entries: clone(mockBattleLeaderboardEntries),
      source: 'frontend-mock',
      source_type: 'mock'
    }
  }

  if (routePath === '/selfplay') {
    if (method === 'POST') return createMockSelfplayRun(body)
    advanceMockSelfplayRuns()
    return { runs: mockSelfplayRuns.map(cloneSelfplayRun) }
  }

  const selfplayActionMatch = routePath.match(/^\/selfplay\/([^/]+)\/(stop|resume|terminate)$/)
  if (selfplayActionMatch && method === 'POST') {
    return applyMockSelfplayAction(
      decodeURIComponent(selfplayActionMatch[1]),
      selfplayActionMatch[2]
    )
  }

  const selfplayGamesMatch = routePath.match(/^\/selfplay\/([^/]+)\/games$/)
  if (selfplayGamesMatch) {
    const runId = decodeURIComponent(selfplayGamesMatch[1])
    return {
      run_id: runId,
      games: mockSelfplayGames(runId)
    }
  }

  const selfplayGameDetailMatch = routePath.match(/^\/selfplay\/([^/]+)\/games\/([^/]+)\/(archive|decisions|events)$/)
  if (selfplayGameDetailMatch) {
    const runId = decodeURIComponent(selfplayGameDetailMatch[1])
    const gameId = decodeURIComponent(selfplayGameDetailMatch[2])
    const detailType = selfplayGameDetailMatch[3]
    if (detailType === 'archive') return mockSelfplayGameArchive(runId, gameId)
    if (detailType === 'decisions') return mockSelfplayGameDecisions(runId, gameId)
    return mockSelfplayGameEvents(runId, gameId)
  }

  const selfplayRunMatch = routePath.match(/^\/selfplay\/([^/]+)$/)
  if (selfplayRunMatch) {
    advanceMockSelfplayRuns()
    const run = findMockSelfplayRun(decodeURIComponent(selfplayRunMatch[1]))
    if (!run) throw new Error('Mock selfplay run not found')
    return cloneSelfplayRun(run)
  }

  if (routePath === '/roles') {
    return { roles: MOCK_EVOLUTION_ROLES.slice() }
  }

  const roleVersionsMatch = routePath.match(/^\/roles\/([^/]+)\/versions$/)
  if (roleVersionsMatch) {
    const role = decodeURIComponent(roleVersionsMatch[1])
    return {
      role,
      versions: mockRoleVersions(role)
    }
  }

  const roleVersionDetailMatch = routePath.match(/^\/roles\/([^/]+)\/versions\/([^/]+)$/)
  if (roleVersionDetailMatch) {
    return mockRoleVersionDetail(
      decodeURIComponent(roleVersionDetailMatch[1]),
      decodeURIComponent(roleVersionDetailMatch[2])
    )
  }

  const roleLeaderboardMatch = routePath.match(/^\/roles\/([^/]+)\/leaderboard$/)
  if (roleLeaderboardMatch) {
    const role = decodeURIComponent(roleLeaderboardMatch[1])
    return {
      kind: 'role_leaderboard',
      schema_version: 1,
      role,
      source: 'frontend-mock',
      entries: clone(mockRoleLeaderboard(role))
    }
  }

  const roleRollbackMatch = routePath.match(/^\/roles\/([^/]+)\/rollback\/([^/]+)$/)
  if (roleRollbackMatch && method === 'POST') {
    return rollbackMockRole(
      decodeURIComponent(roleRollbackMatch[1]),
      decodeURIComponent(roleRollbackMatch[2])
    )
  }

  if (routePath === '/evolution-runs') {
    if (method === 'POST') {
      const roles = Array.isArray(body.roles) ? body.roles : []
      const isSingle = roles.length === 1
      return isSingle ? createMockEvolutionRun(body) : createMockEvolutionBatch(body)
    }
    return {
      kind: 'evolution_runs',
      schema_version: 1,
      runs: clone(mockEvolutionRuns),
      batches: clone([...mockEvolutionBatches, ...mockBenchmarkBatches])
    }
  }

  if ((routePath === '/benchmark' || routePath === '/benchmark/batch') && method === 'POST') {
    return createMockBenchmarkBatch(body)
  }

  const benchmarkStopMatch = routePath.match(/^\/benchmark\/batch\/([^/]+)\/stop$/)
  if (benchmarkStopMatch && method === 'POST') {
    return stopMockBenchmarkBatch(decodeURIComponent(benchmarkStopMatch[1]))
  }

  const evolutionActionMatch = routePath.match(/^\/evolution-runs\/([^/]+)\/actions$/)
  if (evolutionActionMatch && method === 'POST') {
    return applyMockEvolutionAction(decodeURIComponent(evolutionActionMatch[1]), body.action)
  }

  const evolutionDiffMatch = routePath.match(/^\/evolution-runs\/([^/]+)\/diff$/)
  if (evolutionDiffMatch) {
    const id = decodeURIComponent(evolutionDiffMatch[1])
    return {
      kind: 'role_evolution_diff',
      schema_version: 1,
      run_id: id,
      diffs: clone(mockEvolutionDiffs[id] || [])
    }
  }

  const evolutionGamesMatch = routePath.match(/^\/evolution-runs\/([^/]+)\/games$/)
  if (evolutionGamesMatch) {
    const params = new URLSearchParams(queryString)
    const id = decodeURIComponent(evolutionGamesMatch[1])
    const phase = params.get('phase') || 'training'
    const side = params.get('side') || ''
    return {
      kind: 'role_evolution_games',
      schema_version: 1,
      run_id: id,
      phase,
      side: side || null,
      games: mockEvolutionGames(id, phase, side)
    }
  }

  const evolutionGameDetailMatch = routePath.match(/^\/evolution-runs\/([^/]+)\/games\/([^/]+)\/(archive|decisions|events)$/)
  if (evolutionGameDetailMatch) {
    const params = new URLSearchParams(queryString)
    const runId = decodeURIComponent(evolutionGameDetailMatch[1])
    const gameId = decodeURIComponent(evolutionGameDetailMatch[2])
    const detailType = evolutionGameDetailMatch[3]
    const phase = params.get('phase') || 'training'
    const side = params.get('side') || ''
    if (detailType === 'archive') return mockEvolutionGameArchive(runId, gameId, phase, side)
    if (detailType === 'decisions') return mockEvolutionGameDecisions(runId, gameId, phase, side)
    return mockEvolutionGameEvents(runId, gameId, phase, side)
  }

  const evolutionRunMatch = routePath.match(/^\/evolution-runs\/([^/]+)$/)
  if (evolutionRunMatch) {
    const entity = findMockEvolutionEntity(decodeURIComponent(evolutionRunMatch[1]))
    if (!entity) throw new Error('Mock evolution run not found')
    return clone(entity)
  }

  if (routePath === '/games') {
    if (method === 'POST') {
      await sleep(360)
      return snapshot(startGame({
        ...body,
        mode: body.human_player_id ? 'play' : (body.mode || 'watch'),
        scenario: body.scenario || 'good_win'
      }))
    }
    ensureSeedHistory()
    return {
      games: archivedGames.map((game) => ({
        game_id: game.game_id,
        log_name: game.log_name,
        day: game.day,
        phase: game.phase,
        event_count: game.logs.length,
        winner: game.winner,
        mode: game.mode,
        seed: game.seed,
        max_days: game.max_days,
        enable_sheriff: game.enable_sheriff,
        skill_dir: game.skill_dir,
        role_skill_dirs: game.role_skill_dirs || game.config?.role_skill_dirs || {},
        player_count: game.player_count,
        human_player_id: game.human_player_id,
        config: game.config || {}
      }))
    }
  }

  const gameHumanActionMatch = routePath.match(/^\/games\/([^/]+)\/human-action$/)
  if (gameHumanActionMatch) {
    const gameId = decodeURIComponent(gameHumanActionMatch[1])
    return activeGame?.game_id === gameId ? (activeGame.pending_human_action || null) : null
  }

  const gameStopMatch = routePath.match(/^\/games\/([^/]+)\/stop$/)
  if (gameStopMatch && method === 'POST') {
    const stopped = activeGame ? snapshot(activeGame) : null
    activeGame = null
    return stopped || {
      game_id: decodeURIComponent(gameStopMatch[1]),
      status: 'cancelled',
      day: 0,
      phase: 'ended',
      players: [],
      logs: [],
      decisions: [],
      winner: null
    }
  }

  const gameActionMatch = routePath.match(/^\/games\/([^/]+)\/action$/)
  if (gameActionMatch && method === 'POST') {
    await sleep(760)
    const actionType = body.action_type || body.action || ''
    const targetId = body.target == null ? null : Number(body.target)
    if (['speak', 'sheriff_speak', 'pk_speak', 'last_word'].includes(actionType)) {
      return snapshot(addHumanSpeech(body.text || ''))
    }
    if (['exile_vote', 'pk_vote', 'sheriff_vote', 'vote'].includes(actionType)) {
      return snapshot(addHumanVote(targetId || 1, actionType))
    }
    return snapshot(addHumanGenericAction(actionType || 'action', targetId, body.choice || null, body.text || ''))
  }

  const gameMatch = routePath.match(/^\/games\/([^/]+)(?:\/(archive|review))?$/)
  if (gameMatch) {
    ensureSeedHistory()
    const params = new URLSearchParams(queryString)
    const gameId = decodeURIComponent(gameMatch[1])
    if (params.get('advance') === '1' && activeGame?.game_id === gameId && !activeGame.winner) {
      const { delay } = stepActiveGame()
      await sleep(delay)
    }
    const game = archivedGames.find((item) => item.game_id === gameId) || snapshot(activeGame)
    if (!game) throw new Error('Mock game not found')
    if (gameMatch[2] === 'archive') {
      return {
        title: game.log_name,
        summary: '这是一局用于前端联调的多 agent mock 对局，覆盖随机发牌、夜晚行动、12名角色发言、投票、历史复盘和决策来源展示。',
        highlights: [
          '每名玩家都是独立 agent，并拥有按身份生成的详细发言。',
          'step 接口会按阶段延迟返回，模拟智能体推理耗时。',
          'decisions 字段包含 source、confidence、memory_summary、candidates 等复盘信息。'
        ]
      }
    }
    if (gameMatch[2] === 'review') {
      return {
        title: 'Mock 复盘报告',
        verdict: game.winner || '测试剧本未结束',
        game_summary: {
          winner: game.winner || 'villagers',
          total_days: game.day || 1,
          event_count: game.logs?.length || game.events?.length || 0,
          decision_count: game.decisions?.length || 0
        },
        player_evaluations: [
          {
            player_seat: 1,
            role: 'witch',
            speech_score: 0.62,
            vote_score: 0.58,
            skill_score: 0.48,
            information_score: 0.55,
            team_score: 0.61,
            overall_score: 0.57
          },
          {
            player_seat: 2,
            role: 'white_wolf_king',
            speech_score: 0.54,
            vote_score: 0.64,
            skill_score: 0.42,
            information_score: 0.49,
            team_score: 0.52,
            overall_score: 0.51
          }
        ],
        decision_judge: {
          status: 'ok',
          selection: {
            method: 'app.lib.evidence.select_key_decisions',
            total_decisions: game.decisions?.length || 44,
            key_decisions: 44,
            selected_for_judge: 3,
            max_decisions: 3
          },
          metrics: {
            total_decisions: game.decisions?.length || 44,
            key_decisions: 44,
            judged: 3,
            failed: 0
          },
          summary: {
            judged: 3,
            average_score: 4.3,
            quality_counts: {
              bad: 1,
              unknown: 1,
              ok: 1
            },
            lowest_decisions: [
              {
                decision_id: 'mock-wolf-kill',
                player_id: 2,
                role: 'white_wolf_king',
                action_type: 'werewolf_kill',
                score: 3,
                reason: '首夜未提交有效刀人目标，实际行动依赖系统策略修正，不能视为稳定的自主决策。',
                suggestion: '狼人阵营夜刀应明确目标和理由，优先围绕神职威胁、保护可能性和队友暴露风险做选择。'
              }
            ]
          },
          judgments: [
            {
              decision_id: 'mock-wolf-kill',
              player_id: 2,
              role: 'white_wolf_king',
              action_type: 'werewolf_kill',
              score: 3,
              quality: 'bad',
              reason: '首夜未提交有效刀人目标，实际行动依赖系统策略修正，不能视为稳定的自主决策。',
              suggestion: '狼人阵营夜刀应明确目标和理由，优先围绕神职威胁、保护可能性和队友暴露风险做选择。',
              mistake_tags: ['未提交有效刀人目标', '决策被系统策略修正']
            },
            {
              decision_id: 'mock-exile-vote',
              player_id: 1,
              role: 'witch',
              action_type: 'exile_vote',
              score: 5,
              quality: 'unknown',
              reason: '当前公开信息不足，弃票质量无法稳定判断。',
              suggestion: '投票前应结合当天发言、身份跳明和票型压力形成明确站边。',
              mistake_tags: []
            },
            {
              decision_id: 'mock-witch-act',
              player_id: 1,
              role: 'witch',
              action_type: 'witch_act',
              score: 5,
              quality: 'ok',
              reason: '首夜信息有限时不开药可以接受，但操作选择需要避免无效提交。',
              suggestion: '提交技能前确认候选项和药剂状态，确保系统执行的是原始意图。',
              mistake_tags: ['提交无效操作']
            }
          ]
        },
        notes: [
          '角色按 4平民、3普狼、1白狼王、守卫、女巫、预言家、猎人各1 随机分配。',
          '预言家、金水、狼坑和投票焦点会随随机身份动态变化。',
          '投票结果用于测试票型展示和历史详情页。'
        ]
      }
    }
    return game
  }

  throw new Error(`Unhandled mock API path: ${path}`)
}
