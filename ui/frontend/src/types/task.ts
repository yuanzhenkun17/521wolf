import type { Pagination, UnknownRecord } from './api'

export type TaskQueueStatus =
  | 'queued'
  | 'running'
  | 'succeeded'
  | 'failed'
  | 'cancelled'
  | 'interrupted'
  | string

export interface TaskQueueRow extends UnknownRecord {
  task_id: string
  id: string
  kind: string
  status: TaskQueueStatus
  priority: number
  payload: UnknownRecord
  result: UnknownRecord | null
  error: UnknownRecord | null
  progress: UnknownRecord | null
  attempt: number
  max_attempts: number
  queued_at: string
  started_at: string
  updated_at: string
  finished_at: string
  cancel_requested: boolean
  parent_task_id: string
  source: string
  metadata: UnknownRecord
  progressPercent: number
  progressLabel: string
  stageLabel: string
  statusLabel: string
  isActive: boolean
  isTerminal: boolean
}

export interface TaskArtifact extends UnknownRecord {
  artifact_id: string
  id: string
  task_id: string
  artifact_type: string
  name: string
  relative_path: string
  content_type: string
  size_bytes: number | null
  sha256: string
  created_at: string
  metadata: UnknownRecord
  isJson: boolean
  sizeLabel: string
  shortSha: string
}

export interface TaskEventRow extends UnknownRecord {
  event_id?: number | string
  id?: number | string
  event?: string
  event_type?: string
  type?: string
  created_at?: string
  payload?: unknown
}

export interface TaskListResponse {
  tasks: TaskQueueRow[]
  pagination?: Pagination
  raw?: unknown
}

export interface TaskArtifactsResponse {
  task_id: string
  artifacts: TaskArtifact[]
  raw?: unknown
}

export interface TaskEventsResponse {
  task_id: string
  after_event_id: number
  events: TaskEventRow[]
  raw?: unknown
}

export interface TaskActionResponse {
  task_id: string
  action: string
  changed: boolean
  task: TaskQueueRow
  raw?: unknown
}
