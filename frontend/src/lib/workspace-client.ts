import { getAuthToken } from '@/lib/auth'

export type WorkspaceStatus =
  | 'not_created'
  | 'pending'
  | 'running'
  | 'stopping'
  | 'stopped'
  | 'failed'
  | 'expired'

export type WorkspaceSyncState = 'pending' | 'syncing' | 'synced' | 'quota_exceeded' | 'failed'

export interface WorkspaceState {
  workspace_id: string | null
  product: string
  status: WorkspaceStatus
  session_expires_at: string | null
  usage_bytes: number
  quota_bytes: number
  sync_state: WorkspaceSyncState
  last_synced_at: string | null
  failure_code: string | null
  can_open: boolean
  can_stop: boolean
}

export interface WorkspaceLaunch {
  url: string
  expires_at: string
}

export class WorkspaceApiError extends Error {
  constructor(message: string, readonly code: string, readonly status: number) {
    super(message)
  }
}

const platformBase = (import.meta.env.VITE_PLATFORM_API_BASE_URL ?? '').replace(/\/$/, '')

async function request<T>(path: string, init: RequestInit = {}): Promise<T> {
  const response = await fetch(`${platformBase}/v1${path}`, {
    ...init,
    headers: {
      Authorization: `Bearer ${getAuthToken()}`,
      ...init.headers,
    },
  })
  if (!response.ok) {
    const body = await response.json().catch(() => ({}))
    throw new WorkspaceApiError(
      body?.error?.message ?? body?.detail ?? `Workspace request failed (${response.status})`,
      body?.error?.code ?? body?.code ?? 'workspace_request_failed',
      response.status,
    )
  }
  return response.json() as Promise<T>
}

export const workspaceApi = {
  current: () => request<WorkspaceState>('/workspaces/current'),
  start: () => request<WorkspaceState>('/workspaces/current/start', { method: 'POST' }),
  stop: () => request<WorkspaceState>('/workspaces/current/stop', { method: 'POST' }),
  launch: () => request<WorkspaceLaunch>('/workspaces/current/launch', { method: 'POST' }),
}
