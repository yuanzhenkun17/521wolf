<script setup lang="ts">
import type { PropType } from 'vue'
import RoleStats from './RoleStats.vue'

interface GroupedJudgeLogEntry {
  speaker?: string
  message?: string
}

interface GroupedJudgeLog {
  key: string | number
  day: number | string
  phaseLabel: string
  phase: string
  logs: GroupedJudgeLogEntry[]
}

interface RoleStat {
  role: string
  alive: number
  total: number
}

type LogFormatter = (log: GroupedJudgeLogEntry) => string

const props = defineProps({
  groupedJudgeLogs: { type: Array as PropType<GroupedJudgeLog[]>, default: () => [] },
  displayPhase: { type: String, default: '' },
  roleStats: { type: Array as PropType<RoleStat[]>, default: () => [] },
  livingCount: { type: Number, default: 0 },
  totalCount: { type: Number, default: 0 },
  logSpeaker: Function as PropType<LogFormatter>,
  logMessage: Function as PropType<LogFormatter>
})

function speaker(log: GroupedJudgeLogEntry) {
  return props.logSpeaker ? props.logSpeaker(log) : (log?.speaker || '')
}

function message(log: GroupedJudgeLogEntry) {
  return props.logMessage ? props.logMessage(log) : (log?.message || '')
}
</script>

<template>
  <aside class="info-stack">
    <section class="judge-panel match-panel">
      <header>
        <span>法官日志</span>
        <strong>{{ displayPhase }}</strong>
      </header>
      <div class="judge-list">
        <div v-for="group in groupedJudgeLogs" :key="group.key" class="log-group">
          <div class="log-group-header">
            <span class="log-day">第 {{ group.day }} 天</span>
            <span class="log-phase">{{ group.phaseLabel }}</span>
            <span class="log-phase-icon">{{ group.phase === 'night' ? '☾' : '☀' }}</span>
          </div>
          <article v-for="(log, index) in group.logs" :key="index" class="log-entry">
            <span class="log-speaker">{{ speaker(log) }}</span>
            <p class="log-message">{{ message(log) }}</p>
          </article>
        </div>
      </div>
    </section>
    <RoleStats
      :stats="roleStats"
      :living-count="livingCount"
      :total-count="totalCount"
    />
  </aside>
</template>
