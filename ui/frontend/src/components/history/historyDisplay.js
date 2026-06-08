const ROLE_LABELS = {
  villager: '村民',
  civilian: '村民',
  werewolf: '狼人',
  wolf: '狼人',
  seer: '预言家',
  witch: '女巫',
  guard: '守卫',
  hunter: '猎人',
  idiot: '白痴',
  sheriff: '警长',
  white_wolf: '白狼王',
  white_wolf_king: '白狼王',
  wolf_king: '狼王'
}

const WINNER_LABELS = {
  werewolves: '狼人阵营',
  werewolf: '狼人阵营',
  wolves: '狼人阵营',
  wolf: '狼人阵营',
  villagers: '好人阵营',
  villager: '好人阵营',
  village: '好人阵营',
  good: '好人阵营',
  town: '好人阵营',
  humans: '好人阵营',
  human: '好人阵营',
  draw: '平局',
  tie: '平局',
  error: '异常结束',
  failed: '异常结束',
  cancelled: '已取消',
  canceled: '已取消',
  none: '未记录',
  unknown: '未记录'
}

const PHASE_LABELS = {
  setup: '开局配置',
  game_init: '开局配置',
  night: '黑夜行动',
  night_start: '黑夜开始',
  night_end: '黑夜结果',
  night_result: '黑夜结果',
  night_death_reveal: '死亡公布',
  day: '白天',
  day_speech: '白天发言',
  day_speech_start: '白天发言',
  day_speech_end: '发言结束',
  speech: '白天发言',
  vote: '公投放逐',
  exile_vote: '放逐投票',
  pk_vote: '对决投票',
  sheriff: '警长竞选',
  sheriff_election: '警长竞选',
  sheriff_vote: '警长投票',
  sheriff_result: '警长结果',
  sheriff_election_start: '警长竞选',
  sheriff_election_end: '警长结果',
  result: '结算',
  ended: '终局',
  finished: '结束',
  unknown: '未知阶段'
}

const ACTION_LABELS = {
  action_request: '行动请求',
  action_response: '行动响应',
  invalid_response: '非法响应',
  default_action: '默认行动',
  agent_error: '智能体错误',
  game_init: '开局配置',
  setup: '开局配置',
  night_start: '黑夜开始',
  night_end: '黑夜结果',
  speak: '发言',
  sheriff_speak: '警上发言',
  pk_speak: '对决发言',
  last_word: '遗言',
  speech_order: '发言顺序',
  vote: '投票',
  vote_prompt: '投票提醒',
  exile_vote: '放逐投票',
  exile_vote_start: '放逐投票',
  exile_vote_end: '放逐结果',
  exile_vote_tie: '平票',
  sheriff_vote: '警长投票',
  pk_vote: '对决投票',
  pk_vote_end: '对决投票结果',
  kill: '狼人袭击',
  werewolf_kill: '狼人夜刀',
  werewolf_result: '狼人结果',
  death: '死亡',
  exile: '放逐',
  night_result: '夜晚结果',
  night_death_reveal: '死亡公布',
  guard: '守护',
  guard_protect: '守卫守护',
  guard_result: '守卫结果',
  inspect: '查验',
  seer_check: '预言查验',
  seer_result: '预言结果',
  witch_act: '女巫行动',
  witch_result: '女巫结果',
  poison: '毒药',
  antidote: '解药',
  shoot: '开枪',
  hunter_shoot: '猎人开枪',
  white_wolf_burst: '白狼王自爆',
  white_wolf_explode: '白狼王自爆',
  white_wolf_explosion: '白狼王自爆',
  white_wolf_burst_kill: '白狼王带走',
  white_wolf_burst_death: '白狼王死亡',
  sheriff_run: '上警',
  sheriff_pass: '不上警',
  sheriff_withdraw: '退水',
  sheriff_stay: '留警上',
  sheriff_elect: '警长当选',
  sheriff_start: '警长竞选',
  sheriff_result: '警长结果',
  sheriff_election_start: '警长竞选',
  sheriff_election_end: '警长结果',
  sheriff_badge: '警徽处理',
  sheriff_badge_transfer: '移交警徽',
  sheriff_badge_destroy: '撕毁警徽',
  sheriff_transfer: '移交警徽',
  sheriff_destroy: '撕毁警徽',
  game_over: '游戏结束',
  game_end: '游戏结束',
  finished: '结束',
  ended: '终局',
  policy_skipped: '快测跳过',
  policy_adjusted: '策略修正',
  llm_error: '模型错误',
  fallback: '规则回退'
}

const CHOICE_LABELS = {
  pass: '跳过',
  skip: '跳过',
  none: '不使用',
  no_target: '无目标',
  save: '使用解药',
  antidote: '使用解药',
  poison: '使用毒药',
  burst: '发动自爆',
  explode: '发动自爆',
  shoot: '开枪',
  run: '竞选',
  withdraw: '退水',
  stay: '留警上',
  transfer: '移交警徽',
  destroy: '撕毁警徽',
  forward: '顺序发言',
  reverse: '逆序发言'
}

const SOURCE_LABELS = {
  policy_skipped: '快测跳过',
  policy_adjusted: '策略修正',
  llm_error: '模型错误',
  fallback: '规则回退',
  human: '真人操作',
  llm: '模型决策',
  tot: '树式推理',
  got: '图式推理',
  unknown: '未知来源'
}

export function displayRoleLabel(role) {
  const key = String(role || '').trim().toLowerCase()
  return ROLE_LABELS[key] || role || '未知'
}

export function displayWinnerLabel(winner) {
  if (winner == null || winner === '') return '未记录'
  const key = String(winner).trim().toLowerCase()
  return WINNER_LABELS[key] || normalizeHistoryDisplayText(winner)
}

export function displayPhaseLabel(phase) {
  const key = String(phase || '').trim().toLowerCase()
  return PHASE_LABELS[key] || normalizeHistoryDisplayText(phase) || '阶段'
}

export function displayDayLabel(day) {
  if (day == null || day === '') return '未记录'
  return `第${day}天`
}

export function displayActionLabel(action) {
  const key = String(action || '').trim().toLowerCase()
  return ACTION_LABELS[key] || '决策'
}

export function displayChoiceLabel(choice) {
  const key = String(choice || '').trim().toLowerCase()
  return CHOICE_LABELS[key] || normalizeHistoryDisplayText(choice) || '未选择'
}

export function displaySourceLabel(source) {
  const key = String(source || '').trim().toLowerCase()
  if (SOURCE_LABELS[key]) return SOURCE_LABELS[key]
  if (key.includes('skip')) return '快测跳过'
  if (key.includes('policy')) return '策略修正'
  if (key.includes('fallback')) return '规则回退'
  if (key.includes('error')) return '错误'
  if (key.includes('human')) return '真人操作'
  if (key.includes('llm')) return '模型决策'
  if (key.includes('tree') || key === 'tot' || key.includes('graph') || key === 'got') return '推理链'
  return '其他来源'
}

export function displaySkillDirLabel(skillDir) {
  const key = String(skillDir || '').trim().toLowerCase()
  const map = {
    baseline: '默认技能',
    default: '默认技能',
    none: '未配置'
  }
  return map[key] || normalizeHistoryDisplayText(skillDir) || '默认技能'
}

export function displayDeathReason(reason) {
  const key = String(reason || '').trim().toLowerCase()
  const map = {
    werewolf: '狼人袭击',
    werewolves: '狼人袭击',
    wolf: '狼人袭击',
    exile: '放逐',
    exile_vote: '放逐投票',
    vote: '放逐投票',
    poison: '女巫毒药',
    witch: '女巫毒药',
    hunter: '猎人开枪',
    hunter_shoot: '猎人开枪',
    white_wolf: '白狼王自爆'
  }
  return map[key] || normalizeHistoryDisplayText(reason)
}

export function normalizeHistoryDisplayText(value) {
  if (value == null || value === '') return ''
  let text = String(value)

  if (/^(ok|none|null|undefined|ui backend fallback model|backend fallback model|fallback model)$/i.test(text.trim())) return ''
  text = text.replace(/\bD(\d+)\b/g, '第$1天')
  text = text.replace(/\bP(\d+)\s*\(([^)]+)\)/gi, (_, seat, role) => `${seat}号（${displayRoleLabel(role)}）`)
  text = text.replace(/\bP(\d+)\b/g, '$1号')
  text = text.replace(/(\d+)\s+号/g, '$1号')
  text = text.replace(/死亡玩家[:：]\s*\[([^\]]*)\]/g, (_, raw) => {
    const seats = String(raw).match(/\d+/g) || []
    return `死亡玩家：${seats.length ? seats.map((seat) => `${seat}号`).join('、') : '无'}`
  })
  text = text.replace(/第\s*(\d+)\s*夜/g, '第$1夜')
  text = text.replace(/请求\s*(\d+)号执行\s*([a-z_]+)/gi, (_, seat, action) =>
    `请求${seat}号执行${displayActionLabel(action)}`
  )
  text = text.replace(/(\d+)号执行\s*([a-z_]+)\s*失败/gi, (_, seat, action) =>
    `${seat}号执行${displayActionLabel(action)}失败`
  )
  text = text.replace(/(\d+)号响应\s*([a-z_]+)/gi, (_, seat, action) =>
    `${seat}号响应${displayActionLabel(action)}`
  )
  text = text.replace(/响应\s*([a-z_]+)/gi, (_, action) =>
    `响应${displayActionLabel(action)}`
  )
  text = text.replace(/选择\s*([a-z_]+)/gi, (_, choice) =>
    `选择${displayChoiceLabel(choice)}`
  )
  text = text.replace(/决策说明[:：]\s*(ok|none|null|undefined)/gi, '')

  text = text.replace(/胜(利方|方)[:：]?\s*(werewolves|werewolf|wolves|wolf|villagers|villager|village|good|town|humans|human)\b/gi, (_, label, winner) =>
    `胜${label}：${displayWinnerLabel(winner)}`
  )
  text = text.replace(/原因[:：]\s*(werewolves|werewolf|wolves|wolf|exile_vote|exile|vote|poison|witch|hunter_shoot|hunter|white_wolf)\b/gi, (_, reason) =>
    `原因：${displayDeathReason(reason)}`
  )

  const replacements = [
    [/\bpolicy_adjusted\b/gi, '策略修正'],
    [/\bllm_error\b/gi, '模型错误'],
    [/\bfallback\b/gi, '规则回退'],
    [/\bstandard_12\b/gi, '标准12人局'],
    [/\bunknown\b/gi, '未知'],
    [/\baction_request\b/gi, '行动请求'],
    [/\baction_response\b/gi, '行动响应'],
    [/\binvalid_response\b/gi, '非法响应'],
    [/\bdefault_action\b/gi, '默认行动'],
    [/\bagent_error\b/gi, '智能体错误'],
    [/\bgame_init\b/gi, '开局配置'],
    [/\bnight_start\b/gi, '黑夜开始'],
    [/\bnight_end\b/gi, '黑夜结果'],
    [/\bnight_result\b/gi, '黑夜结果'],
    [/\bnight_death_reveal\b/gi, '死亡公布'],
    [/\bday_speech_start\b/gi, '白天发言'],
    [/\bday_speech_end\b/gi, '发言结束'],
    [/\bday_speech\b/gi, '白天发言'],
    [/\bwitch_act\b/gi, '女巫行动'],
    [/\bwitch_result\b/gi, '女巫结果'],
    [/\bwerewolf_kill\b/gi, '狼人夜刀'],
    [/\bwerewolf_result\b/gi, '狼人结果'],
    [/\bseer_check\b/gi, '预言查验'],
    [/\bseer_result\b/gi, '预言结果'],
    [/\bguard_protect\b/gi, '守卫守护'],
    [/\bguard_result\b/gi, '守卫结果'],
    [/\bhunter_shoot\b/gi, '猎人开枪'],
    [/\bsheriff_vote\b/gi, '警长投票'],
    [/\bexile_vote\b/gi, '放逐投票'],
    [/\bpk_vote\b/gi, '对决投票'],
    [/\bspeech_order\b/gi, '发言顺序'],
    [/\bsheriff_badge_transfer\b/gi, '移交警徽'],
    [/\bsheriff_badge_destroy\b/gi, '撕毁警徽'],
    [/\bsheriff_badge\b/gi, '警徽处理'],
    [/\bsheriff_election_start\b/gi, '警长竞选'],
    [/\bsheriff_election_end\b/gi, '警长结果'],
    [/\bsheriff_election\b/gi, '警长竞选'],
    [/\bsheriff_result\b/gi, '警长结果'],
    [/\bsheriff_run\b/gi, '上警'],
    [/\bsheriff_pass\b/gi, '不上警'],
    [/\bsheriff_withdraw\b/gi, '退水'],
    [/\bsheriff_stay\b/gi, '留警上'],
    [/\bwhite_wolf_explode\b/gi, '白狼王自爆'],
    [/\bwhite_wolf_explosion\b/gi, '白狼王自爆'],
    [/\bdeath\b/gi, '死亡'],
    [/\bpass\b/gi, '跳过'],
    [/\bnone\b/gi, '不使用'],
    [/\bsheriff_speak\b/gi, '警上发言'],
    [/\blast_word\b/gi, '遗言'],
    [/\bfinished\b/gi, '结束'],
    [/\bended\b/gi, '终局'],
    [/\bwerewolves\b/gi, '狼人阵营'],
    [/\bvillagers\b/gi, '好人阵营'],
    [/\bwerewolf\b/gi, '狼人'],
    [/\bvillager\b/gi, '村民'],
    [/\bseer\b/gi, '预言家'],
    [/\bwitch\b/gi, '女巫'],
    [/\bguard\b/gi, '守卫'],
    [/\bhunter\b/gi, '猎人']
  ]
  for (const [pattern, replacement] of replacements) {
    text = text.replace(pattern, replacement)
  }
  return text
    .replace(/[，,]\s*。/g, '。')
    .replace(/[，,]\s*$/g, '')
    .replace(/\s{2,}/g, ' ')
    .trim()
}
