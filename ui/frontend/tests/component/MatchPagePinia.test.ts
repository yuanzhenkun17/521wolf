// @vitest-environment jsdom

import { flushPromises, mount } from '@vue/test-utils'
import { createPinia, setActivePinia } from 'pinia'
import { describe, expect, it, vi } from 'vitest'

import { useGameStore, useReplayStore, useSessionStore, useUiStore } from '../../src/stores'
import type { Game } from '../../src/types/game'

vi.mock('../../src/components/MobileTaskShell.vue', () => ({
  default: {
    name: 'MobileTaskShell',
    template: '<section class="mobile-task-shell-stub"><slot /></section>',
  },
}))

vi.mock('../../src/components/CouncilScene.vue', () => ({
  default: {
    name: 'CouncilScene',
    props: ['game', 'isNight', 'isWatch', 'isReplayMode', 'roleAssignmentComplete', 'judgeBoardStarted', 'players', 'speakerMessage', 'voteTally', 'sceneEffects', 'deferModelLoading'],
    emits: ['ready', 'loading-progress'],
    setup(_props, { emit }) {
      function emitReady() {
        emit('ready', (globalThis as any).__matchSceneApi || {})
      }
      function emitLoaded() {
        emit('loading-progress', { label: '议事厅就绪', progress: 1, ready: true })
      }
      return { emitReady, emitLoaded }
    },
    template: `
      <section class="council-scene-stub" :data-game-id="game?.game_id" :data-night="String(isNight)" :data-watch="String(isWatch)" :data-replay="String(isReplayMode)" :data-role-ready="String(roleAssignmentComplete)" :data-judge-started="String(judgeBoardStarted)" :data-player-count="String(players.length)" :data-speaker-message="speakerMessage" :data-vote-count="String(voteTally.length)" :data-effect-count="String(sceneEffects.length)" :data-defer="String(deferModelLoading)">
        <button class="emit-ready" @click="emitReady" />
        <button class="emit-loaded" @click="emitLoaded" />
      </section>
    `,
  },
}))

vi.mock('../../src/components/MatchControlStrip.vue', () => ({
  default: {
    name: 'MatchControlStrip',
    props: ['game', 'loading', 'backendMode', 'isNight', 'isReplayMode', 'watchRunning', 'promptText', 'judgeStripMessage', 'judgeBoardStarted', 'judgeBoardStarting'],
    template: '<section class="match-control-stub" :data-game-id="game?.game_id" :data-loading="String(loading)" :data-backend-mode="backendMode" :data-night="String(isNight)" :data-replay="String(isReplayMode)" :data-watch="String(watchRunning)" :data-prompt="promptText" :data-judge-count="String(judgeStripMessage.length)" :data-judge-started="String(judgeBoardStarted)" :data-judge-starting="String(judgeBoardStarting)" />',
  },
}))

vi.mock('../../src/components/ReplayControls.vue', () => ({
  default: {
    name: 'ReplayControls',
    props: ['isReplayMode', 'cursor', 'total', 'playing', 'speed', 'eventLabel'],
    template: '<section class="replay-controls-stub" :data-replay="String(isReplayMode)" :data-cursor="String(cursor)" :data-total="String(total)" :data-playing="String(playing)" :data-speed="String(speed)" :data-event-label="eventLabel" />',
  },
}))

vi.mock('../../src/components/ActionPanel.vue', () => ({
  default: {
    name: 'ActionPanel',
    props: [
      'humanPlayer',
      'roleName',
      'skillState',
      'isHumanWitch',
      'isHumanWhiteWolf',
      'canUseWitchAntidote',
      'canUseWitchPoison',
      'canWhiteWolfBurst',
      'pendingActionType',
      'pendingChoiceOptions',
      'actionInstruction',
      'speechCountdownText',
      'canVotePlayers',
      'actionCandidates',
      'whiteWolfTargets',
      'needsTarget',
      'speech',
      'witchChoice',
      'actionChoice',
      'burstArmed',
      'actionTarget',
    ],
    emits: ['update:speech', 'update:witchChoice', 'update:actionChoice', 'update:burstArmed', 'update:actionTarget'],
    template: `
      <section
        class="action-panel-stub"
        :data-human-id="String(humanPlayer?.id || '')"
        :data-role-name="roleName"
        :data-witch="String(isHumanWitch)"
        :data-action-type="pendingActionType"
        :data-choice-count="String(pendingChoiceOptions.length)"
        :data-action-instruction="actionInstruction"
        :data-countdown="speechCountdownText"
        :data-can-vote-count="String(canVotePlayers.length)"
        :data-candidate-count="String(actionCandidates.length)"
        :data-white-wolf-count="String(whiteWolfTargets.length)"
        :data-needs-target="String(needsTarget)"
        :data-speech="speech"
        :data-witch-choice="witchChoice"
        :data-action-choice="actionChoice"
        :data-burst-armed="String(burstArmed)"
        :data-action-target="String(actionTarget ?? '')"
      >
        <button class="set-speech" @click="$emit('update:speech', 'updated speech')" />
        <button class="set-witch" @click="$emit('update:witchChoice', 'antidote')" />
        <button class="set-action-choice" @click="$emit('update:actionChoice', 'skip')" />
        <button class="set-burst" @click="$emit('update:burstArmed', false)" />
        <button class="set-target" @click="$emit('update:actionTarget', 3)" />
      </section>
    `,
  },
}))
vi.mock('../../src/components/ApiErrorPanel.vue', () => ({ default: { name: 'ApiErrorPanel', template: '<section class="api-error-panel-stub" />' } }))
vi.mock('../../src/components/ChatLog.vue', () => ({
  default: {
    name: 'ChatLog',
    props: ['logs'],
    template: '<section class="chat-log-stub" :data-log-count="String(logs.length)" />',
  },
}))
vi.mock('../../src/components/GameOverBoard.vue', () => ({ default: { name: 'GameOverBoard', template: '<section class="game-over-stub" />' } }))
vi.mock('../../src/components/PlayerCarousel.vue', () => ({
  default: {
    name: 'PlayerCarousel',
    props: ['carousel', 'message'],
    template: '<section class="player-carousel-stub" :data-carousel-count="String(carousel.length)" :data-message="message" />',
  },
}))
vi.mock('../../src/components/PlayerIdentityBoard.vue', () => ({
  default: {
    name: 'PlayerIdentityBoard',
    props: ['players'],
    template: '<section class="player-identity-stub" :data-player-count="String(players.length)" />',
  },
}))

import MatchPage from '../../src/pages/MatchPage.vue'

function gameFixture(gameId: string, overrides: Partial<Game> = {}): Game {
  return {
    game_id: gameId,
    mode: 'watch',
    status: 'running',
    phase: 'night',
    day: 2,
    player_count: 0,
    players: [],
    logs: [],
    decisions: [],
    waiting_for: 'none',
    pending_action: null,
    skill_state: {},
    ...overrides,
  }
}

function createDeferred<T = void>() {
  let resolve!: (value: T | PromiseLike<T>) => void
  let reject!: (reason?: unknown) => void
  const promise = new Promise<T>((resolvePromise, rejectPromise) => {
    resolve = resolvePromise
    reject = rejectPromise
  })
  return { promise, resolve, reject }
}

function mountMatchPage(props = {}, setupStores: () => void) {
  const pinia = createPinia()
  setActivePinia(pinia)
  setupStores()

  return mount(MatchPage, {
    props,
    global: {
      plugins: [pinia],
    },
  })
}

describe('MatchPage Pinia fallback', () => {
  it('keeps the intro overlay until council models finish warming', async () => {
    vi.useFakeTimers()
    const modelReady = createDeferred()
    let waitForModels = 0
    let syncScene = 0
    ;(globalThis as any).__matchSceneApi = {
      waitForCouncilModels() {
        waitForModels += 1
        return modelReady.promise
      },
      scheduleSyncCouncilScene() {
        syncScene += 1
      },
    }
    let wrapper: ReturnType<typeof mountMatchPage> | null = null

    try {
      wrapper = mountMatchPage(
        {
          game: gameFixture('intro-game', {
            players: [
              { id: 1, seat: 1, name: '1号', role_hint: '村民', alive: true, is_human: false, is_sheriff: false },
              { id: 2, seat: 2, name: '2号', role_hint: '狼人', alive: true, is_human: false, is_sheriff: false },
            ],
          }),
          roleAssignmentComplete: true,
          judgeBoardStarted: true,
        },
        () => {}
      )

      await wrapper.find('.emit-ready').trigger('click')
      await flushPromises()

      expect(waitForModels).toBe(1)
      expect(wrapper.find('.match-intro-overlay').exists()).toBe(true)

      await vi.advanceTimersByTimeAsync(5000)
      await flushPromises()
      expect(wrapper.find('.match-intro-overlay').exists()).toBe(true)

      modelReady.resolve()
      await flushPromises()
      expect(syncScene).toBeGreaterThan(0)

      await vi.advanceTimersByTimeAsync(2500)
      await flushPromises()
      expect(wrapper.find('.match-intro-overlay').exists()).toBe(false)
    } finally {
      wrapper?.unmount()
      delete (globalThis as any).__matchSceneApi
      vi.useRealTimers()
    }
  })

  it('uses core game, session, replay, and notice state from stores when props are absent', () => {
    const wrapper = mountMatchPage({}, () => {
      useGameStore().hydrateFromRuntime({
        game: gameFixture('store-game'),
        loading: true,
        watchRunning: true,
        roleAssignmentComplete: true,
        judgeBoardStarted: true,
        judgeBoardStarting: false,
        promptText: 'store prompt',
        judgeStripMessage: [{ message: 'store judge' }],
        playerIdentityList: [{ id: 1, speaking: true }],
        matchRecordLogs: [{ message: 'store log' }],
        livingPlayers: [{ id: 1 }],
        speakerCarousel: [{ key: 1, image: '', label: '1号' }],
        speakerMessage: 'store speaker',
        sceneVoteTally: [{ target: 1, count: 2 }],
        sceneEffects: [{ type: 'vote' }],
      })
      useSessionStore().hydrateFromRuntime({ backendMode: 'api' })
      useReplayStore().hydrateFromRuntime({
        isReplayMode: true,
        replayCursor: 4,
        replayPlaying: true,
        replaySpeed: 1.5,
        replayTotal: 9,
        replayEventLabel: 'store replay label',
      })
      useUiStore().hydrateFromRuntime({
        matchNotice: { type: 'success', message: 'store notice' },
      })
    })

    const controls = wrapper.find('.match-control-stub')
    expect(controls.attributes('data-game-id')).toBe('store-game')
    expect(controls.attributes('data-loading')).toBe('true')
    expect(controls.attributes('data-backend-mode')).toBe('api')
    expect(controls.attributes('data-night')).toBe('true')
    expect(controls.attributes('data-replay')).toBe('true')
    expect(controls.attributes('data-watch')).toBe('true')
    expect(controls.attributes('data-judge-started')).toBe('true')
    expect(wrapper.find('.council-scene-stub').attributes('data-player-count')).toBe('1')
    expect(wrapper.find('.council-scene-stub').attributes('data-speaker-message')).toBe('store speaker')
    expect(wrapper.find('.council-scene-stub').attributes('data-vote-count')).toBe('1')
    expect(wrapper.find('.council-scene-stub').attributes('data-effect-count')).toBe('1')
    expect(wrapper.find('.chat-log-stub').attributes('data-log-count')).toBe('1')
    expect(wrapper.find('.player-identity-stub').attributes('data-player-count')).toBe('1')
    expect(wrapper.find('.player-carousel-stub').attributes('data-carousel-count')).toBe('1')
    expect(wrapper.find('.player-carousel-stub').attributes('data-message')).toBe('store speaker')
    expect(wrapper.find('.replay-controls-stub').attributes('data-cursor')).toBe('4')
    expect(wrapper.find('.replay-controls-stub').attributes('data-total')).toBe('9')
    expect(wrapper.find('.replay-controls-stub').attributes('data-playing')).toBe('true')
    expect(wrapper.find('.replay-controls-stub').attributes('data-speed')).toBe('1.5')
    expect(wrapper.find('.replay-controls-stub').attributes('data-event-label')).toBe('store replay label')
    expect(wrapper.find('.match-action-notice').text()).toContain('store notice')
  })

  it('reads and mutates match action controls through the game store when props are absent', async () => {
    let gameStore!: ReturnType<typeof useGameStore>
    const actionGame = gameFixture('action-game', {
      mode: 'play',
      phase: 'night',
      player_count: 3,
      human_player_id: 1,
      waiting_for: 'action',
      players: [
        { id: 1, seat: 1, name: 'Human', role_hint: '女巫', alive: true, is_human: true, is_sheriff: false },
        { id: 2, seat: 2, name: 'Target', role_hint: '狼人', alive: true, is_human: false, is_sheriff: false },
        { id: 3, seat: 3, name: 'Other', role_hint: '平民', alive: true, is_human: false, is_sheriff: false },
      ],
      pending_action: {
        type: 'witch_act',
        prompt: '女巫请选择是否发动技能。',
        candidate_ids: [2],
        target_required: false,
        allow_no_target: true,
        options: {
          poison_available: true,
          antidote_available: true,
          attacked_player: 2,
        },
      },
      skill_state: {
        witch_antidote_used: false,
        witch_poison_used: false,
      },
    })

    const wrapper = mountMatchPage({}, () => {
      gameStore = useGameStore()
      gameStore.hydrateFromRuntime({
        game: actionGame,
        roleAssignmentComplete: true,
        speechRemaining: 75,
      })
      gameStore.setSpeech('store speech')
      gameStore.setWitchChoice('poison')
      gameStore.setBurstArmed(true)
      gameStore.setActionTarget(2)
    })

    const panel = wrapper.find('.action-panel-stub')
    expect(panel.attributes('data-human-id')).toBe('1')
    expect(panel.attributes('data-role-name')).toBe('女巫')
    expect(panel.attributes('data-witch')).toBe('true')
    expect(panel.attributes('data-action-type')).toBe('witch_act')
    expect(panel.attributes('data-action-instruction')).toBe('法官提醒：点击一名玩家模型使用毒药。')
    expect(panel.attributes('data-countdown')).toBe('1:15')
    expect(panel.attributes('data-needs-target')).toBe('true')
    expect(panel.attributes('data-speech')).toBe('store speech')
    expect(panel.attributes('data-witch-choice')).toBe('poison')
    expect(panel.attributes('data-burst-armed')).toBe('true')
    expect(panel.attributes('data-action-target')).toBe('2')

    await wrapper.find('.set-speech').trigger('click')
    await wrapper.find('.set-witch').trigger('click')
    await wrapper.find('.set-action-choice').trigger('click')
    await wrapper.find('.set-burst').trigger('click')
    await wrapper.find('.set-target').trigger('click')

    expect(gameStore.speech).toBe('updated speech')
    expect(gameStore.witchChoice).toBe('antidote')
    expect(gameStore.actionChoice).toBe('skip')
    expect(gameStore.burstArmed).toBe(false)
    expect(gameStore.actionTarget).toBe(3)
  })

  it('keeps explicitly passed runtime props ahead of store state during migration', () => {
    const wrapper = mountMatchPage(
      {
        game: gameFixture('prop-game', { phase: 'day', mode: 'play' }),
        loading: false,
        backendMode: 'mock',
        isNight: false,
        isReplayMode: false,
        watchRunning: false,
        roleAssignmentComplete: true,
        judgeBoardStarted: false,
        matchNotice: { type: 'success', message: 'prop notice' },
        promptText: 'prop prompt',
        judgeStripMessage: [],
      },
      () => {
        useGameStore().hydrateFromRuntime({
          game: gameFixture('store-game'),
          loading: true,
          watchRunning: true,
          roleAssignmentComplete: true,
          judgeBoardStarted: true,
        })
        useSessionStore().hydrateFromRuntime({ backendMode: 'api' })
        useReplayStore().hydrateFromRuntime({ isReplayMode: true, replayCursor: 8 })
        useUiStore().hydrateFromRuntime({ matchNotice: { type: 'warning', message: 'store notice' } })
      }
    )

    const controls = wrapper.find('.match-control-stub')
    expect(controls.attributes('data-game-id')).toBe('prop-game')
    expect(controls.attributes('data-loading')).toBe('false')
    expect(controls.attributes('data-backend-mode')).toBe('mock')
    expect(controls.attributes('data-night')).toBe('false')
    expect(controls.attributes('data-replay')).toBe('false')
    expect(controls.attributes('data-watch')).toBe('false')
    expect(controls.attributes('data-prompt')).toBe('prop prompt')
    expect(controls.attributes('data-judge-count')).toBe('0')
    expect(controls.attributes('data-judge-started')).toBe('false')
    expect(wrapper.find('.replay-controls-stub').exists()).toBe(false)
    expect(wrapper.find('.match-action-notice').text()).toContain('prop notice')
  })
})
