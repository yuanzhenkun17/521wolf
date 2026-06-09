import { defineStore } from 'pinia'
import { computed, ref } from 'vue'
import type { BenchmarkRun, BenchmarkSuite } from '../types/benchmark'

export const useBenchmarkStore = defineStore('benchmark', () => {
  const suites = ref<BenchmarkSuite[]>([])
  const runs = ref<BenchmarkRun[]>([])
  const selectedBenchmarkId = ref('')
  const selectedBatchId = ref('')
  const loading = ref(false)
  const error = ref('')

  const selectedSuite = computed(() => suites.value.find((suite) => suite.id === selectedBenchmarkId.value) || null)

  return {
    suites,
    runs,
    selectedBenchmarkId,
    selectedBatchId,
    loading,
    error,
    selectedSuite
  }
})
