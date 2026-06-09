import { defineStore } from 'pinia'
import { computed, ref } from 'vue'
import type { EvolutionRun, RoleVersion } from '../types/evolution'

export const useEvolutionStore = defineStore('evolution', () => {
  const runs = ref<EvolutionRun[]>([])
  const versionsByRole = ref<Record<string, RoleVersion[]>>({})
  const selectedRole = ref('')
  const selectedRunId = ref('')
  const loading = ref(false)
  const error = ref('')

  const selectedRun = computed(() => runs.value.find((run) => run.id === selectedRunId.value || run.run_id === selectedRunId.value) || null)
  const selectedRoleVersions = computed(() => versionsByRole.value[selectedRole.value] || [])

  return {
    runs,
    versionsByRole,
    selectedRole,
    selectedRunId,
    loading,
    error,
    selectedRun,
    selectedRoleVersions
  }
})
