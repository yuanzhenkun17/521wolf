// @vitest-environment jsdom

import { mount } from '@vue/test-utils'
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
    props: ['game', 'isNight', 'isWatch', 'isReplayMode', 'roleAssignmentComplete', 'judgeBoardStarted', 'players', 'speakerMessage', 'voteTally', 'sceneEffects'],
    template: '<section class="council-scene-stub" :data-game-id="game?.game_id" :data-night="String(isNight)" :data-watch="String(isWatch)" :data-replay="String(isReplayMode)" :data-role-ready="String(roleAssignmentComplete)" :data-judge-started="String(judgeBoardStarted)" :data-player-count="String(players.length)" :data-speaker-message="speakerMessage" :data-vote-count="String(voteTally.length)" :data-effect-count="String(sceneEffects.length)" />',
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

vi.mock('../../src/components/ActionPanel.vue', () => ({ default: { name: 'ActionPanel', template: '<section class="action-panel-stub" />' } }))
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
