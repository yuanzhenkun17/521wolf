import {
  normalizeTaskActionResponse,
  normalizeTaskArtifactsResponse,
  normalizeTaskEventsResponse,
  normalizeTaskListResponse,
  normalizeTaskResponse
} from '../domain/task/normalizers'
import type { QueryParams, QueryValue, ServiceOptions } from '../types/api'
import type { TaskActionResponse, TaskArtifactsResponse, TaskEventsResponse, TaskListResponse, TaskQueueRow } from '../types/task'
import { API_BASE, defaultApiClient } from './api'

type TaskQuery = {
  status?: string | string[]
  limit?: number
}

function taskQueryParams(query: TaskQuery = {}): QueryParams {
  const params: Record<string, QueryValue | QueryValue[]> = {}
  if (query.status) params.status = query.status
  if (query.limit) params.limit = query.limit
  return params
}

function joinApiPath(apiBase: string, path: string): string {
  return `${apiBase.replace(/\/$/, '')}${path}`
}

export function createTaskService(options: ServiceOptions = {}) {
  const client = options.client || defaultApiClient
  const apiBase = options.apiBase || client.apiBase || API_BASE

  return {
    async list(query: TaskQuery = {}): Promise<TaskListResponse> {
      return normalizeTaskListResponse(
        await client.fetch('/tasks', {
          query: taskQueryParams(query)
        })
      )
    },
    async get(taskId: string): Promise<TaskQueueRow> {
      return normalizeTaskResponse(await client.fetch(`/tasks/${encodeURIComponent(taskId)}`))
    },
    async cancel(taskId: string): Promise<TaskActionResponse> {
      return normalizeTaskActionResponse(
        await client.fetch(`/tasks/${encodeURIComponent(taskId)}/cancel`, {
          method: 'POST'
        })
      )
    },
    async retry(taskId: string): Promise<TaskActionResponse> {
      return normalizeTaskActionResponse(
        await client.fetch(`/tasks/${encodeURIComponent(taskId)}/retry`, {
          method: 'POST'
        })
      )
    },
    async events(taskId: string, afterEventId = 0): Promise<TaskEventsResponse> {
      return normalizeTaskEventsResponse(
        await client.fetch(`/tasks/${encodeURIComponent(taskId)}/events`, {
          query: { after_event_id: afterEventId }
        })
      )
    },
    async artifacts(taskId: string): Promise<TaskArtifactsResponse> {
      return normalizeTaskArtifactsResponse(await client.fetch(`/tasks/${encodeURIComponent(taskId)}/artifacts`))
    },
    async previewJsonArtifact(taskId: string, artifactId: string): Promise<unknown> {
      return client.fetch(`/tasks/${encodeURIComponent(taskId)}/artifacts/${encodeURIComponent(artifactId)}`)
    },
    artifactUrl(taskId: string, artifactId: string): string {
      return joinApiPath(apiBase, `/tasks/${encodeURIComponent(taskId)}/artifacts/${encodeURIComponent(artifactId)}`)
    }
  }
}

export type TaskService = ReturnType<typeof createTaskService>
