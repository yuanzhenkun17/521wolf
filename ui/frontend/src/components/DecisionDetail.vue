<script setup>
const props = defineProps({
  decision: Object,
  detailTab: { type: String, default: 'summary' },
  emptyText: { type: String, default: '点击左侧卡片查看详情' }
})

const emit = defineEmits(['update:detailTab'])

const tabs = [
  { key: 'summary', label: '理由' },
  { key: 'candidates', label: '候选' },
  { key: 'process', label: '决策' },
  { key: 'memory', label: '记忆' },
  { key: 'skills', label: 'Skills' },
  { key: 'prompt', label: 'Prompt' },
  { key: 'raw', label: 'Raw Output' }
]

function setTab(key) {
  emit('update:detailTab', key)
}

function rawOutput(value) {
  if (value == null || value === '') return '无 Raw Output 数据'
  return typeof value === 'string' ? value : JSON.stringify(value, null, 2)
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
          <p>{{ decision.private_reasoning || decision.reason || '暂无理由' }}</p>
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
              <tr v-for="candidate in decision.candidates" :key="candidate.id">
                <td>{{ candidate.seat }}号</td>
                <td>{{ candidate.role }}</td>
              </tr>
            </tbody>
          </table>
        </div>
        <div class="nmc-dt" v-if="decision.alternatives?.length">
          <h4>备选</h4>
          <p>{{ decision.alternatives.join('、') }}</p>
        </div>
        <p v-if="!decision.candidates?.length && !decision.alternatives?.length && !decision.targetName" style="color:#8a7e6a;">
          暂无候选数据
        </p>
      </div>
      <div v-if="detailTab === 'process'">
        <div class="nmc-dt">
          <p>{{ decision.private_reasoning || decision.reason || '暂无决策内容' }}</p>
        </div>
      </div>
      <div v-if="detailTab === 'memory'">
        <div class="nmc-dt" v-if="decision.memory_summary?.length">
          <h4>记忆摘要</h4>
          <ul class="nmc-mem">
            <li v-for="(item, index) in decision.memory_summary" :key="index">{{ item }}</li>
          </ul>
        </div>
        <p v-if="!decision.memory_summary?.length" style="color:#8a7e6a;">暂无记忆数据</p>
      </div>
      <div v-if="detailTab === 'skills'">
        <div class="nmc-dt" v-if="decision.selected_skill">
          <h4>使用技能</h4>
          <p><span class="nmc-badge skl">{{ decision.selected_skill }}</span></p>
        </div>
        <div class="nmc-dt" v-if="decision.policy_adjustments?.length">
          <h4>策略修正</h4>
          <p v-for="(item, index) in decision.policy_adjustments" :key="index">{{ item }}</p>
        </div>
        <div class="nmc-dt" v-if="decision.errors?.length">
          <h4>错误</h4>
          <p v-for="(item, index) in decision.errors" :key="index" style="color:#c0392b;">{{ item }}</p>
        </div>
        <p v-if="!decision.selected_skill && !decision.policy_adjustments?.length && !decision.errors?.length" style="color:#8a7e6a;">
          暂无技能数据
        </p>
      </div>
      <div v-if="detailTab === 'prompt'">
        <div class="nmc-dt">
          <h4>Prompt</h4>
          <div class="nmc-code">{{ decision.private_reasoning || decision.reason || '无 Prompt 数据' }}</div>
        </div>
      </div>
      <div v-if="detailTab === 'raw'">
        <div class="nmc-dt">
          <h4>Raw Output</h4>
          <div class="nmc-code">{{ rawOutput(decision.raw_output) }}</div>
        </div>
      </div>
    </div>
  </div>
  <div v-else class="night-right night-right-empty">{{ emptyText }}</div>
</template>
