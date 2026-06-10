<script setup lang="ts">
import { computed, type PropType } from 'vue'

interface VoteRecord {
  actorName?: string
  actor_name?: string
  actor_id?: string | number
}

interface VoteTallyItem {
  count?: number | string
  votes?: VoteRecord[]
  voter_ids?: Array<string | number>
  voters?: string[]
  target?: string
  targetName?: string
  target_id?: string | number
}

const props = defineProps({
  tally: { type: Array as PropType<VoteTallyItem[]>, default: () => [] }
})

const colors = ['#8b5425', '#c0392b', '#2980b9', '#27ae60', '#8e44ad', '#d35400', '#16a085']
const maxCount = computed(() => Math.max(...props.tally.map((item) => voteCount(item)), 1))

function voteCount(item: VoteTallyItem) {
  const count = Number(item?.count)
  if (Number.isFinite(count) && count > 0) return count
  if (Array.isArray(item?.votes)) return item.votes.length
  if (Array.isArray(item?.voter_ids)) return item.voter_ids.length
  if (Array.isArray(item?.voters)) return item.voters.length
  return 0
}

function barStyle(item: VoteTallyItem, index: number) {
  return {
    width: `${(voteCount(item) / maxCount.value) * 100}%`,
    background: colors[index % colors.length]
  }
}

function targetLabel(item: VoteTallyItem) {
  return item.target || item.targetName || (item.target_id ? `${item.target_id}号` : '未知')
}

function voterLabels(item: VoteTallyItem) {
  if (Array.isArray(item.voters) && item.voters.length) return item.voters
  if (Array.isArray(item.votes) && item.votes.length) {
    return item.votes
      .map((vote) => vote.actorName || vote.actor_name || (vote.actor_id ? `${vote.actor_id}号` : ''))
      .filter(Boolean)
  }
  if (Array.isArray(item.voter_ids) && item.voter_ids.length) {
    return item.voter_ids.map((id) => `${id}号`)
  }
  return []
}

function voterText(item: VoteTallyItem) {
  const voters = voterLabels(item)
  return voters.length ? voters.join('、') : '暂无投票人记录'
}
</script>

<template>
  <div v-if="tally.length" class="sheriff-bar-chart">
    <div v-for="(item, index) in tally" :key="targetLabel(item)" class="sheriff-bar-row">
      <span class="sheriff-bar-label">{{ targetLabel(item) }}</span>
      <div class="sheriff-bar-main">
        <div class="sheriff-bar-track">
          <div class="sheriff-bar-fill" :style="barStyle(item, index)"></div>
        </div>
        <small class="sheriff-bar-voters">{{ voterText(item) }}</small>
      </div>
      <span class="sheriff-bar-val">{{ voteCount(item) }} 票</span>
    </div>
  </div>
</template>
