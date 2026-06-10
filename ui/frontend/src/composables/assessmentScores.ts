interface AssessmentPlayer {
  id?: unknown
  role?: unknown
  role_hint?: unknown
  [key: string]: unknown
}

interface AssessmentDecision {
  action_type?: string
  actor_id?: unknown
  target_id?: unknown
  day?: unknown
  reason?: unknown
  public_summary?: unknown
  confidence?: unknown
  [key: string]: unknown
}

interface AssessmentLog {
  day?: unknown
  [key: string]: unknown
}

interface AssessmentSource {
  players?: AssessmentPlayer[]
  decisions?: AssessmentDecision[]
  logs?: AssessmentLog[]
  [key: string]: unknown
}

interface AssessmentScore {
  player: AssessmentPlayer
  speech: number
  vote: number
  skill: number
  logic: number
  team: number
  risk_penalty: number
  role_score: number
  information: number
  cooperation: number
}

const SPEECH_ACTION_TYPES = new Set(['speech_order', 'speak', 'sheriff_speak'])
const VOTE_ACTION_TYPES = new Set(['exile_vote', 'pk_vote', 'vote', 'sheriff_vote'])
const SKILL_ACTION_TYPES = new Set([
  'kill',
  'werewolf_kill',
  'guard',
  'guard_protect',
  'inspect',
  'seer_check',
  'poison',
  'witch_act',
  'antidote',
  'shoot',
  'hunter_shoot'
])

function textLength(value: unknown): number {
  return String(value || '').length
}

function confidenceValue(value: unknown): number {
  return Number(value || 0.7)
}

export function buildAssessmentScores(source: AssessmentSource | null | undefined): AssessmentScore[] {
  if (!source) return []
  const players = source.players ?? []
  const decisions = source.decisions ?? []
  const allLogs = source.logs ?? []
  const scores = new Map<unknown, AssessmentScore>()
  players.forEach((player) => {
    scores.set(player.id, {
      player,
      speech: 20, vote: 20, skill: 15,
      logic: 50, team: 50,
      risk_penalty: 0, role_score: 0,
      // Legacy aliases
      information: 50, cooperation: 50,
    })
  })

  const speechByPlayer = new Map<unknown, AssessmentDecision[]>()
  decisions
    .filter((decision) => SPEECH_ACTION_TYPES.has(String(decision.action_type || '')))
    .forEach((decision) => {
      if (!speechByPlayer.has(decision.actor_id)) speechByPlayer.set(decision.actor_id, [])
      speechByPlayer.get(decision.actor_id)?.push(decision)
    })
  for (const [playerId, list] of speechByPlayer) {
    const score = scores.get(playerId)
    if (!score) continue
    const participation = Math.min(list.length * 10, 40)
    const totalLen = list.reduce((sum, decision) =>
      sum + (textLength(decision.reason) + textLength(decision.public_summary)), 0)
    const volume = Math.min(Math.floor(totalLen / 25) * 4, 45)
    const avgConf = list.reduce((sum, decision) => sum + confidenceValue(decision.confidence), 0) / list.length
    score.speech = Math.min(20 + participation + volume + Math.round(avgConf * 15), 100)
  }

  const allVotes = decisions.filter((decision) => VOTE_ACTION_TYPES.has(String(decision.action_type || '')))
  const dayNumbers = [...new Set(allLogs.filter((log) => log.day).map((log) => log.day))].sort((a, b) => Number(a) - Number(b))
  for (const day of dayNumbers) {
    const dayVotes = allVotes.filter((decision) => (decision.day || 1) === day)
    if (!dayVotes.length) continue
    const tally: Record<string, number> = {}
    dayVotes.forEach((vote) => {
      const target = String(vote.target_id || 'none')
      tally[target] = (tally[target] || 0) + 1
    })
    const consensus = Object.entries(tally).sort((a, b) => b[1] - a[1])[0]?.[0]
    for (const vote of dayVotes) {
      const score = scores.get(vote.actor_id)
      if (!score) continue
      score.vote += 8
      score.vote += vote.target_id === consensus ? 12 : 4
      score.vote += Math.round(confidenceValue(vote.confidence) * 6)
    }
  }
  for (const [, score] of scores) score.vote = Math.min(score.vote, 100)

  decisions
    .filter((decision) => SKILL_ACTION_TYPES.has(String(decision.action_type || '')))
    .forEach((action) => {
      const score = scores.get(action.actor_id)
      if (!score) return
      const confBonus = Math.round(confidenceValue(action.confidence) * 5)
      switch (action.action_type) {
        case 'kill':
        case 'werewolf_kill':
          score.skill += 18 + confBonus
          break
        case 'poison':
          score.skill += 16 + confBonus
          break
        case 'inspect':
        case 'seer_check':
          score.skill += 14 + confBonus
          break
        case 'shoot':
        case 'hunter_shoot':
          score.skill += 22 + confBonus
          break
        case 'guard':
        case 'guard_protect':
          score.skill += 10 + confBonus
          break
        case 'antidote':
        case 'witch_act':
          score.skill += 13 + confBonus
          break
        default:
          score.skill += 6 + confBonus
      }
    })
  for (const [, score] of scores) score.skill = Math.min(score.skill, 100)

  // --- information_score ---
  // Based on: seer check sharing (did they mention check results in speech?),
  // wolf coordination signals, general information contribution
  const infoSpeechKeywords = ['查验', '验了', '查杀', '金水', '好人', '狼人', '预言家', 'checked', 'seer', 'inspect']
  for (const [playerId, speeches] of speechByPlayer) {
    const score = scores.get(playerId)
    if (!score) continue
    const role = String(score.player.role || score.player.role_hint || '').toLowerCase()
    const isSeer = role.includes('seer') || role.includes('预言')
    const isWolf = role.includes('wolf') || role.includes('狼')
    for (const speech of speeches) {
      const text = `${speech.public_summary || ''} ${speech.reason || ''}`.toLowerCase()
      const mentionsInfo = infoSpeechKeywords.some((kw) => text.includes(kw.toLowerCase()))
      if (mentionsInfo) {
        score.information += isSeer ? 15 : 8
      }
      // Reward speech length as proxy for information sharing
      if (text.length > 100) score.information += 3
    }
  }
  // Bonus for performing inspection actions (seer checks)
  decisions
    .filter((d) => ['inspect', 'seer_check'].includes(String(d.action_type || '')))
    .forEach((d) => {
      const score = scores.get(d.actor_id)
      if (score) score.information += 10
    })
  for (const [, score] of scores) score.information = Math.min(Math.max(score.information, 0), 100)
  // Map to spec: logic_score = information_score
  for (const [, score] of scores) score.logic = score.information

  // --- cooperation_score → team_score ---
  // Based on: vote alignment with teammates, protective actions, team coordination
  for (const day of dayNumbers) {
    const dayVotes = allVotes.filter((d) => (d.day || 1) === day)
    if (!dayVotes.length) continue
    const tally: Record<string, number> = {}
    dayVotes.forEach((vote) => {
      const target = String(vote.target_id || 'none')
      tally[target] = (tally[target] || 0) + 1
    })
    const consensus = Object.entries(tally).sort((a, b) => b[1] - a[1])[0]?.[0]
    for (const vote of dayVotes) {
      const score = scores.get(vote.actor_id)
      if (!score) continue
      // Aligning with the majority shows cooperation
      score.cooperation += vote.target_id === consensus ? 8 : 2
    }
  }
  // Protective actions demonstrate teamwork
  decisions
    .filter((d) => ['guard', 'guard_protect', 'antidote'].includes(String(d.action_type || '')))
    .forEach((d) => {
      const score = scores.get(d.actor_id)
      if (score) score.cooperation += 12
    })
  // Sheriff speech participation shows engagement with group process
  decisions
    .filter((d) => String(d.action_type || '') === 'sheriff_speak')
    .forEach((d) => {
      const score = scores.get(d.actor_id)
      if (score) score.cooperation += 5
    })
  // Running for sheriff shows willingness to lead
  decisions
    .filter((d) => String(d.action_type || '') === 'sheriff_run' || String(d.action_type || '') === 'sheriff_elect')
    .forEach((d) => {
      const score = scores.get(d.actor_id)
      if (score) score.cooperation += 6
    })
  for (const [, score] of scores) score.cooperation = Math.min(Math.max(score.cooperation, 0), 100)
  // Map to spec: team_score = cooperation_score
  for (const [, score] of scores) score.team = score.cooperation

  // --- role_score (spec formula: weighted_base - risk_penalty) ---
  const weights = { speech: 0.25, vote: 0.25, skill: 0.20, logic: 0.20, team: 0.10 }
  for (const [, score] of scores) {
    const base = score.speech * weights.speech + score.vote * weights.vote + score.skill * weights.skill + score.logic * weights.logic + score.team * weights.team
    score.role_score = Math.max(0, Math.round(base - score.risk_penalty))
  }

  return [...scores.values()]
}
