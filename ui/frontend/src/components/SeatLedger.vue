<script setup lang="ts">
import type { PropType } from 'vue'

type PlayerId = string | number

interface SeatLedgerPlayer {
  id: PlayerId
  is_sheriff?: boolean
  seat?: string | number
  role_hint?: string
}

interface SelectedPage {
  phase?: string
}

type AliveMap = Record<string, boolean>
type RoleIconImage = (player: SeatLedgerPlayer) => string

const props = defineProps({
  players: { type: Array as PropType<SeatLedgerPlayer[]>, default: () => [] },
  aliveMap: { type: Object as PropType<AliveMap>, default: () => ({}) },
  sheriffId: [String, Number, null],
  selectedPage: Object as PropType<SelectedPage | null>,
  roleIconImage: Function as PropType<RoleIconImage>,
  selectable: Boolean,
  selectedPlayerId: [String, Number, null]
})

const emit = defineEmits(['select-player'])

function roleImage(player: SeatLedgerPlayer) {
  return props.roleIconImage ? props.roleIconImage(player) : ''
}

function showSheriff(player: SeatLedgerPlayer) {
  return player.id === props.sheriffId
    && props.selectedPage
    && ['sheriff_result', 'speech', 'vote', 'night', 'ended'].includes(props.selectedPage.phase)
}

function selectPlayer(player: SeatLedgerPlayer) {
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
