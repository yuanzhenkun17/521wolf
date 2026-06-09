// @ts-nocheck
const ROLE_META = {
  white_wolf_king: { label: '白狼王', image: '/role-icons/optimized/白狼王.webp' },
  werewolf: { label: '狼人', image: '/role-icons/optimized/普通狼.webp' },
  villager: { label: '村民', image: '/role-icons/optimized/平民.webp' },
  seer: { label: '预言家', image: '/role-icons/optimized/预言家.webp' },
  witch: { label: '女巫', image: '/role-icons/optimized/女巫.webp' },
  hunter: { label: '猎人', image: '/role-icons/optimized/猎人.webp' },
  guard: { label: '守卫', image: '/role-icons/optimized/守卫.webp' }
}

const EVOLUTION_TERMINAL_STATUSES = new Set(['promoted', 'rejected', 'failed', 'completed'])
const EVOLUTION_ACTIVE_STATUSES = new Set([
  'queued',
  'running',
  'training',
  'consolidating',
  'applying',
  'scenario_replay',
  'battling',
  'combined_battling',
  'rate_limited'
])

const STATUS_LABELS = {
  progress: '进度',
  queued: '排队',
  running: '运行中',
  training: '训练',
  consolidating: '归纳',
  applying: '应用',
  scenario_replay: '快筛',
  battling: '对战',
  combined_battling: '组合对战',
  reviewing: '待评审',
  promoted: '已晋升',
  rejected: '已拒绝',
  failed: '失败',
  completed: '已完成',
  paused: '已暂停',
  rate_limited: '限流重试'
}

const SOURCE_LABELS = {
  setup: '准备',
  night: '黑夜',
  night_start: '黑夜开始',
  night_end: '黑夜结果',
  speech: '发言',
  day_speech: '白天发言',
  vote: '投票',
  sheriff: '警长竞选',
  sheriff_vote: '警长投票',
  ended: '终局',
  finished: '结束',
  completed: '已完成',
  failed: '失败',
  reviewing: '待评审',
  promoted: '已晋升',
  rejected: '已拒绝',
  queued: '排队',
  running: '运行中',
  baseline: '基线',
  shadow: '影子',
  canary: '灰度',
  draft: '草稿',
  candidate: '候选',
  version: '版本',
  manual: '手动发布',
  evolution: '自进化',
  app: '应用',
  app_registry: '版本库',
  'app-registry': '版本库',
  app_fallback: '本地兜底',
  'app-fallback': '本地兜底',
  default_baseline: '默认基线',
  frontend_mock: '前端模拟',
  'frontend-mock': '前端模拟',
  selfplay: '自博弈',
  battle: '对战',
  training: '训练',
  archive: '档案',
  decision: '决策',
  decisions: '决策',
  events: '事件',
  event: '事件',
  agent: '智能体',
  run: '运行',
  game: '对局',
  werewolf_kill: '狼人夜刀',
  guard_protect: '守卫守护',
  seer_check: '预言查验',
  witch_act: '女巫行动',
  hunter_shoot: '猎人开枪',
  white_wolf_explode: '白狼王自爆',
  progress: '进度',
  mock: '模拟',
  default: '默认'
}

const RECOMMENDATION_LABELS = {
  promote: '建议晋升',
  reject: '建议拒绝',
  review: '待评审',
  hold: '继续观察',
  baseline: '基线',
  base: '基线'
}

function roleMeta(role) {
  return ROLE_META[role] || {
    label: '未知角色',
    image: '/role-icons/optimized/未知.webp'
  }
}

function roleLabel(role, fallback = '—') {
  return ROLE_META[role]?.label || fallback
}

function shortId(value, length = 8, fallback = '—') {
  return value ? String(value).slice(0, length) : fallback
}

function pct(value) {
  const n = Number(value || 0)
  return Math.max(0, Math.min(100, Math.round(n * 100)))
}

function statusText(status) {
  return STATUS_LABELS[status] || '未知'
}

function sourceText(source) {
  const key = String(source || '').trim().toLowerCase()
  if (SOURCE_LABELS[key]) return SOURCE_LABELS[key]
  if (!key) return '未知'
  return /^[a-z0-9_.:-]+$/i.test(key) ? '未知' : String(source)
}

function recommendationText(value) {
  const key = String(value || '').trim().toLowerCase()
  if (RECOMMENDATION_LABELS[key]) return RECOMMENDATION_LABELS[key]
  if (!key) return '未标记'
  return /^[a-z0-9_.:-]+$/i.test(key) ? '未标记' : String(value)
}

function normalizeLeaderboardEntry(entry) {
  const score = Number(entry.target_role_role_weighted_score || 0)
  const winRate = Number(entry.target_side_win_rate || 0)
  return {
    ...entry,
    short: shortId(entry.hash),
    scorePct: pct(score),
    winRatePct: pct(winRate),
    deltaScore: Number(entry.delta_vs_baseline?.target_role_role_weighted_score || 0),
    fallbackPct: pct(entry.target_role_fallback_rate || 0),
    recommendationLabel: recommendationText(entry.recommendation)
  }
}

function isEvolutionBatch(batch) {
  return batch?.kind === 'role_evolution_batch' || String(batch?.batch_id || '').startsWith('evo_batch_')
}

function isBenchmarkBatch(batch) {
  return batch?.kind === 'benchmark_batch' || String(batch?.batch_id || '').startsWith('bench_')
}

export {
  EVOLUTION_ACTIVE_STATUSES,
  EVOLUTION_TERMINAL_STATUSES,
  ROLE_META,
  isBenchmarkBatch,
  isEvolutionBatch,
  normalizeLeaderboardEntry,
  pct,
  recommendationText,
  roleLabel,
  roleMeta,
  shortId,
  sourceText,
  statusText
}
