<script setup lang="ts">
import type { PropType } from 'vue'
import {
  displayChoiceLabel,
  displayRoleLabel,
  normalizeHistoryDisplayText
} from './history/historyDisplay.ts'

type CandidateValue = string | number | Candidate

type Candidate = {
  id?: string | number
  player_id?: string | number
  seat?: string | number
  seat_id?: string | number
  target_id?: string | number
  name?: string | number
  role?: string
  role_hint?: string
  identity?: string
}

type DecisionDetail = {
  private_reasoning?: unknown
  reason?: unknown
  public_summary?: unknown
  targetName?: string
  candidates?: CandidateValue[]
  alternatives?: unknown[]
  memory_summary?: unknown[]
  selected_skill?: unknown
  policy_adjustments?: unknown[]
  errors?: unknown[]
  raw_output?: unknown
}

const props = defineProps({
  decision: Object as PropType<DecisionDetail | null>,
  detailTab: { type: String, default: 'summary' },
  emptyText: { type: String, default: '点击左侧卡片查看详情' }
})

const emit = defineEmits<{
  'update:detailTab': [key: string]
}>()

const tabs = [
  { key: 'summary', label: '理由' },
  { key: 'candidates', label: '候选' },
  { key: 'process', label: '决策' },
  { key: 'memory', label: '记忆' },
  { key: 'skills', label: '技能' },
  { key: 'reasoning', label: '推理' },
  { key: 'raw', label: '原始' }
]

function setTab(key: string) {
  emit('update:detailTab', key)
}

function rawOutput(value: unknown) {
  if (value == null || value === '') return '无原始输出数据'
  const text = typeof value === 'string' ? value : JSON.stringify(value, null, 2)
  return normalizeHistoryDisplayText(text) || '无可展示内容'
}

function decisionText(...values: unknown[]) {
  for (const value of values) {
    const text = normalizeHistoryDisplayText(value || '')
    if (text) return text
  }
  return '暂无可展示内容'
}

function roleText(role: unknown) {
  return displayRoleLabel(role)
}

function skillText(skill: unknown) {
  return displayChoiceLabel(skill)
}

function candidateSeat(candidate: CandidateValue) {
  const raw = typeof candidate === 'object' && candidate !== null
    ? (candidate.seat ?? candidate.seat_id ?? candidate.id ?? candidate.player_id ?? candidate.target_id ?? candidate.name)
    : candidate
  const seat = Number(raw)
  if (Number.isFinite(seat) && seat > 0) return `${seat}号`
  return normalizeHistoryDisplayText(raw) || '未知'
}

function candidateRole(candidate: CandidateValue) {
  if (typeof candidate !== 'object' || candidate === null) return '未知'
  return roleText(candidate.role ?? candidate.role_hint ?? candidate.identity ?? '')
}

function candidateKey(candidate: CandidateValue, index = 0): string | number {
  if (typeof candidate === 'object' && candidate !== null) {
    return candidate.id ?? candidate.player_id ?? candidate.seat ?? candidate.name ?? index
  }
  if (typeof candidate === 'number') return candidate
  return String(candidate)
}

function normalizedList(items: unknown[] = []) {
  return items.map((item) => normalizeHistoryDisplayText(item)).filter(Boolean)
}
</script>

<template>
  <div v-if="decision" class="night-right">
    <div class="nmc-tabs">
      <button
        v-for="tab in tabs"
        :key="tab.key"
        :class="['nmc-tab', { on: detailTab === tab.key }]"
        @click="setTab(tab.key)"
      >
        {{ tab.label }}
      </button>
    </div>
    <div class="nmc-detail-body">
      <div v-if="detailTab === 'summary'">
        <div class="nmc-dt">
          <p>{{ decisionText(decision.private_reasoning, decision.reason, decision.public_summary) }}</p>
        </div>
      </div>
      <div v-if="detailTab === 'candidates'">
        <div class="nmc-dt" v-if="decision.targetName && decision.targetName !== '无目标'">
          <h4>目标</h4>
          <p>{{ decision.targetName }}</p>
        </div>
        <div class="nmc-dt" v-if="decision.candidates?.length">
          <h4>候选</h4>
          <table class="nmc-tbl">
            <thead>
              <tr><th>座位</th><th>角色</th></tr>
            </thead>
            <tbody>
              <tr v-for="(candidate, index) in decision.candidates" :key="candidateKey(candidate, index)">
                <td>{{ candidateSeat(candidate) }}</td>
                <td>{{ candidateRole(candidate) }}</td>
              </tr>
            </tbody>
          </table>
        </div>
        <div class="nmc-dt" v-if="decision.alternatives?.length">
          <h4>备选</h4>
          <p>{{ normalizedList(decision.alternatives).join('、') || '暂无备选数据' }}</p>
        </div>
        <p v-if="!decision.candidates?.length && !decision.alternatives?.length && !decision.targetName" style="color:#8a7e6a;">
          暂无候选数据
        </p>
      </div>
      <div v-if="detailTab === 'process'">
        <div class="nmc-dt">
          <p>{{ decisionText(decision.public_summary, decision.private_reasoning, decision.reason) }}</p>
        </div>
      </div>
      <div v-if="detailTab === 'memory'">
        <div class="nmc-dt" v-if="decision.memory_summary?.length">
          <h4>记忆摘要</h4>
          <ul class="nmc-mem">
            <li v-for="(item, index) in normalizedList(decision.memory_summary)" :key="index">{{ item }}</li>
          </ul>
        </div>
        <p v-if="!decision.memory_summary?.length" style="color:#8a7e6a;">暂无记忆数据</p>
      </div>
      <div v-if="detailTab === 'skills'">
        <div class="nmc-dt" v-if="decision.selected_skill">
          <h4>使用技能</h4>
          <p><span class="nmc-badge skl">{{ skillText(decision.selected_skill) }}</span></p>
        </div>
        <div class="nmc-dt" v-if="decision.policy_adjustments?.length">
          <h4>策略修正</h4>
          <p v-for="(item, index) in normalizedList(decision.policy_adjustments)" :key="index">{{ item }}</p>
        </div>
        <div class="nmc-dt" v-if="decision.errors?.length">
          <h4>错误</h4>
          <p v-for="(item, index) in normalizedList(decision.errors)" :key="index" style="color:#c0392b;">{{ item }}</p>
        </div>
        <p v-if="!decision.selected_skill && !decision.policy_adjustments?.length && !decision.errors?.length" style="color:#8a7e6a;">
          暂无技能数据
        </p>
      </div>
      <div v-if="detailTab === 'reasoning'">
        <div class="nmc-dt">
          <h4>推理 / 理由</h4>
          <div class="nmc-code">{{ decisionText(decision.private_reasoning, decision.reason) }}</div>
        </div>
      </div>
      <div v-if="detailTab === 'raw'">
        <div class="nmc-dt">
          <h4>原始输出</h4>
          <div class="nmc-code">{{ rawOutput(decision.raw_output) }}</div>
        </div>
      </div>
    </div>
  </div>
  <div v-else class="night-right night-right-empty">{{ emptyText }}</div>
</template>
