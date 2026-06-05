<script setup>
const props = defineProps({
  players: { type: Array, default: () => [] },
  aliveMap: { type: Object, default: () => ({}) },
  sheriffId: [String, Number, null],
  selectedPage: Object,
  roleIconImage: Function
})

function roleImage(player) {
  return props.roleIconImage ? props.roleIconImage(player) : ''
}

function showSheriff(player) {
  return player.id === props.sheriffId
    && props.selectedPage
    && ['sheriff_result', 'speech', 'vote', 'night', 'ended'].includes(props.selectedPage.phase)
}
</script>

<template>
  <section v-if="players.length" class="history-seat-ledger" aria-label="玩家席位">
    <article
      v-for="player in players"
      :key="'history-seat-' + player.id"
      :class="{ dead: !aliveMap[player.id], sheriff: player.is_sheriff || player.id === sheriffId }"
    >
      <img :src="roleImage(player)" :alt="player.role_hint" />
      <b>{{ player.seat }}号</b>
      <span>{{ player.role_hint }}</span>
      <img v-if="showSheriff(player)" src="/ui/sheriff-badge.png" class="sheriff-badge-inline" alt="警长" />
    </article>
  </section>
</template>
