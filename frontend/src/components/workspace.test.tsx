// @vitest-environment jsdom
import { render, screen, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { beforeEach, describe, expect, it, vi } from 'vitest'
import type { WorkspaceState } from '@/lib/workspace-client'

const api = vi.hoisted(() => ({
  current: vi.fn(),
  start: vi.fn(),
  stop: vi.fn(),
  launch: vi.fn(),
}))

vi.mock('@/lib/workspace-client', async (importOriginal) => ({
  ...(await importOriginal<typeof import('@/lib/workspace-client')>()),
  workspaceApi: api,
}))

import { Workspace } from './workspace'

const stopped: WorkspaceState = {
  workspace_id: 'workspace-1',
  product: 'aurinara',
  status: 'stopped',
  session_expires_at: null,
  usage_bytes: 1024,
  quota_bytes: 5 * 1024 ** 3,
  sync_state: 'synced',
  last_synced_at: '2026-10-22T12:00:00Z',
  failure_code: null,
  can_open: true,
  can_stop: false,
}

const running: WorkspaceState = {
  ...stopped,
  status: 'running',
  session_expires_at: '2099-10-22T14:00:00Z',
  can_stop: true,
}

describe('Workspace', () => {
  beforeEach(() => {
    vi.clearAllMocks()
    api.current.mockResolvedValue(stopped)
    api.start.mockResolvedValue(running)
    api.stop.mockResolvedValue(stopped)
    api.launch.mockResolvedValue({ url: 'https://platform.example/v1/workspaces/id/ide-login?grant=opaque', expires_at: '2099-10-22T12:01:00Z' })
  })

  it('starts and opens the workspace in the synchronously-created tab', async () => {
    const replace = vi.fn()
    vi.spyOn(window, 'open').mockReturnValue({ document: { title: '' }, location: { replace }, close: vi.fn() } as unknown as Window)
    render(<Workspace />)

    await userEvent.click(await screen.findByRole('button', { name: /open workspace/i }))

    await waitFor(() => expect(replace).toHaveBeenCalledWith(expect.stringContaining('grant=opaque')))
    expect(api.start).toHaveBeenCalledOnce()
    expect(api.launch).toHaveBeenCalledOnce()
  })

  it('shows a direct link when popups are blocked', async () => {
    vi.spyOn(window, 'open').mockReturnValue(null)
    render(<Workspace />)

    await userEvent.click(await screen.findByRole('button', { name: /open workspace/i }))

    expect((await screen.findByRole('link', { name: /workspace ready/i })).getAttribute('href')).toContain('grant=opaque')
  })

  it('stops a running workspace', async () => {
    api.current.mockResolvedValue(running)
    render(<Workspace />)

    await userEvent.click(await screen.findByRole('button', { name: /stop workspace/i }))

    await waitFor(() => expect(api.stop).toHaveBeenCalledOnce())
  })
})
