import { computed, onBeforeUnmount, onMounted, ref, watch } from 'vue'
import type { Ref } from 'vue'
import type { Game, GameLog } from '../types/game'

const AUDIO_ENABLED_KEY = 'wolf-audio-enabled'
const TTS_ENABLED_KEY = 'wolf-tts-enabled'
const viteEnv = import.meta.env

type LooseRecord = Record<string, any>
type MaybeRef<T> = T | Ref<T>
type AudioEffect = keyof typeof AUDIO_LIBRARY.sfx
type AudioVariant = 'victory' | 'failure' | string

interface GameAudioRuntime {
  currentView: MaybeRef<string>
  game: MaybeRef<Game | null>
  isReplayMode: MaybeRef<boolean>
  externalStatus: MaybeRef<LooseRecord | null>
  apiBase: MaybeRef<string>
  roleAssignmentComplete: MaybeRef<boolean>
}

interface TtsItem {
  key: string
  text: string
  speaker: string
  seat: number | null
}

function envFlag(key: keyof ImportMetaEnv, fallback = false) {
  const value = viteEnv[key]
  if (value == null || value === '') return fallback
  return !['0', 'false', 'no', 'off'].includes(String(value).trim().toLowerCase())
}

function envNumber(key: keyof ImportMetaEnv, fallback: number, min: number, max: number) {
  const value = Number(viteEnv[key])
  if (!Number.isFinite(value)) return fallback
  return Math.max(min, Math.min(max, value))
}

const TTS_CONFIG = {
  enabled: envFlag('VITE_TTS_ENABLED', true),
  maxChars: Math.round(envNumber('VITE_TTS_MAX_CHARS', 140, 40, 180)),
  includeSpeaker: envFlag('VITE_TTS_INCLUDE_SPEAKER', false)
}

const AUDIO_LIBRARY = {
  bgm: {
    lobby: { label: '大厅', name: 'Mystery Dark', src: '' },
    match: { label: '对局', name: 'Dark Suspense Thriller', src: '' }
  },
  sfx: {
    night: { label: '天黑', src: '' },
    daybreak: { label: '天亮', src: '' },
    voteCountdown: { label: '投票倒计时', src: '' },
    death: { label: '出局', src: '' },
    settlement: { label: '结算', src: '' }
  }
}

const VOTE_PHASES = new Set(['vote', 'exile_vote', 'pk_vote', 'sheriff_vote'])
const SPEECH_PHASES = new Set(['speech', 'sheriff', 'pk_speak', 'last_word'])
const SPEECH_LOG_TYPES = new Set([
  'speech',
  'speak',
  'talk',
  'message',
  'chat',
  'statement',
  'discussion',
  'day_speech',
  'player_speech',
  'sheriff_speak',
  'sheriff_speech',
  'pk_speak',
  'pk_speech',
  'last_word'
])
const RESULT_PHASES = new Set(['ended', 'result', 'finished'])
const JUDGE_SPEAKERS = new Set(['法官', '系统'])
const SFX_HOLD_MS = {
  night: 1100,
  daybreak: 900,
  voteCountdown: 1100,
  death: 1200,
  settlement: 1600
}
const DEATH_LOG_TYPES = new Set([
  'death',
  'exile',
  'night_death_reveal',
  'hunter_shoot',
  'hunter_shot',
  'white_wolf_burst_kill',
  'white_wolf_burst_death',
  'white_wolf_explosion'
])

function valueOf<T>(item: MaybeRef<T>): T {
  return (item && typeof item === 'object' && 'value' in item ? (item as Ref<T>).value : item) as T
}

function hasWindow() {
  return typeof window !== 'undefined'
}

function readBooleanPreference(key: string, fallback = true) {
  if (!hasWindow()) return fallback
  const stored = window.localStorage.getItem(key)
  return stored == null ? fallback : stored === 'true'
}

function writeBooleanPreference(key: string, enabled: boolean) {
  if (hasWindow()) window.localStorage.setItem(key, String(Boolean(enabled)))
}

function aliveCount(game: Game | null | undefined) {
  const players = Array.isArray(game?.players) ? game.players : []
  if (!players.length) return null
  return players.filter((player) => player?.alive).length
}

function logType(log: Partial<GameLog> | LooseRecord | null | undefined) {
  return log?.type || log?.event_type || log?.action || log?.action_type || log?.kind || log?.category || ''
}

function lastDeathLogKey(game: Game | null | undefined) {
  const logs = Array.isArray(game?.logs) ? game.logs : []
  for (let index = logs.length - 1; index >= 0; index -= 1) {
    const log = logs[index]
    const type = logType(log)
    if (DEATH_LOG_TYPES.has(type)) {
      return `${log.sequence ?? index}:${type}:${log.actor_id ?? ''}:${log.target_id ?? log.target ?? ''}`
    }
  }
  return ''
}

function isVoteActive(game: Partial<Game> | null | undefined) {
  const phase = String(game?.phase || '')
  return game?.waiting_for === 'vote' || VOTE_PHASES.has(phase)
}

function settlementVariant(game: Game | null | undefined): AudioVariant {
  const winner = String(game?.winner || '').toLowerCase()
  const human = game?.players?.find((player) => player?.id === game?.human_player_id)
  if (!human) return 'victory'
  const team = String(human.team || human.role || human.role_hint || '').toLowerCase()
  const wolfWin = /wolf|were|狼人/.test(winner)
  const goodWin = /vill|good|town|human|村民|好人|平民/.test(winner)
  const humanWolf = /wolf|were|狼人/.test(team)
  const humanGood = /vill|good|town|human|村民|好人|平民/.test(team)
  if (wolfWin) return humanWolf ? 'victory' : 'failure'
  if (goodWin) return humanGood ? 'victory' : 'failure'
  return 'victory'
}

function isPublicPlayerSpeech(log: Partial<GameLog> | LooseRecord | null | undefined) {
  const type = logType(log)
  const speaker = String(log?.speaker || '')
  const visibility = String(log?.visibility || 'public')
  const hasPlayer = log?.actor_id != null || (speaker && !JUDGE_SPEAKERS.has(speaker))
  return SPEECH_LOG_TYPES.has(type)
    && hasPlayer
    && visibility !== 'private'
    && visibility !== 'god'
    && !JUDGE_SPEAKERS.has(speaker)
    && Boolean(cleanTtsText(log?.message))
}

function cleanTtsText(text: unknown) {
  return String(text || '')
    .replace(/[`*_#>{}[\]\\]/g, '')
    .replace(/\s+/g, ' ')
    .trim()
}

function clipTtsText(text: unknown) {
  const cleaned = cleanTtsText(text)
  if (cleaned.length <= TTS_CONFIG.maxChars) return cleaned
  return `${cleaned.slice(0, TTS_CONFIG.maxChars)}。`
}

function speechLogKey(log: Partial<GameLog> | LooseRecord | null | undefined, index: number) {
  return [
    log?.sequence ?? index,
    logType(log),
    log?.day ?? '',
    log?.phase ?? '',
    log?.actor_id ?? '',
    log?.speaker ?? '',
    cleanTtsText(log?.message)
  ].join('|')
}

function speechLogItems(game: Game | null | undefined) {
  const logs = Array.isArray(game?.logs) ? game.logs : []
  return logs
    .map((log, index) => ({ log, index, key: speechLogKey(log, index) }))
    .filter(({ log }) => isPublicPlayerSpeech(log))
}

function buildTtsText(log: Partial<GameLog> | LooseRecord) {
  const message = clipTtsText(log?.message)
  if (!TTS_CONFIG.includeSpeaker) return message
  const speaker = cleanTtsText(log?.speaker || (log?.actor_id ? `${log.actor_id}号` : ''))
  return speaker ? `${speaker}发言。${message}` : message
}

export function useGameAudio(runtime: GameAudioRuntime, options: { installLifecycle?: boolean } = {}) {
  const audioEnabled = ref(readBooleanPreference(AUDIO_ENABLED_KEY, true))
  const ttsEnabled = ref(readBooleanPreference(TTS_ENABLED_KEY, TTS_CONFIG.enabled))
  const audioUnlocked = ref(false)
  const ttsSpeaking = ref(false)
  let audioContext: AudioContext | null = null
  let bgmAudio: HTMLAudioElement | null = null
  let currentBgmKey = ''
  let activeTtsStreamSources = new Set<AudioBufferSourceNode>()
  let activeTtsGain: GainNode | null = null
  let activeTtsController: AbortController | null = null
  let activeTtsKey = ''
  let ttsRunId = 0
  let ttsQueue: TtsItem[] = []
  let ttsQueuedKeys = new Set<string>()
  let ttsSeenGameId = ''
  let ttsSeenKeys = new Set<string>()
  let ttsDelayTimer = 0

  const currentView = computed(() => valueOf(runtime.currentView))
  const game = computed(() => valueOf(runtime.game))
  const isReplayMode = computed(() => Boolean(valueOf(runtime.isReplayMode)))
  const externalStatus = computed(() => valueOf(runtime.externalStatus))
  const apiBase = computed(() => String(valueOf(runtime.apiBase) || '/api').replace(/\/$/, ''))
  const ttsAvailable = computed(() => TTS_CONFIG.enabled && externalStatus.value?.tts === 'configured')
  const audioRuntimeActive = computed(() => currentView.value === 'match')
  const bgmKey = computed(() => {
    if (currentView.value === 'lobby') return 'lobby'
    if (currentView.value === 'match') return 'match'
    return ''
  })
  const roleAssignmentComplete = computed(() => Boolean(valueOf(runtime.roleAssignmentComplete)))
  const bgmHoldActive = ref(false)
  let bgmHoldTimer = 0
  const bgmPauseReason = computed(() => {
    if (!audioEnabled.value) return '已静音'
    if (!bgmKey.value) return '离开场景'
    if (currentView.value !== 'match') return ''
    const currentGame = game.value
    if (!currentGame) return '准备'
    if (!roleAssignmentComplete.value && !isReplayMode.value) return '准备'
    if (isReplayMode.value) return '回放'
    if (currentGame.winner) return '结算'
    if (ttsSpeaking.value) return '发言'
    if (bgmHoldActive.value) return '音效'
    if (currentGame.waiting_for === 'speech' || SPEECH_PHASES.has(String(currentGame.phase || ''))) return '发言'
    if (isVoteActive(currentGame)) return '投票'
    if (RESULT_PHASES.has(String(currentGame.phase || ''))) return '结算'
    return ''
  })
  const audioSceneLabel = computed(() => {
    if (!audioEnabled.value) return '已静音'
    if (bgmPauseReason.value && bgmPauseReason.value !== '离开场景') return '短音效'
    return AUDIO_LIBRARY.bgm[bgmKey.value]?.label || '音效'
  })

  function canPlayTts() {
    return Boolean(
      ttsAvailable.value
      && ttsEnabled.value
      && audioRuntimeActive.value
      && !isReplayMode.value
      && !game.value?.winner
    )
  }

  function clearTtsDelayTimer() {
    if (!ttsDelayTimer) return
    if (hasWindow()) window.clearTimeout(ttsDelayTimer)
    ttsDelayTimer = 0
  }

  function scheduleNextTts(delay = 100) {
    if (!hasWindow()) return
    clearTtsDelayTimer()
    ttsDelayTimer = window.setTimeout(() => {
      ttsDelayTimer = 0
      void playNextTts()
    }, delay)
  }

  function stopTts({ clearQueue = true }: { clearQueue?: boolean } = {}) {
    clearTtsDelayTimer()
    ttsRunId += 1
    activeTtsKey = ''
    if (clearQueue) {
      ttsQueue = []
      ttsQueuedKeys = new Set()
    }
    activeTtsController?.abort?.()
    activeTtsController = null
    if (activeTtsStreamSources.size) {
      const sources = activeTtsStreamSources
      activeTtsStreamSources = new Set()
      for (const source of sources) {
        source.onended = null
        try {
          source.stop()
        } catch {}
        source.disconnect?.()
      }
    }
    if (activeTtsGain) {
      activeTtsGain.disconnect?.()
      activeTtsGain = null
    }
    ttsSpeaking.value = false
    void syncBgm()
  }

  function finishTtsStream(gain: GainNode, { continueQueue = true }: { continueQueue?: boolean } = {}) {
    if (activeTtsGain !== gain) return
    for (const source of activeTtsStreamSources) {
      source.disconnect?.()
    }
    activeTtsStreamSources = new Set()
    activeTtsGain = null
    activeTtsController = null
    activeTtsKey = ''
    gain?.disconnect?.()
    ttsSpeaking.value = false
    void syncBgm()
    if (continueQueue) scheduleNextTts(100)
  }

  function ttsRequestBody(item: TtsItem) {
    return JSON.stringify({
      text: item.text,
      speaker: item.speaker || '',
      seat: item.seat || null
    })
  }

  async function requestTtsStream(item: TtsItem, signal: AbortSignal) {
    return fetch(`${apiBase.value}/tts/speech/stream`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: ttsRequestBody(item),
      signal
    })
  }

  function concatBytes(left: Uint8Array, right: Uint8Array) {
    if (!left?.length) return right
    if (!right?.length) return left
    const combined = new Uint8Array(left.length + right.length)
    combined.set(left, 0)
    combined.set(right, left.length)
    return combined
  }

  function schedulePcmChunk(
    context: AudioContext,
    gain: GainNode,
    bytes: Uint8Array,
    sampleRate: number,
    nextStartRef: { value: number },
    runId: number,
    streamDoneRef: { done: boolean }
  ) {
    if (runId !== ttsRunId || !bytes?.length) return
    const frameCount = Math.floor(bytes.length / 2)
    if (!frameCount) return
    const buffer = context.createBuffer(1, frameCount, sampleRate)
    const channel = buffer.getChannelData(0)
    const view = new DataView(bytes.buffer, bytes.byteOffset, frameCount * 2)
    for (let index = 0; index < frameCount; index += 1) {
      channel[index] = Math.max(-1, Math.min(1, view.getInt16(index * 2, true) / 32768))
    }

    const source = context.createBufferSource()
    source.buffer = buffer
    source.connect(gain)
    activeTtsStreamSources.add(source)
    source.onended = () => {
      activeTtsStreamSources.delete(source)
      source.disconnect?.()
      if (streamDoneRef.done && activeTtsStreamSources.size === 0) finishTtsStream(gain)
    }
    if (!ttsSpeaking.value) {
      ttsSpeaking.value = true
      void syncBgm()
    }
    const startAt = Math.max(nextStartRef.value, context.currentTime + 0.01)
    source.start(startAt)
    nextStartRef.value = startAt + buffer.duration
  }

  async function playTtsStream(item: TtsItem, controller: AbortController, runId: number) {
    const context = ensureAudioContext()
    if (!context) throw new Error('浏览器不支持流式音频播放')
    if (context.state === 'suspended') await context.resume()
    if (context.state !== 'running') throw new Error('音频上下文未解锁')

    const response = await requestTtsStream(item, controller.signal)
    if (!response.ok || !response.body?.getReader) throw new Error('流式发言朗读不可用')
    const sampleRate = Number(response.headers?.get?.('X-TTS-Sample-Rate')) || 24000
    const reader = response.body.getReader()
    const gain = context.createGain()
    const nextStartRef = { value: context.currentTime + 0.04 }
    const streamDoneRef = { done: false }
    let pending = new Uint8Array(0)
    let scheduled = false

    gain.gain.value = 0.88
    gain.connect(context.destination)
    activeTtsGain = gain

    try {
      while (runId === ttsRunId && !controller.signal.aborted) {
        const { done, value } = await reader.read()
        if (done) break
        const chunk = concatBytes(pending, value instanceof Uint8Array ? value : new Uint8Array(value || []))
        const evenLength = chunk.length - (chunk.length % 2)
        pending = evenLength === chunk.length ? new Uint8Array(0) : chunk.slice(evenLength)
        if (evenLength > 0) {
          schedulePcmChunk(context, gain, chunk.slice(0, evenLength), sampleRate, nextStartRef, runId, streamDoneRef)
          scheduled = true
        }
      }
      if (runId !== ttsRunId || controller.signal.aborted) return true
      if (pending.length > 1) {
        schedulePcmChunk(context, gain, pending, sampleRate, nextStartRef, runId, streamDoneRef)
        scheduled = true
      }
      streamDoneRef.done = true
      if (!scheduled || activeTtsStreamSources.size === 0) finishTtsStream(gain)
      return true
    } catch (error) {
      if (activeTtsGain === gain) {
        for (const source of activeTtsStreamSources) {
          source.onended = null
          try {
            source.stop()
          } catch {}
          source.disconnect?.()
        }
        activeTtsStreamSources = new Set()
        activeTtsGain = null
        gain.disconnect?.()
      }
      throw error
    } finally {
      reader.releaseLock?.()
    }
  }

  async function playNextTts() {
    if (activeTtsStreamSources.size || activeTtsController || ttsSpeaking.value) return
    if (!canPlayTts()) {
      stopTts()
      return
    }
    const next = ttsQueue.shift()
    if (!next) return
    if (next.key) ttsQueuedKeys.delete(next.key)

    const controller = new AbortController()
    const runId = ttsRunId + 1
    ttsRunId = runId
    activeTtsKey = next.key || ''
    activeTtsController = controller
    try {
      if (!audioUnlocked.value) await unlockAudio()
      await playTtsStream(next, controller, runId)
    } catch {
      if (runId !== ttsRunId) return
      stopTts({ clearQueue: false })
      scheduleNextTts(120)
    }
  }

  function enqueueTts(logs: Array<Partial<GameLog> | LooseRecord>) {
    const item = logs
      .map((log) => ({
        key: speechLogKey(log, 0),
        text: buildTtsText(log),
        speaker: cleanTtsText(log?.speaker || (log?.actor_id ? `${log.actor_id}号` : '')),
        seat: Number(log?.actor_id || log?.seat || 0) || null
      }))
      .filter((item) => item.text && !ttsQueuedKeys.has(item.key))
      .at(-1)
    if (!item || activeTtsKey === item.key) return
    if (activeTtsKey || activeTtsStreamSources.size || activeTtsController || ttsSpeaking.value) {
      stopTts({ clearQueue: true })
    }
    ttsQueuedKeys = new Set([item.key])
    ttsQueue = [item]
    playNextTts()
  }

  function enqueueLatestTts({ includeSeen = false }: { includeSeen?: boolean } = {}) {
    const items = speechLogItems(game.value)
    for (let index = items.length - 1; index >= 0; index -= 1) {
      const item = items[index]
      if (!includeSeen && ttsSeenKeys.has(item.key)) continue
      ttsSeenKeys.add(item.key)
      enqueueTts([item.log])
      return true
    }
    return false
  }

  function ensureAudioContext() {
    if (!hasWindow()) return null
    if (!audioContext) {
      const AudioContextCtor = window.AudioContext || (window as typeof window & { webkitAudioContext?: typeof AudioContext }).webkitAudioContext
      if (!AudioContextCtor) return null
      audioContext = new AudioContextCtor()
    }
    return audioContext
  }

  async function unlockAudio() {
    const context = ensureAudioContext()
    if (!context) return false
    try {
      if (context.state === 'suspended') await context.resume()
      audioUnlocked.value = context.state === 'running'
      return audioUnlocked.value
    } catch {
      audioUnlocked.value = false
      return false
    }
  }

  function stopBgm() {
    if (!bgmAudio) return
    bgmAudio.pause()
    bgmAudio.currentTime = 0
    bgmAudio = null
    currentBgmKey = ''
  }

  function pauseBgm() {
    if (bgmAudio && !bgmAudio.paused) bgmAudio.pause()
  }

  async function syncBgm() {
    const nextKey = bgmKey.value
    const track = AUDIO_LIBRARY.bgm[nextKey]
    if (!audioEnabled.value || !track?.src) {
      stopBgm()
      return
    }
    await unlockAudio()
    if (currentBgmKey !== nextKey || !bgmAudio) {
      stopBgm()
      const audio = new Audio(track.src)
      audio.loop = true
      audio.volume = 0.36
      bgmAudio = audio
      currentBgmKey = nextKey
    }
    if (bgmPauseReason.value) {
      pauseBgm()
      return
    }
    if (bgmAudio.paused) bgmAudio.play().catch(() => null)
  }

  function holdBgm(effect: AudioEffect) {
    const duration = SFX_HOLD_MS[effect] || 900
    if (bgmHoldTimer) window.clearTimeout(bgmHoldTimer)
    bgmHoldActive.value = true
    void syncBgm()
    bgmHoldTimer = window.setTimeout(() => {
      bgmHoldActive.value = false
      bgmHoldTimer = 0
      void syncBgm()
    }, duration)
  }

  function scheduleTone(context: AudioContext, {
    start = 0,
    duration = 0.2,
    frequency = 440,
    endFrequency = null,
    type = 'sine',
    gain = 0.05
  }: {
    start?: number
    duration?: number
    frequency?: number
    endFrequency?: number | null
    type?: OscillatorType
    gain?: number
  }) {
    const now = context.currentTime + start
    const oscillator = context.createOscillator()
    const envelope = context.createGain()
    oscillator.type = type
    oscillator.frequency.setValueAtTime(Math.max(1, frequency), now)
    if (endFrequency) {
      oscillator.frequency.exponentialRampToValueAtTime(Math.max(1, endFrequency), now + duration)
    }
    envelope.gain.setValueAtTime(0.0001, now)
    envelope.gain.exponentialRampToValueAtTime(Math.max(0.0002, gain), now + 0.025)
    envelope.gain.exponentialRampToValueAtTime(0.0001, now + duration)
    oscillator.connect(envelope)
    envelope.connect(context.destination)
    oscillator.start(now)
    oscillator.stop(now + duration + 0.04)
  }

  function playSynthEffect(effect: AudioEffect, variant: AudioVariant = 'victory') {
    const context = ensureAudioContext()
    if (!context || context.state !== 'running') return
    if (effect === 'night') {
      scheduleTone(context, { duration: 0.72, frequency: 146, endFrequency: 82, type: 'sawtooth', gain: 0.045 })
      scheduleTone(context, { start: 0.08, duration: 0.82, frequency: 58, endFrequency: 46, type: 'sine', gain: 0.075 })
      return
    }
    if (effect === 'daybreak') {
      ;[523, 659, 784].forEach((frequency, index) => {
        scheduleTone(context, { start: index * 0.13, duration: 0.2, frequency, type: 'triangle', gain: 0.055 })
      })
      return
    }
    if (effect === 'voteCountdown') {
      ;[940, 940, 940, 620].forEach((frequency, index) => {
        scheduleTone(context, { start: index * 0.18, duration: 0.055, frequency, type: 'square', gain: 0.05 })
      })
      return
    }
    if (effect === 'death') {
      scheduleTone(context, { duration: 0.48, frequency: 116, endFrequency: 42, type: 'sine', gain: 0.12 })
      scheduleTone(context, { start: 0.03, duration: 0.28, frequency: 62, endFrequency: 38, type: 'triangle', gain: 0.08 })
      return
    }
    if (effect === 'settlement') {
      const notes = variant === 'failure' ? [330, 262, 196] : [392, 523, 659, 784]
      notes.forEach((frequency, index) => {
        scheduleTone(context, {
          start: index * 0.14,
          duration: variant === 'failure' ? 0.28 : 0.24,
          frequency,
          type: variant === 'failure' ? 'sawtooth' : 'triangle',
          gain: variant === 'failure' ? 0.04 : 0.055
        })
      })
    }
  }

  async function playAudioEffect(effect: AudioEffect, variant?: AudioVariant) {
    if (!audioRuntimeActive.value || !audioEnabled.value || isReplayMode.value) return
    const entry = AUDIO_LIBRARY.sfx[effect]
    if (!entry) return
    const unlocked = await unlockAudio()
    if (!unlocked) return
    holdBgm(effect)
    if (entry.src) {
      const audio = new Audio(entry.src)
      audio.volume = 0.68
      audio.play().catch(() => playSynthEffect(effect, variant))
      return
    }
    playSynthEffect(effect, variant)
  }

  function toggleAudio() {
    audioEnabled.value = !audioEnabled.value
    writeBooleanPreference(AUDIO_ENABLED_KEY, audioEnabled.value)
    if (!audioEnabled.value) {
      stopBgm()
      return
    }
    void unlockAudio().then(() => {
      void syncBgm()
      void playAudioEffect('daybreak')
    })
  }

  function toggleTts() {
    if (!ttsAvailable.value) return
    ttsEnabled.value = !ttsEnabled.value
    writeBooleanPreference(TTS_ENABLED_KEY, ttsEnabled.value)
    if (!ttsEnabled.value) {
      stopTts()
      return
    }
    void unlockAudio().then(() => {
      enqueueLatestTts({ includeSeen: true })
      playNextTts()
    })
  }

  function handleGestureUnlock() {
    const track = AUDIO_LIBRARY.bgm[bgmKey.value]
    if ((audioEnabled.value && track?.src) || canPlayTts()) void unlockAudio().then(syncBgm)
  }

  function dispose() {
    if (hasWindow()) {
      window.removeEventListener('pointerdown', handleGestureUnlock)
      window.removeEventListener('keydown', handleGestureUnlock)
    }
    stopBgm()
    stopTts()
    if (bgmHoldTimer) {
      window.clearTimeout(bgmHoldTimer)
      bgmHoldTimer = 0
    }
    if (audioContext) {
      audioContext.close?.()
      audioContext = null
    }
  }

  watch([audioEnabled, bgmKey, bgmPauseReason], syncBgm)

  watch([ttsEnabled, ttsAvailable, currentView, isReplayMode, () => game.value?.winner], () => {
    if (!canPlayTts()) stopTts()
    else playNextTts()
  })

  watch(
    () => {
      if (!audioRuntimeActive.value || isReplayMode.value) {
        return { gameId: '', keys: '' }
      }
      const currentGame = game.value
      return {
        gameId: currentGame?.game_id || '',
        keys: speechLogItems(currentGame).map((item) => item.key).join('\n')
      }
    },
    (current) => {
      if (!audioRuntimeActive.value || isReplayMode.value) {
        ttsSeenGameId = ''
        ttsSeenKeys = new Set()
        ttsQueuedKeys = new Set()
        stopTts()
        return
      }
      const currentGame = game.value
      const items = speechLogItems(currentGame)
      if (!current.gameId) {
        ttsSeenGameId = ''
        ttsSeenKeys = new Set()
        ttsQueuedKeys = new Set()
        stopTts()
        return
      }
      if (current.gameId !== ttsSeenGameId) {
        ttsSeenGameId = current.gameId
        ttsSeenKeys = new Set(items.map((item) => item.key))
        ttsQueuedKeys = new Set()
        stopTts()
        return
      }
      const fresh = []
      for (const item of items) {
        if (ttsSeenKeys.has(item.key)) continue
        ttsSeenKeys.add(item.key)
        fresh.push(item.log)
      }
      if (fresh.length && canPlayTts()) enqueueTts(fresh)
    },
    { flush: 'post' }
  )

  watch(
    () => {
      if (!audioRuntimeActive.value) {
        return {
          gameId: '',
          phase: '',
          waitingFor: '',
          winner: '',
          aliveCount: null,
          deathLogKey: '',
          logCount: 0
        }
      }
      const currentGame = game.value
      return {
        gameId: currentGame?.game_id || '',
        phase: currentGame?.phase || '',
        waitingFor: currentGame?.waiting_for || '',
        winner: currentGame?.winner || '',
        aliveCount: aliveCount(currentGame),
        deathLogKey: lastDeathLogKey(currentGame),
        logCount: Array.isArray(currentGame?.logs) ? currentGame.logs.length : 0
      }
    },
    (current, previous) => {
      if (!current.gameId || !previous || current.gameId !== previous.gameId) return
      if (!audioRuntimeActive.value) return
      if (isReplayMode.value) return
      if (current.phase === 'night' && previous.phase !== 'night') void playAudioEffect('night')
      if (previous.phase === 'night' && current.phase && current.phase !== 'night' && !current.winner) void playAudioEffect('daybreak')
      if (isVoteActive({ phase: current.phase, waiting_for: current.waitingFor }) && !isVoteActive({ phase: previous.phase, waiting_for: previous.waitingFor })) {
        void playAudioEffect('voteCountdown')
      }
      if (
        current.aliveCount != null
        && previous.aliveCount != null
        && current.aliveCount < previous.aliveCount
      ) {
        void playAudioEffect('death')
      } else if (current.logCount > previous.logCount && current.deathLogKey && current.deathLogKey !== previous.deathLogKey) {
        void playAudioEffect('death')
      }
      if (current.winner && !previous.winner) void playAudioEffect('settlement', settlementVariant(game.value))
    },
    { flush: 'post' }
  )

  if (options.installLifecycle !== false) {
    onMounted(() => {
      if (!hasWindow()) return
      window.addEventListener('pointerdown', handleGestureUnlock, { once: true, passive: true })
      window.addEventListener('keydown', handleGestureUnlock, { once: true })
    })

    onBeforeUnmount(dispose)
  }

  return {
    audioEnabled,
    ttsEnabled,
    ttsAvailable,
    ttsSpeaking,
    audioUnlocked,
    audioSceneLabel,
    bgmPauseReason,
    toggleAudio,
    toggleTts,
    playAudioEffect,
    dispose
  }
}

export { AUDIO_LIBRARY }
