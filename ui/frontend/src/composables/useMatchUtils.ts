import { computed } from 'vue'
import { normalizeHistoryDisplayText } from '../components/history/historyDisplay.ts'

const roleIconSpecs = [
  { key: 'whiteWolfKing', role: '白狼王', tokens: ['白狼王'], image: '/role-badges/white-wolf-king.png' },
  { key: 'werewolf', role: '狼人', tokens: ['狼人'], image: '/role-badges/werewolf.png' },
  { key: 'villager', role: '村民', tokens: ['村民'], image: '/role-badges/villager.png' },
  { key: 'seer', role: '预言家', tokens: ['预言'], image: '/role-badges/seer.png' },
  { key: 'witch', role: '女巫', tokens: ['女巫'], image: '/role-badges/witch.png' },
  { key: 'hunter', role: '猎人', tokens: ['猎人'], image: '/role-badges/hunter.png' },
  { key: 'guard', role: '守卫', tokens: ['守卫'], image: '/role-badges/guard.png' }
]

function roleMatches(role = '', tokens = []) {
  return tokens.some((token) => role.includes(token))
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

function useMatchUtils(state) {
  const visualSeatById = computed(() =>
    new Map((state.visualSeatPlayers?.value ?? []).map((player, index) => [player.id, index + 1]))
  )

  function playerNumber(player) {
    if (!player) return ''
    return visualSeatById.value.get(player.id) || player.seat || player.id
  }

  function playerNumberById(id) {
    const player = state.game?.value?.players?.find((item) => item.id === id)
    return player ? playerNumber(player) : id
  }

  function playerLabel(player) {
    const number = playerNumber(player)
    return number ? `${number}号` : ''
  }

  let normRegexCache = []
  let normRegexSig = ''

  function buildNormRegexCache(players) {
    const sig = `${state.isWatch?.value}:${state.backendMode?.value}:${state.visualSeatSalt?.value}:` +
      players.map((p) => `${p.id}:${p.seat}:${p.name}`).join('|')
    if (sig === normRegexSig) return
    normRegexSig = sig
    const sorted = [...players].sort((a, b) => String(b.name || '').length - String(a.name || '').length)
    normRegexCache = sorted.map((player) => {
      const visual = playerLabel(player)
      if (!visual) return null
      const escapedName = String(player.name || '').replace(/[.*+?^${}()|[\]\\]/g, '\\$&')
      return {
        visual,
        seatNameSp: `${player.seat}号 ${player.name}`,
        seatName: `${player.seat}号${player.name}`,
        nameRe: escapedName ? new RegExp(escapedName, 'g') : null,
        seatRe: new RegExp(`${player.seat}\\s*号`, 'g')
      }
    }).filter(Boolean)
  }

  function normalizePlayerText(text = '') {
    let value = String(text || '')
    const players = state.game?.value?.players ?? []
    if (players.length) {
      buildNormRegexCache(players)
      for (const entry of normRegexCache) {
        value = value.replaceAll(entry.seatNameSp, entry.visual)
        value = value.replaceAll(entry.seatName, entry.visual)
        if (entry.nameRe) value = value.replace(entry.nameRe, entry.visual)
        value = value.replace(entry.seatRe, entry.visual)
      }
    }
    return normalizeHistoryDisplayText(value)
  }

  function logSpeaker(log) {
    const player = state.game?.value?.players?.find((item) => item.id === log?.actor_id || item.name === log?.speaker)
    if (!player) return normalizePlayerText(log?.speaker || '')
    const roleSuffix = String(log?.speaker || '').replace(new RegExp(`^${player.seat}\\s*号`), '')
    return roleSuffix && roleSuffix !== player.name ? `${playerLabel(player)}${roleSuffix}` : playerLabel(player)
  }

  function logMessage(log) {
    return normalizePlayerText(log?.message || '')
  }

  function cardImage(player) {
    if (!state.isWatch?.value && player && !player.is_human && !player.role_visible) return '/cards/card-back.png'
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
    if (hint.includes('预言')) return '/role-icons/optimized/预言家.webp'
    if (hint.includes('女巫')) return '/role-icons/optimized/女巫.webp'
    if (hint.includes('猎人')) return '/role-icons/optimized/猎人.webp'
    if (hint.includes('守卫')) return '/role-icons/optimized/守卫.webp'
    if (hint.includes('白狼王')) return '/role-icons/optimized/白狼王.webp'
    if (hint.includes('狼人')) return '/role-icons/optimized/普通狼.webp'
    return '/role-icons/optimized/平民.webp'
  }

  function speakerImage(player) {
    return player ? cardImage(player) : '/livehall-assets/props/judge-avatar.png'
  }

  return {
    roleIconSpecs,
    roleMatches,
    visualSeatById,
    playerNumber,
    playerNumberById,
    playerLabel,
    normalizePlayerText,
    logSpeaker,
    logMessage,
    squareSeatStyle,
    cardImage,
    roleIconImage,
    speakerImage
  }
}

export { roleIconSpecs, roleMatches, squareSeatStyle, useMatchUtils }
