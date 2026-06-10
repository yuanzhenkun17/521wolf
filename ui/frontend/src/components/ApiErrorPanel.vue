<script setup lang="ts">
import { computed } from 'vue'
import { formatApiErrorForDisplay } from '../composables/apiErrorDisplay.ts'

const props = defineProps({
  error: { type: [Object, String, Error], default: null },
  title: { type: String, default: '请求失败' },
  compact: Boolean,
  retryLabel: { type: String, default: '' },
  retryBusyLabel: { type: String, default: '重试中' },
  retrying: Boolean,
  retryDisabled: Boolean
})

const emit = defineEmits(['retry'])

const view = computed(() => formatApiErrorForDisplay(props.error, props.title))
const rootClass = computed(() => ['api-error-panel', { 'api-error-panel--compact': props.compact }])
const canRetry = computed(() => Boolean(props.retryLabel))
const retryText = computed(() => (props.retrying || props.retryDisabled) ? props.retryBusyLabel : props.retryLabel)

function handleRetry() {
  if (props.retryDisabled || props.retrying) return
  emit('retry')
}
</script>

<template>
  <section :class="rootClass" role="alert" aria-live="polite">
    <header>
      <div class="api-error-panel__heading">
        <strong>{{ view.message }}</strong>
        <small v-if="view.code || view.status">
          <span v-if="view.code">{{ view.code }}</span>
          <span v-if="view.status">HTTP {{ view.status }}</span>
        </small>
      </div>
      <div v-if="view.requestId || canRetry" class="api-error-panel__actions">
        <code v-if="view.requestId">request {{ view.requestId }}</code>
        <button
          v-if="canRetry"
          type="button"
          class="api-error-panel__retry"
          :disabled="retryDisabled || retrying"
          @click="handleRetry"
        >
          {{ retryText }}
        </button>
      </div>
    </header>

    <p v-if="view.detail && view.detail !== view.message">{{ view.detail }}</p>

    <details v-if="view.hasDiagnostics" :open="!compact">
      <summary>诊断明细 {{ view.diagnostics.length }}</summary>
      <ul>
        <li v-for="item in view.diagnostics" :key="item.key">
          <b>{{ item.label }}</b>
          <span v-if="item.message">{{ item.message }}</span>
          <small v-if="item.meta.length">{{ item.meta.join(' · ') }}</small>
        </li>
      </ul>
    </details>
  </section>
</template>

<style scoped>
.api-error-panel {
  display: grid;
  gap: 10px;
  min-width: 0;
  padding: 12px 14px;
  border: 1px solid var(--status-danger, #a13d36);
  border-radius: 8px;
  background: color-mix(in srgb, var(--status-danger, #a13d36) 9%, #fff);
  color: var(--text-main, #2c1d16);
}

.api-error-panel--compact {
  gap: 6px;
  padding: 9px 11px;
}

.api-error-panel header {
  display: flex;
  align-items: flex-start;
  justify-content: space-between;
  gap: 12px;
  min-width: 0;
}

.api-error-panel__heading {
  display: grid;
  gap: 4px;
  min-width: 0;
}

.api-error-panel__actions {
  display: flex;
  flex: 0 1 auto;
  flex-wrap: wrap;
  align-items: flex-start;
  justify-content: flex-end;
  gap: 6px;
  min-width: 0;
}

.api-error-panel strong {
  color: var(--status-danger, #8b1f1a);
  font-size: 14px;
  line-height: 1.35;
}

.api-error-panel small,
.api-error-panel code,
.api-error-panel p,
.api-error-panel summary,
.api-error-panel li span {
  overflow-wrap: anywhere;
}

.api-error-panel header small {
  display: flex;
  flex-wrap: wrap;
  gap: 6px;
  color: var(--text-muted, #6b5d54);
  font-size: 12px;
  font-weight: 800;
}

.api-error-panel code {
  flex: 0 1 auto;
  max-width: 240px;
  padding: 2px 6px;
  border-radius: 5px;
  background: rgba(0, 0, 0, 0.06);
  color: var(--text-muted, #6b5d54);
  font-size: 11px;
}

.api-error-panel__retry {
  flex: 0 0 auto;
  min-height: 24px;
  padding: 0 10px;
  border: 1px solid color-mix(in srgb, var(--status-danger, #a13d36) 84%, #1f1f1f);
  border-radius: 6px;
  background: var(--status-danger, #a13d36);
  color: #fff;
  font-size: 12px;
  font-weight: 900;
  cursor: pointer;
}

.api-error-panel__retry:hover:not(:disabled) {
  background: color-mix(in srgb, var(--status-danger, #a13d36) 86%, #1f1f1f);
}

.api-error-panel__retry:disabled {
  opacity: 0.52;
  cursor: not-allowed;
}

.api-error-panel p {
  margin: 0;
  color: var(--text-muted, #6b5d54);
  font-size: 13px;
  line-height: 1.45;
}

.api-error-panel details {
  display: grid;
  gap: 8px;
}

.api-error-panel summary {
  cursor: pointer;
  color: var(--status-danger, #8b1f1a);
  font-size: 12px;
  font-weight: 900;
}

.api-error-panel ul {
  display: grid;
  gap: 6px;
  margin: 8px 0 0;
  padding: 0;
  list-style: none;
}

.api-error-panel li {
  display: grid;
  gap: 3px;
  min-width: 0;
  padding: 8px;
  border-radius: 6px;
  background: rgba(255, 255, 255, 0.56);
}

.api-error-panel li b {
  color: var(--text-main, #2c1d16);
  font-size: 12px;
}

.api-error-panel li span,
.api-error-panel li small {
  color: var(--text-muted, #6b5d54);
  font-size: 12px;
  line-height: 1.35;
}
</style>
