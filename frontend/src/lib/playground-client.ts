import { getAuthToken } from '@/lib/auth'

export type PlaygroundAgent = {
  id: string
  name: string
  description: string | null
}

export type PlaygroundConversation = {
  id: string
  agent_id: string
  title: string | null
  state: string
  pending_interrupt_id: string | null
  pending_tool_name: string | null
  created_at: string
  updated_at: string
}

export type PlaygroundMessage = {
  id: string
  conversation_id: string
  role: string
  content: string
  created_at: string
}

export type PlaygroundEvent =
  | { type: 'text_delta'; text: string }
  | { type: 'tool_status'; tool_name: string; status: string; tool_use_id?: string }
  | {
      type: 'approval_required'
      interrupt_id: string
      tool_name: string
      summary?: string
      arguments?: unknown
    }
  | { type: 'completed'; status: string }
  | { type: 'error'; code: string; message: string; retryable: boolean }

const base = (import.meta.env.VITE_PLATFORM_API_BASE_URL ?? '').replace(/\/$/, '')

async function request<T>(path: string, init: RequestInit = {}): Promise<T> {
  const response = await fetch(`${base}${path}`, {
    ...init,
    headers: {
      Authorization: `Bearer ${getAuthToken()}`,
      ...(init.body ? { 'Content-Type': 'application/json' } : {}),
      ...init.headers,
    },
  })
  if (!response.ok) {
    const body = await response.json().catch(() => ({}))
    throw new Error(body?.error?.message || `Playground request failed (${response.status})`)
  }
  return response.status === 204 ? (undefined as T) : (response.json() as Promise<T>)
}

async function stream(
  path: string,
  body: object,
  signal: AbortSignal,
  onEvent: (event: PlaygroundEvent) => void,
): Promise<void> {
  const response = await fetch(`${base}${path}`, {
    method: 'POST',
    signal,
    headers: {
      Authorization: `Bearer ${getAuthToken()}`,
      'Content-Type': 'application/json',
    },
    body: JSON.stringify(body),
  })
  if (!response.ok || !response.body) {
    const problem = await response.json().catch(() => ({}))
    throw new Error(problem?.error?.message || `Agent stream failed (${response.status})`)
  }

  const reader = response.body.getReader()
  const decoder = new TextDecoder()
  let buffer = ''
  while (true) {
    const { done, value } = await reader.read()
    buffer += decoder.decode(value ?? new Uint8Array(), { stream: !done })
    const frames = buffer.split('\n\n')
    buffer = frames.pop() ?? ''
    for (const frame of frames) {
      let type = ''
      const data: string[] = []
      for (const line of frame.split('\n')) {
        if (line.startsWith('event:')) type = line.slice(6).trim()
        if (line.startsWith('data:')) data.push(line.slice(5).trimStart())
      }
      if (type && data.length) {
        onEvent({ type, ...JSON.parse(data.join('\n')) } as PlaygroundEvent)
      }
    }
    if (done) break
  }
}

export const playgroundApi = {
  agents: () => request<PlaygroundAgent[]>('/v1/playground/agents'),
  conversations: (agentId: string) =>
    request<PlaygroundConversation[]>(`/v1/playground/conversations?agent_id=${encodeURIComponent(agentId)}`),
  createConversation: (agentId: string) =>
    request<PlaygroundConversation>('/v1/playground/conversations', {
      method: 'POST',
      body: JSON.stringify({ agent_id: agentId }),
    }),
  closeConversation: (id: string) =>
    request<PlaygroundConversation>(`/v1/playground/conversations/${id}/close`, {
      method: 'POST',
    }),
  messages: (id: string) =>
    request<PlaygroundMessage[]>(`/v1/playground/conversations/${id}/messages`),
  updateConversation: (id: string, body: { title?: string; state?: 'active' | 'archived' }) =>
    request<PlaygroundConversation>(`/v1/playground/conversations/${id}`, {
      method: 'PATCH',
      body: JSON.stringify(body),
    }),
  message: (
    id: string,
    message: string,
    signal: AbortSignal,
    onEvent: (event: PlaygroundEvent) => void,
  ) =>
    stream(`/v1/playground/conversations/${id}/messages`, { message }, signal, onEvent),
  approval: (
    id: string,
    interruptId: string,
    decision: 'approve' | 'deny',
    signal: AbortSignal,
    onEvent: (event: PlaygroundEvent) => void,
  ) =>
    stream(
      `/v1/playground/conversations/${id}/approvals/${encodeURIComponent(interruptId)}`,
      { decision },
      signal,
      onEvent,
    ),
}
