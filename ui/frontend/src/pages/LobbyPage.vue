<script setup>
import { computed, onMounted, ref, watch } from 'vue'
import { roleLabel, shortId, sourceText } from '../composables/workbenchShared.js'

const props = defineProps({
  backendMode: { type: String, default: 'mock' },
  externalStatus: { type: Object, default: null },
  loading: Boolean,
  playerCount: { type: Number, default: 12 },
  apiFetch: { type: Function, default: null }
})

const emit = defineEmits(['start-mode'])
const backendAvailable = computed(() => props.backendMode !== 'offline')
const supportsHuman = computed(() => props.externalStatus?.supports_human !== false)
const isMock = computed(() => props.backendMode === 'mock')
const roles = ref([])
const versionsByRole = ref({})
const roleVersionSelections = ref({})
const registryLoading = ref(false)
const registryError = ref('')

const roleRows = computed(() => roles.value
  .map((role) => ({
    role,
    label: roleLabel(role, role),
    versions: versionsByRole.value[role] || []
  }))
  .filter((row) => row.versions.length)
)
const selectedRoleVersions = computed(() =>
  Object.fromEntries(
    Object.entries(roleVersionSelections.value)
      .filter(([, versionId]) => versionId)
  )
)
const selectedOverrideCount = computed(() => Object.keys(selectedRoleVersions.value).length)

function roleVersionLabel(version) {
  const source = version.source || (version.is_baseline ? 'baseline' : 'version')
  const id = shortId(version.version_id, 12)
  return `${version.is_baseline ? '当前基线 · ' : ''}${id} · ${sourceText(source)}`
}

function start(mode) {
  const body = {
    player_count: Number(props.playerCount) || 12,
    human_player_id: mode === 'play' ? 1 : null
  }
  if (selectedOverrideCount.value) body.role_versions = selectedRoleVersions.value
  emit('start-mode', { mode, options: body })
}

async function loadRoleVersions() {
  if (!props.apiFetch || !backendAvailable.value) return
  registryLoading.value = true
  registryError.value = ''
  try {
    const roleData = await props.apiFetch('/roles')
    const nextRoles = roleData.roles || []
    const entries = await Promise.all(nextRoles.map(async (role) => {
      try {
        const data = await props.apiFetch(`/roles/${encodeURIComponent(role)}/versions`)
        return [role, data.versions || []]
      } catch {
        return [role, []]
      }
    }))
    roles.value = nextRoles
    versionsByRole.value = Object.fromEntries(entries)
    roleVersionSelections.value = Object.fromEntries(
      nextRoles.map((role) => [role, roleVersionSelections.value[role] || ''])
    )
  } catch (err) {
    roles.value = []
    versionsByRole.value = {}
    registryError.value = err?.message || '角色版本读取失败'
  } finally {
    registryLoading.value = false
  }
}

onMounted(loadRoleVersions)
watch(() => props.backendMode, () => {
  loadRoleVersions()
})
</script>

<template>
  <section class="lobby">
    <section class="lobby-hero">
      <span class="hero-mark"></span>
      <h1>黑夜将至</h1>
      <p>召集议会。不要轻信任何人。</p>
    </section>

    <section class="card-fan" aria-label="角色牌">
      <figure class="role-card-art werewolf" aria-label="狼人角色牌">
        <img class="lobby-card-image" src="/lobby-cards/werewolf.png" alt="" />
        <img class="lobby-card-frame" src="/lobby-cards/frame.png" alt="" />
      </figure>
      <figure class="role-card-art villager" aria-label="村民角色牌">
        <img class="lobby-card-image" src="/lobby-cards/villager.png" alt="" />
        <img class="lobby-card-frame" src="/lobby-cards/frame.png" alt="" />
      </figure>
      <figure class="role-card-art judge" aria-label="法官角色牌">
        <img class="lobby-card-image" src="/lobby-cards/judge.png" alt="" />
        <img class="lobby-card-frame" src="/lobby-cards/frame.png" alt="" />
      </figure>
      <figure class="role-card-art hunter" aria-label="猎人角色牌">
        <img class="lobby-card-image" src="/lobby-cards/hunter.png" alt="" />
        <img class="lobby-card-frame" src="/lobby-cards/frame.png" alt="" />
      </figure>
      <figure class="role-card-art witch" aria-label="女巫角色牌">
        <img class="lobby-card-image" src="/lobby-cards/witch.png" alt="" />
        <img class="lobby-card-frame" src="/lobby-cards/frame.png" alt="" />
      </figure>
    </section>

    <section class="lobby-actions">
      <button class="mode-card watch" :disabled="loading || !backendAvailable" @click="start('watch')">
        <span>{{ isMock ? '观战模式' : '真实后端' }}</span>
        <strong>{{ backendAvailable ? (isMock ? '观看智能体对局' : '连接本地后端对局') : '后端未连接' }}</strong>
      </button>
      <button class="mode-card play" :disabled="loading || !backendAvailable || !supportsHuman" @click="start('play')">
        <span>玩家模式</span>
        <strong>{{ supportsHuman ? '加入智能体对局' : '后端暂不支持加入' }}</strong>
      </button>
    </section>
  </section>
</template>
