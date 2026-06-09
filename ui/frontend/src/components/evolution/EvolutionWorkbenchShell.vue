<script setup>
import { computed } from 'vue'
import ApiErrorPanel from '../ApiErrorPanel.vue'
import { inlineNoticeForDisplay, noticeErrorForPanel } from '../../composables/apiErrorDisplay.js'

const props = defineProps({
  title: { type: String, required: true },
  tabs: { type: Array, default: () => [] },
  activeTab: { type: String, required: true },
  roles: { type: Array, default: () => [] },
  selectedRole: { type: String, default: '' },
  selectedRunSummary: { type: Object, default: null },
  error: { type: [String, Object, Error], default: '' },
  notice: { type: Object, default: null }
})

const emit = defineEmits(['update:activeTab', 'refresh', 'select-role'])

const selectedRoleRow = computed(() =>
  props.roles.find((role) => role.key === props.selectedRole) || props.roles[0] || null
)

const activeTabLabel = computed(() =>
  props.tabs.find((tab) => tab.key === props.activeTab)?.label || '—'
)

const runSummary = computed(() => props.selectedRunSummary || {})
const refreshRetrying = computed(() => Boolean(runSummary.value.loading))
const refreshRetryDisabled = computed(() => Boolean(runSummary.value.loading || runSummary.value.actionLoading))
const pageNotice = computed(() => {
  if (props.notice?.message) return props.notice
  if (props.error) return { type: 'error', message: props.error?.message || props.error, error: props.error }
  return null
})
const inlineNotice = computed(() => inlineNoticeForDisplay(pageNotice.value))
const errorNotice = computed(() => noticeErrorForPanel(pageNotice.value))

function progressPercent(value) {
  const number = Number(value)
  if (!Number.isFinite(number)) return 0
  return Math.max(0, Math.min(100, Math.round(number)))
}

function retryRefresh() {
  if (refreshRetryDisabled.value) return
  emit('refresh')
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
          <ApiErrorPanel
            v-if="errorNotice"
            class="evo-error-panel"
            :error="errorNotice"
            title="自进化操作失败"
            retry-label="重试刷新"
            retry-busy-label="刷新中"
            :retrying="refreshRetrying"
            :retry-disabled="refreshRetryDisabled"
            compact
            @retry="retryRefresh"
          />
          <div v-else-if="inlineNotice" :class="['evo-alert', inlineNotice.type]">{{ inlineNotice.message }}</div>
          <slot />
        </div>
      </section>
    </main>
  </section>
</template>
