<script setup>
import { computed } from 'vue'

const props = defineProps({
  title: { type: String, required: true },
  tabs: { type: Array, default: () => [] },
  activeTab: { type: String, required: true },
  roles: { type: Array, default: () => [] },
  selectedRole: { type: String, default: '' },
  selectedRunSummary: { type: Object, default: null },
  error: { type: String, default: '' }
})

const emit = defineEmits(['update:activeTab', 'refresh', 'select-role'])

const selectedRoleRow = computed(() =>
  props.roles.find((role) => role.key === props.selectedRole) || props.roles[0] || null
)

const activeTabLabel = computed(() =>
  props.tabs.find((tab) => tab.key === props.activeTab)?.label || '—'
)

const runSummary = computed(() => props.selectedRunSummary || {})

function progressPercent(value) {
  const number = Number(value)
  if (!Number.isFinite(number)) return 0
  return Math.max(0, Math.min(100, Math.round(number)))
}
</script>

<template>
  <section class="evo-shell parchment-logbook">
    <aside class="evo-control-rail" aria-label="进化角色">
      <header class="evo-rail-header">
        <span>角色上下文</span>
      </header>

      <div class="evo-rail-summary">
        <span>
          <small>知识库</small>
          <b>{{ selectedRoleRow?.label || '—' }}</b>
        </span>
        <span>
          <small>基线</small>
          <b>{{ selectedRoleRow?.baselineShort || '—' }}</b>
        </span>
      </div>

      <div class="evo-role-panel" aria-label="知识库角色上下文">
        <span class="evo-role-bar-label">知识库角色</span>
        <div class="evo-role-list">
          <button
            v-for="role in roles"
            :key="role.key"
            type="button"
            :class="['evo-role-chip', { selected: selectedRole === role.key }]"
            @click="emit('select-role', role.key)"
          >
            <img :src="role.image" alt="" aria-hidden="true" />
            <span class="evo-role-name">{{ role.label }}</span>
          </button>
        </div>
      </div>
    </aside>

    <main class="evo-detail-panel">
      <header class="evo-command-bar">
        <div class="evo-command-title">
          <h2>{{ title }}工作台</h2>
        </div>
        <div class="evo-command-actions">
          <button type="button" class="evo-refresh-button" @click="emit('refresh')">
            <span aria-hidden="true">&#8635;</span> 刷新
          </button>
        </div>
      </header>

      <div class="evo-detail-topbar">
        <nav class="evo-nav detail-workspace-tabs" aria-label="自进化视图">
          <button
            v-for="tab in tabs"
            :key="tab.key"
            type="button"
            :class="['evo-nav-tab', { active: activeTab === tab.key }]"
            @click="emit('update:activeTab', tab.key)"
          >
            <span>{{ tab.label }}</span>
          </button>
        </nav>
      </div>

      <section class="evo-main-pane">
        <div class="evo-scroll">
          <div v-if="error" class="evo-alert">{{ error }}</div>
          <slot />
        </div>
      </section>
    </main>
  </section>
</template>
