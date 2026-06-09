<script setup lang="ts">
// @ts-nocheck
import { computed, useSlots } from 'vue'

const props = defineProps({
  title: { type: String, required: true },
  eyebrow: { type: String, default: 'Lab' },
  workbenchKey: { type: String, default: 'lab' },
  ariaLabel: { type: String, default: '' },
  bridge: { type: Boolean, default: false },
  tabs: { type: Array, default: () => [] },
  activeTab: { type: String, default: '' },
  tabsLabel: { type: String, default: 'Lab workbench views' },
  boundaryLabel: { type: String, default: 'Lab boundary' },
  railLabel: { type: String, default: 'Lab context rail' },
  contextLabel: { type: String, default: 'Lab context panel' },
  actionLabel: { type: String, default: '刷新' },
  actionBusyLabel: { type: String, default: '刷新中' },
  actionBusy: { type: Boolean, default: false },
  actionDisabled: { type: Boolean, default: false },
  meta: { type: Array, default: () => [] },
  mainLabel: { type: String, default: '' },
  showHeader: { type: Boolean, default: true }
})

const emit = defineEmits(['update:activeTab', 'action'])
const slots = useSlots()
const hasContext = computed(() => Boolean(slots.context))
const hasTabsActions = computed(() => Boolean(slots['tabs-actions']))

const rootClass = computed(() => [
  props.bridge ? 'lab-workbench-bridge' : 'lab-workbench-shell',
  `lab-workbench-shell--${props.workbenchKey || 'lab'}`,
  { 'lab-workbench-shell--has-context': hasContext.value }
])

const resolvedAriaLabel = computed(() =>
  props.ariaLabel || `${props.title} Lab 工作台`
)

const activeTabLabel = computed(() =>
  props.tabs.find((tab) => tab.key === props.activeTab)?.label || props.title
)

function selectTab(tab) {
  if (!tab?.key || tab.disabled) return
  emit('update:activeTab', tab.key)
}
</script>

<template>
  <section
    :class="rootClass"
    :data-lab-workbench="workbenchKey"
    :aria-label="resolvedAriaLabel"
  >
    <slot v-if="bridge" />

    <template v-else>
      <aside v-if="slots.rail" class="lab-workbench-rail" :aria-label="railLabel">
        <slot name="rail" />
      </aside>

      <main class="lab-workbench-main">
        <header v-if="showHeader" class="lab-workbench-action-bar" :aria-label="`${title} 操作区`">
          <div class="lab-workbench-title">
            <small>{{ eyebrow }}</small>
            <h1>{{ title }}</h1>
          </div>

          <div v-if="slots.meta || meta.length" class="lab-workbench-meta" aria-label="Lab boundary summary">
            <slot name="meta">
              <span
                v-for="item in meta"
                :key="item.key || item.label"
                :data-tone="item.tone || 'neutral'"
              >
                <small>{{ item.label }}</small>
                <b :title="String(item.value || '')">{{ item.value }}</b>
              </span>
            </slot>
          </div>

          <div class="lab-workbench-action-area">
            <slot name="actions">
              <button
                type="button"
                class="lab-workbench-primary-action"
                :disabled="actionDisabled || actionBusy"
                @click="emit('action')"
              >
                {{ actionBusy ? actionBusyLabel : actionLabel }}
              </button>
            </slot>
          </div>
        </header>

        <section
          v-if="slots.boundary"
          class="lab-workbench-boundary-bar"
          :aria-label="boundaryLabel"
        >
          <slot name="boundary" />
        </section>

        <nav
          v-if="tabs.length"
          class="lab-workbench-tabs"
          :aria-label="tabsLabel"
          data-lab-tabs
        >
          <button
            v-for="tab in tabs"
            :key="tab.key"
            type="button"
            :class="['lab-workbench-tab', { active: activeTab === tab.key }]"
            :aria-current="activeTab === tab.key ? 'page' : undefined"
            :disabled="Boolean(tab.disabled)"
            @click="selectTab(tab)"
          >
            <span>{{ tab.label }}</span>
          </button>
          <div v-if="hasTabsActions" class="lab-workbench-tabs-actions">
            <slot name="tabs-actions" />
          </div>
        </nav>

        <section v-if="slots.notice" class="lab-workbench-notice-area" aria-label="Lab notice">
          <slot name="notice" />
        </section>

        <section class="lab-workbench-main-pane" :aria-label="mainLabel || `${activeTabLabel} 主面板`">
          <slot />
        </section>
      </main>

      <aside v-if="hasContext" class="lab-workbench-context" :aria-label="contextLabel">
        <slot name="context" />
      </aside>
    </template>
  </section>
</template>

<style scoped>
.lab-workbench-bridge {
  display: contents;
}

.lab-workbench-shell {
  --lab-bg: var(--bench-bg, var(--evo-bg, var(--logbook-bg, #f2dfae)));
  --lab-panel: var(--bench-panel, var(--evo-surface, var(--logbook-panel, rgba(255, 252, 245, 0.82))));
  --lab-border: var(--bench-border, var(--evo-border, var(--logbook-border, rgba(93, 48, 17, 0.18))));
  --lab-border-strong: var(--bench-border-strong, var(--evo-border-strong, var(--logbook-border-strong, rgba(93, 48, 17, 0.34))));
  --lab-text: var(--bench-text, var(--evo-text, var(--logbook-text, #3a2a18)));
  --lab-muted: var(--bench-text-secondary, var(--evo-text-secondary, var(--logbook-muted, rgba(93, 48, 17, 0.66))));
  --lab-accent: var(--bench-accent-strong, var(--evo-accent-strong, var(--logbook-accent-strong, #5a3319)));
  --lab-active-bg: var(--bench-active-bg, var(--evo-active-bg, var(--logbook-active-bg, rgba(139, 94, 52, 0.1))));
  --lab-danger: var(--bench-danger, var(--evo-danger, var(--logbook-danger, #993026)));
  display: grid;
  grid-template-columns: var(--lab-rail-width, 316px) minmax(0, 1fr);
  gap: 14px;
  width: 100%;
  height: 100%;
  min-width: 0;
  min-height: 0;
  padding: 14px;
  overflow: hidden;
  background: transparent;
}

.lab-workbench-shell--has-context {
  grid-template-columns:
    var(--lab-rail-width, 316px)
    minmax(0, 1fr)
    var(--lab-context-width, 320px);
}

.lab-workbench-shell *:not(svg):not(svg *) {
  box-sizing: border-box;
}

.lab-workbench-rail,
.lab-workbench-main,
.lab-workbench-context,
.lab-workbench-main-pane {
  min-width: 0;
  min-height: 0;
}

.lab-workbench-rail {
  overflow: hidden;
}

.lab-workbench-context {
  overflow: hidden;
  overflow-x: hidden;
  overflow-y: auto;
  overscroll-behavior: contain;
  scrollbar-gutter: stable;
}

.lab-workbench-main {
  display: grid;
  grid-template-rows: auto auto auto auto minmax(0, 1fr);
  gap: 10px;
  overflow: hidden;
}

.lab-workbench-action-bar {
  display: grid;
  grid-template-columns: minmax(168px, 0.58fr) minmax(0, 1.42fr) auto;
  align-items: center;
  gap: 12px;
  min-width: 0;
  padding: 10px 12px;
  border: 1px solid var(--lab-border);
  border-radius: 8px;
  background: var(--lab-panel);
  box-shadow: 0 2px 8px rgba(91, 47, 18, 0.08);
}

.lab-workbench-title {
  display: grid;
  gap: 2px;
  min-width: 0;
}

.lab-workbench-title small,
.lab-workbench-meta small {
  color: var(--lab-muted);
  font-size: 11px;
  font-weight: 850;
  letter-spacing: 0;
}

.lab-workbench-title h1 {
  min-width: 0;
  overflow: hidden;
  margin: 0;
  color: var(--lab-text);
  font-size: 22px;
  font-weight: 950;
  line-height: 1.05;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.lab-workbench-meta {
  display: grid;
  grid-template-columns: repeat(3, minmax(0, 1fr));
  gap: 8px;
  min-width: 0;
}

.lab-workbench-meta span {
  display: grid;
  gap: 3px;
  min-width: 0;
  min-height: 42px;
  padding: 7px 9px;
  border: 1px solid var(--lab-border);
  border-radius: 6px;
  background: rgba(255, 248, 226, 0.58);
}

.lab-workbench-meta span[data-tone="danger"] {
  border-color: rgba(153, 48, 38, 0.32);
  background: rgba(153, 48, 38, 0.06);
}

.lab-workbench-meta b {
  min-width: 0;
  overflow: hidden;
  color: var(--lab-text);
  font-size: 12px;
  font-weight: 900;
  line-height: 1.2;
  overflow-wrap: anywhere;
}

.lab-workbench-action-area {
  display: flex;
  justify-content: flex-end;
  min-width: 0;
}

.lab-workbench-primary-action {
  display: inline-flex;
  align-items: center;
  justify-content: center;
  height: 36px;
  min-width: 78px;
  padding: 0 14px;
  border: 1px solid var(--lab-accent);
  border-radius: 6px;
  background: var(--lab-accent);
  color: #fff7dc;
  font-size: 13px;
  font-weight: 900;
  cursor: pointer;
  white-space: nowrap;
}

.lab-workbench-primary-action:disabled {
  opacity: 0.48;
  cursor: not-allowed;
}

.lab-workbench-boundary-bar {
  display: grid;
  gap: 8px;
  min-width: 0;
}

.lab-workbench-tabs {
  display: flex;
  align-items: center;
  gap: 6px;
  min-width: 0;
  overflow-x: auto;
  padding: 4px;
  border: 1px solid var(--lab-border);
  border-radius: 8px;
  background: var(--lab-panel);
  scrollbar-width: none;
}

.lab-workbench-tabs-actions {
  position: sticky;
  right: 0;
  z-index: 1;
  display: flex;
  flex: 0 0 auto;
  justify-content: flex-end;
  margin-left: auto;
  padding-left: 8px;
  background: var(--lab-panel);
}

.lab-workbench-tabs-actions .lab-workbench-primary-action {
  height: 32px;
}

.lab-workbench-tabs::-webkit-scrollbar {
  display: none;
}

.lab-workbench-tab {
  display: inline-flex;
  flex: 0 0 auto;
  align-items: center;
  justify-content: center;
  height: 32px;
  min-width: 0;
  padding: 0 14px;
  border: 1px solid transparent;
  border-radius: 6px;
  background: transparent;
  color: var(--lab-muted);
  font-size: 12px;
  font-weight: 900;
  cursor: pointer;
}

.lab-workbench-tab span {
  min-width: 0;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.lab-workbench-tab.active {
  border-color: var(--lab-border-strong);
  background: var(--lab-active-bg);
  color: var(--lab-accent);
}

.lab-workbench-tab:disabled {
  opacity: 0.48;
  cursor: not-allowed;
}

.lab-workbench-notice-area {
  display: grid;
  gap: 8px;
  min-width: 0;
}

.lab-workbench-main-pane {
  display: grid;
  align-content: start;
  min-width: 0;
  min-height: 0;
  overflow: hidden;
  overflow-x: auto;
  overflow-y: auto;
  overscroll-behavior: contain;
  scrollbar-gutter: stable;
}

@media (max-width: 1120px) {
  .lab-workbench-shell {
    grid-template-columns: minmax(236px, 280px) minmax(0, 1fr);
  }

  .lab-workbench-action-bar {
    grid-template-columns: minmax(0, 1fr) auto;
  }

  .lab-workbench-meta {
    grid-column: 1 / -1;
  }
}

@media (max-width: 960px) {
  .lab-workbench-shell {
    grid-template-columns: minmax(0, 1fr);
    grid-template-rows: auto minmax(0, 1fr);
    gap: 10px;
    padding: 12px;
    overflow-x: hidden;
    overflow-y: auto;
  }

  .lab-workbench-rail {
    max-height: 220px;
    overflow: auto;
  }

  .lab-workbench-main {
    overflow: visible;
  }

  .lab-workbench-main-pane {
    overflow: visible;
  }
}

@media (max-width: 640px) {
  .lab-workbench-shell {
    padding: 10px;
  }

  .lab-workbench-action-bar {
    grid-template-columns: minmax(0, 1fr) auto;
    gap: 8px;
    padding: 9px;
  }

  .lab-workbench-title h1 {
    font-size: 18px;
  }

  .lab-workbench-title small {
    display: none;
  }

  .lab-workbench-meta {
    grid-template-columns: repeat(3, minmax(0, 1fr));
    gap: 5px;
  }

  .lab-workbench-meta span {
    min-height: 34px;
    padding: 5px 6px;
  }

  .lab-workbench-meta small {
    font-size: 9px;
  }

  .lab-workbench-meta b {
    font-size: 11px;
  }

  .lab-workbench-tabs {
    display: grid;
    grid-template-columns: repeat(auto-fit, minmax(58px, 1fr));
    gap: 5px;
  }

  .lab-workbench-tab {
    width: 100%;
    height: 30px;
    padding: 0 6px;
  }
}
</style>
