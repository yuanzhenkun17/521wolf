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

const MOCK_BENCHMARK_SUITES = [
  {
    id: 'role-baseline-quick-v1',
    version: 1,
    name: '角色基线快速',
    description: '固定种子的低成本角色版本评测',
    target_type: 'role_version',
    roles: MOCK_EVOLUTION_ROLES.slice(),
    game_count: 3,
    max_days: 5,
    paired_seed: true,
    seed_set_id: 'role-baseline-quick-202606',
    seed_count: 3,
    seed_preview: [260600, 260601, 260602],
    cost_tier: 'smoke',
    evaluation_set_id: 'role-baseline-quick-v1@v1',
    last_run: {
      batch_id: 'bench-role-quick-20260609',
      status: 'completed',
      current_stage: 'completed',
      target_type: 'role_version',
      started_at: '2026-06-09T09:12:00+08:00',
      finished_at: '2026-06-09T09:18:00+08:00',
      last_heartbeat_at: '2026-06-09T09:18:00+08:00',
      role_count: 7,
      result_count: 7,
      diagnostic_count: 1
    }
  },
  {
    id: 'role-baseline-standard-v1',
    version: 1,
    name: '角色基线标准',
    description: '固定种子的标准角色版本排行榜评测',
    target_type: 'role_version',
    roles: MOCK_EVOLUTION_ROLES.slice(),
    game_count: 30,
    max_days: 5,
    paired_seed: true,
    seed_set_id: 'role-baseline-standard-202606',
    seed_count: 30,
    seed_preview: [261000, 261001, 261002, 261003, 261004],
    cost_tier: 'standard',
    evaluation_set_id: 'role-baseline-standard-v1@v1',
    last_run: {
      batch_id: 'bench-role-standard-20260609',
      status: 'running',
      current_stage: 'judge_decisions',
      target_type: 'role_version',
      started_at: '2026-06-09T10:40:00+08:00',
      last_heartbeat_at: '2026-06-09T10:54:00+08:00',
      role_count: 7,
      result_count: 4,
      diagnostic_count: 3
    },
    latest_snapshot: {
      kind: 'benchmark_leaderboard_snapshot',
      schema_version: 1,
      snapshot_id: 'snap-role-standard-20260608',
      title: '角色标准发布 2026-06-08',
      scope: 'role_version',
      benchmark_id: 'role-baseline-standard-v1',
      benchmark_version: 1,
      evaluation_set_id: 'role-baseline-standard-v1@v1',
      seed_set_id: 'role-baseline-standard-202606',
      target_role: '',
      row_count: 14,
      content_hash: 'sha256:9a7c4b2e91d03b6e0d0f1b7a4c8a6f2e6d5c4b3a2f1e0d9c8b7a6f5e4d3c2b1a0',
      created_at: '2026-06-08T21:00:00+08:00'
    }
  },
  {
    id: 'model-baseline-standard-v1',
    version: 1,
    name: '模型基线标准',
    description: '固定种子的全角色模型/运行时比较评测',
    target_type: 'model',
    roles: MOCK_EVOLUTION_ROLES.slice(),
    game_count: 30,
    max_days: 5,
    paired_seed: true,
    seed_set_id: 'model-baseline-standard-202606',
    seed_count: 30,
    seed_preview: [271000, 271001, 271002, 271003, 271004],
    cost_tier: 'release',
    evaluation_set_id: 'model-baseline-standard-v1@v1',
    last_run: {
      batch_id: 'bench-model-release-20260609',
      status: 'failed',
      current_stage: 'runtime',
      target_type: 'model',
      started_at: '2026-06-09T08:00:00+08:00',
      finished_at: '2026-06-09T08:42:00+08:00',
      last_heartbeat_at: '2026-06-09T08:42:00+08:00',
      role_count: 7,
      result_count: 1,
      diagnostic_count: 5
    },
    latest_snapshot: {
      kind: 'benchmark_leaderboard_snapshot',
      schema_version: 1,
      snapshot_id: 'snap-model-standard-20260608',
      title: '模型标准发布 2026-06-08',
      scope: 'model',
      benchmark_id: 'model-baseline-standard-v1',
      benchmark_version: 1,
      evaluation_set_id: 'model-baseline-standard-v1@v1',
      seed_set_id: 'model-baseline-standard-202606',
      row_count: 2,
      content_hash: 'sha256:7fd1a0319b88c4e182ebad4e8db7afc977af530921227ba504891db36f6aa2ef',
      created_at: '2026-06-08T22:20:00+08:00'
    }
  }
]

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
    config: { roles: ['seer'], training_games: 20, battle_games: 10, max_days: 5, auto_promote: false },
    training_games: 20,
    battle_games: 10,
    training_completed: 20,
    battle_completed: 10,
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
    config: { roles: ['witch'], training_games: 20, battle_games: 10, max_days: 5, auto_promote: false },
    training_games: 20,
    battle_games: 10,
    training_completed: 20,
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
    config: { roles: MOCK_EVOLUTION_ROLES, training_games: 20, battle_games: 10, max_days: 5, auto_promote: false },
    training_games: 20,
    battle_games: 10,
    training_completed: 140,
    battle_completed: 42,
    runs: ['mock-evo-seer-review', 'mock-evo-witch-active']
  }
]

let mockBenchmarkCounter = 1
let mockBenchmarkSnapshotCounter = 1
const MOCK_DEFAULT_BENCHMARK_ROLE = MOCK_EVOLUTION_ROLES[0]
const MOCK_DEFAULT_BENCHMARK_BATCH_ID = `mock-bench-${MOCK_DEFAULT_BENCHMARK_ROLE}`
const MOCK_DEFAULT_BENCHMARK_RESULT_ID = `${MOCK_DEFAULT_BENCHMARK_BATCH_ID}:${MOCK_DEFAULT_BENCHMARK_ROLE}`

const mockBenchmarkBatches = [
  {
    kind: 'benchmark_batch',
    schema_version: 1,
    batch_id: MOCK_DEFAULT_BENCHMARK_BATCH_ID,
    roles: [MOCK_DEFAULT_BENCHMARK_ROLE],
    status: 'completed',
    started_at: '2026-06-05T09:20:00',
    finished_at: '2026-06-05T09:24:00',
    benchmark: {
      id: 'role-baseline-quick-v1',
      version: 1,
      evaluation_set_id: 'role-baseline-quick-v1@v1',
      seed_set_id: 'role-baseline-quick-202606'
    },
    config: {
      benchmark_id: 'role-baseline-quick-v1',
      evaluation_set_id: 'role-baseline-quick-v1@v1',
      roles: [MOCK_DEFAULT_BENCHMARK_ROLE],
      battle_games: 10,
      max_days: 5
    },
    result: {
      result_batch_id: MOCK_DEFAULT_BENCHMARK_RESULT_ID,
      batch_id: MOCK_DEFAULT_BENCHMARK_BATCH_ID,
      target_role: MOCK_DEFAULT_BENCHMARK_ROLE,
      target_version_id: `base-${MOCK_DEFAULT_BENCHMARK_ROLE}-20260604`,
      game_count: 10,
      attempted_game_count: 10,
      completed: 8,
      errored: 2,
      score_summary: {
        game_count: 10,
        avg_role_score: 0.54,
        target_role_role_weighted_score: 0.54,
        target_side_win_rate: 0.47,
        decision_judge_aggregate: {
          avg_score: 6.8,
          bad_rate: 0.18,
          judged_decisions: 42,
          top_mistake_tags: [
            { tag: 'late-claim', count: 3 },
            { tag: 'vote-swing', count: 2 }
          ]
        }
      },
      fairness: { is_fair: true, reason: 'mock' },
      rankable: false,
      rankable_reason: '排行榜门禁未通过：有效对局率低于阈值',
      diagnostics: [
        {
          kind: 'leaderboard_gate_failed',
          level: 'warning',
          origin: 'gate',
          stage: 'rankable',
          message: '排行榜门禁未通过：有效对局率低于阈值',
          target_role: MOCK_DEFAULT_BENCHMARK_ROLE,
          result_batch_id: MOCK_DEFAULT_BENCHMARK_RESULT_ID,
          game_id: `${MOCK_DEFAULT_BENCHMARK_BATCH_ID}-game-002`,
          seed: 260902
        }
      ]
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

const mockModelLeaderboardEntries = [
  {
    scope: 'model',
    hash: 'qwen3-flash-runtime-a',
    subject_id: 'qwen3-flash-runtime-a',
    model_id: 'ali/qwen3.5-flash',
    model_config_hash: 'qwen3-flash-runtime-a',
    evaluation_set_id: 'model-baseline-standard-v1@v1',
    seed_set_id: 'model-baseline-standard-202606',
    game_count: 30,
    games_played: 30,
    strength_score: 0.68,
    avg_role_score: 0.64,
    target_side_win_rate: 0.57,
    fallback_rate: 0.04,
    target_role_fallback_rate: 0.04,
    rankable: true,
    data_sufficient: true,
    delta_vs_baseline: {}
  },
  {
    scope: 'model',
    hash: 'qwen-max-runtime-b',
    subject_id: 'qwen-max-runtime-b',
    model_id: 'qwen-max',
    model_config_hash: 'qwen-max-runtime-b',
    evaluation_set_id: 'model-baseline-standard-v1@v1',
    seed_set_id: 'model-baseline-standard-202606',
    game_count: 30,
    games_played: 30,
    strength_score: 0.62,
    avg_role_score: 0.59,
    target_side_win_rate: 0.53,
    fallback_rate: 0.05,
    target_role_fallback_rate: 0.05,
    rankable: true,
    data_sufficient: true,
    delta_vs_baseline: {}
  }
]

const mockBenchmarkSnapshots = []
const mockBenchmarkViews = new Map()

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

function tallyDecisionSources(decisions = []) {
  return decisions.reduce((acc, decision) => {
    const source = decision?.source || 'unknown'
    acc[source] = (acc[source] || 0) + 1
    return acc
  }, {})
}

function mockPublicEvents(game = {}) {
  return (game.logs || [])
    .filter((event) => event.visibility !== 'god' && event.visibility !== 'private')
    .map((event) => ({
      sequence: event.sequence,
      day: event.day,
      phase: event.phase,
      event_type: event.event_type || event.type,
      type: event.type || event.event_type,
      actor_id: event.actor_id ?? null,
      target_id: event.target_id ?? null,
      speaker: event.speaker || '',
      visibility: event.visibility || 'public',
      source: event.source || 'mock',
      message: event.message || ''
    }))
}

function mockArchiveHighlights(game = {}, events = [], decisions = []) {
  const winner = game.winner ? `最终裁定：${game.winner}。` : '本局仍保留完整过程证据。'
  const voteEvent = events.find((event) => /vote|exile|投票|放逐/.test(`${event.event_type || ''} ${event.message || ''}`))
  const nightDecision = decisions.find((decision) => ['seer_check', 'witch_act', 'guard_protect', 'werewolf_kill'].includes(decision.action))
  return [
    winner,
    voteEvent?.message || '公开事件已按阶段归档，可回溯夜晚、发言和投票链路。',
    nightDecision?.public_summary || '决策账本保留来源、置信度、目标与公开摘要。'
  ].filter(Boolean)
}

function mockGameArchivePayload(game = {}) {
  const events = mockPublicEvents(game)
  const decisions = game.decisions || []
  const sourceTally = tallyDecisionSources(decisions)
  const errorCount = decisions.filter((decision) => Array.isArray(decision.errors) && decision.errors.length).length
  const fallbackCount = decisions.filter((decision) => ['fallback', 'policy_adjusted', 'policy_skipped'].includes(decision.source)).length
  const players = Array.isArray(game.players)
    ? game.players.map((player, index) => {
        const id = player.id ?? player.player_id ?? player.seat ?? index + 1
        return {
          ...player,
          id,
          seat: player.seat ?? id,
          alive: player.alive !== false
        }
      })
    : []
  const alivePlayerIds = players
    .filter((player) => player.alive !== false)
    .map((player) => player.id)
  const deadPlayerIds = players
    .filter((player) => player.alive === false)
    .map((player) => player.id)
  const playerCount = game.player_count ?? game.config?.player_count ?? players.length
  return {
    kind: 'game_trace_archive',
    schema_version: 1,
    game_id: game.game_id,
    title: game.log_name || `对局档案 · ${game.game_id}`,
    summary: `胜利方：${game.winner || '未结束'}；当前/结束天数：${game.day || 0}；公开事件 ${events.length} 条，决策 ${decisions.length} 条。`,
    highlights: mockArchiveHighlights(game, events, decisions),
    seed: game.seed,
    config: game.config || {
      seed: game.seed,
      max_days: game.max_days,
      enable_sheriff: game.enable_sheriff,
      skill_dir: game.skill_dir,
      role_skill_dirs: game.role_skill_dirs || {},
      player_count: playerCount,
      human_player_id: game.human_player_id
    },
    players,
    player_count: playerCount,
    sheriff_id: game.sheriff_id ?? game.config?.sheriff_id ?? null,
    alive_player_ids: Array.isArray(game.alive_player_ids) ? game.alive_player_ids : alivePlayerIds,
    dead_player_ids: Array.isArray(game.dead_player_ids) ? game.dead_player_ids : deadPlayerIds,
    winner: game.winner,
    events,
    decisions,
    event_count: events.length,
    decision_count: decisions.length,
    error_count: errorCount,
    fallback_count: fallbackCount,
    decision_sources: sourceTally,
    review: game.review || null,
    source: 'frontend-mock'
  }
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

const MOCK_HISTORY_PHASE_ALIASES = {
  result: 'night',
  sheriff_election: 'sheriff',
  day_speech: 'speech',
  pk_speak: 'speech',
  finished: 'ended'
}

function mockHistoryPhase(phase = 'setup') {
  return MOCK_HISTORY_PHASE_ALIASES[phase] || phase || 'setup'
}

function findMockBenchmarkReplayRow(gameId) {
  const id = String(gameId || '')
  if (!id) return null
  for (const batch of mockBenchmarkBatches) {
    const row = mockBenchmarkGameRows(batch).find((game) =>
      game.game_id === id || game.history_game_id === id
    )
    if (row) return { batch, row }
  }
  return null
}

function mockBenchmarkReplayGame(gameId) {
  const match = findMockBenchmarkReplayRow(gameId)
  if (!match || match.row.replay_available === false) return null
  const seed = Number(match.row.seed)
  const scenario = match.row.status === 'failed' ? 'wolf_win' : 'good_win'
  const game = buildCompletedMockGame(Number.isFinite(seed) ? Math.abs(seed) % 9 : 0, scenario)
  game.game_id = match.row.history_game_id || match.row.game_id
  game.log_name = `评测回放 · ${match.row.game_id}`
  game.source = 'benchmark'
  game.log_source = 'benchmark'
  game.log_source_label = '批量评测'
  game.source_run_id = match.batch.batch_id
  game.source_phase = 'benchmark'
  game.source_phase_label = '评测运行'
  game.comparison_group_id = match.row.result_batch_id
  game.evidence_source = {
    log_source: 'benchmark',
    log_source_label: '批量评测',
    source_run_id: match.batch.batch_id,
    source_phase: 'benchmark',
    source_phase_label: '评测运行',
    seed: match.row.seed
  }
  game.mode = 'watch'
  game.config = {
    ...(game.config || {}),
    source: 'benchmark',
    log_source: 'benchmark',
    log_source_label: '批量评测',
    source_run_id: match.batch.batch_id,
    source_phase: 'benchmark',
    source_phase_label: '评测运行',
    batch_id: match.batch.batch_id,
    result_batch_id: match.row.result_batch_id,
    benchmark_id: match.batch.benchmark?.id || '',
    evaluation_set_id: match.batch.benchmark?.evaluation_set_id || '',
    seed: match.row.seed,
    target_role: match.row.target_role
  }
  return game
}

function mockHistoryGameById(gameId) {
  const id = String(gameId || '')
  return archivedGames.find((item) => item.game_id === id)
    || (activeGame?.game_id === id ? snapshot(activeGame) : null)
    || mockBenchmarkReplayGame(id)
}

function mockPagePagination(rows, offset, limit) {
  return {
    total: rows.length,
    offset,
    limit,
    returned: rows.slice(offset, offset + limit).length,
    has_more: offset + limit < rows.length
  }
}

function mockGamePhasePayload(game, queryString = '') {
  const params = new URLSearchParams(queryString)
  const day = Math.max(1, Number(params.get('day') || game.day || 1) || 1)
  const phase = mockHistoryPhase(params.get('phase') || game.phase || 'setup')
  const logOffset = Math.max(0, Number(params.get('log_offset') || 0) || 0)
  const logLimit = Math.max(1, Number(params.get('log_limit') || 300) || 300)
  const decisionOffset = Math.max(0, Number(params.get('decision_offset') || 0) || 0)
  const decisionLimit = Math.max(1, Number(params.get('decision_limit') || 200) || 200)
  const logs = (game.logs || []).filter((item) =>
    Number(item.day || day) === day && mockHistoryPhase(item.phase || phase) === phase
  )
  const decisions = (game.decisions || []).filter((item) =>
    Number(item.day || day) === day && mockHistoryPhase(item.phase || phase) === phase
  )
  return {
    kind: 'game_phase_detail',
    schema_version: 1,
    game_id: game.game_id,
    day,
    phase,
    logs: logs.slice(logOffset, logOffset + logLimit),
    decisions: decisions.slice(decisionOffset, decisionOffset + decisionLimit),
    summary: {
      log_count: logs.length,
      decision_count: decisions.length
    },
    pagination: {
      logs: mockPagePagination(logs, logOffset, logLimit),
      decisions: mockPagePagination(decisions, decisionOffset, decisionLimit)
    }
  }
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

function mockRolesOverview() {
  const roles = MOCK_EVOLUTION_ROLES.slice()
  return {
    kind: 'role_overview',
    schema_version: 1,
    roles,
    versions: Object.fromEntries(roles.map((role) => [role, mockRoleVersions(role)])),
    leaderboards: Object.fromEntries(roles.map((role) => [
      role,
      {
        kind: 'role_leaderboard',
        schema_version: 1,
        role,
        source: 'frontend-mock',
        entries: clone(mockRoleLeaderboard(role))
      }
    ]))
  }
}

function mockModelLeaderboard(evaluationSetId = '') {
  const rows = evaluationSetId
    ? mockModelLeaderboardEntries.filter((item) => item.evaluation_set_id === evaluationSetId)
    : mockModelLeaderboardEntries
  return {
    kind: 'model_leaderboard',
    schema_version: 1,
    scope: 'model',
    evaluation_set_id: evaluationSetId || null,
    source: 'frontend-mock',
    entries: clone(rows)
  }
}

function mockBenchmarkLeaderboardRows({ scope = 'role_version', evaluationSetId = '', targetRole = '' } = {}) {
  if (scope === 'model') {
    return mockModelLeaderboard(evaluationSetId).entries
  }
  const role = targetRole || MOCK_EVOLUTION_ROLES[0]
  return mockRoleLeaderboard(role).map((row) => ({
    ...row,
    scope: 'role_version',
    subject_id: row.hash,
    target_role: role,
    target_version_id: row.hash,
    evaluation_set_id: evaluationSetId || 'role-baseline-quick-v1@v1',
    seed_set_id: 'role-baseline-quick-202606',
    game_count: row.total_games,
    games_played: row.total_games,
    rankable: row.data_sufficient !== false
  }))
}

function mockLeaderboardCompare(queryString = '') {
  const query = new URLSearchParams(queryString)
  const scope = query.get('scope') || 'role_version'
  const evaluationSetId = query.get('evaluation_set_id') || ''
  const targetRole = query.get('target_role') || ''
  const baselineSubjectId = query.get('baseline_subject_id') || ''
  const rows = mockBenchmarkLeaderboardRows({ scope, evaluationSetId, targetRole })
  const baseline = rows.find((row) =>
    baselineSubjectId &&
    [row.subject_id, row.hash, row.model_config_hash, row.target_version_id, row.model_id].includes(baselineSubjectId)
  ) || rows.find((row) => row.is_baseline) || rows.find((row) => row.rankable !== false) || rows[0] || null
  const baselineKey = baseline?.subject_id || baseline?.hash || baseline?.model_config_hash || baseline?.target_version_id || null
  const baselineScore = Number(baseline?.strength_score ?? baseline?.avg_role_score ?? baseline?.target_role_role_weighted_score ?? 0)
  const baselineWinRate = Number(baseline?.target_side_win_rate ?? 0)
  const compareRows = rows.map((row) => {
    const key = row.subject_id || row.hash || row.model_config_hash || row.target_version_id || row.model_id
    const score = Number(row.strength_score ?? row.avg_role_score ?? row.target_role_role_weighted_score ?? 0)
    const winRate = Number(row.target_side_win_rate ?? 0)
    const boundaryWarnings = []
    if (baseline?.evaluation_set_id && row.evaluation_set_id && row.evaluation_set_id !== baseline.evaluation_set_id) {
      boundaryWarnings.push('evaluation_set_mismatch')
    }
    if (baseline?.seed_set_id && row.seed_set_id && row.seed_set_id !== baseline.seed_set_id) {
      boundaryWarnings.push('seed_set_mismatch')
    }
    const isReference = Boolean(baselineKey && key === baselineKey)
    const comparable = Boolean(baseline && !boundaryWarnings.length)
    const scoreDelta = score - baselineScore
    return {
      ...row,
      is_reference: isReference,
      baseline_subject_id: baselineKey,
      comparable,
      boundary_warnings: boundaryWarnings,
      change: isReference ? 'reference' : (!comparable ? 'incomparable' : (scoreDelta > 0 ? 'improvement' : (scoreDelta < 0 ? 'regression' : 'stable'))),
      confidence: Number(row.games_played || row.game_count || 0) < 30 ? 'low_sample' : 'comparable',
      delta_vs_baseline: {
        score: scoreDelta,
        target_role_role_weighted_score: scoreDelta,
        strength_score: scoreDelta,
        target_side_win_rate: winRate - baselineWinRate
      },
      delta: {
        score: scoreDelta,
        target_side_win_rate: winRate - baselineWinRate
      }
    }
  })
  const byChange = countBy(compareRows, (row) => row.change)
  return {
    kind: 'benchmark_leaderboard_compare',
    schema_version: 1,
    scope,
    evaluation_set_id: evaluationSetId || null,
    target_role: targetRole || null,
    baseline_subject_id: baselineKey,
    baseline: clone(baseline),
    rows: clone(compareRows),
    summary: {
      row_count: compareRows.length,
      rankable_count: compareRows.filter((row) => row.rankable !== false).length,
      unrankable_count: compareRows.filter((row) => row.rankable === false).length,
      improvement_count: byChange.improvement || 0,
      regression_count: byChange.regression || 0,
      stable_count: byChange.stable || 0,
      incomparable_count: byChange.incomparable || 0,
      reference_count: byChange.reference || 0,
      boundary_mismatch_count: compareRows.filter((row) => row.boundary_warnings.length).length,
      by_change: byChange
    }
  }
}

function mockSnapshotStringList(values = []) {
  const input = Array.isArray(values) ? values : [values]
  const seen = new Set()
  const output = []
  for (const value of input) {
    const text = String(value || '').trim()
    if (!text || seen.has(text)) continue
    seen.add(text)
    output.push(text)
  }
  return output
}

function mockSnapshotCount(value, fallback = 0) {
  const number = Number(value)
  return Number.isFinite(number) && number >= 0 ? Math.floor(number) : fallback
}

function mockSnapshotMatchingRunIds(snapshot = {}) {
  const benchmarkId = String(snapshot.benchmark_id || '').trim()
  const evaluationSetId = String(snapshot.evaluation_set_id || '').trim()
  const targetRole = String(snapshot.target_role || '').trim()
  const fromBatches = mockBenchmarkBatches
    .filter((batch) => {
      const batchBenchmarkId = String(batch.benchmark?.id || batch.config?.benchmark_id || '').trim()
      const batchEvaluationSetId = String(batch.benchmark?.evaluation_set_id || batch.config?.evaluation_set_id || '').trim()
      const batchRoles = Array.isArray(batch.roles) ? batch.roles : []
      if (benchmarkId && batchBenchmarkId && batchBenchmarkId !== benchmarkId) return false
      if (evaluationSetId && batchEvaluationSetId && batchEvaluationSetId !== evaluationSetId) return false
      if (targetRole && batchRoles.length && !batchRoles.includes(targetRole)) return false
      return true
    })
    .map((batch) => batch.batch_id)
  const suiteRunId = MOCK_BENCHMARK_SUITES.find((suite) =>
    (!benchmarkId || suite.id === benchmarkId) &&
    (!evaluationSetId || suite.evaluation_set_id === evaluationSetId)
  )?.last_run?.batch_id
  return mockSnapshotStringList([...fromBatches, suiteRunId])
}

function mockSnapshotAuditFields(snapshot = {}, rowsInput = null) {
  const rows = Array.isArray(rowsInput)
    ? rowsInput
    : (Array.isArray(snapshot.rows) ? snapshot.rows : [])
  const summary = snapshot.summary && typeof snapshot.summary === 'object' ? snapshot.summary : {}
  const rowCount = mockSnapshotCount(snapshot.row_count ?? summary.row_count, rows.length)
  const rankableFromRows = rows.filter((row) => row?.rankable !== false).length
  const rankableCount = mockSnapshotCount(
    snapshot.rankable_count ?? summary.rankable_count,
    rows.length ? rankableFromRows : 0
  )
  const unrankableCount = mockSnapshotCount(
    snapshot.unrankable_count ?? summary.unrankable_count,
    Math.max(0, rowCount - rankableCount)
  )
  const rowRunIds = mockSnapshotStringList(rows.flatMap((row) => [
    row?.run_id,
    row?.batch_id,
    row?.benchmark_batch_id,
    row?.source_run_id,
    row?.source_batch_id,
    row?.result_batch_id ? String(row.result_batch_id).split(':')[0] : ''
  ]))
  const summaryRunIds = mockSnapshotStringList(summary.linked_run_ids)
  const explicitRunIds = mockSnapshotStringList(snapshot.linked_run_ids)
  const linkedRunIds = explicitRunIds.length
    ? explicitRunIds
    : summaryRunIds.length
      ? summaryRunIds
      : (
          rowRunIds.length
            ? rowRunIds
            : mockSnapshotMatchingRunIds(snapshot)
        )
  const rowReportIds = mockSnapshotStringList(rows.flatMap((row) => [row?.report_id, row?.source_report_id]))
  const explicitReportIds = mockSnapshotStringList(snapshot.linked_report_ids)
  const summaryReportIds = mockSnapshotStringList(summary.linked_report_ids)
  const linkedReportIds = explicitReportIds.length
    ? explicitReportIds
    : summaryReportIds.length
      ? summaryReportIds
      : mockSnapshotStringList([
          ...rowReportIds,
          ...linkedRunIds.map((runId) => `benchmark_report:${runId}`)
        ])
  const rowResultBatchIds = mockSnapshotStringList(rows.flatMap((row) => [
    row?.result_batch_id,
    row?.evaluation_batch_id
  ]))
  const explicitResultBatchIds = mockSnapshotStringList(snapshot.linked_result_batch_ids)
  const summaryResultBatchIds = mockSnapshotStringList(summary.linked_result_batch_ids)
  const linkedResultBatchIds = explicitResultBatchIds.length
    ? explicitResultBatchIds
    : summaryResultBatchIds.length
      ? summaryResultBatchIds
      : rowResultBatchIds
  const sourceRunCount = mockSnapshotCount(snapshot.source_run_count ?? summary.source_run_count, linkedRunIds.length)
  const sourceReportCount = mockSnapshotCount(snapshot.source_report_count ?? summary.source_report_count, linkedReportIds.length)
  const sourceResultBatchCount = mockSnapshotCount(
    snapshot.source_result_batch_count ?? summary.source_result_batch_count,
    linkedResultBatchIds.length
  )

  return {
    ...snapshot,
    linked_run_ids: linkedRunIds,
    linked_report_ids: linkedReportIds,
    linked_result_batch_ids: linkedResultBatchIds,
    source_run_count: sourceRunCount,
    source_report_count: sourceReportCount,
    source_result_batch_count: sourceResultBatchCount,
    row_count: rowCount,
    rankable_count: rankableCount,
    unrankable_count: unrankableCount,
    content_hash: String(
      snapshot.content_hash ||
      `sha256:mock-${snapshot.snapshot_id || snapshot.benchmark_id || 'snapshot'}-${rowCount}`
    ),
    summary: {
      ...summary,
      row_count: rowCount,
      rankable_count: rankableCount,
      unrankable_count: unrankableCount,
      linked_run_ids: linkedRunIds,
      linked_report_ids: linkedReportIds,
      linked_result_batch_ids: linkedResultBatchIds,
      source_run_count: sourceRunCount,
      source_report_count: sourceReportCount,
      source_result_batch_count: sourceResultBatchCount
    }
  }
}

function ensureMockBenchmarkSnapshots() {
  if (mockBenchmarkSnapshots.length) return
  const role = MOCK_DEFAULT_BENCHMARK_ROLE
  const quickRows = mockBenchmarkLeaderboardRows({
    scope: 'role_version',
    evaluationSetId: 'role-baseline-quick-v1@v1',
    targetRole: role
  })
  mockBenchmarkSnapshots.push(mockSnapshotAuditFields({
    kind: 'benchmark_leaderboard_snapshot',
    schema_version: 1,
    snapshot_id: 'snap-role-quick-20260608',
    title: '角色快速发布 2026-06-08',
    release_notes: '用于快照历史审计复核的固定种子模拟快照。',
    scope: 'role_version',
    benchmark_id: 'role-baseline-quick-v1',
    benchmark_version: 1,
    evaluation_set_id: 'role-baseline-quick-v1@v1',
    seed_set_id: 'role-baseline-quick-202606',
    benchmark_config_hash: 'sha256:quick-history',
    target_role: role,
    source_filter: {
      rankable: 'all',
      target_role: role,
      evaluation_set_id: 'role-baseline-quick-v1@v1'
    },
    view_config: { view: 'leaderboard', mode: 'role_version', role },
    linked_run_ids: [MOCK_DEFAULT_BENCHMARK_BATCH_ID],
    linked_report_ids: [`${MOCK_DEFAULT_BENCHMARK_BATCH_ID}:report`],
    rows: clone(quickRows),
    created_at: '2026-06-08T20:30:00+08:00'
  }, quickRows))

  const standardRows = mockBenchmarkLeaderboardRows({
    scope: 'role_version',
    evaluationSetId: 'role-baseline-standard-v1@v1',
    targetRole: role
  })
  mockBenchmarkSnapshots.push(mockSnapshotAuditFields({
    kind: 'benchmark_leaderboard_snapshot',
    schema_version: 1,
    snapshot_id: 'snap-role-standard-20260608',
    title: '角色标准发布 2026-06-08',
    scope: 'role_version',
    benchmark_id: 'role-baseline-standard-v1',
    benchmark_version: 1,
    evaluation_set_id: 'role-baseline-standard-v1@v1',
    seed_set_id: 'role-baseline-standard-202606',
    benchmark_config_hash: 'sha256:standard-history',
    target_role: role,
    source_filter: {
      rankable: 'all',
      target_role: role,
      evaluation_set_id: 'role-baseline-standard-v1@v1'
    },
    view_config: { view: 'leaderboard', mode: 'role_version', role },
    linked_run_ids: ['bench-role-standard-20260609'],
    linked_report_ids: ['bench-role-standard-20260609:report'],
    rows: clone(standardRows),
    created_at: '2026-06-08T21:00:00+08:00'
  }, standardRows))

  const modelRows = mockBenchmarkLeaderboardRows({
    scope: 'model',
    evaluationSetId: 'model-baseline-standard-v1@v1'
  })
  mockBenchmarkSnapshots.push(mockSnapshotAuditFields({
    kind: 'benchmark_leaderboard_snapshot',
    schema_version: 1,
    snapshot_id: 'snap-model-standard-20260608',
    title: '模型标准发布 2026-06-08',
    scope: 'model',
    benchmark_id: 'model-baseline-standard-v1',
    benchmark_version: 1,
    evaluation_set_id: 'model-baseline-standard-v1@v1',
    seed_set_id: 'model-baseline-standard-202606',
    benchmark_config_hash: 'sha256:model-history',
    source_filter: {
      rankable: 'all',
      evaluation_set_id: 'model-baseline-standard-v1@v1'
    },
    view_config: { view: 'leaderboard', mode: 'model' },
    linked_run_ids: ['bench-model-release-20260609'],
    linked_report_ids: ['bench-model-release-20260609:report'],
    rows: clone(modelRows),
    created_at: '2026-06-08T22:20:00+08:00'
  }, modelRows))
}

function mockSnapshotSummary(snapshot) {
  const { rows, ...summary } = mockSnapshotAuditFields(snapshot)
  return clone(summary)
}

function listMockBenchmarkSnapshots(queryString = '') {
  ensureMockBenchmarkSnapshots()
  const query = new URLSearchParams(queryString)
  const scope = query.get('scope') || ''
  const evaluationSetId = query.get('evaluation_set_id') || ''
  const benchmarkId = query.get('benchmark_id') || ''
  const targetRole = query.get('target_role') || ''
  const limit = Math.max(1, Math.min(500, Number(query.get('limit') || 50)))
  const items = mockBenchmarkSnapshots
    .filter((snapshot) => !scope || snapshot.scope === scope)
    .filter((snapshot) => !evaluationSetId || snapshot.evaluation_set_id === evaluationSetId)
    .filter((snapshot) => !benchmarkId || snapshot.benchmark_id === benchmarkId)
    .filter((snapshot) => !targetRole || snapshot.target_role === targetRole)
    .slice(0, limit)
    .map(mockSnapshotSummary)
  return {
    kind: 'benchmark_leaderboard_snapshots',
    schema_version: 1,
    scope: scope || null,
    evaluation_set_id: evaluationSetId || null,
    benchmark_id: benchmarkId || null,
    target_role: targetRole || null,
    items
  }
}

function createMockBenchmarkSnapshot(body = {}) {
  const scope = body.scope === 'model' ? 'model' : 'role_version'
  const rows = mockBenchmarkLeaderboardRows({
    scope,
    evaluationSetId: body.evaluation_set_id || '',
    targetRole: body.target_role || ''
  })
  if (!rows.length) throw new Error('cannot snapshot empty leaderboard')
  const rowCount = rows.length
  const rankableCount = rows.filter((row) => row.rankable !== false).length
  const snapshot = mockSnapshotAuditFields({
    kind: 'benchmark_leaderboard_snapshot',
    schema_version: 1,
    snapshot_id: `mock-bench-snapshot-${++mockBenchmarkSnapshotCounter}`,
    title: body.title || `${body.evaluation_set_id || 'mock'} / ${scope} release`,
    release_notes: body.release_notes || '',
    scope,
    benchmark_id: body.benchmark_id || '',
    benchmark_version: body.benchmark_version ?? null,
    evaluation_set_id: body.evaluation_set_id || '',
    seed_set_id: body.seed_set_id || '',
    benchmark_config_hash: body.benchmark_config_hash || 'sha256:frontend-mock',
    target_role: scope === 'role_version' ? (body.target_role || MOCK_EVOLUTION_ROLES[0]) : '',
    source_filter: body.source_filter || {},
    view_config: body.view_config || {},
    rows: clone(rows),
    summary: {
      row_count: rowCount,
      rankable_count: rankableCount,
      unrankable_count: rowCount - rankableCount,
      scope,
      evaluation_set_id: body.evaluation_set_id || '',
      target_role: scope === 'role_version' ? (body.target_role || MOCK_EVOLUTION_ROLES[0]) : null
    },
    row_count: rowCount,
    content_hash: `sha256:mock-${Date.now()}-${rowCount}`,
    created_at: new Date().toISOString()
  }, rows)
  mockBenchmarkSnapshots.unshift(snapshot)
  return clone(snapshot)
}

function getMockBenchmarkSnapshot(snapshotId) {
  ensureMockBenchmarkSnapshots()
  const snapshot = mockBenchmarkSnapshots.find((item) => item.snapshot_id === snapshotId)
  if (!snapshot) throw new Error('benchmark snapshot not found')
  return clone(mockSnapshotAuditFields(snapshot))
}

function mockSnapshotCompareNumber(...values) {
  for (const value of values) {
    const number = Number(value)
    if (Number.isFinite(number)) return number
  }
  return 0
}

function mockSnapshotCompareRowKey(row, index, scope) {
  const value = scope === 'model'
    ? row?.model_config_hash || row?.subject_id || row?.hash || row?.model_id
    : row?.target_version_id || row?.version_id || row?.subject_id || row?.hash
  return String(value || `${scope}-${index + 1}`)
}

function mockSnapshotCompareRow(row = {}, index = 0, scope = 'role_version') {
  const key = mockSnapshotCompareRowKey(row, index, scope)
  const score = mockSnapshotCompareNumber(
    row.score,
    row.strength_score,
    row.avg_role_score,
    row.target_role_role_weighted_score
  )
  const winRate = mockSnapshotCompareNumber(
    row.winRate,
    row.target_side_win_rate,
    row.summary?.target_side_win_rate,
    row.summary?.win_rate
  )
  const games = mockSnapshotCompareNumber(row.games, row.game_count, row.games_played, row.total_games)
  const primary = scope === 'model'
    ? String(row.model_id || row.model_config_hash || row.subject_id || row.hash || key)
    : String(row.short || row.target_version_id || row.version_id || row.subject_id || row.hash || key)
  const secondary = scope === 'model'
    ? [row.model_config_hash || row.subject_id || row.hash, row.provider, row.runtime || row.runtime_id]
    : [row.target_version_id || row.version_id || row.subject_id || row.hash, row.source]
  const rankable = row.rankable == null
    ? (row.data_sufficient == null ? null : row.data_sufficient !== false)
    : row.rankable !== false
  return {
    ...row,
    key,
    primary,
    secondary: secondary.map((value) => String(value || '').trim()).filter(Boolean).join(' / '),
    score,
    winRate,
    games,
    game_count: games,
    rankable,
    rankableReason: String(row.rankable_reason || row.reason || row.gate_reason || '').trim()
  }
}

function mockSnapshotCompareChange(current, previous) {
  return {
    key: current.key,
    current,
    snapshot: previous,
    scoreDelta: current.score - previous.score,
    winRateDelta: current.winRate - previous.winRate,
    gamesDelta: current.games - previous.games,
    rankableChanged: current.rankable !== previous.rankable
  }
}

function mockBenchmarkSnapshotCompare(snapshotId, queryString = '') {
  const snapshot = getMockBenchmarkSnapshot(snapshotId)
  const query = new URLSearchParams(queryString)
  const againstSnapshotId = query.get('against_snapshot_id') || ''
  const againstSnapshot = againstSnapshotId ? getMockBenchmarkSnapshot(againstSnapshotId) : null
  const scope = query.get('scope') || snapshot.scope || 'role_version'
  const evaluationSetId = query.get('evaluation_set_id') || snapshot.evaluation_set_id || ''
  const benchmarkId = query.get('benchmark_id') || snapshot.benchmark_id || ''
  const targetRole = query.get('target_role') || snapshot.target_role || ''
  const currentSourceRows = mockBenchmarkLeaderboardRows({ scope, evaluationSetId, targetRole })
  const frozenRows = (snapshot.rows?.length ? snapshot.rows : currentSourceRows)
    .map((row, index) => mockSnapshotCompareRow(row, index, scope))
  let currentRows = (againstSnapshot
    ? (againstSnapshot.rows?.length ? againstSnapshot.rows : currentSourceRows)
    : currentSourceRows
  )
    .map((row, index) => mockSnapshotCompareRow(row, index, scope))

  if (!currentRows.length && frozenRows.length) {
    currentRows = [mockSnapshotCompareRow(frozenRows[0], 0, scope)]
  }

  const frozenByKey = new Map(frozenRows.map((row) => [row.key, row]))
  const currentByKey = new Map(currentRows.map((row) => [row.key, row]))
  const changed = []
  const added = []
  const removed = []

  for (const row of currentRows) {
    const previous = frozenByKey.get(row.key)
    if (!previous) {
      added.push(row)
      continue
    }
    const change = mockSnapshotCompareChange(row, previous)
    if (
      Math.abs(change.scoreDelta) > 0.000001 ||
      Math.abs(change.winRateDelta) > 0.000001 ||
      change.gamesDelta !== 0 ||
      change.rankableChanged
    ) {
      changed.push(change)
    }
  }

  for (const row of frozenRows) {
    if (!currentByKey.has(row.key)) removed.push(row)
  }

  if (!changed.length && frozenRows.length) {
    const previous = frozenRows[0]
    const current = {
      ...previous,
      score: previous.score + 0.03,
      target_role_role_weighted_score: previous.score + 0.03,
      strength_score: previous.score + 0.03,
      winRate: previous.winRate + 0.02,
      target_side_win_rate: previous.winRate + 0.02,
      games: previous.games + 2,
      game_count: previous.games + 2
    }
    currentRows = [current, ...currentRows.filter((row) => row.key !== current.key)]
    changed.push(mockSnapshotCompareChange(current, previous))
  }

  if (!added.length) {
    const row = mockSnapshotCompareRow(
      scope === 'model'
        ? {
            scope,
            subject_id: 'mock-added-model-runtime',
            model_id: 'mock-added-model',
            model_config_hash: 'mock-added-model-runtime',
            strength_score: 0.64,
            target_side_win_rate: 0.55,
            game_count: 30,
            rankable: true
          }
        : {
            scope,
            subject_id: `${targetRole || MOCK_DEFAULT_BENCHMARK_ROLE}_mock_added_v2`,
            target_role: targetRole || MOCK_DEFAULT_BENCHMARK_ROLE,
            target_version_id: `${targetRole || MOCK_DEFAULT_BENCHMARK_ROLE}_mock_added_v2`,
            target_role_role_weighted_score: 0.64,
            target_side_win_rate: 0.55,
            game_count: 30,
            rankable: true
          },
      currentRows.length,
      scope
    )
    currentRows.push(row)
    added.push(row)
  }

  if (!removed.length) {
    const row = mockSnapshotCompareRow(
      scope === 'model'
        ? {
            scope,
            subject_id: 'mock-removed-model-runtime',
            model_id: 'mock-removed-model',
            model_config_hash: 'mock-removed-model-runtime',
            strength_score: 0.58,
            target_side_win_rate: 0.49,
            game_count: 24,
            rankable: true
          }
        : {
            scope,
            subject_id: `${targetRole || MOCK_DEFAULT_BENCHMARK_ROLE}_mock_removed_v1`,
            target_role: targetRole || MOCK_DEFAULT_BENCHMARK_ROLE,
            target_version_id: `${targetRole || MOCK_DEFAULT_BENCHMARK_ROLE}_mock_removed_v1`,
            target_role_role_weighted_score: 0.58,
            target_side_win_rate: 0.49,
            game_count: 24,
            rankable: true
          },
      frozenRows.length,
      scope
    )
    frozenRows.push(row)
    removed.push(row)
  }

  const boundaryWarnings = []
  if (snapshot.evaluation_set_id && evaluationSetId && snapshot.evaluation_set_id !== evaluationSetId) {
    boundaryWarnings.push({
      kind: 'evaluation_set_mismatch',
      level: 'warning',
      snapshot_value: snapshot.evaluation_set_id,
      current_value: evaluationSetId,
      message: '快照评测集与当前排行榜不同。'
    })
  }
  if (snapshot.benchmark_id && benchmarkId && snapshot.benchmark_id !== benchmarkId) {
    boundaryWarnings.push({
      kind: 'benchmark_id_mismatch',
      level: 'warning',
      snapshot_value: snapshot.benchmark_id,
      current_value: benchmarkId,
      message: '快照基准与当前套件不同。'
    })
  }
  if (againstSnapshot) {
    if (snapshot.scope && againstSnapshot.scope && snapshot.scope !== againstSnapshot.scope) {
      boundaryWarnings.push({
        kind: 'scope_mismatch',
        level: 'warning',
        snapshot_value: snapshot.scope,
        current_value: againstSnapshot.scope,
        message: '快照 scope 不一致。'
      })
    }
    if (snapshot.evaluation_set_id && againstSnapshot.evaluation_set_id && snapshot.evaluation_set_id !== againstSnapshot.evaluation_set_id) {
      boundaryWarnings.push({
        kind: 'evaluation_set_mismatch',
        level: 'warning',
        snapshot_value: snapshot.evaluation_set_id,
        current_value: againstSnapshot.evaluation_set_id,
        message: 'Snapshot evaluation sets differ.'
      })
    }
  }
  const benchmarkConfigHash = query.get('benchmark_config_hash') || 'sha256:frontend-current'
  if (snapshot.benchmark_config_hash && benchmarkConfigHash !== snapshot.benchmark_config_hash) {
    boundaryWarnings.push({
      kind: 'benchmark_config_hash_mismatch',
      level: 'info',
      snapshot_value: snapshot.benchmark_config_hash,
      current_value: benchmarkConfigHash,
      message: 'Current leaderboard config hash is not identical to the frozen snapshot.'
    })
  }

  return {
    kind: 'benchmark_snapshot_compare',
    schema_version: 1,
    compare_mode: againstSnapshot ? 'snapshot_to_snapshot' : 'current_vs_snapshot',
    snapshot_id: snapshot.snapshot_id,
    scope,
    evaluation_set_id: evaluationSetId || null,
    benchmark_id: benchmarkId || null,
    target_role: targetRole || null,
    snapshot: clone(frozenRows),
    snapshot_meta: mockSnapshotSummary(snapshot),
    ...(againstSnapshot ? { against_snapshot: mockSnapshotSummary(againstSnapshot) } : {}),
    current: clone(currentRows),
    summary: {
      compare_mode: againstSnapshot ? 'snapshot_to_snapshot' : 'current_vs_snapshot',
      snapshot_id: snapshot.snapshot_id,
      ...(againstSnapshot ? { against_snapshot_id: againstSnapshot.snapshot_id } : {}),
      snapshot_row_count: frozenRows.length,
      current_row_count: currentRows.length,
      changed_count: changed.length,
      added_count: added.length,
      removed_count: removed.length,
      boundary_warning_count: boundaryWarnings.length
    },
    changed: clone(changed),
    added: clone(added),
    removed: clone(removed),
    boundary_warnings: clone(boundaryWarnings)
  }
}

function mockBenchmarkViewPayload(view) {
  return {
    kind: 'benchmark_saved_view',
    schema_version: 1,
    view_key: view.view_key,
    name: view.name || '默认视图',
    scope: view.scope || 'role_version',
    benchmark_id: view.benchmark_id || null,
    evaluation_set_id: view.evaluation_set_id || null,
    target_role: view.target_role || null,
    view_config: view.view_config || {},
    created_at: view.created_at || null,
    updated_at: view.updated_at || null
  }
}

function listMockBenchmarkViews(queryString = '') {
  const query = new URLSearchParams(queryString)
  const scope = query.get('scope') || ''
  const evaluationSetId = query.get('evaluation_set_id') || ''
  const benchmarkId = query.get('benchmark_id') || ''
  const targetRole = query.get('target_role') || ''
  const viewKey = query.get('view_key') || ''
  const limit = Math.max(1, Math.min(500, Number(query.get('limit') || 50)))
  const items = [...mockBenchmarkViews.values()]
    .filter((view) => !viewKey || view.view_key === viewKey)
    .filter((view) => !scope || view.scope === scope)
    .filter((view) => !evaluationSetId || view.evaluation_set_id === evaluationSetId)
    .filter((view) => !benchmarkId || view.benchmark_id === benchmarkId)
    .filter((view) => !targetRole || view.target_role === targetRole)
    .sort((a, b) => String(b.updated_at || '').localeCompare(String(a.updated_at || '')))
    .slice(0, limit)
    .map(mockBenchmarkViewPayload)
  return {
    kind: 'benchmark_saved_views',
    schema_version: 1,
    scope: scope || null,
    evaluation_set_id: evaluationSetId || null,
    benchmark_id: benchmarkId || null,
    target_role: targetRole || null,
    items
  }
}

function saveMockBenchmarkView(body = {}) {
  const viewKey = String(body.view_key || '').trim()
  if (!viewKey) throw new Error('view_key is required')
  const existing = mockBenchmarkViews.get(viewKey) || {}
  const now = new Date().toISOString()
  const view = {
    view_key: viewKey,
    name: body.name || '默认视图',
    scope: body.scope === 'model' ? 'model' : 'role_version',
    benchmark_id: body.benchmark_id || null,
    evaluation_set_id: body.evaluation_set_id || null,
    target_role: body.target_role || null,
    view_config: body.view_config || {},
    created_at: existing.created_at || now,
    updated_at: now
  }
  mockBenchmarkViews.set(viewKey, view)
  return mockBenchmarkViewPayload(view)
}

function getMockBenchmarkView(viewKey) {
  const view = mockBenchmarkViews.get(viewKey)
  if (!view) throw new Error('benchmark view not found')
  return mockBenchmarkViewPayload(view)
}

function deleteMockBenchmarkView(viewKey) {
  const deleted = mockBenchmarkViews.delete(viewKey)
  if (!deleted) throw new Error('benchmark view not found')
  return {
    kind: 'benchmark_saved_view_deleted',
    schema_version: 1,
    view_key: viewKey,
    deleted: true
  }
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
      training_games: Number(body.training_games || 20),
      battle_games: Number(body.battle_games || 10),
      max_days: Number(body.max_days || 5),
      auto_promote: Boolean(body.auto_promote)
    },
    training_games: Number(body.training_games || 20),
    battle_games: Number(body.battle_games || 10),
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
      training_games: Number(body.training_games || 20),
      battle_games: Number(body.battle_games || 10),
      max_days: Number(body.max_days || 5),
      auto_promote: Boolean(body.auto_promote)
    },
    training_games: Number(body.training_games || 20),
    battle_games: Number(body.battle_games || 10),
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
  const battleGames = Number(body.battle_games || 10)
  const maxDays = Number(body.max_days || 5)
  const suite = MOCK_BENCHMARK_SUITES.find((item) => item.id === body.benchmark_id) || null
  const isModelBenchmark = body.target_type === 'model' || suite?.target_type === 'model'
  const roles = isModelBenchmark
    ? (suite?.roles?.slice() || MOCK_EVOLUTION_ROLES.slice())
    : (Array.isArray(body.roles) && body.roles.length ? body.roles : [MOCK_EVOLUTION_ROLES[0]])
  const benchmark = suite
    ? {
        id: suite.id,
        version: suite.version,
        target_type: suite.target_type,
        evaluation_set_id: suite.evaluation_set_id,
        seed_set_id: suite.seed_set_id
      }
    : null
  const id = `mock-bench-${++mockBenchmarkCounter}`
  const batch = {
    kind: 'benchmark_batch',
    schema_version: 1,
    batch_id: id,
    roles,
    status: 'completed',
    started_at: new Date().toISOString(),
    finished_at: new Date().toISOString(),
    ...(benchmark ? { benchmark } : {}),
    config: {
      ...(suite ? { benchmark_id: suite.id, target_type: suite.target_type, evaluation_set_id: suite.evaluation_set_id } : {}),
      roles,
      battle_games: battleGames,
      max_days: maxDays
    },
    result: {
      batch_id: id,
      game_count: battleGames,
      completed: battleGames,
      errored: 0,
      score_summary: { game_count: battleGames },
      fairness: { is_fair: true, reason: 'mock' },
      rankable: battleGames > 0,
      rankable_reason: battleGames > 0 ? '' : 'No games in batch'
    }
  }
  if (isModelBenchmark) {
    const modelId = body.model_id || 'mock/current-model'
    const modelConfigHash = body.model_config_hash || `mock-runtime-${mockBenchmarkCounter}`
    mockModelLeaderboardEntries.unshift({
      scope: 'model',
      hash: modelConfigHash,
      subject_id: modelConfigHash,
      model_id: modelId,
      model_config_hash: modelConfigHash,
      evaluation_set_id: suite?.evaluation_set_id || null,
      seed_set_id: suite?.seed_set_id || null,
      game_count: battleGames,
      games_played: battleGames,
      strength_score: 0.6 + Math.min(0.18, battleGames / 300),
      avg_role_score: 0.58 + Math.min(0.14, battleGames / 360),
      target_side_win_rate: 0.52 + Math.min(0.12, battleGames / 420),
      fallback_rate: 0.03,
      target_role_fallback_rate: 0.03,
      rankable: battleGames > 0,
      data_sufficient: battleGames > 0,
      delta_vs_baseline: {}
    })
  }
  mockBenchmarkBatches.unshift(batch)
  return clone(batch)
}

function findMockBenchmarkBatch(batchId) {
  const batch = mockBenchmarkBatches.find((item) => item.batch_id === batchId || item.run_id === batchId)
  if (!batch) throw new Error('Mock benchmark batch not found')
  return batch
}

function mockBenchmarkResultRows(batch) {
  const result = batch.result || {}
  const targetRole = result.target_role || batch.roles?.[0] || MOCK_EVOLUTION_ROLES[0]
  const resultBatchId = result.result_batch_id || `${batch.batch_id}:${targetRole}`
  return [{
    ...clone(result),
    result_batch_id: resultBatchId,
    batch_id: batch.batch_id,
    target_role: targetRole,
    target_version_id: result.target_version_id || `base-${targetRole}-20260604`,
    game_count: Number(result.game_count ?? batch.config?.battle_games ?? 10),
    attempted_game_count: Number(result.attempted_game_count ?? result.game_count ?? batch.config?.battle_games ?? 10),
    completed: Number(result.completed ?? result.game_count ?? batch.config?.battle_games ?? 10),
    errored: Number(result.errored ?? 0),
    rankable: result.rankable !== false,
    rankable_reason: result.rankable_reason || '',
    config: {
      ...(batch.config || {}),
      batch_id: batch.batch_id,
      result_batch_id: resultBatchId,
      target_role: targetRole,
      target_version_id: result.target_version_id || `base-${targetRole}-20260604`
    }
  }]
}

function mockBenchmarkGameRows(batch) {
  const targetRole = batch.result?.target_role || batch.roles?.[0] || MOCK_EVOLUTION_ROLES[0]
  const resultBatchId = batch.result?.result_batch_id || `${batch.batch_id}:${targetRole}`
  return [
    {
      kind: 'benchmark_game',
      result_batch_id: resultBatchId,
      game_id: `${batch.batch_id}-game-001`,
      history_game_id: `${batch.batch_id}-game-001`,
      status: 'completed',
      seed: 260901,
      target_role: targetRole,
      event_count: 72,
      decision_count: 38,
      diagnostic_count: 0,
      replay_available: true
    },
    {
      kind: 'benchmark_game',
      result_batch_id: resultBatchId,
      game_id: `${batch.batch_id}-game-002`,
      history_game_id: `${batch.batch_id}-game-002`,
      status: 'failed',
      seed: 260902,
      target_role: targetRole,
      event_count: 41,
      decision_count: 21,
      diagnostic_count: 2,
      replay_available: true,
      diagnostics: [
        {
          kind: 'game_failure',
          level: 'error',
          origin: 'game',
          stage: 'game.persist',
          message: 'game failed before terminal replay artifact was persisted',
          target_role: targetRole,
          result_batch_id: resultBatchId,
          game_id: `${batch.batch_id}-game-002`,
          seed: 260902
        }
      ]
    },
    {
      kind: 'benchmark_game',
      result_batch_id: resultBatchId,
      game_id: `${batch.batch_id}-game-003`,
      history_game_id: `${batch.batch_id}-game-003`,
      status: 'timeout',
      seed: 260903,
      target_role: targetRole,
      event_count: 54,
      decision_count: 27,
      diagnostic_count: 1,
      replay_available: false,
      replay_unavailable_reason: 'timeout before archive',
      diagnostics: [
        {
          kind: 'decision_judge_degraded',
          level: 'warning',
          origin: 'judge',
          stage: 'decision_judge',
          message: 'decision judge skipped timeout game; aggregate may be degraded',
          target_role: targetRole,
          result_batch_id: resultBatchId,
          game_id: `${batch.batch_id}-game-003`,
          seed: 260903
        }
      ]
    }
  ]
}

function mockBenchmarkDiagnosticEntries(batch) {
  const resultDiagnostics = Array.isArray(batch.result?.diagnostics) ? batch.result.diagnostics : []
  const gameDiagnostics = mockBenchmarkGameRows(batch).flatMap((game) => game.diagnostics || [])
  return [...clone(resultDiagnostics), ...clone(gameDiagnostics)].map((item, index) => ({
    id: `${batch.batch_id}:diagnostic:${index}`,
    batch_id: batch.batch_id,
    ...item
  }))
}

function mockBenchmarkDiagnosticSummary(diagnostics) {
  return {
    total: diagnostics.length,
    by_kind: countBy(diagnostics, (item) => item.kind || 'diagnostic'),
    by_level: countBy(diagnostics, (item) => item.level || 'warning'),
    by_origin: countBy(diagnostics, (item) => item.origin || 'unknown')
  }
}

function mockBenchmarkGameSummary(games) {
  return {
    total: games.length,
    by_status: countBy(games, (item) => item.status || 'unknown'),
    failed: games.filter((item) => item.status === 'failed').length,
    timeout: games.filter((item) => item.status === 'timeout').length,
    abnormal: games.filter((item) => item.status === 'abnormal').length,
    completed: games.filter((item) => item.status === 'completed').length
  }
}

function countBy(items, selector) {
  return items.reduce((counts, item) => {
    const key = String(selector(item) || 'unknown')
    counts[key] = (counts[key] || 0) + 1
    return counts
  }, {})
}

function mockBenchmarkBatchDetail(batchId) {
  const batch = findMockBenchmarkBatch(batchId)
  const games = mockBenchmarkGameRows(batch)
  const diagnostics = mockBenchmarkDiagnosticEntries(batch)
  return {
    kind: 'benchmark_batch_detail',
    schema_version: 1,
    batch_id: batch.batch_id,
    status: batch.status,
    started_at: batch.started_at,
    finished_at: batch.finished_at,
    benchmark: batch.benchmark || null,
    target_type: batch.benchmark?.target_type || batch.config?.target_type || 'role_version',
    result_count: 1,
    results: mockBenchmarkResultRows(batch),
    game_summary: mockBenchmarkGameSummary(games),
    diagnostic_summary: mockBenchmarkDiagnosticSummary(diagnostics)
  }
}

function mockBenchmarkBatchGames(batchId, queryString = '') {
  const batch = findMockBenchmarkBatch(batchId)
  const query = new URLSearchParams(queryString)
  const statusFilter = query.get('status')
  const statuses = statusFilter
    ? new Set(statusFilter.split(',').map((item) => item.trim()).filter(Boolean))
    : null
  const offset = Math.max(0, Number(query.get('offset') || 0))
  const limit = Math.max(1, Math.min(200, Number(query.get('limit') || 20)))
  const rows = mockBenchmarkGameRows(batch).filter((game) => !statuses || statuses.has(game.status))
  const page = rows.slice(offset, offset + limit)
  return {
    kind: 'benchmark_batch_games',
    schema_version: 1,
    batch_id: batch.batch_id,
    games: clone(page),
    pagination: {
      total: rows.length,
      offset,
      limit,
      returned: page.length,
      has_more: offset + page.length < rows.length
    }
  }
}

function mockBenchmarkBatchDiagnostics(batchId) {
  const batch = findMockBenchmarkBatch(batchId)
  const diagnostics = mockBenchmarkDiagnosticEntries(batch)
  return {
    kind: 'benchmark_batch_diagnostics',
    schema_version: 1,
    batch_id: batch.batch_id,
    diagnostics,
    summary: mockBenchmarkDiagnosticSummary(diagnostics)
  }
}

function mockBenchmarkBatchReport(batchId, queryString = '') {
  const query = new URLSearchParams(queryString)
  const format = String(query.get('format') || 'json').toLowerCase()
  const report = mockBenchmarkBatchReportPayload(batchId)

  if (!format || format === 'json') return clone(report)
  if (format === 'markdown') {
    return {
      kind: 'benchmark_run_report_export',
      schema_version: 1,
      format,
      content_type: 'text/markdown; charset=utf-8',
      content: mockBenchmarkBatchReportMarkdown(report),
      report: clone(report)
    }
  }
  if (format === 'csv') {
    return {
      kind: 'benchmark_run_report_export',
      schema_version: 1,
      format,
      content_type: 'text/csv; charset=utf-8',
      content: mockBenchmarkBatchReportCsv(report),
      report: clone(report)
    }
  }
  throw new Error(`Unsupported benchmark report format: ${format}`)
}

function mockBenchmarkBatchReportPayload(batchId) {
  const batch = findMockBenchmarkBatch(batchId)
  const detail = mockBenchmarkBatchDetail(batchId)
  const problemGames = mockBenchmarkBatchGames(batchId, 'status=failed,timeout,abnormal&limit=20&offset=0')
  const diagnostics = mockBenchmarkBatchDiagnostics(batchId)
  const results = Array.isArray(detail.results) ? detail.results : []
  const firstResult = results[0] || {}
  const targetType = detail.target_type || batch.benchmark?.target_type || batch.config?.target_type || 'role_version'
  const evaluationSetId = detail.benchmark?.evaluation_set_id || batch.config?.evaluation_set_id || null
  const seedSetId = detail.benchmark?.seed_set_id || batch.config?.seed_set_id || null
  const benchmarkConfigHash = detail.benchmark?.config_hash ||
    batch.config?.benchmark_config_hash ||
    batch.config?.config_hash ||
    batch.config_hash ||
    `mock:${batch.batch_id}`
  const runId = batch.run_id || batch.batch_id
  const subject = targetType === 'model'
    ? {
        type: 'model',
        model_id: firstResult.model_id || batch.config?.model_id || null,
        model_config_hash: firstResult.model_config_hash || batch.config?.model_config_hash || null
      }
    : {
        type: 'role_version',
        target_role: firstResult.target_role || batch.roles?.[0] || null,
        target_version_id: firstResult.target_version_id || firstResult.config?.target_version_id || null
      }
  const topTags = results
    .flatMap((row) => row.score_summary?.decision_judge_aggregate?.top_mistake_tags || [])
    .filter(Boolean)

  return {
    kind: 'benchmark_run_report',
    schema_version: 1,
    generated_at: new Date().toISOString(),
    run_id: runId,
    batch_id: batch.batch_id,
    status: detail.status || batch.status,
    evaluation_set_id: evaluationSetId,
    seed_set_id: seedSetId,
    benchmark_config_hash: benchmarkConfigHash,
    suite: {
      id: detail.benchmark?.id || batch.config?.benchmark_id || null,
      version: detail.benchmark?.version || null,
      target_type: targetType,
      evaluation_set_id: evaluationSetId,
      seed_set_id: seedSetId,
      config_hash: benchmarkConfigHash
    },
    subject,
    summary: {
      result_count: detail.result_count || results.length,
      game_summary: clone(detail.game_summary || {}),
      diagnostic_summary: clone(detail.diagnostic_summary || diagnostics.summary || {}),
      problem_game_count: problemGames.pagination?.total ?? problemGames.games.length,
      diagnostic_count: diagnostics.summary?.total ?? diagnostics.diagnostics.length
    },
    results: clone(results),
    gates: results.map((row) => ({
      result_batch_id: row.result_batch_id,
      target_role: row.target_role || null,
      rankable: row.rankable !== false,
      reason: row.rankable_reason || ''
    })),
    problem_games: clone(problemGames.games),
    diagnostics: clone(diagnostics.diagnostics),
    tags: clone(topTags),
    reproducibility: {
      run_id: runId,
      batch_id: batch.batch_id,
      benchmark_id: detail.benchmark?.id || batch.config?.benchmark_id || null,
      evaluation_set_id: evaluationSetId,
      seed_set_id: seedSetId,
      benchmark_config_hash: benchmarkConfigHash,
      roles: clone(batch.roles || []),
      target_type: targetType
    },
    leaderboard: {
      rankable_count: results.filter((row) => row.rankable !== false).length,
      unrankable_count: results.filter((row) => row.rankable === false).length,
      rows: results.map((row) => ({
        result_batch_id: row.result_batch_id,
        target_role: row.target_role || null,
        rankable: row.rankable !== false,
        rankable_reason: row.rankable_reason || ''
      }))
    }
  }
}

function mockBenchmarkBatchReportMarkdown(report) {
  const lines = [
    '# Benchmark Run Report',
    '',
    `- Run: ${report.run_id}`,
    `- Evaluation set: ${report.evaluation_set_id || ''}`,
    `- Seed set: ${report.seed_set_id || ''}`,
    `- Config hash: ${report.benchmark_config_hash || ''}`,
    `- Status: ${report.status || ''}`,
    '',
    '## Results',
    '',
    '| Result batch | Target | Rankable | Reason |',
    '| --- | --- | --- | --- |',
    ...report.results.map((row) => `| ${row.result_batch_id || ''} | ${row.target_role || row.model_id || ''} | ${row.rankable !== false ? 'yes' : 'no'} | ${row.rankable_reason || ''} |`),
    '',
    '## Problem Games',
    '',
    '| Game | Status | Seed | Diagnostics |',
    '| --- | --- | --- | --- |',
    ...report.problem_games.map((game) => `| ${game.game_id || ''} | ${game.status || ''} | ${game.seed ?? ''} | ${game.diagnostic_count ?? 0} |`),
    '',
    '## Diagnostics',
    '',
    '| Kind | Level | Stage | Message |',
    '| --- | --- | --- | --- |',
    ...report.diagnostics.map((item) => `| ${item.kind || ''} | ${item.level || ''} | ${item.stage || ''} | ${item.message || ''} |`)
  ]
  return `${lines.join('\n')}\n`
}

function mockBenchmarkBatchReportCsv(report) {
  const rows = [
    ['section', 'key', 'value'],
    ['run', 'run_id', report.run_id],
    ['run', 'evaluation_set_id', report.evaluation_set_id],
    ['run', 'seed_set_id', report.seed_set_id],
    ['run', 'benchmark_config_hash', report.benchmark_config_hash],
    ...report.results.map((row) => ['result', row.result_batch_id, row.rankable !== false ? 'rankable' : row.rankable_reason || 'unrankable']),
    ...report.problem_games.map((game) => ['problem_game', game.game_id, game.status]),
    ...report.diagnostics.map((item) => ['diagnostic', item.kind, item.message])
  ]
  return `${rows.map((row) => row.map(mockReportCsvCell).join(',')).join('\n')}\n`
}

function mockReportCsvCell(value) {
  const text = value == null ? '' : String(value)
  return /[",\n]/.test(text) ? `"${text.replace(/"/g, '""')}"` : text
}

function mockBenchmarkReportSummary(report, batch) {
  const results = Array.isArray(report.results) ? report.results : []
  const leaderboardRows = Array.isArray(report.leaderboard?.rows) ? report.leaderboard.rows : results
  const rankableCount = report.leaderboard?.rankable_count ??
    leaderboardRows.filter((row) => row.rankable !== false).length
  const unrankableCount = report.leaderboard?.unrankable_count ??
    leaderboardRows.filter((row) => row.rankable === false).length

  return {
    kind: 'benchmark_run_report_summary',
    schema_version: 1,
    report_id: report.report_id || `${report.run_id || report.batch_id}:report`,
    run_id: report.run_id || batch?.run_id || batch?.batch_id || '',
    batch_id: report.batch_id || batch?.batch_id || '',
    status: report.status || batch?.status || '',
    suite: clone(report.suite || {}),
    subject: clone(report.subject || {}),
    summary: clone(report.summary || {}),
    evaluation_set_id: report.evaluation_set_id || report.suite?.evaluation_set_id || null,
    seed_set_id: report.seed_set_id || report.suite?.seed_set_id || null,
    benchmark_config_hash: report.benchmark_config_hash || report.suite?.config_hash || null,
    problem_game_count: report.summary?.problem_game_count ?? report.problem_games?.length ?? 0,
    diagnostic_count: report.summary?.diagnostic_count ?? report.diagnostics?.length ?? 0,
    rankable_count: rankableCount,
    unrankable_count: unrankableCount,
    generated_at: report.generated_at || batch?.finished_at || batch?.completed_at || batch?.started_at || null,
    created_at: batch?.finished_at || batch?.completed_at || batch?.started_at || report.generated_at || null
  }
}

function mockBenchmarkReports(queryString = '') {
  const query = new URLSearchParams(queryString)
  const scope = String(query.get('scope') || '').trim()
  const benchmarkId = String(query.get('benchmark_id') || '').trim()
  const evaluationSetId = String(query.get('evaluation_set_id') || '').trim()
  const targetRole = String(query.get('target_role') || '').trim()
  const offset = Math.max(0, Number(query.get('offset') || 0))
  const limit = Math.max(1, Math.min(200, Number(query.get('limit') || 50)))
  const summaries = []

  for (const batch of mockBenchmarkBatches) {
    const report = mockBenchmarkBatchReportPayload(batch.batch_id)
    const reportScope = report.suite?.target_type || report.subject?.type || 'role_version'
    const reportBenchmarkId = report.suite?.id || batch.benchmark?.id || batch.config?.benchmark_id || ''
    const reportEvaluationSetId = report.evaluation_set_id || report.suite?.evaluation_set_id || ''
    const reportTargetRole = report.subject?.target_role || report.results?.[0]?.target_role || batch.roles?.[0] || ''

    if (scope && reportScope !== scope) continue
    if (benchmarkId && reportBenchmarkId !== benchmarkId) continue
    if (evaluationSetId && reportEvaluationSetId !== evaluationSetId) continue
    if (targetRole && reportTargetRole !== targetRole) continue
    summaries.push(mockBenchmarkReportSummary(report, batch))
  }

  summaries.sort((a, b) =>
    String(b.generated_at || b.created_at || '').localeCompare(String(a.generated_at || a.created_at || ''))
  )
  const page = summaries.slice(offset, offset + limit)

  return {
    kind: 'benchmark_run_reports',
    schema_version: 1,
    scope: scope || null,
    evaluation_set_id: evaluationSetId || null,
    benchmark_id: benchmarkId || null,
    target_role: targetRole || null,
    items: clone(page),
    pagination: {
      total: summaries.length,
      offset,
      limit,
      returned: page.length,
      has_more: offset + page.length < summaries.length
    }
  }
}

function mockBenchmarkDiagnosticsAggregate(queryString = '') {
  const query = new URLSearchParams(queryString)
  const scope = String(query.get('scope') || '').trim()
  const benchmarkId = String(query.get('benchmark_id') || '').trim()
  const evaluationSetId = String(query.get('evaluation_set_id') || '').trim()
  const targetRole = String(query.get('target_role') || '').trim()
  const kindFilter = filterSet(query.get('kind'))
  const levelFilter = filterSet(query.get('level'))
  const statusFilter = filterSet(query.get('status'))
  const stageFilter = filterSet(query.get('stage'))
  const seedFilter = filterSet(query.get('seed'))
  const offset = Math.max(0, Number(query.get('offset') || 0))
  const limit = Math.max(1, Math.min(1000, Number(query.get('limit') || 200)))
  const matched = []
  const diagnostics = []
  const affectedGames = []

  for (const batch of mockBenchmarkBatches) {
    const batchScope = batch.benchmark?.target_type || batch.config?.target_type || 'role_version'
    const batchBenchmarkId = batch.benchmark?.id || batch.config?.benchmark_id || ''
    const batchEvaluationSetId = batch.benchmark?.evaluation_set_id || batch.config?.evaluation_set_id || ''
    if (scope && batchScope !== scope) continue
    if (benchmarkId && batchBenchmarkId !== benchmarkId) continue
    if (evaluationSetId && batchEvaluationSetId !== evaluationSetId) continue
    if (statusFilter && !statusFilter.has(String(batch.status || '').toLowerCase())) continue

    const rows = mockBenchmarkDiagnosticEntries(batch)
      .filter((item) => {
        if (targetRole && item.target_role && item.target_role !== targetRole) return false
        if (targetRole && !item.target_role && !batch.roles?.includes(targetRole)) return false
        if (kindFilter && !kindFilter.has(String(item.kind || '').toLowerCase())) return false
        if (levelFilter && !levelFilter.has(String(item.level || '').toLowerCase())) return false
        if (stageFilter && !stageFilter.has(String(item.stage || '').toLowerCase())) return false
        if (seedFilter && !seedFilter.has(String(item.seed || '').toLowerCase())) return false
        return true
      })
      .map((item) => ({
        ...item,
        batch_status: batch.status,
        target_type: batchScope,
        benchmark_id: batchBenchmarkId,
        evaluation_set_id: batchEvaluationSetId,
        seed_set_id: batch.benchmark?.seed_set_id || ''
      }))
    if (!rows.length) continue
    diagnostics.push(...rows)
    matched.push({ batch, rows })
    const countsByGame = countBy(rows.filter((item) => item.game_id), (item) => item.game_id)
    for (const game of mockBenchmarkGameRows(batch)) {
      if (countsByGame[game.game_id]) {
        affectedGames.push({
          ...game,
          batch_id: batch.batch_id,
          diagnostic_count: countsByGame[game.game_id]
        })
      }
    }
  }

  const page = diagnostics.slice(offset, offset + limit)
  return {
    kind: 'benchmark_diagnostics',
    schema_version: 1,
    scope: scope || null,
    evaluation_set_id: evaluationSetId || null,
    benchmark_id: benchmarkId || null,
    target_role: targetRole || null,
    filters: {
      kind: query.get('kind'),
      level: query.get('level'),
      status: query.get('status'),
      stage: query.get('stage'),
      seed: query.get('seed')
    },
    diagnostics: clone(page),
    affected_runs: clone(matched.map(({ batch, rows }) => ({
      id: batch.batch_id,
      batch_id: batch.batch_id,
      status: batch.status,
      started_at: batch.started_at,
      finished_at: batch.finished_at,
      current_stage: batch.current_stage || batch.stage || batch.status,
      benchmark_id: batch.benchmark?.id || batch.config?.benchmark_id || '',
      evaluation_set_id: batch.benchmark?.evaluation_set_id || batch.config?.evaluation_set_id || '',
      seed_set_id: batch.benchmark?.seed_set_id || '',
      target_type: batch.benchmark?.target_type || batch.config?.target_type || 'role_version',
      roles: batch.roles || [],
      diagnostic_count: rows.length,
      diagnostic_summary: mockBenchmarkDiagnosticSummary(rows)
    }))),
    affected_games: clone(affectedGames),
    summary: {
      ...mockBenchmarkDiagnosticSummary(diagnostics),
      by_stage: countBy(diagnostics, (item) => item.stage || 'unknown'),
      by_target_role: countBy(diagnostics, (item) => item.target_role || 'all'),
      by_batch: countBy(diagnostics, (item) => item.batch_id || 'unknown'),
      by_seed: countBy(diagnostics.filter((item) => item.seed != null), (item) => item.seed),
      affected_run_count: matched.length,
      affected_game_count: new Set(diagnostics.map((item) => item.game_id).filter(Boolean)).size
    },
    pagination: {
      total: diagnostics.length,
      offset,
      limit,
      returned: page.length,
      has_more: offset + page.length < diagnostics.length
    }
  }
}

function filterSet(value) {
  const items = String(value || '').split(',').map((item) => item.trim().toLowerCase()).filter(Boolean)
  return items.length ? new Set(items) : null
}

function createMockBenchmarkPlan(body = {}) {
  const suite = MOCK_BENCHMARK_SUITES.find((item) => item.id === body.benchmark_id) || null
  const isModelBenchmark = body.target_type === 'model' || suite?.target_type === 'model'
  const roles = isModelBenchmark
    ? (suite?.roles?.slice() || MOCK_EVOLUTION_ROLES.slice())
    : (Array.isArray(body.roles) && body.roles.length ? body.roles : [MOCK_EVOLUTION_ROLES[0]])
  const gameCount = Number(suite?.game_count ?? body.battle_games ?? 10)
  const maxDays = Number(suite?.max_days ?? body.max_days ?? 5)
  const evalBatchCount = isModelBenchmark ? 1 : Math.max(1, roles.length)
  const totalGames = evalBatchCount * gameCount
  const judgeMaxDecisions = Number(suite?.judge?.judge_max_decisions || 0)
  const judgeDecisionUnits = totalGames * judgeMaxDecisions
  const gameDecisionUnits = totalGames * maxDays * 12
  const estimatedUnits = gameDecisionUnits + judgeDecisionUnits
  const budgetLimit = body.budget_limit_units == null || body.budget_limit_units === ''
    ? null
    : Number(body.budget_limit_units)
  const budgetExceeded = Number.isFinite(budgetLimit) && estimatedUnits > budgetLimit
  return {
    kind: 'benchmark_run_plan',
    schema_version: 1,
    benchmark: suite ? clone(suite) : null,
    target_type: isModelBenchmark ? 'model' : 'role_version',
    roles,
    role_count: roles.length,
    eval_batch_count: evalBatchCount,
    game_count_per_eval_batch: gameCount,
    max_days: maxDays,
    total_games: totalGames,
    seed_set_id: suite?.seed_set_id || null,
    seed_count: Number(suite?.seed_count ?? gameCount),
    cost_tier: suite?.cost_tier || 'ad_hoc',
    judge: {
      enabled: judgeMaxDecisions > 0,
      max_decisions_per_game: judgeMaxDecisions,
      estimated_decisions: judgeDecisionUnits,
      concurrency: suite?.judge?.judge_concurrency || null,
      timeout_seconds: suite?.judge?.judge_timeout_seconds || null
    },
    estimates: {
      player_count: 12,
      game_decision_units: gameDecisionUnits,
      judge_decision_units: judgeDecisionUnits,
      estimated_llm_call_units: estimatedUnits,
      assumptions: [
        'game_decision_units = total_games * max_days * 12 players',
        'judge_decision_units = total_games * judge_max_decisions when decision judge is enabled'
      ]
    },
    budget: {
      limit_units: Number.isFinite(budgetLimit) ? budgetLimit : null,
      estimated_units: estimatedUnits,
      exceeded: budgetExceeded
    },
    launchable: !budgetExceeded,
    warnings: budgetExceeded
      ? [{ kind: 'budget_exceeded', message: '预计评测成本超过预算上限' }]
      : []
  }
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
  const decisions = mockEvolutionGameDecisions(runId, gameId, phase, side).decisions.map((decision, index) => ({
    ...decision,
    source: decision.source || ['llm', 'tot', 'policy_adjusted'][index % 3]
  }))
  const events = mockEvolutionGameEvents(runId, gameId, phase, side).events.map((event, index) => ({
    ...event,
    source: event.source || ['mock', 'llm', 'got'][index % 3]
  }))
  const winner = gameId.includes('-2') ? 'werewolves' : 'good'
  return {
    kind: 'role_evolution_game_archive',
    schema_version: 1,
    run_id: runId,
    game_id: gameId,
    title: `${sideLabel}样本局 · ${gameId}`,
    summary: `${runId} 的${sideLabel}样本局，用于核对候选技能在发言、投票和夜间行动中的实际行为。`,
    winner,
    verdict: gameId.includes('-2') ? '狼人胜利' : '好人胜利',
    highlights: [
      '预言家发言是否清晰给出查验链路。',
      '关键轮次投票是否贴合站边与狼坑收敛。',
      '夜间技能行动是否减少无效目标和重复信息。'
    ],
    events,
    decisions,
    event_count: events.length,
    decision_count: decisions.length,
    error_count: 0,
    fallback_count: decisions.filter((decision) => ['fallback', 'policy_adjusted'].includes(decision.source)).length,
    decision_sources: tallyDecisionSources(decisions),
    config: {
      run_id: runId,
      phase,
      side: side || null,
      seed: `${runId}-${gameId}`,
      max_days: 20,
      skill_dir: side === 'candidate' ? 'skills/candidates' : 'baseline',
      role_skill_dirs: {
        seer: side === 'candidate' ? 'skills/candidates/seer' : 'baseline',
        witch: side === 'candidate' ? 'skills/candidates/witch' : 'baseline'
      },
      role_versions: {
        seer: side === 'candidate' ? 'cand-seer-review-a4' : 'base-seer-20260604'
      }
    },
    phase,
    side: side || null,
    history_game_id: `${runId}-${phase || 'training'}-${side || 'sample'}-${gameId}`,
    replay_available: true,
    replay_unavailable_reason: null
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
  const decisions = mockSelfplayGameDecisions(runId, gameId).decisions.map((decision, index) => ({
    ...decision,
    source: decision.source || ['llm', 'got', 'tot'][index % 3]
  }))
  const events = mockSelfplayGameEvents(runId, gameId).events.map((event, index) => ({
    ...event,
    source: event.source || ['mock', 'llm', 'got'][index % 3]
  }))
  const winner = gameId.includes('-2') ? 'werewolves' : 'good'
  return {
    kind: 'game_trace_archive',
    schema_version: 1,
    run_id: runId,
    game_id: gameId,
    title: `评测对局 · ${gameId}`,
    summary: `${runId} 的 selfplay 对局，用于评估当前 agent 版本在完整 12 人局中的胜负、发言、投票和技能决策质量。`,
    winner,
    verdict: gameId.includes('-2') ? '狼人胜利' : '好人胜利',
    highlights: [
      '首日发言是否能形成可复盘的站边依据。',
      '关键夜晚技能目标是否符合局势收益。',
      '投票轮是否能从历史发言和票型中收束焦点。'
    ],
    events,
    decisions,
    event_count: events.length,
    decision_count: decisions.length,
    error_count: 0,
    fallback_count: 0,
    decision_sources: tallyDecisionSources(decisions),
    config: {
      run_id: runId,
      seed: `${runId}-${gameId}`,
      max_days: 20,
      enable_sheriff: true,
      skill_dir: 'selfplay',
      role_skill_dirs: {
        seer: 'selfplay/seer',
        villager: 'selfplay/villager'
      },
      player_count: 12
    }
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
    const query = new URLSearchParams(queryString)
    if (query.get('scope') === 'model') {
      return mockModelLeaderboard(query.get('evaluation_set_id') || '')
    }
    return {
      entries: clone(mockBattleLeaderboardEntries),
      source: 'frontend-mock',
      source_type: 'mock'
    }
  }

  if (routePath === '/leaderboards/compare') {
    return mockLeaderboardCompare(queryString)
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

  if (routePath === '/roles/overview') {
    return mockRolesOverview()
  }

  if (routePath === '/benchmarks') {
    return { items: clone(MOCK_BENCHMARK_SUITES) }
  }

  if (routePath === '/benchmark/snapshots') {
    if (method === 'POST') return createMockBenchmarkSnapshot(body)
    return listMockBenchmarkSnapshots(queryString)
  }

  if (routePath === '/benchmark/views') {
    if (method === 'POST') return saveMockBenchmarkView(body)
    return listMockBenchmarkViews(queryString)
  }

  const benchmarkViewMatch = routePath.match(/^\/benchmark\/views\/([^/]+)$/)
  if (benchmarkViewMatch) {
    const viewKey = decodeURIComponent(benchmarkViewMatch[1])
    if (method === 'DELETE') return deleteMockBenchmarkView(viewKey)
    return getMockBenchmarkView(viewKey)
  }

  const benchmarkSnapshotCompareMatch = routePath.match(/^\/benchmark\/snapshots\/([^/]+)\/compare$/)
  if (benchmarkSnapshotCompareMatch) {
    return mockBenchmarkSnapshotCompare(decodeURIComponent(benchmarkSnapshotCompareMatch[1]), queryString)
  }

  const benchmarkSnapshotMatch = routePath.match(/^\/benchmark\/snapshots\/([^/]+)$/)
  if (benchmarkSnapshotMatch) {
    return getMockBenchmarkSnapshot(decodeURIComponent(benchmarkSnapshotMatch[1]))
  }

  if (routePath === '/models/leaderboard') {
    const query = new URLSearchParams(queryString)
    return mockModelLeaderboard(query.get('evaluation_set_id') || '')
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

  if (routePath === '/benchmark/plan' && method === 'POST') {
    return createMockBenchmarkPlan(body)
  }

  if ((routePath === '/benchmark' || routePath === '/benchmark/batch') && method === 'POST') {
    return createMockBenchmarkBatch(body)
  }

  if (routePath === '/benchmark/diagnostics') {
    return mockBenchmarkDiagnosticsAggregate(queryString)
  }

  if (routePath === '/benchmark/reports') {
    return mockBenchmarkReports(queryString)
  }

  const benchmarkBatchGamesMatch = routePath.match(/^\/benchmark\/batch\/([^/]+)\/games$/)
  if (benchmarkBatchGamesMatch) {
    return mockBenchmarkBatchGames(decodeURIComponent(benchmarkBatchGamesMatch[1]), queryString)
  }

  const benchmarkBatchDiagnosticsMatch = routePath.match(/^\/benchmark\/batch\/([^/]+)\/diagnostics$/)
  if (benchmarkBatchDiagnosticsMatch) {
    return mockBenchmarkBatchDiagnostics(decodeURIComponent(benchmarkBatchDiagnosticsMatch[1]))
  }

  const benchmarkBatchReportMatch = routePath.match(/^\/benchmark\/batch\/([^/]+)\/report$/)
  if (benchmarkBatchReportMatch) {
    return mockBenchmarkBatchReport(decodeURIComponent(benchmarkBatchReportMatch[1]), queryString)
  }

  const benchmarkBatchDetailMatch = routePath.match(/^\/benchmark\/batch\/([^/]+)$/)
  if (benchmarkBatchDetailMatch) {
    return mockBenchmarkBatchDetail(decodeURIComponent(benchmarkBatchDetailMatch[1]))
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

  const gamePhaseMatch = routePath.match(/^\/games\/([^/]+)\/phase$/)
  if (gamePhaseMatch) {
    ensureSeedHistory()
    const gameId = decodeURIComponent(gamePhaseMatch[1])
    const game = mockHistoryGameById(gameId)
    if (!game) throw new Error('Mock game not found')
    return mockGamePhasePayload(game, queryString)
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

  const gameDeleteMatch = routePath.match(/^\/games\/([^/]+)$/)
  if (gameDeleteMatch && method === 'DELETE') {
    ensureSeedHistory()
    const gameId = decodeURIComponent(gameDeleteMatch[1])
    archivedGames = archivedGames.filter((item) => item.game_id !== gameId)
    if (activeGame?.game_id === gameId) activeGame = null
    writeStoredHistory(archivedGames)
    return { game_id: gameId, deleted: true, log_source: 'normal', force: false }
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
    const game = mockHistoryGameById(gameId)
    if (!game) throw new Error('Mock game not found')
    if (gameMatch[2] === 'archive') {
      return mockGameArchivePayload(game)
    }
    if (gameMatch[2] === 'review') {
      return {
        title: 'Mock 复盘报告',
        verdict: game.winner || '测试剧本未结束',
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
