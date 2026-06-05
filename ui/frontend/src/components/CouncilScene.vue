<script setup>
import { nextTick, onBeforeUnmount, onMounted, ref, watch } from 'vue'

const props = defineProps({
  game: Object,
  isNight: Boolean,
  isWatch: Boolean,
  isReplayMode: Boolean,
  roleAssignmentComplete: Boolean,
  judgeBoardStarted: Boolean,
  players: { type: Array, default: () => [] },
  selectableIds: { type: Array, default: () => [] },
  currentSpeakerId: [String, Number, null],
  voteTally: { type: Array, default: () => [] }
})

const emit = defineEmits(['ready', 'container-ready', 'player-select'])
const containerRef = ref(null)
let scene = null
let rafId = 0
let sceneFactoryPromise = null
const sceneApi = { waitForCouncilModels, syncCouncilScene, scheduleSyncCouncilScene }

function publishContainer() {
  if (containerRef.value) {
    emit('ready', sceneApi)
    emit('container-ready', containerRef)
  }
}

async function ensureScene() {
  await nextTick()
  if (!containerRef.value) return
  if (!scene) {
    if (!sceneFactoryPromise) {
      sceneFactoryPromise = import('../CouncilHallScene.js').then((module) => module.createCouncilHallScene)
    }
    const createCouncilHallScene = await sceneFactoryPromise
    if (!containerRef.value) return
    scene = createCouncilHallScene(containerRef.value)
  }
  containerRef.value.style.visibility = ''
  publishContainer()
}

function scenePayload(revealPlayers = props.roleAssignmentComplete || props.isReplayMode) {
  return {
    players: props.players,
    currentSpeakerId: props.currentSpeakerId ?? null,
    speechByPlayer: {},
    isNight: props.isNight,
    revealPlayers,
    humanId: props.isWatch ? null : props.game?.human_player_id ?? null,
    selectableIds: props.selectableIds,
    onPlayerSelect: (id) => emit('player-select', id),
    pageVoteTally: props.voteTally,
    voteTally: props.voteTally
  }
}

function updateScene() {
  if (!scene) return
  scene.update?.(scenePayload())
}

function scheduleSyncCouncilScene() {
  if (rafId) cancelAnimationFrame(rafId)
  rafId = requestAnimationFrame(async () => {
    rafId = 0
    await ensureScene()
    updateScene()
  })
}

function syncCouncilScene() {
  updateScene()
}

async function waitForCouncilModels() {
  await ensureScene()
  scene?.update?.(scenePayload(true))
  const preload = scene?.preloadModels?.()
  if (preload) {
    await Promise.race([preload, new Promise((resolve) => window.setTimeout(resolve, 3200))])
  }
  updateScene()
}

onMounted(scheduleSyncCouncilScene)
watch(() => [props.players, props.currentSpeakerId, props.isNight, props.roleAssignmentComplete, props.isReplayMode, props.selectableIds, props.voteTally], scheduleSyncCouncilScene, { deep: true })

onBeforeUnmount(() => {
  if (rafId) cancelAnimationFrame(rafId)
  scene?.dispose?.()
  scene = null
})

defineExpose({ containerRef, waitForCouncilModels, syncCouncilScene, scheduleSyncCouncilScene })
</script>

<template>
  <div ref="containerRef" class="council-scene" aria-hidden="true"></div>
</template>
