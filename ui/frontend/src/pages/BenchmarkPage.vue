<script setup>
import { computed, ref, onMounted } from 'vue'
import { useEvaluationWorkbench } from '../composables/useEvaluationWorkbench.js'
import BenchmarkBatchRunsTable from '../components/benchmark/BenchmarkBatchRunsTable.vue'
import BenchmarkConfigPanel from '../components/benchmark/BenchmarkConfigPanel.vue'
import BenchmarkLeaderboardTable from '../components/benchmark/BenchmarkLeaderboardTable.vue'

defineOptions({
  inheritAttrs: false
})

defineProps({
  returnToMatchAvailable: Boolean
})

const emit = defineEmits(['back-to-match'])

const benchmark = useEvaluationWorkbench()

const activeTab = ref('config')
const selectedRunCount = computed(() => benchmark.filteredBatchRunRows.value.length)

const navTabs = [
  { key: 'config', label: '配置' },
  { key: 'model-lb', label: '模型榜' },
  { key: 'role-lb', label: '角色版本榜' },
  { key: 'batches', label: '评测记录' }
]

function refresh() {
  benchmark.refreshAll()
}

onMounted(() => benchmark.refreshAll())
</script>

<template>
  <section class="bench-page battle-log-page" aria-label="批量评测">
    <section class="bench-shell parchment-logbook">
      <aside class="bench-control-rail" aria-label="评测角色">
        <header class="bench-rail-header">
          <span>评测角色</span>
        </header>

        <div class="bench-rail-summary">
          <span>
            <small>当前</small>
            <b>{{ benchmark.selectedRoleLabel.value }}</b>
          </span>
          <span>
            <small>角色数</small>
            <b>{{ benchmark.roleRows.value.length }} 个</b>
          </span>
        </div>

        <div class="bench-role-panel" aria-label="角色选择">
          <span class="bench-role-bar-label">角色列表</span>
          <div class="bench-role-list">
            <button
              v-for="role in benchmark.roleRows.value"
              :key="role.key"
              type="button"
              :class="['bench-role-chip', { selected: benchmark.selectedRole.value === role.key }]"
              @click="benchmark.selectRole(role.key)"
            >
              <img :src="role.image" alt="" aria-hidden="true" />
              <span class="bench-role-name">{{ role.label }}</span>
            </button>
          </div>
        </div>
      </aside>

      <main class="bench-detail-panel">
        <header class="bench-command-bar">
          <div class="bench-command-title">
            <h2>批量评测工作台</h2>
          </div>
          <div class="bench-command-actions">
            <button type="button" class="bench-refresh-button" @click="refresh">
              <span aria-hidden="true">&#8635;</span> 刷新
            </button>
          </div>
        </header>

        <div class="bench-detail-topbar">
          <nav class="bench-nav detail-workspace-tabs" aria-label="评测视图">
            <button
              v-for="tab in navTabs"
              :key="tab.key"
              type="button"
              :class="['bench-nav-tab', { active: activeTab === tab.key }]"
              @click="activeTab = tab.key"
            >
              <span>{{ tab.label }}</span>
            </button>
          </nav>
        </div>

        <section class="bench-main-pane">
          <div class="bench-scroll">
          <div v-if="benchmark.error.value" class="bench-alert">{{ benchmark.error.value }}</div>

          <BenchmarkConfigPanel
            v-if="activeTab === 'config'"
            :benchmark="benchmark"
          />

          <BenchmarkLeaderboardTable
            v-if="activeTab === 'model-lb'"
            kind="model"
            title="模型排行榜"
            :meta="`${benchmark.selectedRoleLabel.value} · ${benchmark.modelLeaderboardRows.value.length} 条`"
            :rows="benchmark.modelLeaderboardRows.value"
          />

          <BenchmarkLeaderboardTable
            v-if="activeTab === 'role-lb'"
            kind="role"
            title="角色版本排行榜"
            :meta="`${benchmark.selectedRoleLabel.value} · ${benchmark.roleLeaderboardRows.value.length} 条`"
            :rows="benchmark.roleLeaderboardRows.value"
          />

          <BenchmarkBatchRunsTable
            v-if="activeTab === 'batches'"
            :benchmark="benchmark"
          />
          </div>
        </section>
      </main>
    </section>
  </section>
</template>

<style scoped>
.bench-page {
  --bench-bg: #f8f0e0;
  --bench-surface: rgba(255, 252, 245, 0.7);
  --bench-border: rgba(139, 94, 52, 0.15);
  --bench-text: #3a2a18;
  --bench-text-secondary: #8b6b4a;
  --bench-accent: #8b5e34;
  --bench-accent-strong: #5a3319;
  --bench-input-bg: rgba(255, 255, 250, 0.8);
  --bench-input-border: rgba(139, 94, 52, 0.2);
  --bench-hover: rgba(139, 94, 52, 0.06);
  --bench-active-bg: rgba(139, 94, 52, 0.1);
  --bench-font: "Microsoft YaHei", "PingFang SC", "Noto Sans SC", -apple-system, BlinkMacSystemFont, sans-serif;
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
  color: var(--bench-text);
  font-family: var(--bench-font);
  -webkit-font-smoothing: auto;
  text-rendering: auto;
}

.bench-shell {
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

.bench-shell.parchment-logbook {
  grid-template-columns: 248px minmax(0, 1fr);
}

.bench-detail-panel {
  display: contents;
}

.bench-command-bar {
  grid-area: command;
  display: grid;
  grid-template-columns: minmax(220px, 1.1fr) minmax(300px, 1fr) auto;
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

.bench-command-title {
  display: grid;
  grid-template-columns: minmax(0, 1fr);
  align-items: end;
  gap: 4px;
  min-width: 0;
}

.bench-command-title small {
  grid-column: 1 / -1;
  color: rgba(232, 196, 132, 0.72);
  font-size: 11px;
  font-weight: 700;
  letter-spacing: 0;
}

.bench-command-title h2 {
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

.bench-command-metrics {
  display: grid;
  grid-template-columns: repeat(4, minmax(68px, 1fr));
  align-items: center;
  gap: 8px;
  min-width: 0;
}

.bench-command-metrics span {
  display: grid;
  gap: 4px;
  min-height: 48px;
  padding: 8px 10px;
  border: 1px solid rgba(232, 196, 132, 0.18);
  border-radius: 7px;
  background: rgba(255, 246, 218, 0.08);
}

.bench-command-metrics small {
  color: rgba(232, 210, 170, 0.68);
  font-size: 11px;
  font-weight: 700;
  line-height: 1;
}

.bench-command-metrics b {
  min-width: 0;
  overflow: hidden;
  color: #fff4d9;
  font-size: 15px;
  font-weight: 800;
  line-height: 1.15;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.bench-command-actions {
  display: flex;
  justify-content: flex-end;
}

.bench-refresh-button {
  display: inline-flex;
  align-items: center;
  justify-content: center;
  gap: 8px;
  min-width: 92px;
  height: 42px;
  padding: 0 15px;
  border: 1px solid rgba(232, 196, 132, 0.25);
  border-radius: 7px;
  color: #2d1e10;
  background: #e8c484;
  box-shadow: 0 3px 10px rgba(18, 10, 5, 0.18);
  font-size: 13px;
  font-weight: 800;
  cursor: pointer;
  transition: transform 0.15s ease, box-shadow 0.15s ease;
  white-space: nowrap;
}

.bench-refresh-button:hover {
  transform: translateY(-1px);
  box-shadow: 0 5px 14px rgba(18, 10, 5, 0.22);
}

.bench-workspace {
  display: grid;
  grid-template-columns: 232px minmax(0, 1fr);
  min-width: 0;
  min-height: 0;
  overflow: hidden;
}

.bench-control-rail {
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

.bench-rail-header {
  display: flex;
  align-items: center;
  gap: 10px;
  min-height: 48px;
  padding: 14px 14px 12px;
  border-bottom: 1px solid var(--bench-border);
}

.bench-rail-header span {
  color: var(--bench-text);
  font-size: 16px;
  font-weight: 800;
  letter-spacing: 0;
}

.bench-rail-header strong {
  margin-left: auto;
  display: inline-flex;
  align-items: center;
  justify-content: center;
  min-width: 26px;
  height: 22px;
  padding: 0 7px;
  border-radius: 11px;
  background: var(--bench-active-bg);
  color: var(--bench-accent);
  font-size: 12px;
  font-weight: 800;
}

.bench-rail-summary {
  display: grid;
  grid-template-columns: repeat(2, minmax(0, 1fr));
  gap: 7px;
  padding: 0 0 2px;
}

.bench-rail-summary span {
  display: grid;
  gap: 4px;
  min-width: 0;
  min-height: 48px;
  padding: 8px 10px;
  border: 1px solid var(--bench-border);
  border-radius: 7px;
  background: rgba(255, 252, 245, 0.42);
}

.bench-rail-summary small {
  color: var(--bench-text-secondary);
  font-size: 11px;
  font-weight: 700;
  line-height: 1;
}

.bench-rail-summary b {
  min-width: 0;
  overflow: hidden;
  color: var(--bench-text);
  font-size: 13px;
  font-weight: 800;
  line-height: 1.1;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.bench-main-pane {
  grid-area: pane;
  align-self: start;
  min-width: 0;
  min-height: 0;
  max-height: calc(100vh - 245px);
  border: 1px solid var(--bench-border);
  border-top: none;
  border-radius: 0 0 8px 8px;
  background: rgba(255, 252, 245, 0.24);
  overflow: hidden;
}

.bench-detail-topbar {
  grid-area: topbar;
  display: grid;
  grid-template-columns: minmax(0, 1fr);
  grid-template-areas: "workspace";
  align-items: center;
  gap: 8px 14px;
  flex: 0 0 auto;
  min-width: 0;
  padding: 10px 16px;
  border-right: 1px solid var(--bench-border);
  border-left: 1px solid var(--bench-border);
  border-bottom: 1px solid var(--bench-border);
  background: rgba(255, 252, 245, 0.4);
}

.bench-nav {
  grid-area: workspace;
  display: flex;
  gap: 6px;
  min-width: 0;
  overflow-x: auto;
  padding-bottom: 2px;
  scrollbar-width: none;
}

.bench-nav::-webkit-scrollbar {
  display: none;
}

.bench-nav-tab {
  display: inline-flex;
  align-items: center;
  justify-content: space-between;
  gap: 6px;
  flex: 0 0 auto;
  width: auto;
  height: 34px;
  padding: 0 12px;
  border: 1px solid var(--bench-input-border);
  border-radius: 7px;
  background: rgba(255, 252, 245, 0.62);
  color: var(--bench-accent-strong);
  font-size: 12px;
  font-weight: 800;
  text-align: left;
  cursor: pointer;
  white-space: nowrap;
}

.bench-nav-tab:hover {
  border-color: var(--bench-accent-strong);
}

.bench-nav-tab.active {
  border-color: var(--bench-accent-strong);
  background: var(--bench-accent-strong);
  color: #fff7dc;
}

.bench-role-panel {
  display: grid;
  grid-template-rows: auto minmax(0, 1fr);
  gap: 8px;
  min-height: 0;
}

.bench-role-bar-label {
  color: var(--bench-accent);
  font-size: 12px;
  font-weight: 800;
}

.bench-role-list {
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

.bench-role-chip {
  display: inline-flex;
  align-items: center;
  justify-content: flex-start;
  gap: 6px;
  width: 100%;
  height: 31px;
  padding: 0 10px;
  border: 1px solid var(--bench-input-border);
  border-radius: 7px;
  background: rgba(255, 252, 245, 0.62);
  color: var(--bench-text-secondary);
  font-size: 12px;
  font-weight: 800;
  cursor: pointer;
  transition: background 0.16s ease, border-color 0.16s ease, color 0.16s ease;
}

.bench-role-chip:hover {
  background: var(--bench-hover);
  border-color: var(--bench-accent);
}

.bench-role-chip img {
  flex: 0 0 auto;
  width: 19px;
  height: 19px;
  border-radius: 50%;
  border: 1px solid var(--bench-border);
}

.bench-role-name {
  font-size: 12px;
  font-weight: 800;
}

.bench-role-chip.selected {
  background: var(--bench-accent-strong);
  color: #fff;
  border-color: var(--bench-accent-strong);
  box-shadow: 0 2px 8px rgba(90, 51, 25, 0.2);
}

.bench-role-chip.selected .bench-role-name {
  color: #fff;
}

.bench-role-chip.selected img {
  border-color: rgba(255, 255, 255, 0.3);
}

.bench-scroll {
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

.bench-scroll::-webkit-scrollbar {
  width: 6px;
}

.bench-scroll::-webkit-scrollbar-track {
  background: transparent;
}

.bench-scroll::-webkit-scrollbar-thumb {
  background: rgba(139, 94, 52, 0.15);
  border-radius: 3px;
}

.bench-scroll::-webkit-scrollbar-thumb:hover {
  background: rgba(139, 94, 52, 0.25);
}

.bench-alert {
  margin-bottom: 16px;
  padding: 10px 14px;
  border: 1px solid rgba(168, 42, 42, 0.2);
  border-radius: 8px;
  background: rgba(168, 42, 42, 0.06);
  color: #8b3a3a;
  font-size: 13px;
  font-weight: 600;
}

@media (max-width: 1120px) {
  .bench-command-bar {
    grid-template-columns: minmax(0, 1fr) minmax(220px, 0.8fr);
    margin: 0 12px 10px;
  }

  .bench-command-actions {
    grid-column: 1 / -1;
    justify-content: flex-start;
  }

  .bench-command-metrics {
    grid-template-columns: repeat(2, minmax(0, 1fr));
  }

  .bench-shell,
  .bench-shell.parchment-logbook {
    grid-template-columns: 224px minmax(0, 1fr);
  }

  .bench-detail-topbar {
    grid-template-columns: minmax(0, 1fr);
    grid-template-areas: "workspace";
    align-items: stretch;
  }
}

@media (max-width: 960px) {
  .bench-page {
    right: 18px;
    left: 18px;
    padding: 0 0 18px;
  }

  .bench-shell,
  .bench-shell.parchment-logbook {
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

  .bench-command-bar {
    grid-template-columns: minmax(0, 1fr);
    align-items: stretch;
    gap: 10px;
    margin: 0 12px 8px;
    padding: 14px;
  }

  .bench-command-actions {
    grid-column: auto;
  }

  .bench-workspace {
    grid-template-columns: 1fr;
    grid-template-rows: auto minmax(0, 1fr);
  }

  .bench-control-rail {
    grid-template-columns: minmax(0, 1fr);
    grid-template-rows: auto;
    gap: 8px;
    max-height: 50px;
    overflow: hidden;
    padding: 0 0 8px;
    border-right: none;
    border-bottom: 1px solid var(--bench-border);
  }

  .bench-rail-header {
    display: none;
  }

  .bench-rail-summary {
    display: none;
  }

  .bench-detail-topbar {
    padding: 10px 12px;
    overflow: hidden;
  }

  .bench-nav-tab {
    justify-content: center;
    min-width: max-content;
    min-width: 0;
    padding: 0 8px;
  }

  .bench-nav-tab span {
    min-width: 0;
    overflow: hidden;
    text-overflow: ellipsis;
  }

  .bench-role-panel {
    grid-template-columns: auto minmax(0, 1fr);
    grid-template-rows: auto;
    align-items: center;
    min-width: 0;
  }

  .bench-role-list {
    display: flex;
    gap: 8px;
    align-content: initial;
    overflow-x: auto;
    overflow-y: hidden;
    padding-right: 0;
    scrollbar-width: none;
  }

  .bench-role-list::-webkit-scrollbar {
    display: none;
  }

  .bench-role-chip,
  .bench-role-bar-label {
    flex: 0 0 auto;
  }

  .bench-role-chip {
    width: auto;
    min-width: max-content;
  }

  .bench-scroll {
    padding: 12px;
    overflow: visible;
  }

  .bench-main-pane {
    overflow: visible;
  }
}

@media (max-width: 640px) {
  .bench-page {
    right: 10px;
    left: 10px;
    padding-bottom: 10px;
  }

  .bench-shell,
  .bench-shell.parchment-logbook {
    gap: 10px;
    padding: 10px;
  }

  .bench-command-bar {
    grid-template-columns: minmax(0, 1fr) auto;
    grid-template-areas:
      "title action"
      "metrics metrics";
    gap: 6px;
    margin: 0 10px 8px;
    padding: 9px;
  }

  .bench-command-title {
    grid-area: title;
  }

  .bench-command-actions {
    grid-area: action;
    justify-content: end;
    align-self: center;
  }

  .bench-command-metrics {
    grid-area: metrics;
  }

  .bench-command-title {
    grid-template-columns: minmax(0, 1fr);
    gap: 2px;
  }

  .bench-command-title small {
    display: none;
  }

  .bench-command-title h2 {
    font-size: 18px;
  }

  .bench-command-metrics {
    grid-template-columns: repeat(4, minmax(0, 1fr));
    gap: 4px;
  }

  .bench-command-metrics span {
    min-height: 32px;
    padding: 3px 5px;
  }

  .bench-command-metrics small {
    display: block;
    overflow: hidden;
    font-size: 9px;
    text-align: center;
    text-overflow: ellipsis;
    white-space: nowrap;
  }

  .bench-command-metrics b {
    font-size: 12px;
    text-align: center;
  }

  .bench-refresh-button {
    width: auto;
    min-width: 64px;
    height: 30px;
    padding: 0 10px;
    font-size: 12px;
  }

  .bench-control-rail {
    grid-template-columns: minmax(0, 1fr);
    gap: 6px;
    max-height: 40px;
    padding: 0 0 6px;
  }

  .bench-detail-topbar {
    grid-template-columns: minmax(0, 1fr);
    grid-template-areas: "workspace";
    padding: 8px;
  }

  .bench-nav {
    display: grid;
    grid-template-columns: repeat(4, minmax(0, 1fr));
    gap: 5px;
    padding-bottom: 0;
  }

  .bench-nav-tab {
    flex: initial;
    width: 100%;
    height: 30px;
    padding: 0 6px;
  }

  .bench-role-chip {
    height: 30px;
  }

  .bench-scroll {
    padding: 10px;
  }
}

/* Match the quiet wood-board language used by the battle log. */
.bench-page {
  --bench-surface: rgba(255, 239, 194, 0.42);
  --bench-border: rgba(93, 48, 17, 0.18);
  --bench-text: #3a1b08;
  --bench-text-secondary: rgba(93, 48, 17, 0.66);
  --bench-accent: #70401e;
  --bench-accent-strong: #5d3011;
  --bench-input-bg: rgba(255, 245, 214, 0.7);
  --bench-input-border: rgba(93, 48, 17, 0.22);
  --bench-hover: rgba(255, 245, 211, 0.5);
  --bench-active-bg: rgba(224, 184, 111, 0.66);
}

.bench-shell.parchment-logbook {
  background:
    repeating-linear-gradient(90deg, rgba(118, 71, 27, 0.024) 0 1px, transparent 1px 34px),
    #f2dfae;
}

.bench-nav-tab,
.bench-role-chip,
.bench-refresh-button {
  border: 1px solid rgba(93, 48, 17, 0.18);
  border-bottom-color: rgba(93, 48, 17, 0.34);
  border-radius: 6px;
  color: rgba(59, 28, 9, 0.78);
  background: rgba(255, 239, 194, 0.58);
  box-shadow: inset 0 1px 0 rgba(255, 252, 228, 0.76);
}

.bench-nav-tab:hover,
.bench-role-chip:hover,
.bench-refresh-button:hover {
  border-color: rgba(93, 48, 17, 0.32);
  color: #3a1b08;
  background: rgba(255, 245, 214, 0.88);
  box-shadow: inset 0 1px 0 rgba(255, 252, 228, 0.82);
  transform: none;
}

.bench-nav-tab.active,
.bench-role-chip.selected {
  border-color: rgba(93, 48, 17, 0.45);
  color: #3a1b08;
  background: rgba(224, 184, 111, 0.66);
  box-shadow: inset 0 1px 2px rgba(93, 48, 17, 0.18);
}

.bench-role-chip.selected .bench-role-name {
  color: #3a1b08;
}

.bench-card {
  border-color: rgba(93, 48, 17, 0.18);
  border-radius: 7px;
  background: rgba(255, 239, 194, 0.34);
  box-shadow: none;
}

.bench-card header {
  background: rgba(255, 245, 214, 0.36);
}

@media (min-width: 961px) {
  .bench-shell,
  .bench-shell.parchment-logbook {
    grid-template-columns: 260px minmax(0, 1fr);
    column-gap: 24px;
    padding: 22px 26px;
  }

  .bench-control-rail {
    gap: 10px;
    padding-right: 20px;
    border-right-color: rgba(93, 48, 17, 0.22);
  }

  .bench-rail-header {
    min-height: 46px;
    padding: 0 0 12px;
    border-bottom-color: rgba(93, 48, 17, 0.2);
  }

  .bench-rail-header span {
    font-size: 22px;
    font-weight: 950;
  }

  .bench-rail-header strong {
    height: auto;
    padding: 0;
    border-radius: 0;
    background: transparent;
    color: var(--bench-text-secondary);
    font-size: 13px;
  }

  .bench-rail-summary {
    gap: 8px;
  }

  .bench-rail-summary span {
    min-height: 44px;
    padding: 7px 9px;
    border-color: rgba(93, 48, 17, 0.16);
    background: rgba(255, 239, 194, 0.42);
  }

  .bench-role-chip {
    height: 36px;
    padding: 0 11px;
  }

  .bench-command-bar {
    grid-template-columns: minmax(0, 1fr) auto;
    gap: 20px;
    padding: 0 0 12px;
    border: 0;
    border-bottom: 1px solid rgba(93, 48, 17, 0.2);
    border-radius: 0;
    background: transparent;
    box-shadow: none;
  }

  .bench-command-title small {
    color: var(--bench-text-secondary);
  }

  .bench-command-title h2 {
    color: var(--bench-text);
    font-size: 22px;
    font-weight: 950;
  }

  .bench-command-metrics {
    gap: 18px;
  }

  .bench-command-metrics span {
    min-height: auto;
    padding: 0;
    border: 0;
    border-radius: 0;
    background: transparent;
  }

  .bench-command-metrics small {
    color: var(--bench-text-secondary);
  }

  .bench-command-metrics b {
    color: var(--bench-text);
  }

  .bench-refresh-button {
    height: 36px;
  }

  .bench-detail-topbar {
    padding: 10px 0;
    border: 0;
    border-bottom: 1px solid rgba(93, 48, 17, 0.16);
    background: transparent;
  }

  .bench-nav {
    gap: 8px;
    padding: 0;
  }

  .bench-nav-tab {
    height: 32px;
    padding: 0 14px;
  }

  .bench-main-pane {
    max-height: calc(100vh - 205px);
    border: 0;
    border-radius: 0;
    background: transparent;
  }

  .bench-scroll {
    max-height: calc(100vh - 205px);
    padding: 14px 0 0;
  }
}
</style>
