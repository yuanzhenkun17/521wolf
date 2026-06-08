<script setup>
import { computed, onMounted, ref } from 'vue'
import { useEvolutionWorkbench } from '../composables/useEvolutionWorkbench.js'
import EvolutionConsolePanel from '../components/evolution/EvolutionConsolePanel.vue'
import EvolutionEventsPanel from '../components/evolution/EvolutionEventsPanel.vue'
import EvolutionLeaderboardPanel from '../components/evolution/EvolutionLeaderboardPanel.vue'
import EvolutionProposalReviewPanel from '../components/evolution/EvolutionProposalReviewPanel.vue'
import EvolutionRunsPanel from '../components/evolution/EvolutionRunsPanel.vue'
import EvolutionSamplesPanel from '../components/evolution/EvolutionSamplesPanel.vue'
import EvolutionVersionsPanel from '../components/evolution/EvolutionVersionsPanel.vue'
import EvolutionWorkbenchShell from '../components/evolution/EvolutionWorkbenchShell.vue'

defineOptions({
  inheritAttrs: false
})

defineProps({
  returnToMatchAvailable: Boolean
})

const emit = defineEmits(['back-to-match', 'open-sample-log', 'replay-sample-game'])

const evo = useEvolutionWorkbench()

const activeTab = ref('console')

const navTabs = [
  { key: 'console', label: '控制台', icon: '⚙' },
  { key: 'review', label: '审核', icon: '✓' },
  { key: 'runs', label: '运行', icon: '▶' },
  { key: 'leaderboard', label: '排行榜', icon: '📊' },
  { key: 'versions', label: '版本', icon: '📋' },
  { key: 'events', label: '事件', icon: '⚡' },
  { key: 'samples', label: '样本局', icon: '🎲' }
]

const selectedIsBatch = computed(() => evo.selectedIsBatch.value)
const selectedCanReview = computed(() => evo.selectedIsRun.value && evo.selectedRun.value?.status === 'reviewing')
const selectedCanTerminate = computed(() => {
  return Boolean(evo.selectedRun.value) && !evo.selectedRun.value.isTerminal
})

onMounted(() => evo.refreshAll())
</script>

<template>
  <section class="evo-page" aria-label="自进化">
    <EvolutionWorkbenchShell
      v-model:active-tab="activeTab"
      title="自进化"
      :tabs="navTabs"
      :roles="evo.roleRows.value"
      :selected-role="evo.selectedRole.value"
      :selected-run-summary="evo.selectedRunSummary.value"
      :error="evo.error.value"
      @refresh="evo.refreshAll()"
      @select-role="evo.selectRole"
    >
      <EvolutionConsolePanel
        v-if="activeTab === 'console'"
        :evo="evo"
        :selected-is-batch="selectedIsBatch"
        :selected-can-review="selectedCanReview"
        :selected-can-terminate="selectedCanTerminate"
      />
      <EvolutionRunsPanel v-if="activeTab === 'runs'" :evo="evo" />
      <EvolutionProposalReviewPanel v-if="activeTab === 'review'" :evo="evo" />
      <EvolutionLeaderboardPanel v-if="activeTab === 'leaderboard'" :evo="evo" />
      <EvolutionVersionsPanel v-if="activeTab === 'versions'" :evo="evo" />
      <EvolutionEventsPanel v-if="activeTab === 'events'" :evo="evo" />
      <EvolutionSamplesPanel
        v-if="activeTab === 'samples'"
        :evo="evo"
        @open-sample-log="emit('open-sample-log', $event)"
        @replay-sample-game="emit('replay-sample-game', $event)"
      />
    </EvolutionWorkbenchShell>
  </section>
</template>

<style>
/* ========================================
   Design Tokens
   ======================================== */
.evo-page {
  --evo-bg: #f8f0e0;
  --evo-surface: rgba(255, 252, 245, 0.7);
  --evo-border: rgba(139, 94, 52, 0.15);
  --evo-text: #3a2a18;
  --evo-text-secondary: #8b6b4a;
  --evo-accent: #8b5e34;
  --evo-accent-strong: #5a3319;
  --evo-input-bg: rgba(255, 255, 250, 0.8);
  --evo-input-border: rgba(139, 94, 52, 0.2);
  --evo-hover: rgba(139, 94, 52, 0.06);
  --evo-active-bg: rgba(139, 94, 52, 0.1);
  --evo-success: #4a7c44;
  --evo-danger: #8b3a2a;
  --evo-font: "Microsoft YaHei", "PingFang SC", "Noto Sans SC", -apple-system, BlinkMacSystemFont, sans-serif;
}

/* ========================================
   Layout
   ======================================== */
.evo-page {
  position: fixed;
  z-index: 11;
  top: 72px;
  right: 0;
  bottom: 0;
  left: 0;
  margin: 0;
  padding: 0;
  overflow: hidden;
  background: transparent;
  color: var(--evo-text);
  font-family: var(--evo-font);
  -webkit-font-smoothing: auto;
  text-rendering: auto;
}

.evo-shell {
  display: grid;
  grid-template-columns: 248px minmax(0, 1fr);
  grid-template-rows: auto auto minmax(0, 1fr);
  grid-template-areas:
    "rail command"
    "rail topbar"
    "rail pane";
  column-gap: 24px;
  row-gap: 0;
  padding: 26px;
  height: 100%;
  min-height: 0;
  overflow: hidden;
}

.evo-shell.parchment-logbook {
  grid-template-columns: 248px minmax(0, 1fr);
}

.evo-detail-panel {
  display: contents;
}

/* ========================================
   Command Bar
   ======================================== */
.evo-command-bar {
  grid-area: command;
  display: grid;
  grid-template-columns: minmax(180px, 0.9fr) minmax(300px, 1.2fr) minmax(220px, 0.8fr) auto;
  align-items: center;
  gap: 16px;
  min-width: 0;
  flex: 0 0 auto;
  margin: 0;
  padding: 18px 20px 16px;
  border: 1px solid rgba(90, 51, 25, 0.18);
  border-bottom: none;
  border-radius: 8px 8px 0 0;
  background:
    linear-gradient(135deg, rgba(58, 42, 24, 0.96), rgba(90, 51, 25, 0.9)),
    repeating-linear-gradient(90deg, rgba(232, 196, 132, 0.08) 0 1px, transparent 1px 18px);
  box-shadow: 0 2px 8px rgba(91, 47, 18, 0.1);
  overflow: hidden;
}

.evo-command-title {
  display: grid;
  grid-template-columns: minmax(0, 1fr);
  align-items: end;
  gap: 4px;
  min-width: 0;
}

.evo-command-title small {
  grid-column: 1 / -1;
  color: rgba(232, 196, 132, 0.72);
  font-size: 11px;
  font-weight: 700;
  letter-spacing: 0;
}

.evo-command-title h2 {
  min-width: 0;
  overflow: hidden;
  margin: 0;
  color: #fff4d9;
  font-size: 22px;
  font-weight: 800;
  line-height: 1.1;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.evo-command-metrics {
  display: grid;
  grid-template-columns: repeat(4, minmax(68px, 1fr));
  align-items: center;
  gap: 8px;
  min-width: 0;
}

.evo-command-metrics span {
  display: grid;
  gap: 4px;
  min-height: 48px;
  padding: 8px 10px;
  border: 1px solid rgba(232, 196, 132, 0.18);
  border-radius: 7px;
  background: rgba(255, 246, 218, 0.08);
}

.evo-command-metrics small {
  color: rgba(232, 210, 170, 0.68);
  font-size: 11px;
  font-weight: 700;
  line-height: 1;
}

.evo-command-metrics b {
  min-width: 0;
  overflow: hidden;
  color: #fff4d9;
  font-size: 15px;
  font-weight: 800;
  line-height: 1.15;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.evo-command-actions {
  display: flex;
  justify-content: flex-end;
}

.evo-command-run {
  display: grid;
  gap: 6px;
  min-width: 0;
  padding: 8px 10px;
  border: 1px solid rgba(232, 196, 132, 0.18);
  border-radius: 7px;
  background: rgba(255, 246, 218, 0.08);
}

.evo-command-run div:first-child {
  display: flex;
  align-items: baseline;
  gap: 8px;
  min-width: 0;
}

.evo-command-run small,
.evo-command-run p {
  overflow: hidden;
  margin: 0;
  color: rgba(232, 210, 170, 0.68);
  font-size: 11px;
  font-weight: 700;
  line-height: 1.2;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.evo-command-run b {
  min-width: 0;
  overflow: hidden;
  color: #fff4d9;
  font-size: 13px;
  font-weight: 800;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.evo-top-progress,
.evo-run-progress {
  display: block;
  width: 100%;
  height: 6px;
  overflow: hidden;
  border-radius: 999px;
  background: rgba(232, 196, 132, 0.14);
}

.evo-top-progress span,
.evo-run-progress i {
  display: block;
  height: 100%;
  border-radius: inherit;
  background: #e8c484;
  transition: width 0.25s ease;
}

.evo-refresh-button {
  display: inline-flex;
  align-items: center;
  justify-content: center;
  gap: 8px;
  min-width: 92px;
  height: 42px;
  padding: 0 15px;
  border: 1px solid rgba(232, 196, 132, 0.24);
  border-radius: 7px;
  background: #e8c484;
  color: #2d1e10;
  font-size: 13px;
  font-weight: 800;
  cursor: pointer;
  box-shadow: 0 3px 10px rgba(18, 10, 5, 0.18);
  transition: transform 0.15s ease, box-shadow 0.15s ease;
  white-space: nowrap;
}

.evo-refresh-button:hover {
  transform: translateY(-1px);
  box-shadow: 0 5px 14px rgba(18, 10, 5, 0.22);
}

/* ========================================
   View Nav
   ======================================== */
.evo-detail-topbar {
  grid-area: topbar;
  display: grid;
  grid-template-columns: minmax(0, 1fr);
  grid-template-areas: "workspace";
  align-items: center;
  gap: 8px 14px;
  flex: 0 0 auto;
  min-width: 0;
  padding: 10px 16px;
  border-right: 1px solid var(--evo-border);
  border-left: 1px solid var(--evo-border);
  border-bottom: 1px solid var(--evo-border);
  background: rgba(255, 252, 245, 0.4);
}

.evo-nav {
  grid-area: workspace;
  display: flex;
  gap: 6px;
  min-width: 0;
  overflow-x: auto;
  padding-bottom: 2px;
  scrollbar-width: none;
}

.evo-nav::-webkit-scrollbar {
  display: none;
}

.evo-nav-tab {
  display: inline-flex;
  align-items: center;
  justify-content: space-between;
  gap: 6px;
  flex: 0 0 auto;
  width: auto;
  height: 34px;
  padding: 0 12px;
  border: 1px solid var(--evo-input-border);
  border-radius: 7px;
  background: rgba(255, 252, 245, 0.62);
  color: var(--evo-accent-strong);
  font-size: 12px;
  font-weight: 800;
  text-align: left;
  cursor: pointer;
  white-space: nowrap;
}

.evo-nav-tab:hover {
  border-color: var(--evo-accent-strong);
}

.evo-nav-tab.active {
  border-color: var(--evo-accent-strong);
  background: var(--evo-accent-strong);
  color: #fff7dc;
}

/* ========================================
   Role Rail
   ======================================== */
.evo-control-rail {
  grid-area: rail;
  display: grid;
  grid-template-rows: auto auto minmax(0, 1fr);
  gap: 12px;
  min-width: 0;
  min-height: 0;
  padding: 0 14px 0 0;
  border-right: 1px solid rgba(91, 47, 18, 0.2);
  background: transparent;
}

.evo-rail-header {
  display: flex;
  align-items: center;
  gap: 10px;
  min-height: 48px;
  padding: 14px 14px 12px;
  border-bottom: 1px solid var(--evo-border);
}

.evo-rail-header span {
  color: var(--evo-text);
  font-size: 16px;
  font-weight: 800;
  letter-spacing: 0;
}

.evo-rail-header strong {
  margin-left: auto;
  display: inline-flex;
  align-items: center;
  justify-content: center;
  min-width: 26px;
  height: 22px;
  padding: 0 7px;
  border-radius: 11px;
  background: var(--evo-active-bg);
  color: var(--evo-accent);
  font-size: 12px;
  font-weight: 800;
}

.evo-rail-summary {
  display: grid;
  grid-template-columns: repeat(2, minmax(0, 1fr));
  gap: 7px;
  padding: 0 0 2px;
}

.evo-rail-summary span {
  display: grid;
  gap: 4px;
  min-width: 0;
  min-height: 48px;
  padding: 8px 10px;
  border: 1px solid var(--evo-border);
  border-radius: 7px;
  background: rgba(255, 252, 245, 0.42);
}

.evo-rail-summary small {
  color: var(--evo-text-secondary);
  font-size: 11px;
  font-weight: 700;
  line-height: 1;
}

.evo-rail-summary b {
  min-width: 0;
  overflow: hidden;
  color: var(--evo-text);
  font-size: 13px;
  font-weight: 800;
  line-height: 1.1;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.evo-role-panel {
  display: grid;
  grid-template-rows: auto minmax(0, 1fr);
  gap: 8px;
  min-height: 0;
}

.evo-role-bar-label {
  color: var(--evo-accent);
  font-size: 12px;
  font-weight: 800;
}

.evo-role-list {
  display: grid;
  grid-template-columns: 1fr;
  grid-auto-rows: max-content;
  gap: 7px;
  align-content: start;
  min-height: 0;
  overflow-y: auto;
  padding-right: 2px;
  scrollbar-width: thin;
  scrollbar-color: rgba(139, 94, 52, 0.28) transparent;
}

.evo-role-chip {
  display: inline-flex;
  align-items: center;
  justify-content: flex-start;
  gap: 6px;
  width: 100%;
  height: 31px;
  padding: 0 10px;
  border: 1px solid var(--evo-input-border);
  border-radius: 7px;
  background: rgba(255, 252, 245, 0.62);
  color: var(--evo-text-secondary);
  font-size: 12px;
  font-weight: 800;
  cursor: pointer;
  transition: background 0.16s ease, border-color 0.16s ease, color 0.16s ease;
}

.evo-role-chip:hover {
  background: var(--evo-hover);
  border-color: var(--evo-accent);
}

.evo-role-chip img {
  flex: 0 0 auto;
  width: 19px;
  height: 19px;
  border-radius: 50%;
  border: 1px solid var(--evo-border);
}

.evo-role-name {
  font-size: 12px;
  font-weight: 800;
}

.evo-role-chip.selected {
  background: var(--evo-accent-strong);
  color: #fff;
  border-color: var(--evo-accent-strong);
  box-shadow: 0 2px 8px rgba(90, 51, 25, 0.2);
}

.evo-role-chip.selected .evo-role-name {
  color: #fff;
}

.evo-role-chip.selected img {
  border-color: rgba(255, 255, 255, 0.3);
}

/* ========================================
   Content Area
   ======================================== */
.evo-main-pane {
  grid-area: pane;
  align-self: start;
  min-width: 0;
  min-height: 0;
  max-height: calc(100vh - 245px);
  border: 1px solid var(--evo-border);
  border-top: none;
  border-radius: 0 0 8px 8px;
  background: rgba(255, 252, 245, 0.24);
  overflow: hidden;
}

/* ========================================
   Scroll Area
   ======================================== */
.evo-scroll {
  display: flex;
  flex-direction: column;
  height: auto;
  min-height: 0;
  max-height: calc(100vh - 245px);
  overflow-y: auto;
  padding: 16px;
  scrollbar-width: thin;
  scrollbar-color: rgba(139, 94, 52, 0.34) transparent;
}

.evo-scroll::-webkit-scrollbar {
  width: 6px;
}

.evo-scroll::-webkit-scrollbar-track {
  background: transparent;
}

.evo-scroll::-webkit-scrollbar-thumb {
  background: rgba(139, 94, 52, 0.15);
  border-radius: 3px;
}

.evo-scroll::-webkit-scrollbar-thumb:hover {
  background: rgba(139, 94, 52, 0.25);
}

/* ========================================
   Alert
   ======================================== */
.evo-alert {
  margin-bottom: 12px;
  padding: 10px 14px;
  border: 1px solid rgba(139, 58, 42, 0.25);
  border-radius: 8px;
  background: rgba(139, 58, 42, 0.06);
  color: var(--evo-danger);
  font-size: 13px;
}

.evo-alert.compact {
  margin: 6px 0;
  padding: 6px 10px;
  font-size: 12px;
}

/* ========================================
   Tab Panel
   ======================================== */
.evo-tab-panel {
  display: flex;
  flex-direction: column;
  gap: 16px;
}

/* ========================================
   Cards
   ======================================== */
.evo-card {
  padding: 16px;
  border: 1px solid var(--evo-border);
  border-radius: 10px;
  background: var(--evo-surface);
  backdrop-filter: blur(6px);
  box-shadow: 0 1px 3px rgba(90, 51, 25, 0.04);
}

.evo-card header {
  display: flex;
  align-items: baseline;
  gap: 8px;
  margin-bottom: 14px;
  padding-bottom: 10px;
  border-bottom: 1px solid var(--evo-border);
}

.evo-card header h2 {
  margin: 0;
  color: var(--evo-text);
  font-size: 14px;
  font-weight: 700;
}

.evo-card header b {
  margin-left: auto;
  color: var(--evo-text-secondary);
  font-size: 12px;
  font-weight: 600;
}

/* ========================================
   Empty States
   ======================================== */
.evo-empty {
  padding: 32px 20px;
  color: var(--evo-text-secondary);
  font-size: 13px;
  text-align: center;
  opacity: 0.7;
}

.evo-empty.compact {
  padding: 12px 8px;
  font-size: 12px;
}

.evo-loading {
  color: var(--evo-text-secondary);
  font-size: 12px;
}

/* ========================================
   Form Controls
   ======================================== */
.evo-form-grid {
  display: grid;
  grid-template-columns: repeat(auto-fill, minmax(170px, 1fr));
  gap: 12px;
}

.evo-form-grid label {
  display: flex;
  flex-direction: column;
  gap: 5px;
  color: var(--evo-text-secondary);
  font-size: 11px;
  font-weight: 600;
  letter-spacing: 0.02em;
}

.evo-form-grid input {
  box-sizing: border-box;
  width: 100%;
  height: 34px;
  padding: 0 10px;
  border: 1px solid var(--evo-input-border);
  border-radius: 6px;
  background: var(--evo-input-bg);
  color: var(--evo-text);
  font-size: 13px;
  transition: border-color 0.2s ease, box-shadow 0.2s ease;
}

.evo-form-grid input:focus {
  outline: none;
  border-color: var(--evo-accent);
  box-shadow: 0 0 0 3px rgba(139, 94, 52, 0.1);
}

.evo-check-field {
  justify-content: space-between;
}

.evo-check-field input {
  width: 34px;
  height: 34px;
  padding: 0;
  accent-color: var(--evo-accent);
}

.evo-batch-role-grid {
  display: grid;
  grid-template-columns: repeat(auto-fill, minmax(112px, 1fr));
  gap: 8px;
  margin-top: 14px;
}

.evo-role-toggle {
  display: inline-flex;
  align-items: center;
  gap: 8px;
  min-width: 0;
  height: 36px;
  padding: 0 10px;
  border: 1px solid var(--evo-border);
  border-radius: 7px;
  background: rgba(255, 255, 250, 0.5);
  color: var(--evo-text-secondary);
  font-size: 12px;
  font-weight: 700;
  cursor: pointer;
  transition: all 0.18s ease;
}

.evo-role-toggle:hover {
  border-color: rgba(139, 94, 52, 0.35);
  background: var(--evo-hover);
}

.evo-role-toggle.selected {
  border-color: var(--evo-accent);
  background: var(--evo-active-bg);
  color: var(--evo-accent-strong);
}

.evo-role-toggle img {
  flex: 0 0 auto;
  width: 22px;
  height: 22px;
  border-radius: 50%;
}

.evo-role-toggle span {
  min-width: 0;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

/* ========================================
   Command Row / Actions
   ======================================== */
.evo-command-row {
  display: flex;
  align-items: center;
  gap: 10px;
  margin-top: 14px;
}

.evo-action {
  padding: 8px 20px;
  border: none;
  border-radius: 7px;
  background: var(--evo-accent);
  color: #faf5eb;
  font-size: 13px;
  font-weight: 700;
  cursor: pointer;
  box-shadow: 0 2px 4px rgba(90, 51, 25, 0.15);
  transition: all 0.2s ease;
}

.evo-action:hover {
  background: var(--evo-accent-strong);
  box-shadow: 0 3px 8px rgba(90, 51, 25, 0.2);
  transform: translateY(-1px);
}

.evo-action:active {
  transform: translateY(0);
  box-shadow: 0 1px 2px rgba(90, 51, 25, 0.1);
}

.evo-action:disabled {
  opacity: 0.45;
  cursor: not-allowed;
  transform: none;
  box-shadow: none;
}

.evo-action.danger {
  background: var(--evo-danger);
  box-shadow: 0 2px 4px rgba(139, 58, 42, 0.15);
}

.evo-action.danger:hover {
  background: #a04535;
  box-shadow: 0 3px 8px rgba(139, 58, 42, 0.2);
}

.evo-ghost-action {
  padding: 6px 14px;
  border: 1px solid var(--evo-border);
  border-radius: 6px;
  background: transparent;
  color: var(--evo-text);
  font-size: 12px;
  cursor: pointer;
  transition: all 0.2s ease;
}

.evo-ghost-action:hover {
  background: var(--evo-hover);
  border-color: rgba(139, 94, 52, 0.3);
}

.evo-ghost-action:disabled {
  opacity: 0.35;
  cursor: not-allowed;
}

.evo-ghost-action.danger {
  color: var(--evo-danger);
  border-color: rgba(139, 58, 42, 0.25);
}

.evo-ghost-action.danger:hover {
  background: rgba(139, 58, 42, 0.06);
}

/* ========================================
   Review Panel
   ======================================== */
.evo-review-body {
  display: flex;
  flex-direction: column;
  gap: 12px;
}

.evo-progress-card {
  display: grid;
  gap: 8px;
  padding: 10px 12px;
  border: 1px solid var(--evo-border);
  border-radius: 8px;
  background: var(--evo-input-bg);
}

.evo-progress-card.compact {
  padding: 8px 10px;
}

.evo-progress-card.compact p {
  min-width: 0;
  overflow: hidden;
  margin: 0;
  color: var(--evo-text-secondary);
  font-size: 11px;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.evo-progress-grid {
  display: grid;
  grid-template-columns: repeat(4, minmax(0, 1fr));
  gap: 8px;
}

.evo-progress-head {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 10px;
  min-width: 0;
}

.evo-progress-head strong {
  min-width: 0;
  overflow: hidden;
  color: var(--evo-text);
  font-size: 13px;
  font-weight: 800;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.evo-progress-head span {
  flex: 0 0 auto;
  color: var(--evo-text-secondary);
  font-size: 12px;
  font-family: "Cascadia Code", "Fira Code", Consolas, monospace;
}

.evo-progress-track {
  width: 100%;
  height: 8px;
  overflow: hidden;
  border-radius: 999px;
  background: rgba(139, 94, 52, 0.1);
}

.evo-progress-fill {
  display: block;
  height: 100%;
  border-radius: inherit;
  background: linear-gradient(90deg, var(--evo-accent), #d0a96b);
  transition: width 0.25s ease;
}

.evo-detail-list {
  display: grid;
  gap: 8px;
}

.evo-detail-list h3 {
  margin: 0;
  color: var(--evo-text);
  font-size: 12px;
  font-weight: 800;
}

.evo-detail-list ul,
.evo-detail-list ol {
  display: grid;
  gap: 6px;
  margin: 0;
  padding: 0;
  list-style: none;
}

.evo-detail-list li {
  display: grid;
  gap: 3px;
  min-width: 0;
  padding: 8px 10px;
  border: 1px solid var(--evo-border);
  border-radius: 7px;
  background: rgba(255, 252, 245, 0.5);
}

.evo-detail-list strong {
  min-width: 0;
  overflow: hidden;
  color: var(--evo-text);
  font-size: 12px;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.evo-detail-list span,
.evo-detail-list p {
  margin: 0;
  color: var(--evo-text-secondary);
  font-size: 11px;
  line-height: 1.5;
}

.evo-battle-grid {
  display: grid;
  grid-template-columns: repeat(3, minmax(0, 1fr));
  gap: 8px;
}

.evo-battle-grid span {
  display: grid;
  gap: 3px;
  min-width: 0;
  padding: 8px 10px;
  border: 1px solid var(--evo-border);
  border-radius: 7px;
  background: var(--evo-input-bg);
}

.evo-battle-grid small {
  color: var(--evo-text-secondary);
  font-size: 10px;
  font-weight: 700;
}

.evo-battle-grid b {
  min-width: 0;
  overflow: hidden;
  color: var(--evo-text);
  font-size: 13px;
  font-family: "Cascadia Code", "Fira Code", Consolas, monospace;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.evo-kpis {
  display: grid;
  grid-template-columns: repeat(4, 1fr);
  gap: 8px;
}

.evo-kpis span {
  display: flex;
  flex-direction: column;
  align-items: center;
  padding: 8px 6px;
  border: 1px solid var(--evo-border);
  border-radius: 8px;
  background: var(--evo-input-bg);
}

.evo-kpis small {
  color: var(--evo-text-secondary);
  font-size: 10px;
  font-weight: 700;
  letter-spacing: 0.04em;
}

.evo-kpis b {
  color: var(--evo-text);
  font-size: 13px;
  font-family: "Cascadia Code", "Fira Code", Consolas, monospace;
}

.evo-config-grid {
  display: grid;
  grid-template-columns: repeat(3, 1fr);
  gap: 6px;
}

.evo-config-grid span {
  display: flex;
  flex-direction: column;
  padding: 5px 10px;
  border-radius: 6px;
  background: var(--evo-hover);
}

.evo-config-grid small {
  color: var(--evo-text-secondary);
  font-size: 10px;
}

.evo-config-grid b {
  color: var(--evo-text);
  font-size: 12px;
  font-family: "Cascadia Code", "Fira Code", Consolas, monospace;
}

.evo-review-actions {
  display: flex;
  flex-wrap: wrap;
  gap: 8px;
  margin-top: 4px;
}

.evo-batch-detail {
  display: grid;
  gap: 8px;
  padding: 10px 12px;
  border: 1px solid var(--evo-border);
  border-radius: 8px;
  background: var(--evo-input-bg);
}

.evo-batch-detail h3,
.evo-batch-detail p {
  margin: 0;
}

.evo-batch-detail h3 {
  color: var(--evo-text);
  font-size: 12px;
  font-weight: 800;
}

.evo-batch-detail p {
  color: var(--evo-text-secondary);
  font-size: 12px;
}

.evo-child-run-list {
  display: grid;
  gap: 6px;
}

.evo-child-run-row {
  display: grid;
  grid-template-columns: auto minmax(82px, 0.8fr) minmax(0, 1.2fr) auto;
  align-items: center;
  gap: 8px;
  min-width: 0;
  padding: 7px 9px;
  border: 1px solid var(--evo-border);
  border-radius: 7px;
  background: rgba(255, 252, 245, 0.55);
  color: var(--evo-text);
  text-align: left;
  cursor: pointer;
}

.evo-child-run-row:hover {
  border-color: rgba(139, 94, 52, 0.35);
  background: var(--evo-hover);
}

.evo-child-run-row:disabled {
  cursor: not-allowed;
  opacity: 0.5;
}

.evo-child-run-row strong,
.evo-child-run-row small {
  min-width: 0;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.evo-child-run-row strong {
  font-size: 12px;
  font-weight: 800;
}

.evo-child-run-row small,
.evo-child-run-row b {
  color: var(--evo-text-secondary);
  font-size: 11px;
  font-family: "Cascadia Code", "Fira Code", Consolas, monospace;
}

.evo-mini-columns {
  display: grid;
  grid-template-columns: 1fr;
  gap: 8px;
}

.evo-mini-columns h3 {
  margin: 0 0 4px;
  color: var(--evo-text);
  font-size: 12px;
  font-weight: 700;
}

.evo-mini-columns p {
  margin: 0;
  color: var(--evo-text-secondary);
  font-size: 12px;
}

/* ========================================
   Run List
   ======================================== */
.evo-run-tools {
  display: flex;
  align-items: center;
  gap: 10px;
  margin-bottom: 10px;
}

.evo-run-tools input {
  flex: 1;
  height: 30px;
  padding: 0 10px;
  border: 1px solid var(--evo-input-border);
  border-radius: 6px;
  color: var(--evo-text);
  background: var(--evo-input-bg);
  font-size: 12px;
  transition: border-color 0.2s ease;
}

.evo-run-tools input:focus {
  outline: none;
  border-color: var(--evo-accent);
  box-shadow: 0 0 0 3px rgba(139, 94, 52, 0.08);
}

.evo-run-tools span {
  color: var(--evo-text-secondary);
  font-size: 11px;
  white-space: nowrap;
  opacity: 0.7;
}

.evo-run-scroll {
  display: flex;
  flex-direction: column;
  gap: 4px;
  max-height: 520px;
  overflow-y: auto;
}

.evo-run-scroll::-webkit-scrollbar {
  width: 5px;
}

.evo-run-scroll::-webkit-scrollbar-thumb {
  background: rgba(139, 94, 52, 0.15);
  border-radius: 3px;
}

.evo-run-row {
  display: flex;
  align-items: center;
  gap: 10px;
  padding: 9px 12px;
  border: 1px solid var(--evo-border);
  border-radius: 8px;
  background: var(--evo-input-bg);
  text-align: left;
  cursor: pointer;
  transition: all 0.2s ease;
}

.evo-run-row:hover {
  background: var(--evo-hover);
  border-color: rgba(139, 94, 52, 0.25);
}

.evo-run-row.selected {
  border-color: var(--evo-accent);
  background: var(--evo-active-bg);
  box-shadow: 0 1px 4px rgba(139, 94, 52, 0.08);
}

.evo-run-status {
  padding: 3px 8px;
  border-radius: 4px;
  background: rgba(139, 94, 52, 0.1);
  color: var(--evo-accent);
  font-size: 10px;
  font-weight: 700;
  white-space: nowrap;
  letter-spacing: 0.02em;
}

.run-status[data-status="reviewing"],
.evo-run-status[data-status="reviewing"] {
  background: rgba(74, 124, 68, 0.12);
  color: #3a6b34;
}

.run-status[data-status="promoted"],
.evo-run-status[data-status="promoted"] {
  background: rgba(74, 124, 68, 0.18);
  color: #2d5a28;
}

.run-status[data-status="failed"],
.run-status[data-status="rejected"],
.evo-run-status[data-status="failed"],
.evo-run-status[data-status="rejected"] {
  background: rgba(139, 58, 42, 0.12);
  color: #7a3224;
}

.run-status[data-status="paused"],
.evo-run-status[data-status="paused"] {
  background: rgba(139, 94, 52, 0.12);
  color: var(--evo-accent);
}

.evo-run-main {
  flex: 1;
  display: flex;
  flex-direction: column;
  min-width: 0;
}

.evo-run-main strong {
  color: var(--evo-text);
  font-size: 13px;
  font-weight: 600;
}

.evo-run-main small {
  color: var(--evo-text-secondary);
  font-size: 10px;
  font-family: "Cascadia Code", "Fira Code", Consolas, monospace;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
  opacity: 0.65;
}

.evo-run-progress {
  height: 5px;
  margin-top: 5px;
  background: rgba(139, 94, 52, 0.11);
}

.evo-run-progress i {
  background: var(--evo-accent);
}

.evo-run-metric {
  color: var(--evo-text-secondary);
  font-size: 11px;
  font-family: "Cascadia Code", "Fira Code", Consolas, monospace;
  white-space: nowrap;
  opacity: 0.8;
}

.evo-run-more {
  display: grid;
  gap: 7px;
  justify-items: center;
  padding: 8px;
  color: var(--evo-text-secondary);
  font-size: 11px;
  text-align: center;
  opacity: 0.6;
}

.evo-load-more {
  height: 28px;
  padding: 0 12px;
  border: 1px solid var(--evo-input-border);
  border-radius: 6px;
  color: var(--evo-accent-strong);
  background: var(--evo-input-bg);
  font-size: 11px;
  font-weight: 800;
}

.evo-load-more:hover:not(:disabled) {
  border-color: rgba(139, 94, 52, 0.36);
  background: rgba(255, 252, 245, 0.94);
}

.evo-load-more:disabled {
  cursor: not-allowed;
  opacity: 0.55;
}

/* ========================================
   Leaderboard
   ======================================== */
.evo-leaderboard {
  display: flex;
  flex-direction: column;
  gap: 6px;
}

.evo-leaderboard-row {
  display: flex;
  align-items: center;
  gap: 10px;
  padding: 7px 0;
}

.evo-leaderboard-label {
  flex: 0 0 120px;
  display: flex;
  flex-direction: column;
  color: var(--evo-text);
  font-size: 12px;
  font-family: "Cascadia Code", "Fira Code", Consolas, monospace;
}

.evo-leaderboard-label small {
  color: var(--evo-text-secondary);
  font-size: 10px;
  opacity: 0.7;
}

.evo-leaderboard-bar-wrap {
  flex: 1;
  height: 10px;
  border-radius: 5px;
  background: rgba(139, 94, 52, 0.08);
  overflow: hidden;
}

.evo-leaderboard-bar {
  height: 100%;
  border-radius: 5px;
  transition: width 0.4s ease;
}

.evo-leaderboard-value {
  flex: 0 0 42px;
  color: var(--evo-text);
  font-size: 12px;
  font-weight: 700;
  text-align: right;
  font-family: "Cascadia Code", "Fira Code", Consolas, monospace;
}

/* ========================================
   Versions
   ======================================== */
.evo-version-list {
  display: flex;
  flex-direction: column;
  gap: 3px;
  max-height: 280px;
  overflow-y: auto;
}

.evo-version-list::-webkit-scrollbar {
  width: 5px;
}

.evo-version-list::-webkit-scrollbar-thumb {
  background: rgba(139, 94, 52, 0.15);
  border-radius: 3px;
}

.evo-version-row {
  display: flex;
  align-items: center;
  gap: 10px;
  padding: 9px 12px;
  border-radius: 8px;
  background: var(--evo-input-bg);
  border: 1px solid transparent;
  transition: all 0.15s ease;
}

.evo-version-row:hover {
  border-color: var(--evo-border);
  background: var(--evo-hover);
}

.evo-version-row span {
  flex: 1;
  min-width: 0;
}

.evo-version-row strong {
  color: var(--evo-text);
  font-size: 13px;
  font-family: "Cascadia Code", "Fira Code", Consolas, monospace;
}

.evo-version-row small {
  display: block;
  color: var(--evo-text-secondary);
  font-size: 10px;
  opacity: 0.7;
}

.evo-version-actions {
  display: flex;
  gap: 6px;
  flex-shrink: 0;
}

.evo-version-detail {
  margin-top: 12px;
  padding-top: 12px;
  border-top: 1px solid var(--evo-border);
}

.evo-version-detail header {
  display: flex;
  align-items: baseline;
  gap: 8px;
}

.evo-version-detail header strong {
  color: var(--evo-text);
  font-size: 13px;
  font-family: "Cascadia Code", "Fira Code", Consolas, monospace;
}

.evo-version-detail header small {
  color: var(--evo-text-secondary);
  font-size: 11px;
}

.evo-version-kpis {
  display: flex;
  gap: 12px;
  margin: 10px 0;
}

.evo-version-kpis span {
  display: flex;
  flex-direction: column;
  padding: 6px 12px;
  border: 1px solid var(--evo-border);
  border-radius: 6px;
  background: var(--evo-input-bg);
}

.evo-version-kpis small {
  color: var(--evo-text-secondary);
  font-size: 10px;
  font-weight: 600;
}

.evo-version-kpis b {
  color: var(--evo-text);
  font-size: 13px;
  font-family: "Cascadia Code", "Fira Code", Consolas, monospace;
}

.evo-version-skill-list {
  margin: 8px 0;
  padding: 0 0 0 16px;
  list-style: none;
  color: var(--evo-text-secondary);
  font-size: 11px;
  font-family: "Cascadia Code", "Fira Code", Consolas, monospace;
}

.evo-version-skill-list li {
  padding: 2px 0;
}

/* ========================================
   Events
   ======================================== */
.evo-event-list {
  margin: 0;
  padding: 0;
  list-style: none;
}

.evo-event-list li {
  display: flex;
  gap: 10px;
  padding: 8px 0;
  border-bottom: 1px solid var(--evo-border);
  color: var(--evo-text);
  font-size: 12px;
}

.evo-event-list li:last-child {
  border-bottom: none;
}

.evo-event-list strong {
  color: var(--evo-accent);
  font-size: 11px;
  font-weight: 700;
  white-space: nowrap;
}

.evo-event-list span {
  color: var(--evo-text-secondary);
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

/* ========================================
   Sample Games
   ======================================== */
.evo-sample-tabs {
  display: flex;
  gap: 6px;
  margin-bottom: 10px;
}

.evo-sample-tabs button {
  padding: 5px 12px;
  border: 1px solid var(--evo-border);
  border-radius: 6px;
  background: transparent;
  color: var(--evo-text-secondary);
  font-size: 12px;
  cursor: pointer;
  transition: all 0.2s ease;
}

.evo-sample-tabs button:hover {
  background: var(--evo-hover);
  border-color: rgba(139, 94, 52, 0.3);
}

.evo-sample-tabs button.active {
  border-color: var(--evo-accent);
  background: var(--evo-active-bg);
  color: var(--evo-accent-strong);
  font-weight: 700;
}

.evo-sample-layout {
  display: grid;
  grid-template-columns: minmax(280px, 0.8fr) minmax(0, 1.2fr);
  gap: 16px;
  min-height: 0;
}

.evo-sample-list {
  display: flex;
  flex-direction: column;
  gap: 3px;
  max-height: 400px;
  overflow-y: auto;
}

.evo-sample-list::-webkit-scrollbar {
  width: 5px;
}

.evo-sample-list::-webkit-scrollbar-thumb {
  background: rgba(139, 94, 52, 0.15);
  border-radius: 3px;
}

.evo-sample-row {
  display: flex;
  flex-direction: column;
  gap: 3px;
  padding: 9px 12px;
  border: 1px solid var(--evo-border);
  border-radius: 8px;
  background: var(--evo-input-bg);
  text-align: left;
  cursor: pointer;
  transition: all 0.2s ease;
}

.evo-sample-row:hover {
  background: var(--evo-hover);
  border-color: rgba(139, 94, 52, 0.25);
}

.evo-sample-row.selected {
  border-color: var(--evo-accent);
  background: var(--evo-active-bg);
  box-shadow: 0 1px 4px rgba(139, 94, 52, 0.08);
}

.evo-sample-row strong {
  color: var(--evo-text);
  font-size: 12px;
  font-weight: 600;
}

.evo-sample-row span {
  color: var(--evo-text-secondary);
  font-size: 10px;
  opacity: 0.7;
}

.evo-sample-detail {
  display: flex;
  flex-direction: column;
  gap: 10px;
  max-height: 400px;
  overflow-y: auto;
}

.evo-sample-detail-head {
  display: flex;
  align-items: flex-start;
  justify-content: space-between;
  gap: 10px;
  min-width: 0;
}

.evo-sample-detail-head h3 {
  min-width: 0;
  overflow: hidden;
  text-overflow: ellipsis;
}

.evo-sample-actions {
  display: flex;
  flex: 0 0 auto;
  flex-wrap: wrap;
  gap: 6px;
  justify-content: flex-end;
}

.evo-sample-detail h3 {
  margin: 0;
  color: var(--evo-text);
  font-size: 14px;
  font-weight: 700;
}

.evo-sample-detail p {
  margin: 0;
  color: var(--evo-text-secondary);
  font-size: 12px;
  line-height: 1.6;
}

.evo-muted-reason {
  color: var(--evo-danger) !important;
  font-size: 11px !important;
}

.evo-highlight-list {
  margin: 0;
  padding: 0 0 0 16px;
  list-style: none;
}

.evo-highlight-list li {
  padding: 3px 0;
  color: var(--evo-text-secondary);
  font-size: 12px;
}

.evo-evidence-columns {
  display: grid;
  grid-template-columns: 1fr 1fr;
  gap: 16px;
}

.evo-evidence-columns h4 {
  margin: 0 0 6px;
  color: var(--evo-accent);
  font-size: 12px;
  font-weight: 700;
}

.evo-evidence-columns ol {
  margin: 0;
  padding: 0 0 0 16px;
}

.evo-evidence-columns li {
  padding: 3px 0;
  font-size: 11px;
}

.evo-evidence-columns li strong {
  color: var(--evo-text);
  margin-right: 4px;
}

.evo-evidence-columns li span {
  color: var(--evo-text-secondary);
}

.evo-evidence-columns li small {
  color: rgba(139, 107, 74, 0.76);
  font-size: 10px;
  line-height: 1.4;
}

/* ========================================
   Pattern Browser
   ======================================== */
.evo-pattern-browser {
  margin-top: 12px;
  border-top: 1px solid var(--evo-border);
  padding-top: 12px;
}

.evo-pattern-filter-bar {
  display: flex;
  align-items: center;
  gap: 8px;
  margin-bottom: 12px;
}

.evo-pattern-filter-bar select {
  flex: 1;
  min-width: 0;
  height: 30px;
  padding: 0 8px;
  border: 1px solid var(--evo-input-border);
  border-radius: 6px;
  color: var(--evo-text);
  background: var(--evo-input-bg);
  font-size: 12px;
  transition: border-color 0.2s ease;
}

.evo-pattern-filter-bar select:focus {
  outline: none;
  border-color: var(--evo-accent);
}

.evo-pattern-filter-bar small {
  color: var(--evo-text-secondary);
  font-size: 11px;
  white-space: nowrap;
  opacity: 0.7;
}

.evo-pattern-card-list {
  display: flex;
  flex-direction: column;
  gap: 10px;
  max-height: 360px;
  overflow-y: auto;
  padding-right: 4px;
}

.evo-pattern-card-list::-webkit-scrollbar {
  width: 5px;
}

.evo-pattern-card-list::-webkit-scrollbar-thumb {
  background: rgba(139, 94, 52, 0.15);
  border-radius: 3px;
}

.evo-pattern-card {
  padding: 12px 14px;
  border: 1px solid var(--evo-border);
  border-radius: 8px;
  background: var(--evo-input-bg);
}

.evo-pattern-card-header {
  display: flex;
  align-items: center;
  gap: 8px;
  margin-bottom: 8px;
  flex-wrap: wrap;
}

.evo-pattern-status-badge {
  display: inline-block;
  padding: 2px 8px;
  border-radius: 4px;
  color: #fff;
  font-size: 10px;
  font-weight: 800;
  letter-spacing: 0.06em;
  text-transform: uppercase;
}

.evo-pattern-role-tag {
  padding: 2px 8px;
  border-radius: 4px;
  background: rgba(139, 94, 52, 0.1);
  color: var(--evo-accent);
  font-size: 10px;
  font-weight: 700;
}

.evo-pattern-id {
  margin-left: auto;
  color: var(--evo-text-secondary);
  font-size: 10px;
  font-family: "Cascadia Code", "Fira Code", Consolas, monospace;
  opacity: 0.6;
}

.evo-pattern-situation {
  margin-bottom: 6px;
}

.evo-pattern-situation code {
  display: inline-block;
  padding: 3px 8px;
  border-radius: 4px;
  background: rgba(58, 42, 24, 0.06);
  color: var(--evo-text-secondary);
  font-family: "Cascadia Code", "Fira Code", Consolas, monospace;
  font-size: 11px;
  word-break: break-all;
}

.evo-pattern-recommendation {
  margin: 6px 0;
  color: var(--evo-text);
  font-size: 13px;
  line-height: 1.6;
}

/* Win rate comparison bars */
.evo-pattern-winrate-bars {
  display: flex;
  flex-direction: column;
  gap: 5px;
  margin: 10px 0;
}

.evo-pattern-wr-row {
  display: flex;
  align-items: center;
  gap: 8px;
}

.evo-pattern-wr-label {
  flex: 0 0 42px;
  color: var(--evo-text-secondary);
  font-size: 11px;
  text-align: right;
}

.evo-pattern-wr-bar-track {
  flex: 1;
  height: 8px;
  border-radius: 4px;
  background: rgba(139, 94, 52, 0.08);
  overflow: hidden;
}

.evo-pattern-wr-bar-fill {
  height: 100%;
  border-radius: 4px;
  transition: width 0.4s ease;
}

.evo-pattern-wr-value {
  flex: 0 0 38px;
  color: var(--evo-text);
  font-size: 11px;
  font-weight: 700;
  font-family: "Cascadia Code", "Fira Code", Consolas, monospace;
}

/* Meta row */
.evo-pattern-meta-row {
  display: flex;
  align-items: center;
  gap: 16px;
  margin-top: 8px;
  color: var(--evo-text-secondary);
  font-size: 11px;
}

.evo-pattern-meta-row b {
  color: var(--evo-text);
}

.evo-pattern-confidence {
  display: flex;
  align-items: center;
  gap: 5px;
}

.evo-pattern-conf-track {
  display: inline-block;
  width: 52px;
  height: 6px;
  border-radius: 3px;
  background: rgba(139, 94, 52, 0.1);
  overflow: hidden;
}

.evo-pattern-conf-fill {
  display: block;
  height: 100%;
  border-radius: 3px;
  background: var(--evo-accent);
  transition: width 0.3s ease;
}

/* Source games collapsible */
.evo-pattern-source-games {
  margin-top: 8px;
}

.evo-pattern-toggle-btn {
  padding: 3px 10px;
  border: 1px solid var(--evo-border);
  border-radius: 4px;
  background: transparent;
  color: var(--evo-text-secondary);
  font-size: 11px;
  cursor: pointer;
  transition: all 0.2s ease;
}

.evo-pattern-toggle-btn:hover {
  border-color: rgba(139, 94, 52, 0.35);
  background: var(--evo-hover);
  color: var(--evo-accent);
}

.evo-pattern-source-list {
  margin: 6px 0 0;
  padding: 0 0 0 16px;
  list-style: none;
  color: var(--evo-text-secondary);
  font-size: 11px;
  font-family: "Cascadia Code", "Fira Code", Consolas, monospace;
}

.evo-pattern-source-list li {
  padding: 2px 0;
}

.evo-pattern-empty {
  padding: 12px 0;
  color: var(--evo-text-secondary);
  font-size: 12px;
  text-align: center;
  opacity: 0.6;
}

/* ========================================
   Diff Viewer
   ======================================== */
.evo-diff-viewer {
  margin-top: 14px;
  border-top: 1px solid var(--evo-border);
  padding-top: 12px;
}

.evo-diff-viewer h3 {
  margin: 0 0 8px;
  color: var(--evo-accent);
  font-size: 12px;
  font-weight: 800;
  letter-spacing: 0.08em;
  text-transform: uppercase;
}

/* Metrics Delta Strip */
.evo-diff-metrics-strip {
  margin-bottom: 14px;
}

.evo-diff-metrics-row {
  display: flex;
  flex-wrap: wrap;
  gap: 10px;
}

.evo-diff-metric-kpi {
  display: flex;
  flex-direction: column;
  align-items: center;
  padding: 8px 16px;
  border: 1px solid var(--evo-border);
  border-radius: 8px;
  background: var(--evo-input-bg);
  min-width: 76px;
}

.evo-diff-metric-kpi small {
  color: var(--evo-text-secondary);
  font-size: 10px;
  font-weight: 700;
  letter-spacing: 0.06em;
}

.evo-diff-metric-kpi b {
  font-size: 14px;
  font-weight: 800;
  margin-top: 3px;
}

.evo-diff-metric-kpi.positive b {
  color: var(--evo-success);
}

.evo-diff-metric-kpi.negative b {
  color: var(--evo-danger);
}

.evo-diff-arrow {
  font-size: 9px;
  margin-right: 2px;
}

/* Diff sections */
.evo-diff-section {
  margin-bottom: 14px;
}

.evo-diff-section h3 {
  margin: 0 0 8px;
}

/* Skill file changes */
.evo-diff-file-block {
  margin-bottom: 10px;
  border: 1px solid var(--evo-border);
  border-radius: 8px;
  overflow: hidden;
}

.evo-diff-file-header {
  display: flex;
  align-items: center;
  gap: 10px;
  padding: 7px 12px;
  background: rgba(58, 42, 24, 0.08);
  border-bottom: 1px solid var(--evo-border);
}

.evo-diff-filename {
  color: var(--evo-text);
  font-size: 12px;
  font-weight: 700;
  font-family: "Cascadia Code", "Fira Code", Consolas, monospace;
}

.evo-diff-action-badge {
  display: inline-block;
  padding: 2px 8px;
  border-radius: 4px;
  color: #fff;
  font-size: 10px;
  font-weight: 800;
  letter-spacing: 0.04em;
}

.evo-diff-code-block {
  max-height: 220px;
  overflow-y: auto;
  padding: 8px 0;
  background: #2d2218;
  font-family: "Cascadia Code", "Fira Code", Consolas, monospace;
  font-size: 11px;
  line-height: 1.6;
}

.evo-diff-code-block::-webkit-scrollbar {
  width: 5px;
}

.evo-diff-code-block::-webkit-scrollbar-thumb {
  background: rgba(139, 94, 52, 0.3);
  border-radius: 3px;
}

.evo-diff-line {
  display: flex;
  padding: 0 12px;
  white-space: pre-wrap;
  word-break: break-all;
}

.evo-diff-line-added {
  background: rgba(74, 124, 68, 0.2);
}

.evo-diff-line-added .evo-diff-line-marker {
  color: #6ecf6e;
}

.evo-diff-line-removed {
  background: rgba(139, 58, 42, 0.2);
}

.evo-diff-line-removed .evo-diff-line-marker {
  color: #f08070;
}

.evo-diff-line-context {
  background: transparent;
}

.evo-diff-line-context .evo-diff-line-marker {
  color: rgba(180, 160, 130, 0.35);
}

.evo-diff-line-marker {
  flex: 0 0 16px;
  text-align: center;
  font-weight: 700;
  user-select: none;
}

.evo-diff-line-text {
  flex: 1;
  color: rgba(232, 218, 196, 0.9);
}

.evo-diff-no-content {
  margin: 0;
  padding: 8px 12px;
  color: var(--evo-text-secondary);
  font-size: 11px;
  font-style: italic;
  opacity: 0.6;
}

/* Pattern changes */
.evo-diff-pattern-group {
  margin-bottom: 10px;
}

.evo-diff-group-label {
  display: block;
  margin-bottom: 5px;
  font-size: 10px;
  font-weight: 800;
  letter-spacing: 0.06em;
  text-transform: uppercase;
}

.added-label {
  color: var(--evo-success);
}

.removed-label {
  color: var(--evo-danger);
}

.updated-label {
  color: var(--evo-accent);
}

.evo-diff-pattern-card {
  padding: 8px 12px;
  border-radius: 6px;
  margin-bottom: 5px;
  font-size: 12px;
}

.evo-diff-pattern-card strong {
  display: block;
  font-size: 11px;
  font-family: "Cascadia Code", "Fira Code", Consolas, monospace;
  margin-bottom: 3px;
}

.evo-diff-pattern-card span {
  display: block;
  color: var(--evo-text);
  line-height: 1.5;
  opacity: 0.85;
}

.evo-diff-pattern-card.added {
  border-left: 3px solid var(--evo-success);
  background: rgba(74, 124, 68, 0.06);
}

.evo-diff-pattern-card.added strong {
  color: var(--evo-success);
}

.evo-diff-pattern-card.removed {
  border-left: 3px solid var(--evo-danger);
  background: rgba(139, 58, 42, 0.05);
}

.evo-diff-pattern-card.removed strong {
  color: var(--evo-danger);
  text-decoration: line-through;
}

.evo-diff-pattern-card.removed span {
  text-decoration: line-through;
  opacity: 0.5;
}

.evo-diff-pattern-card.updated {
  border-left: 3px solid var(--evo-accent);
  background: rgba(139, 94, 52, 0.05);
}

.evo-diff-pattern-card.updated strong {
  color: var(--evo-accent);
}

/* Legacy fallback list */
.evo-diff-legacy-list {
  margin: 0;
  padding: 0 0 0 16px;
  list-style: none;
  color: var(--evo-text-secondary);
  font-size: 12px;
}

.evo-diff-legacy-list li {
  padding: 3px 0;
}

.evo-diff-empty h3 {
  margin: 12px 0 6px;
  color: var(--evo-text-secondary);
  font-size: 12px;
  font-weight: 700;
}

.evo-diff-empty p {
  margin: 0;
  color: var(--evo-text-secondary);
  opacity: 0.5;
}

@media (max-width: 1120px) {
  .evo-command-bar {
    grid-template-columns: minmax(0, 1fr) minmax(220px, 0.8fr);
    margin: 0 12px 10px;
  }

  .evo-command-actions {
    grid-column: 1 / -1;
    justify-content: flex-start;
  }

  .evo-command-metrics {
    grid-template-columns: repeat(2, minmax(0, 1fr));
  }

  .evo-command-run {
    grid-column: 1 / -1;
  }

  .evo-shell,
  .evo-shell.parchment-logbook {
    grid-template-columns: 224px minmax(0, 1fr);
  }

  .evo-detail-topbar {
    grid-template-columns: minmax(0, 1fr);
    grid-template-areas: "workspace";
    align-items: stretch;
  }
}

@media (max-width: 960px) {
  .evo-page {
    right: 18px;
    left: 18px;
    padding: 0 0 18px;
  }

  .evo-shell,
  .evo-shell.parchment-logbook {
    grid-template-columns: 1fr;
    grid-template-rows: auto auto auto auto;
    grid-template-areas:
      "command"
      "topbar"
      "rail"
      "pane";
    gap: 8px;
    padding: 16px;
    overflow-x: hidden;
    overflow-y: auto;
  }

  .evo-command-bar {
    grid-template-columns: minmax(0, 1fr);
    align-items: stretch;
    gap: 10px;
    margin: 0 12px 8px;
    padding: 14px;
  }

  .evo-command-actions {
    grid-column: auto;
  }

  .evo-control-rail {
    grid-template-columns: minmax(0, 1fr);
    grid-template-rows: auto;
    gap: 8px;
    max-height: 50px;
    overflow: hidden;
    padding: 0 0 8px;
    border-right: none;
    border-bottom: 1px solid var(--evo-border);
  }

  .evo-rail-header,
  .evo-rail-summary {
    display: none;
  }

  .evo-detail-topbar {
    padding: 10px 12px;
    overflow: hidden;
  }

  .evo-nav-tab {
    justify-content: center;
    min-width: 0;
    padding: 0 8px;
  }

  .evo-nav-tab span {
    min-width: 0;
    overflow: hidden;
    text-overflow: ellipsis;
  }

  .evo-role-panel {
    grid-template-columns: auto minmax(0, 1fr);
    grid-template-rows: auto;
    align-items: center;
    min-width: 0;
  }

  .evo-role-list {
    display: flex;
    gap: 8px;
    align-content: initial;
    overflow-x: auto;
    overflow-y: hidden;
    padding-right: 0;
    scrollbar-width: none;
  }

  .evo-role-list::-webkit-scrollbar {
    display: none;
  }

  .evo-role-chip,
  .evo-role-bar-label {
    flex: 0 0 auto;
  }

  .evo-role-chip {
    width: auto;
    min-width: max-content;
  }

  .evo-scroll {
    padding: 12px;
    overflow: visible;
  }

  .evo-main-pane {
    overflow: visible;
  }
}

@media (max-width: 640px) {
  .evo-page {
    right: 10px;
    left: 10px;
    padding-bottom: 10px;
  }

  .evo-shell,
  .evo-shell.parchment-logbook {
    gap: 10px;
    padding: 10px;
  }

  .evo-command-bar {
    grid-template-columns: minmax(0, 1fr) auto;
    grid-template-areas:
      "title action"
      "metrics metrics";
    gap: 6px;
    margin: 0 10px 8px;
    padding: 9px;
  }

  .evo-command-title {
    grid-area: title;
  }

  .evo-command-actions {
    grid-area: action;
    justify-content: end;
    align-self: center;
  }

  .evo-command-metrics {
    grid-area: metrics;
    grid-template-columns: repeat(4, minmax(0, 1fr));
    gap: 4px;
  }

  .evo-command-title {
    grid-template-columns: minmax(0, 1fr);
    gap: 2px;
  }

  .evo-command-title small {
    display: none;
  }

  .evo-command-title h2 {
    font-size: 18px;
  }

  .evo-command-metrics span {
    min-height: 32px;
    padding: 3px 5px;
  }

  .evo-command-metrics small {
    display: block;
    overflow: hidden;
    font-size: 9px;
    text-align: center;
    text-overflow: ellipsis;
    white-space: nowrap;
  }

  .evo-command-metrics b {
    font-size: 12px;
    text-align: center;
  }

  .evo-refresh-button {
    width: auto;
    min-width: 64px;
    height: 30px;
    padding: 0 10px;
    font-size: 12px;
  }

  .evo-control-rail {
    grid-template-columns: minmax(0, 1fr);
    gap: 6px;
    max-height: 40px;
    padding: 0 0 6px;
  }

  .evo-detail-topbar {
    grid-template-columns: minmax(0, 1fr);
    grid-template-areas: "workspace";
    padding: 8px;
  }

  .evo-nav {
    display: grid;
    grid-template-columns: repeat(7, minmax(0, 1fr));
    gap: 5px;
    padding-bottom: 0;
  }

  .evo-nav-tab {
    flex: initial;
    width: 100%;
    height: 30px;
    padding: 0 6px;
  }

  .evo-role-chip {
    height: 30px;
  }

  .evo-scroll {
    padding: 10px;
  }
}
</style>
