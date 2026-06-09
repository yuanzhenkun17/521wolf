<script setup lang="ts">
// @ts-nocheck
const props = defineProps({
  players: { type: Array, default: () => [] },
  aliveMap: { type: Object, default: () => ({}) },
  sheriffId: [String, Number, null],
  selectedPage: Object,
  roleIconImage: Function,
  selectable: Boolean,
  selectedPlayerId: [String, Number, null]
})

const emit = defineEmits(['select-player'])

function roleImage(player) {
  return props.roleIconImage ? props.roleIconImage(player) : ''
}

function showSheriff(player) {
  return player.id === props.sheriffId
    && props.selectedPage
    && ['sheriff_result', 'speech', 'vote', 'night', 'ended'].includes(props.selectedPage.phase)
}

function selectPlayer(player) {
  if (props.selectable) emit('select-player', player)
}
</script>

<template>
  <section v-if="players.length" class="history-seat-ledger" aria-label="玩家席位">
    <article
      v-for="player in players"
      :key="'history-seat-' + player.id"
      :class="{
        dead: !aliveMap[player.id],
        sheriff: player.is_sheriff || player.id === sheriffId,
        selectable,
        selected: selectable && player.id === selectedPlayerId
      }"
      :role="selectable ? 'button' : undefined"
      :tabindex="selectable ? 0 : undefined"
      @click="selectPlayer(player)"
      @keydown.enter.prevent="selectPlayer(player)"
      @keydown.space.prevent="selectPlayer(player)"
    >
      <img :src="roleImage(player)" :alt="player.role_hint" />
      <b>{{ player.seat }}号</b>
      <span>{{ player.role_hint }}</span>
      <img v-if="showSheriff(player)" src="/ui/sheriff-badge.png" class="sheriff-badge-inline" alt="警长" />
    </article>
  </section>
</template>
