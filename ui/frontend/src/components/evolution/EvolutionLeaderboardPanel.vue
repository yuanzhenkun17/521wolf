<script setup>
defineProps({
  evo: { type: Object, required: true }
})
</script>

<template>
  <div class="evo-tab-panel">
    <article class="evo-card">
      <header>
        <h2>角色排行榜</h2>
        <b>{{ evo.selectedRoleLabel.value }}</b>
      </header>
      <div v-if="!evo.selectedRoleLeaderboard.value.length" class="evo-empty">暂无对战数据</div>
      <div v-else class="evo-leaderboard">
        <div
          v-for="item in evo.selectedRoleLeaderboard.value"
          :key="item.hash"
          class="evo-leaderboard-row"
        >
          <span class="evo-leaderboard-label">
            {{ item.short }}<small>{{ item.is_baseline ? '基线' : (item.recommendationLabel || '未标记') }}</small>
          </span>
          <div class="evo-leaderboard-bar-wrap">
            <div class="evo-leaderboard-bar" :style="{ width: item.scorePct + '%', background: item.is_baseline ? '#7b5735' : '#0f6b72' }"></div>
          </div>
          <span class="evo-leaderboard-value">{{ item.scorePct }}%</span>
        </div>
      </div>
    </article>
  </div>
</template>
