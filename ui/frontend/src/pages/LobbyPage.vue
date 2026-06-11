<script setup lang="ts">
import { computed, getCurrentInstance, onBeforeUnmount, onMounted, ref, watch, type PropType } from 'vue'
import { type GameStartRoleVersionMode, gameStartRoleVersionState } from '../composables/gameStartRoleVersions.ts'
import { roleLabel, roleMeta, shortId, sourceText } from '../composables/workbenchShared.ts'
import { runtimeHealthGateSummary, runtimeHealthPayloadFromPreflight } from '../domain/runtimeHealth/gates'
import { useGameStore, useSessionStore } from '../stores'
import type { RuntimeHealthPayload } from '../types/health'
import type { ModelProfile } from '../types/settings'

type RoleVersionModeOption = {
  key: GameStartRoleVersionMode
  label: string
}

type ExternalStatus = {
  supports_human?: boolean
} & Record<string, unknown>

type StartModeOptions = {
  player_count: number
  human_player_id: number | null
  role_versions?: Record<string, unknown>
  model_profile_id?: string
}

const props = defineProps({
  backendMode: { type: String, default: 'mock' },
  externalStatus: { type: Object as PropType<ExternalStatus | null>, default: null },
  runtimeHealth: { type: Object as PropType<RuntimeHealthPayload | null>, default: null },
  loading: Boolean,
  playerCount: { type: Number, default: 12 },
  apiFetch: { type: Function, default: null }
})

const emit = defineEmits(['start-mode'])
const instance = getCurrentInstance()
const sessionStore = useSessionStore()
const gameStore = useGameStore()

const LOBBY_STORE_PROP_ALIASES = {
  backendMode: ['backendMode', 'backend-mode'],
  loading: ['loading']
} as const

function hasExplicitLobbyProp(propName: keyof typeof LOBBY_STORE_PROP_ALIASES) {
  const rawProps = instance?.vnode.props || {}
  return LOBBY_STORE_PROP_ALIASES[propName].some((key) => Object.prototype.hasOwnProperty.call(rawProps, key))
}

const backendMode = computed(() => (
  hasExplicitLobbyProp('backendMode') ? props.backendMode : sessionStore.backendMode
))
const backendAvailable = computed(() => (
  hasExplicitLobbyProp('backendMode') ? backendMode.value !== 'offline' : sessionStore.backendAvailable
))
const loading = computed(() => hasExplicitLobbyProp('loading') ? props.loading : gameStore.loading)
const supportsHuman = computed(() => props.externalStatus?.supports_human !== false)
const baseGameStartGate = computed(() => runtimeHealthGateSummary(props.runtimeHealth, 'game_start'))
const showGameStartGate = ref(false)
const roles = ref([])
const versionsByRole = ref({})
const leaderboardsByRole = ref({})
const roleVersionSelections = ref({})
const modelProfiles = ref<ModelProfile[]>([])
const modelProfilePreflight = ref<Record<string, any> | null>(null)
const gameStartPreflight = ref<Record<string, any> | null>(null)
const registryLoading = ref(false)
const registryError = ref('')
const modelProfilePreflightLoading = ref(false)
const modelProfilePreflightError = ref('')
const gameStartPreflightLoading = ref(false)
const gameStartPreflightError = ref('')
const modelProfilesLoading = ref(false)
const modelProfilesError = ref('')
const startingMode = ref('')
const selectedModelProfileId = ref('')
const roleVersionDrawerOpen = ref(false)
const roleVersionMode = ref<GameStartRoleVersionMode>('baseline')
let gameStartGateTimer: ReturnType<typeof setTimeout> | null = null
let roleVersionLoadPromise = null
let modelProfilesLoadPromise: Promise<void> | null = null
let modelProfilePreflightRequestId = 0
let gameStartPreflightRequestId = 0

const ROLE_VERSION_MODES: RoleVersionModeOption[] = [
  { key: 'baseline', label: '当前基线' },
  { key: 'latest', label: '最新晋升' },
  { key: 'custom', label: '自定义覆盖' }
]
const roleRows = computed(() => roles.value
  .map((role) => {
    const rawVersions = versionsByRole.value[role] || []
    const selectedVersionId = roleVersionSelections.value[role] || ''
    const versionState = gameStartRoleVersionState({
      versions: rawVersions,
      selectedVersionId,
      mode: roleVersionMode.value,
      isFallbackVersion
    })
    const {
      versions,
      baseline,
      latestVersion,
      customVersion,
      effectiveVersion,
      choices,
      hasOverride
    } = versionState
    const boardEntries = leaderboardsByRole.value[role]?.entries || []
    const effectiveScore = scoreForVersion(effectiveVersion, boardEntries)
    const baselineScore = scoreForVersion(baseline, boardEntries)
    return {
      role,
      label: roleLabel(role, role),
      meta: roleMeta(role),
      versions,
      baseline,
      latestVersion,
      customVersion,
      effectiveVersion,
      selectedVersionId,
      effectiveScore,
      baselineScore,
      choices,
      hasOverride,
      hasFallbackBaseline: isFallbackVersion(baseline)
    }
  })
  .filter((row) => row.versions.length)
)
const selectedRoleVersions = computed(() =>
  Object.fromEntries(
    roleRows.value
      .filter((row) => row.hasOverride && row.effectiveVersion)
      .map((row) => [row.role, row.effectiveVersion.version_id])
  )
)
const selectedOverrideCount = computed(() => Object.keys(selectedRoleVersions.value).length)
const fallbackRoleCount = computed(() => roleRows.value.filter((row) => row.hasFallbackBaseline).length)
const readyRoleCount = computed(() => Math.max(0, roleRows.value.length - fallbackRoleCount.value))
const roleVersionModeLabel = computed(() =>
  ROLE_VERSION_MODES.find((item) => item.key === roleVersionMode.value)?.label || '当前基线'
)
const registryStatusText = computed(() => {
  if (!backendAvailable.value) return ''
  if (registryLoading.value) return '角色版本读取中'
  if (registryError.value) return registryError.value
  if (roleRows.value.length) {
    const readiness = `${readyRoleCount.value}/${roleRows.value.length} 已就绪`
    const fallback = fallbackRoleCount.value ? ` · ${fallbackRoleCount.value} 个本地兜底` : ''
    return selectedOverrideCount.value
      ? `${roleVersionModeLabel.value} · 已覆盖 ${selectedOverrideCount.value} 个角色 · ${readiness}${fallback}`
      : `${roleVersionModeLabel.value} · ${readiness}${fallback}`
  }
  if (props.apiFetch) return '暂无可选版本'
  return ''
})
const registryStatusType = computed(() => {
  if (registryError.value) return 'error'
  if (registryLoading.value) return 'loading'
  if (selectedOverrideCount.value) return 'success'
  if (fallbackRoleCount.value) return 'warning'
  return 'neutral'
})
const launchModelProfiles = computed(() =>
  modelProfiles.value
    .filter((profile) => profile.enabled && profile.has_api_key)
    .sort((left, right) => Number(Boolean(right.default_scopes?.game_decision)) - Number(Boolean(left.default_scopes?.game_decision)))
)
const selectedModelProfile = computed(() =>
  launchModelProfiles.value.find((profile) => profile.profile_id === selectedModelProfileId.value) || null
)
const modelProfilePreflightHealth = computed(() =>
  runtimeHealthPayloadFromPreflight(modelProfilePreflight.value, 'game_start')
)
const gameStartPreflightHealth = computed(() =>
  runtimeHealthPayloadFromPreflight(gameStartPreflight.value, 'game_start')
)
const gameStartGate = computed(() =>
  gameStartPreflightHealth.value
    ? runtimeHealthGateSummary(gameStartPreflightHealth.value, 'game_start')
    : selectedModelProfileId.value && modelProfilePreflightHealth.value
    ? runtimeHealthGateSummary(modelProfilePreflightHealth.value, 'game_start')
    : baseGameStartGate.value
)
const modelProfilePreflightPassed = computed(() =>
  !modelProfilePreflightLoading.value
  && !modelProfilePreflightError.value
  && modelProfilePreflight.value?.ready === true
)
const gameStartGateMessage = computed(() => {
  if (gameStartPreflightLoading.value) return '开局预检中。'
  if (gameStartPreflightError.value) return gameStartPreflightError.value
  if (selectedModelProfileId.value) {
    if (modelProfilePreflightLoading.value) return '模型 Profile 预检中。'
    if (modelProfilePreflightError.value) return modelProfilePreflightError.value
  }
  return gameStartGate.value.reason || gameStartGate.value.warning
})
const gameStartGateTone = computed(() => gameStartGate.value.disabled || gameStartPreflightError.value || modelProfilePreflightError.value ? 'error' : 'warning')
const gameStartButtonBusy = computed(() => gameStartPreflightLoading.value)

function versionSource(version) {
  return sourceText(version?.source || (version?.is_baseline ? 'baseline' : 'version'))
}

function isFallbackVersion(version) {
  const source = String(version?.source || '').trim().toLowerCase()
  const status = String(version?.status || '').trim().toLowerCase()
  return source === 'app-fallback' || source === 'app_fallback' || status === 'missing_registry'
}

function modelProfileOptionText(profile) {
  const name = String(profile?.name || '').trim()
  const model = String(profile?.model || '').trim()
  const identity = name && model && name !== model ? `${name} · ${model}` : name || model || '未命名模型'
  return `${identity}${profile?.default_scopes?.game_decision ? ' · 默认游戏' : ''}`
}

function scoreForVersion(version, entries = []) {
  if (!version) return null
  const entry = entries.find((item) =>
    item.target_version_id === version.version_id
    || item.version_id === version.version_id
    || item.hash === version.version_id
  )
  const metrics = version.metrics || {}
  return {
    score: Number(entry?.target_role_role_weighted_score ?? entry?.avg_role_score ?? metrics.score ?? 0),
    winRate: Number(entry?.target_side_win_rate ?? metrics.win_rate ?? 0),
    games: Number(entry?.game_count ?? entry?.games_played ?? metrics.games_played ?? 0),
    rankable: Boolean(entry?.rankable)
  }
}

function metricText(score) {
  if (!score || (!score.score && !score.winRate && !score.games)) return '暂无评测'
  const parts = []
  if (score.score) parts.push(`评分 ${Math.round(score.score * 100)}`)
  if (score.winRate) parts.push(`胜率 ${Math.round(score.winRate * 100)}%`)
  if (score.games) parts.push(`${score.games} 局`)
  return parts.join(' · ')
}

function roleCurrentLabel(row) {
  if (!row.effectiveVersion) return '未配置'
  if (row.hasOverride) return '已覆盖'
  if (row.hasFallbackBaseline) return '本地兜底'
  return '当前基线'
}

function roleVersionStatusTone(row) {
  if (row.hasOverride) return 'override'
  if (row.hasFallbackBaseline) return 'fallback'
  return 'baseline'
}

function versionOptionLabel(version) {
  const label = version.is_baseline ? '当前基线' : '覆盖'
  return `${label} · ${shortId(version.version_id, 8)} · ${versionSource(version)}`
}

function clearRoleVersionOverrides() {
  roleVersionSelections.value = Object.fromEntries(roles.value.map((role) => [role, '']))
  roleVersionMode.value = 'baseline'
}

function clearGameStartGateTimer() {
  if (!gameStartGateTimer) return
  clearTimeout(gameStartGateTimer)
  gameStartGateTimer = null
}

function dismissGameStartGate() {
  clearGameStartGateTimer()
  showGameStartGate.value = false
}

function scheduleGameStartGateDismiss() {
  clearGameStartGateTimer()
  if (!gameStartGateMessage.value) {
    showGameStartGate.value = false
    return
  }
  showGameStartGate.value = true
  gameStartGateTimer = setTimeout(() => {
    showGameStartGate.value = false
    gameStartGateTimer = null
  }, 5200)
}

async function loadModelProfilePreflight() {
  if (!props.apiFetch || !backendAvailable.value) return false
  const profileId = String(selectedModelProfileId.value || '').trim()
  const requestId = ++modelProfilePreflightRequestId
  modelProfilePreflight.value = null
  modelProfilePreflightError.value = ''
  if (!profileId) {
    modelProfilePreflightLoading.value = false
    return true
  }
  modelProfilePreflightLoading.value = true
  try {
    const query = new URLSearchParams({
      scope: 'game_start',
      model_scope: 'game_decision',
      model_profile_id: profileId
    })
    const payload = await props.apiFetch(`/health/preflight?${query.toString()}`, { method: 'POST' })
    if (requestId !== modelProfilePreflightRequestId) return false
    modelProfilePreflight.value = payload || null
    return Boolean(payload?.ready)
  } catch (err) {
    if (requestId === modelProfilePreflightRequestId) {
      modelProfilePreflight.value = null
      modelProfilePreflightError.value = err?.message || '模型 Profile 预检失败'
    }
    return false
  } finally {
    if (requestId === modelProfilePreflightRequestId) modelProfilePreflightLoading.value = false
  }
}

async function runGameStartPreflight() {
  if (!props.apiFetch || !backendAvailable.value) return true
  const profileId = String(selectedModelProfileId.value || '').trim()
  const requestId = ++gameStartPreflightRequestId
  gameStartPreflight.value = null
  gameStartPreflightError.value = ''
  gameStartPreflightLoading.value = true
  try {
    const query = new URLSearchParams({
      scope: 'game_start',
      model_scope: 'game_decision'
    })
    if (profileId) query.set('model_profile_id', profileId)
    const payload = await props.apiFetch(`/health/preflight?${query.toString()}`, { method: 'POST' })
    if (requestId !== gameStartPreflightRequestId) return false
    gameStartPreflight.value = payload || null
    if (profileId) {
      modelProfilePreflight.value = payload || null
      modelProfilePreflightError.value = ''
    }
    return Boolean(payload?.ready)
  } catch (err) {
    if (requestId === gameStartPreflightRequestId) {
      gameStartPreflight.value = null
      gameStartPreflightError.value = err?.message || '开局预检失败'
    }
    return false
  } finally {
    if (requestId === gameStartPreflightRequestId) gameStartPreflightLoading.value = false
  }
}

async function start(mode) {
  dismissGameStartGate()
  startingMode.value = mode
  const preflightReady = await runGameStartPreflight()
  if (!preflightReady || gameStartGate.value.disabled) {
    scheduleGameStartGateDismiss()
    startingMode.value = ''
    return
  }
  dismissGameStartGate()
  const body: StartModeOptions = {
    player_count: Number(props.playerCount) || 12,
    human_player_id: mode === 'play' ? 1 : null
  }
  if (selectedOverrideCount.value) body.role_versions = selectedRoleVersions.value
  if (selectedModelProfileId.value) body.model_profile_id = selectedModelProfileId.value
  emit('start-mode', { mode, options: body })
}

async function loadModelProfiles() {
  if (!props.apiFetch || !backendAvailable.value) return
  if (modelProfilesLoadPromise) return modelProfilesLoadPromise
  modelProfilesLoading.value = true
  modelProfilesError.value = ''
  modelProfilesLoadPromise = (async () => {
    const payload = await props.apiFetch('/settings/model-profiles')
    const profiles = Array.isArray(payload.profiles) ? payload.profiles : []
    modelProfiles.value = profiles
    const available = profiles
      .filter((profile) => profile.enabled && profile.has_api_key)
      .sort((left, right) => Number(Boolean(right.default_scopes?.game_decision)) - Number(Boolean(left.default_scopes?.game_decision)))
    if (selectedModelProfileId.value && available.some((profile) => profile.profile_id === selectedModelProfileId.value)) {
      void loadModelProfilePreflight()
      return
    }
    selectedModelProfileId.value = available.find((profile) => profile.default_scopes?.game_decision)?.profile_id || ''
    if (selectedModelProfileId.value) void loadModelProfilePreflight()
  })()
  try {
    await modelProfilesLoadPromise
  } catch (err) {
    modelProfiles.value = []
    selectedModelProfileId.value = ''
    modelProfilesError.value = err?.message || '模型读取失败'
  } finally {
    modelProfilesLoadPromise = null
    modelProfilesLoading.value = false
  }
}

async function loadRoleVersions() {
  if (!props.apiFetch || !backendAvailable.value) return
  if (roleVersionLoadPromise) return roleVersionLoadPromise
  if (roles.value.length && Object.keys(versionsByRole.value).length && !registryError.value) return
  registryLoading.value = true
  registryError.value = ''
  roleVersionLoadPromise = (async () => {
    let nextRoles = []
    let entries = []
    try {
      const overview = await props.apiFetch('/roles/overview')
      nextRoles = overview.roles || []
      const overviewVersions = overview.versions || {}
      leaderboardsByRole.value = overview.leaderboards || {}
      entries = nextRoles.map((role) => [role, overviewVersions[role] || []])
    } catch {
      const roleData = await props.apiFetch('/roles')
      nextRoles = roleData.roles || []
      leaderboardsByRole.value = {}
      entries = await Promise.all(nextRoles.map(async (role) => {
        try {
          const data = await props.apiFetch(`/roles/${encodeURIComponent(role)}/versions`)
          return [role, data.versions || []]
        } catch {
          return [role, []]
        }
      }))
    }
    roles.value = nextRoles
    versionsByRole.value = Object.fromEntries(entries)
    roleVersionSelections.value = Object.fromEntries(
      nextRoles.map((role) => [role, roleVersionSelections.value[role] || ''])
    )
  })()
  try {
    await roleVersionLoadPromise
  } catch (err) {
    roles.value = []
    versionsByRole.value = {}
    leaderboardsByRole.value = {}
    registryError.value = err?.message || '角色版本读取失败'
  } finally {
    roleVersionLoadPromise = null
    registryLoading.value = false
  }
}

onMounted(() => {
  void loadRoleVersions()
  void loadModelProfiles()
})
onBeforeUnmount(clearGameStartGateTimer)
watch(backendMode, () => {
  gameStartPreflight.value = null
  gameStartPreflightError.value = ''
  void loadRoleVersions()
  void loadModelProfiles()
})
watch(selectedModelProfileId, () => {
  gameStartPreflight.value = null
  gameStartPreflightError.value = ''
  void loadModelProfilePreflight()
})
watch(loading, (isLoading) => {
  if (!isLoading) startingMode.value = ''
})
</script>

<template>
  <section class="lobby">
    <section class="lobby-hero">
      <span class="hero-mark"></span>
      <h1 class="lobby-hero-title">The Night Approaches</h1>
      <div class="lobby-subtitle-stack">
        <p>Gather the council. Trust no one.</p>
        <section
          v-if="backendAvailable && (registryStatusText || roleRows.length)"
          :class="['lobby-version-panel', registryStatusType]"
          aria-label="角色版本"
        >
          <div class="lobby-version-status" role="status" aria-live="polite">
            <div class="lobby-version-title">
              <span>角色版本</span>
              <strong>{{ registryStatusText }}</strong>
              <small v-if="fallbackRoleCount">
                {{ fallbackRoleCount }} 个角色使用本地兜底，正式评测前建议发布基线。
              </small>
            </div>
            <div class="lobby-version-actions">
              <button
                v-if="selectedOverrideCount"
                type="button"
                :disabled="loading || registryLoading"
                @click="clearRoleVersionOverrides"
              >
                清除覆盖
              </button>
              <button
                v-if="registryError"
                type="button"
                :disabled="registryLoading"
                @click="loadRoleVersions"
              >
                {{ registryLoading ? '重试中' : '重试' }}
              </button>
              <button
                v-if="roleRows.length"
                type="button"
                :disabled="registryLoading"
                @click="roleVersionDrawerOpen = true"
              >
                配置
              </button>
            </div>
          </div>
        </section>
      </div>
    </section>

    <section class="card-fan" aria-label="角色牌">
      <figure class="role-card-art werewolf" aria-label="狼人角色牌">
        <picture class="lobby-card-image">
          <source type="image/webp" :srcset="'/lobby-cards/optimized/werewolf-512.webp'" />
          <img :src="'/lobby-cards/werewolf.png'" alt="" decoding="async" />
        </picture>
        <picture class="lobby-card-frame">
          <source type="image/webp" :srcset="'/lobby-cards/optimized/frame-512.webp'" />
          <img :src="'/lobby-cards/frame.png'" alt="" decoding="async" />
        </picture>
      </figure>
      <figure class="role-card-art villager" aria-label="村民角色牌">
        <picture class="lobby-card-image">
          <source type="image/webp" :srcset="'/lobby-cards/optimized/villager-512.webp'" />
          <img :src="'/lobby-cards/villager.png'" alt="" decoding="async" />
        </picture>
        <picture class="lobby-card-frame">
          <source type="image/webp" :srcset="'/lobby-cards/optimized/frame-512.webp'" />
          <img :src="'/lobby-cards/frame.png'" alt="" decoding="async" />
        </picture>
      </figure>
      <figure class="role-card-art judge" aria-label="法官角色牌">
        <picture class="lobby-card-image">
          <source type="image/webp" :srcset="'/lobby-cards/optimized/judge-512.webp'" />
          <img :src="'/lobby-cards/judge.png'" alt="" decoding="async" />
        </picture>
        <picture class="lobby-card-frame">
          <source type="image/webp" :srcset="'/lobby-cards/optimized/frame-512.webp'" />
          <img :src="'/lobby-cards/frame.png'" alt="" decoding="async" />
        </picture>
      </figure>
      <figure class="role-card-art hunter" aria-label="猎人角色牌">
        <picture class="lobby-card-image">
          <source type="image/webp" :srcset="'/lobby-cards/optimized/hunter-512.webp'" />
          <img :src="'/lobby-cards/hunter.png'" alt="" decoding="async" />
        </picture>
        <picture class="lobby-card-frame">
          <source type="image/webp" :srcset="'/lobby-cards/optimized/frame-512.webp'" />
          <img :src="'/lobby-cards/frame.png'" alt="" decoding="async" />
        </picture>
      </figure>
      <figure class="role-card-art witch" aria-label="女巫角色牌">
        <picture class="lobby-card-image">
          <source type="image/webp" :srcset="'/lobby-cards/optimized/witch-512.webp'" />
          <img :src="'/lobby-cards/witch.png'" alt="" decoding="async" />
        </picture>
        <picture class="lobby-card-frame">
          <source type="image/webp" :srcset="'/lobby-cards/optimized/frame-512.webp'" />
          <img :src="'/lobby-cards/frame.png'" alt="" decoding="async" />
        </picture>
      </figure>
    </section>

    <section class="lobby-actions">
      <section
        v-if="backendAvailable && gameStartGateMessage && showGameStartGate"
        :class="['lobby-runtime-gate', gameStartGateTone]"
        aria-label="开局门禁"
        role="status"
      >
        <div>
          <span>{{ gameStartGate.disabled ? '开局已阻断' : '开局预检' }}</span>
          <strong>{{ gameStartGateMessage }}</strong>
        </div>
        <small v-if="gameStartGate.actions.length">{{ gameStartGate.actions[0] }}</small>
        <button type="button" aria-label="关闭开局门禁提示" @click="dismissGameStartGate">关闭</button>
      </section>
      <section
        v-if="backendAvailable && (launchModelProfiles.length || modelProfilesLoading || modelProfilesError)"
        class="lobby-model-panel"
        aria-label="开局模型"
      >
        <div class="lobby-model-select">
          <select
            v-model="selectedModelProfileId"
            aria-label="本地模型"
            :class="{ 'has-inline-status': modelProfilePreflightPassed }"
            :disabled="loading || modelProfilesLoading"
          >
            <option value="">自动选择</option>
            <option
              v-for="profile in launchModelProfiles"
              :key="profile.profile_id"
              :value="profile.profile_id"
            >
              {{ modelProfileOptionText(profile) }}
            </option>
          </select>
          <small v-if="modelProfilePreflightPassed" aria-hidden="true">模型预检通过</small>
        </div>
      </section>
      <button class="mode-card watch" :disabled="loading || !backendAvailable || gameStartButtonBusy" @click="start('watch')">
        <span>观战模式</span>
        <strong>
          {{ !backendAvailable ? '后端未连接' : gameStartButtonBusy ? '开局预检中' : '观看智能体对局' }}
          <i v-if="startingMode === 'watch' && loading" class="mode-loading-dots" aria-label="加载中">
            <b></b><b></b><b></b>
          </i>
        </strong>
      </button>
      <button class="mode-card play" :disabled="loading || !backendAvailable || !supportsHuman || gameStartButtonBusy" @click="start('play')">
        <span>玩家模式</span>
        <strong>
          {{ gameStartButtonBusy ? '开局预检中' : supportsHuman ? '加入智能体对局' : '后端暂不支持加入' }}
          <i v-if="startingMode === 'play' && loading" class="mode-loading-dots" aria-label="加载中">
            <b></b><b></b><b></b>
          </i>
        </strong>
      </button>
    </section>

    <Teleport to="body">
      <Transition name="lobby-version-drawer-motion">
        <div
          v-if="roleVersionDrawerOpen && roleRows.length"
          class="lobby-version-drawer-layer"
          tabindex="-1"
          @keydown.esc="roleVersionDrawerOpen = false"
        >
          <button
            type="button"
            class="lobby-version-backdrop"
            aria-label="关闭角色策略配置"
            @click="roleVersionDrawerOpen = false"
          ></button>
          <aside class="lobby-version-drawer" role="dialog" aria-modal="true" aria-label="角色策略配置">
            <header class="lobby-version-drawer-head">
              <div>
                <span>角色策略配置</span>
                <strong>{{ roleVersionModeLabel }}</strong>
                <small>开局时只提交与基线不同的角色覆盖。</small>
              </div>
              <button type="button" @click="roleVersionDrawerOpen = false">关闭</button>
            </header>

            <div class="lobby-version-mode-tabs" role="tablist" aria-label="角色版本模式">
              <button
                v-for="mode in ROLE_VERSION_MODES"
                :key="mode.key"
                type="button"
                :class="{ active: roleVersionMode === mode.key }"
                :aria-selected="roleVersionMode === mode.key"
                role="tab"
                @click="roleVersionMode = mode.key"
              >
                {{ mode.label }}
              </button>
            </div>

            <div v-if="fallbackRoleCount" class="lobby-version-drawer-note">
              {{ fallbackRoleCount }} 个角色仍在使用本地兜底版本。
            </div>

            <div class="lobby-version-drawer-list">
              <article
                v-for="row in roleRows"
                :key="'version-row-' + row.role"
                :data-tone="roleVersionStatusTone(row)"
                class="lobby-version-row"
              >
                <div class="lobby-version-identity">
                  <img :src="row.meta.image" alt="" />
                  <div>
                    <b>{{ row.label }}</b>
                    <small>{{ roleCurrentLabel(row) }} · {{ versionSource(row.effectiveVersion) }}</small>
                  </div>
                  <em>{{ shortId(row.effectiveVersion?.version_id, 8) }}</em>
                </div>

                <div class="lobby-version-body">
                  <div class="lobby-version-metrics">
                    <span>
                      <small>当前表现</small>
                      <b>{{ metricText(row.effectiveScore) }}</b>
                    </span>
                    <span>
                      <small>基线</small>
                      <b>{{ shortId(row.baseline?.version_id, 10) }} · {{ metricText(row.baselineScore) }}</b>
                    </span>
                  </div>

                  <label v-if="roleVersionMode === 'custom' && row.choices.length" class="lobby-version-select">
                    <span>覆盖版本</span>
                    <select v-model="roleVersionSelections[row.role]" :disabled="loading || registryLoading">
                      <option value="">
                        沿用当前基线 · {{ shortId(row.baseline?.version_id, 8) }}
                      </option>
                      <option
                        v-for="version in row.choices"
                        :key="version.version_id"
                        :value="version.version_id"
                      >
                        {{ versionOptionLabel(version) }} · {{ metricText(scoreForVersion(version, leaderboardsByRole[row.role]?.entries || [])) }}
                      </option>
                    </select>
                  </label>
                  <div v-else-if="roleVersionMode === 'custom'" class="lobby-version-empty">
                    <small>覆盖版本</small>
                    <b>无可用覆盖，沿用当前基线</b>
                  </div>
                  <div v-else class="lobby-version-lock">
                    <small>生效版本</small>
                    <b>{{ roleCurrentLabel(row) }} · {{ shortId(row.effectiveVersion?.version_id, 8) }} · {{ versionSource(row.effectiveVersion) }}</b>
                  </div>
                </div>
              </article>
            </div>
          </aside>
        </div>
      </Transition>
    </Teleport>
  </section>
</template>

<style scoped>
.lobby-subtitle-stack {
  display: grid;
  width: max-content;
  max-width: calc(100vw - 42px);
  gap: 8px;
  justify-items: stretch;
}

.lobby-subtitle-stack > p {
  width: 100%;
  text-align: center;
}

.lobby-hero .lobby-version-panel {
  width: 100%;
  padding: 0;
  border: 0;
  background: transparent;
  box-shadow: none;
}

.lobby-hero .lobby-version-status {
  display: flex;
  width: 100%;
  align-items: center;
  justify-content: center;
  gap: 28px;
}

.lobby-hero .lobby-version-title {
  display: flex;
  flex: 0 1 auto;
  min-width: 0;
  min-height: 26px;
  align-items: center;
  justify-content: center;
  gap: 0;
  padding: 0;
}

.lobby-hero .lobby-version-title span::after {
  content: "：";
}

.lobby-hero .lobby-version-title strong {
  flex: 0 1 auto;
  font-size: 12px;
  line-height: 1;
}

.lobby-hero .lobby-version-title small {
  display: none;
}

.lobby-hero .lobby-version-actions {
  flex: 0 0 auto;
  gap: 4px;
}

.lobby-hero .lobby-version-actions button {
  height: 26px;
  padding: 0 4px;
  border: 0;
  color: rgba(244, 213, 142, 0.88);
  background: transparent;
  font-size: 12px;
  line-height: 1;
}

.lobby-hero .lobby-version-actions button:hover:not(:disabled) {
  color: #f4d58e;
  background: transparent;
}

.lobby-runtime-gate {
  grid-column: 1 / -1;
  display: grid;
  grid-template-columns: minmax(0, 1fr) auto;
  gap: 4px 12px;
  min-height: 0;
  padding: 10px 12px;
  border: 1px solid rgba(244, 213, 142, 0.3);
  border-radius: 8px;
  background: rgba(22, 12, 14, 0.72);
  color: #f5dfaa;
  box-shadow: 0 18px 38px rgba(0, 0, 0, 0.24);
}

.lobby-runtime-gate.error {
  border-color: rgba(219, 91, 73, 0.5);
  color: #ffd9c8;
}

.lobby-runtime-gate div {
  grid-column: 1;
  display: grid;
  gap: 2px;
  min-width: 0;
}

.lobby-runtime-gate small {
  grid-column: 1;
  min-width: 0;
  overflow-wrap: anywhere;
}

.lobby-runtime-gate span,
.lobby-runtime-gate small {
  color: rgba(244, 213, 142, 0.78);
  font-size: 11px;
}

.lobby-runtime-gate strong {
  min-width: 0;
  overflow-wrap: anywhere;
  color: inherit;
  font-size: 13px;
  line-height: 1.35;
}

.lobby-runtime-gate button {
  grid-column: 2;
  grid-row: 1 / span 2;
  align-self: start;
  height: 26px;
  padding: 0 8px;
  border: 1px solid rgba(244, 213, 142, 0.26);
  border-radius: 6px;
  background: rgba(244, 213, 142, 0.1);
  color: rgba(245, 223, 170, 0.82);
  font-size: 11px;
  font-weight: 800;
  cursor: pointer;
}

.lobby-runtime-gate button:hover {
  border-color: rgba(244, 213, 142, 0.42);
  color: #f5dfaa;
  background: rgba(244, 213, 142, 0.16);
}

.lobby-model-panel {
  grid-column: 1 / -1;
  display: block;
  min-width: 0;
}

.lobby-model-select {
  position: relative;
  min-width: 0;
}

.lobby-model-panel select {
  width: 100%;
  min-width: 0;
  height: 34px;
  padding: 0 10px;
  border: 1px solid rgba(224, 198, 128, 0.34);
  border-radius: 0;
  color: #f1e7cf;
  background: rgba(22, 12, 14, 0.78);
  font-size: 12px;
  font-weight: 850;
}

.lobby-model-panel select.has-inline-status {
  padding-right: 122px;
}

.lobby-model-select small {
  position: absolute;
  top: 50%;
  right: 30px;
  z-index: 1;
  color: #9fd6a9;
  font-size: 11px;
  font-weight: 900;
  line-height: 1;
  pointer-events: none;
  transform: translateY(-50%);
  white-space: nowrap;
}

:global(.lobby .card-fan) {
  transform: translateY(-76px);
}

.lobby-version-panel {
  display: grid;
  grid-column: 1 / -1;
  min-width: 0;
  padding: 10px 12px;
  border: 1px solid rgba(224, 198, 128, 0.36);
  border-radius: 0;
  color: #e5e2e1;
  background:
    linear-gradient(90deg, rgba(224, 198, 128, 0.08), transparent 45%),
    rgba(14, 14, 14, 0.92);
  box-shadow: inset 0 0 22px rgba(0, 0, 0, 0.52);
}

.lobby-version-panel.error {
  border-color: rgba(255, 180, 168, 0.64);
}

.lobby-version-panel.warning {
  border-color: rgba(238, 191, 91, 0.74);
}

.lobby-version-panel.success {
  border-color: rgba(224, 198, 128, 0.54);
}

.lobby-version-status {
  display: grid;
  grid-template-columns: minmax(0, 1fr) auto;
  align-items: center;
  gap: 12px;
  min-width: 0;
}

.lobby-version-title {
  display: grid;
  grid-template-columns: auto minmax(0, 1fr);
  gap: 5px;
  min-width: 0;
}

.lobby-version-title span {
  color: var(--lobby-accent);
  font-family: Anton, "Microsoft YaHei", Arial, sans-serif;
  font-size: 12px;
  font-weight: 800;
  letter-spacing: 0.08em;
  line-height: 1;
  text-transform: uppercase;
  white-space: nowrap;
}

.lobby-version-title strong {
  min-width: 0;
  overflow: hidden;
  color: rgba(229, 226, 225, 0.9);
  font-size: 13px;
  font-weight: 900;
  line-height: 1.3;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.lobby-version-title small {
  grid-column: 1 / -1;
  overflow: hidden;
  color: rgba(244, 213, 142, 0.8);
  font-size: 11px;
  font-weight: 850;
  line-height: 1.25;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.lobby-version-actions {
  display: flex;
  flex-wrap: wrap;
  justify-content: flex-end;
  gap: 6px;
  min-width: 0;
}

.lobby-version-actions button {
  flex: 0 0 auto;
  height: 28px;
  padding: 0 12px;
  border: 1px solid rgba(224, 198, 128, 0.46);
  border-radius: 0;
  color: #f1e7cf;
  background: rgba(38, 30, 26, 0.92);
  font-size: 12px;
  font-weight: 950;
  cursor: pointer;
}

.lobby-version-actions button:hover:not(:disabled) {
  border-color: rgba(238, 191, 91, 0.72);
  background: rgba(73, 50, 34, 0.96);
}

.lobby-version-actions button:disabled {
  cursor: default;
  opacity: 0.56;
}

.lobby-version-drawer-layer {
  position: fixed;
  inset: 0;
  z-index: 160;
  display: flex;
  justify-content: flex-end;
  min-width: 0;
  overflow: hidden;
}

.lobby-version-backdrop {
  position: absolute;
  inset: 0;
  padding: 0;
  border: 0;
  background: rgba(4, 4, 4, 0.68);
  backdrop-filter: blur(2px);
  cursor: pointer;
  transition: opacity 0.24s ease;
}

.lobby-version-drawer {
  position: relative;
  z-index: 1;
  display: flex;
  flex-direction: column;
  gap: 14px;
  width: min(640px, 94vw);
  height: 100%;
  min-width: 0;
  padding: 18px 18px 16px;
  border-left: 2px solid rgba(224, 198, 128, 0.42);
  color: #e5e2e1;
  background:
    linear-gradient(180deg, rgba(36, 30, 26, 0.96), rgba(11, 11, 11, 0.98)),
    #111;
  box-shadow: -24px 0 40px rgba(0, 0, 0, 0.5);
  overflow: hidden;
  transition: transform 0.28s cubic-bezier(0.22, 1, 0.36, 1), opacity 0.24s ease;
  will-change: transform, opacity;
}

.lobby-version-drawer-motion-enter-from,
.lobby-version-drawer-motion-leave-to {
  pointer-events: none;
}

.lobby-version-drawer-motion-enter-from .lobby-version-backdrop,
.lobby-version-drawer-motion-leave-to .lobby-version-backdrop {
  opacity: 0;
}

.lobby-version-drawer-motion-enter-from .lobby-version-drawer,
.lobby-version-drawer-motion-leave-to .lobby-version-drawer {
  opacity: 0.72;
  transform: translateX(104%);
}

.lobby-version-drawer-motion-leave-active .lobby-version-drawer {
  transition-duration: 0.2s;
  transition-timing-function: cubic-bezier(0.4, 0, 1, 1);
}

.lobby-version-drawer-motion-leave-active .lobby-version-backdrop {
  transition-duration: 0.2s;
}

.lobby-version-drawer-head {
  display: grid;
  grid-template-columns: minmax(0, 1fr) auto;
  align-items: start;
  gap: 12px;
  min-width: 0;
  padding-bottom: 12px;
  border-bottom: 1px solid rgba(224, 198, 128, 0.22);
}

.lobby-version-drawer-head div {
  display: grid;
  gap: 5px;
  min-width: 0;
}

.lobby-version-drawer-head span,
.lobby-version-mode-tabs button {
  color: rgba(227, 190, 184, 0.76);
  font-size: 11px;
  font-weight: 950;
  letter-spacing: 0.04em;
}

.lobby-version-drawer-head strong {
  color: #f1e7cf;
  font-size: 18px;
  font-weight: 950;
  line-height: 1.1;
}

.lobby-version-drawer-head small {
  color: rgba(229, 226, 225, 0.66);
  font-size: 12px;
  font-weight: 800;
  line-height: 1.35;
}

.lobby-version-drawer-head button {
  height: 30px;
  padding: 0 12px;
  border: 1px solid rgba(224, 198, 128, 0.38);
  border-radius: 0;
  color: #f1e7cf;
  background: rgba(18, 18, 18, 0.72);
  font-size: 12px;
  font-weight: 950;
  cursor: pointer;
}

.lobby-version-mode-tabs {
  display: grid;
  grid-template-columns: repeat(3, minmax(0, 1fr));
  min-width: 0;
  border: 1px solid rgba(90, 64, 60, 0.88);
}

.lobby-version-mode-tabs button {
  height: 34px;
  min-width: 0;
  border: 0;
  border-right: 1px solid rgba(90, 64, 60, 0.88);
  border-radius: 0;
  color: rgba(229, 226, 225, 0.72);
  background: rgba(10, 10, 10, 0.5);
  cursor: pointer;
}

.lobby-version-mode-tabs button:last-child {
  border-right: 0;
}

.lobby-version-mode-tabs button.active {
  color: #15110d;
  background: #e0c680;
}

.lobby-version-drawer-note {
  padding: 8px 10px;
  border: 1px solid rgba(238, 191, 91, 0.42);
  color: #f4d58e;
  background: rgba(95, 65, 24, 0.24);
  font-size: 12px;
  font-weight: 850;
  line-height: 1.4;
}

.lobby-version-drawer-list {
  display: grid;
  align-content: start;
  gap: 10px;
  flex: 1 1 auto;
  min-width: 0;
  min-height: 0;
  overflow-y: auto;
  overflow-x: hidden;
  padding-right: 6px;
  scrollbar-color: rgba(224, 198, 128, 0.44) rgba(10, 10, 10, 0.42);
}

.lobby-version-row {
  display: grid;
  grid-template-columns: minmax(0, 1fr);
  gap: 10px;
  min-width: 0;
  padding: 14px;
  border: 1px solid rgba(90, 64, 60, 0.82);
  border-radius: 0;
  background: rgba(10, 10, 10, 0.42);
}

.lobby-version-row[data-tone="override"] {
  border-color: rgba(145, 218, 170, 0.46);
}

.lobby-version-row[data-tone="fallback"] {
  border-color: rgba(238, 191, 91, 0.54);
}

.lobby-version-identity {
  display: grid;
  grid-template-columns: 36px minmax(0, 1fr) auto;
  align-items: center;
  gap: 10px;
  min-width: 0;
  padding-bottom: 10px;
  border-bottom: 1px solid rgba(90, 64, 60, 0.72);
}

.lobby-version-identity img {
  width: 36px;
  height: 36px;
  object-fit: contain;
}

.lobby-version-identity div,
.lobby-version-body,
.lobby-version-metrics span,
.lobby-version-select,
.lobby-version-lock,
.lobby-version-empty {
  display: grid;
  gap: 4px;
  min-width: 0;
}

.lobby-version-body {
  gap: 10px;
  overflow: hidden;
}

.lobby-version-identity b,
.lobby-version-metrics b,
.lobby-version-lock b,
.lobby-version-empty b {
  color: #f1e7cf;
  font-size: 12px;
  font-weight: 950;
  line-height: 1.35;
  overflow-wrap: anywhere;
}

.lobby-version-identity b {
  font-size: 14px;
  line-height: 1.1;
}

.lobby-version-identity em {
  display: inline-grid;
  align-items: center;
  min-width: 64px;
  height: 24px;
  padding: 0 8px;
  border: 1px solid rgba(224, 198, 128, 0.34);
  color: rgba(224, 198, 128, 0.76);
  background: rgba(224, 198, 128, 0.08);
  font-size: 10px;
  font-style: normal;
  font-weight: 950;
  line-height: 1;
  text-align: center;
  white-space: nowrap;
}

.lobby-version-identity small,
.lobby-version-metrics small,
.lobby-version-select span,
.lobby-version-lock small,
.lobby-version-empty small {
  color: rgba(227, 190, 184, 0.7);
  font-size: 10px;
  font-weight: 950;
  letter-spacing: 0.04em;
  line-height: 1.15;
}

.lobby-version-metrics {
  display: grid;
  grid-template-columns: repeat(2, minmax(0, 1fr));
  gap: 10px;
  min-width: 0;
}

.lobby-version-metrics span {
  min-height: 48px;
  padding: 9px 10px;
  border: 1px solid rgba(90, 64, 60, 0.58);
  background: rgba(7, 7, 7, 0.34);
}

.lobby-version-select,
.lobby-version-lock,
.lobby-version-empty {
  width: 100%;
  max-width: 100%;
  justify-content: stretch;
  overflow: hidden;
}

.lobby-version-select {
  position: relative;
}

.lobby-version-select::after {
  position: absolute;
  right: 12px;
  bottom: 13px;
  width: 7px;
  height: 7px;
  border-right: 2px solid rgba(224, 198, 128, 0.84);
  border-bottom: 2px solid rgba(224, 198, 128, 0.84);
  content: "";
  pointer-events: none;
  transform: rotate(45deg);
}

.lobby-version-select select {
  appearance: none;
  display: block;
  width: 100%;
  max-width: 100%;
  min-width: 0;
  height: 34px;
  padding: 0 30px 0 8px;
  border: 1px solid rgba(90, 64, 60, 0.9);
  border-radius: 0;
  color: #e5e2e1;
  background:
    linear-gradient(90deg, rgba(224, 198, 128, 0.1), transparent 34%),
    #0e0e0e;
  box-shadow: inset 0 0 14px rgba(0, 0, 0, 0.64);
  font-size: 12px;
  font-weight: 850;
  line-height: 34px;
  text-overflow: ellipsis;
  white-space: nowrap;
  cursor: pointer;
}

.lobby-version-select select:disabled {
  opacity: 0.54;
}

.lobby-version-select select:focus {
  outline: 2px solid rgba(224, 198, 128, 0.36);
  outline-offset: 1px;
}

.lobby-version-empty {
  min-height: 34px;
  padding: 8px 10px;
  border: 1px solid rgba(90, 64, 60, 0.58);
  color: rgba(229, 226, 225, 0.72);
  background: rgba(10, 10, 10, 0.34);
}

.lobby-version-empty b {
  color: rgba(229, 226, 225, 0.68);
}

@media (max-width: 1040px) {
  .lobby-version-row {
    grid-template-columns: minmax(0, 1fr);
  }

  .lobby-version-identity {
    grid-template-columns: 32px minmax(0, 1fr) auto;
  }

  .lobby-version-identity img {
    width: 32px;
    height: 32px;
  }
}

@media (max-width: 620px) {
  .lobby-version-status {
    grid-template-columns: 1fr;
  }

  .lobby-version-metrics {
    grid-template-columns: 1fr;
  }

  .lobby-version-actions {
    justify-content: flex-start;
  }

  .lobby-version-title strong {
    white-space: normal;
  }

  .lobby-version-title small {
    white-space: normal;
  }

  .lobby-version-drawer {
    width: 100vw;
    padding: 14px;
  }

  .lobby-version-drawer-head {
    grid-template-columns: minmax(0, 1fr);
  }

  .lobby-version-mode-tabs button {
    font-size: 10px;
  }

  .lobby-version-row {
    grid-template-columns: minmax(0, 1fr);
  }

  .lobby-version-identity {
    border-right: 0;
    border-bottom: 1px solid rgba(90, 64, 60, 0.78);
    padding: 0 0 10px;
  }
}
</style>
