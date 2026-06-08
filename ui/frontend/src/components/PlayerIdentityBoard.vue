<script setup>
const props = defineProps({
  players: { type: Array, default: () => [] },
  activeSeat: { type: [String, Number], default: '' },
  selectedTargetId: { type: [String, Number, null], default: null },
  panelHeight: { type: Number, default: 146 }
})

function isActiveSeat(player) {
  return Boolean(props.activeSeat) && String(player?.displaySeat ?? '') === String(props.activeSeat)
}

function isSelectedTarget(player) {
  if (props.selectedTargetId == null || props.selectedTargetId === '') return false
  return Number(player?.id) === Number(props.selectedTargetId)
}
</script>

<template>
  <aside class="role-grid-panel" :style="{ height: `${panelHeight}px` }" aria-label="玩家身份列">
    <div class="role-grid">
      <article
        v-for="(player, index) in players"
        :key="player.id"
        :class="{ speaking: player.speaking, linked: isActiveSeat(player), targeted: isSelectedTarget(player), dead: !player.alive }"
        :style="{ '--i': index }"
      >
        <img v-show="player.isSheriff" class="sheriff-badge-sm" src="/ui/sheriff-badge.png" alt="警长" />
        <div class="role-icon-wrap" :class="{ dead: !player.alive }">
          <img :src="player.roleIcon" :alt="player.role_hint" />
        </div>
        <div class="role-grid-seat">
          <b>{{ player.displaySeat }}</b>
        </div>
      </article>
    </div>
  </aside>
</template>
