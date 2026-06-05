<script setup>
import { computed, onMounted, ref, watch } from 'vue'

const ROLE_LABELS = {
  white_wolf_king: '白狼王',
  werewolf: '狼人',
  villager: '村民',
  seer: '预言家',
  witch: '女巫',
  hunter: '猎人',
  guard: '守卫'
}

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
const settings = ref({
  seed: '',
  skill_dir: ''
})
const roles = ref([])
const versionsByRole = ref({})
const roleVersionSelections = ref({})
const registryLoading = ref(false)
const registryError = ref('')

const roleRows = computed(() => roles.value
  .map((role) => ({
    role,
    label: ROLE_LABELS[role] || role,
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
  return `${version.is_baseline ? '当前 baseline · ' : ''}${id} · ${source}`
}

function shortId(value, length = 10) {
  return value ? String(value).slice(0, length) : '—'
}

function optionalSeed() {
  if (settings.value.seed === '' || settings.value.seed == null) return undefined
  const seed = Number(settings.value.seed)
  return Number.isInteger(seed) ? seed : undefined
}

function start(mode) {
  const body = {
    player_count: Number(props.playerCount) || 12,
    human_player_id: mode === 'play' ? 1 : null
  }
  const seed = optionalSeed()
  const skillDir = String(settings.value.skill_dir || '').trim()
  if (seed !== undefined) body.seed = seed
  if (skillDir) body.skill_dir = skillDir
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
      <h1>The Night Approaches</h1>
      <p>Gather the council. Trust no one.</p>
    </section>

    <section class="card-fan" aria-label="NightCouncil roles">
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
      <article class="lobby-start-panel" aria-label="开局参数">
        <div class="lobby-settings-grid">
          <label>
            <span>Seed</span>
            <input v-model="settings.seed" type="number" inputmode="numeric" placeholder="随机" />
          </label>
          <label>
            <span>技能目录</span>
            <input v-model="settings.skill_dir" placeholder="默认 baseline" />
          </label>
        </div>

        <details class="lobby-role-versions">
          <summary>
            <span>角色版本覆盖</span>
            <b>{{ selectedOverrideCount || 'baseline' }}</b>
          </summary>

          <div v-if="registryLoading" class="lobby-version-note">读取版本...</div>
          <div v-else-if="registryError" class="lobby-version-note error">{{ registryError }}</div>
          <div v-else-if="!roleRows.length" class="lobby-version-note">暂无 registry 版本</div>
          <div v-else class="lobby-version-grid">
            <label v-for="row in roleRows" :key="row.role">
              <span>{{ row.label }}</span>
              <select v-model="roleVersionSelections[row.role]">
                <option value="">当前 baseline</option>
                <option
                  v-for="version in row.versions"
                  :key="version.version_id"
                  :value="version.version_id"
                >
                  {{ roleVersionLabel(version) }}
                </option>
              </select>
            </label>
          </div>
        </details>
      </article>

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
