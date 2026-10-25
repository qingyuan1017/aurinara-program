import { useCallback, useEffect, useState, type ReactNode } from 'react'
import { Cloud, ExternalLink, HardDrive, LoaderCircle, SquareTerminal, StopCircle } from 'lucide-react'
import { Button } from '@/components/ui/button'
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from '@/components/ui/card'
import { WorkspaceApiError, workspaceApi, type WorkspaceState } from '@/lib/workspace-client'

const sleep = (milliseconds: number) => new Promise((resolve) => window.setTimeout(resolve, milliseconds))

function formatBytes(value: number): string {
  if (!value) return '0 MB'
  return `${(value / 1024 ** 3).toFixed(value >= 1024 ** 3 ? 1 : 2)} GB`
}

function message(error: unknown): string {
  return error instanceof Error ? error.message : 'Workspace request failed'
}

export function Workspace() {
  const [workspace, setWorkspace] = useState<WorkspaceState | null>(null)
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState('')
  const [readyUrl, setReadyUrl] = useState('')
  const [nowMilliseconds, setNowMilliseconds] = useState(() => Date.now())

  const refresh = useCallback(async () => {
    const state = await workspaceApi.current()
    setWorkspace(state)
    return state
  }, [])

  useEffect(() => { void refresh().catch((reason) => setError(message(reason))) }, [refresh])
  useEffect(() => {
    const timer = window.setInterval(() => setNowMilliseconds(Date.now()), 1000)
    return () => window.clearInterval(timer)
  }, [])

  const remaining = workspace?.session_expires_at
    ? (() => {
        const seconds = Math.max(0, Math.floor((Date.parse(workspace.session_expires_at) - nowMilliseconds) / 1000))
        return `${Math.floor(seconds / 60)}m ${seconds % 60}s`
      })()
    : null

  const openWorkspace = async () => {
    const popup = window.open('about:blank', '_blank')
    if (popup) popup.document.title = 'Preparing Aurinara Workspace…'
    setBusy(true)
    setError('')
    setReadyUrl('')
    try {
      let state = await workspaceApi.start()
      setWorkspace(state)
      while (state.status === 'pending') {
        await sleep(2000)
        state = await refresh()
      }
      if (state.status !== 'running') throw new Error('Workspace did not become ready')
      const launch = await workspaceApi.launch()
      if (popup) popup.location.replace(launch.url)
      else setReadyUrl(launch.url)
    } catch (reason) {
      popup?.close()
      setError(message(reason))
    } finally {
      setBusy(false)
    }
  }

  const stopWorkspace = async () => {
    setBusy(true)
    setError('')
    try {
      let state = await workspaceApi.stop()
      setWorkspace(state)
      while (state.status === 'stopping') {
        await sleep(2000)
        state = await refresh()
      }
    } catch (reason) {
      const suffix = reason instanceof WorkspaceApiError && reason.code === 'workspace_quota_exceeded'
        ? ' Reduce the workspace below 5 GB, then try again.'
        : ''
      setError(`${message(reason)}${suffix}`)
    } finally {
      setBusy(false)
    }
  }

  if (!workspace) {
    return <Card><CardContent className="flex items-center gap-2 py-8 text-sm text-muted-foreground"><LoaderCircle className="size-4 animate-spin" />Loading workspace…</CardContent></Card>
  }

  const active = ['pending', 'running', 'stopping'].includes(workspace.status)
  const syncLabel = workspace.sync_state === 'quota_exceeded' ? 'Storage limit exceeded'
    : workspace.sync_state === 'synced' ? 'Saved to cloud'
      : workspace.sync_state === 'syncing' ? 'Saving…' : workspace.sync_state

  return (
    <Card className="max-w-4xl">
      <CardHeader>
        <div className="flex items-start gap-3">
          <div className="rounded-xl bg-primary/10 p-3 text-primary"><SquareTerminal className="size-6" /></div>
          <div><CardTitle>Your Aurinara workspace</CardTitle><CardDescription className="mt-1">Work with your authorized S3/MinIO Repository files in VS Code. Existing file edits are saved as new Repository versions.</CardDescription></div>
        </div>
      </CardHeader>
      <CardContent className="space-y-5">
        <div className="grid gap-3 sm:grid-cols-2 lg:grid-cols-4">
          <Summary label="Status" value={workspace.status.replace('_', ' ')} />
          <Summary icon={<HardDrive />} label="Storage" value={`${formatBytes(workspace.usage_bytes)} / ${formatBytes(workspace.quota_bytes)}`} />
          <Summary icon={<Cloud />} label="Persistence" value={syncLabel} warning={workspace.sync_state === 'quota_exceeded'} />
          <Summary label="Session remaining" value={active && remaining ? remaining : 'Not running'} />
        </div>
        {workspace.sync_state === 'quota_exceeded' && <p className="rounded-lg border border-destructive/30 bg-destructive/5 p-3 text-sm text-destructive">Reduce this workspace below 5 GB before stopping so the latest files can be saved.</p>}
        {error && <p className="rounded-lg border border-destructive/30 bg-destructive/5 p-3 text-sm text-destructive">{error}</p>}
        {readyUrl && <p className="text-sm text-muted-foreground">Your browser blocked the new tab. <a className="inline-flex items-center gap-1 font-medium text-primary underline" href={readyUrl} target="_blank" rel="noreferrer">Workspace ready — Open <ExternalLink className="size-3" /></a></p>}
        <div className="flex flex-wrap gap-2">
          <Button disabled={busy || !workspace.can_open} onClick={() => void openWorkspace()}>{busy ? <LoaderCircle className="animate-spin" /> : <SquareTerminal />}Open Workspace</Button>
          {active && <Button variant="outline" disabled={busy || !workspace.can_stop} onClick={() => void stopWorkspace()}><StopCircle />Stop Workspace</Button>}
        </div>
        <p className="text-xs text-muted-foreground">Sessions stop automatically after two hours. Changes synchronize every minute.</p>
      </CardContent>
    </Card>
  )
}

function Summary({ label, value, icon, warning = false }: { label: string; value: string; icon?: ReactNode; warning?: boolean }) {
  return <div className="rounded-lg border bg-muted/25 p-3"><span className="flex items-center gap-1.5 text-xs text-muted-foreground [&>svg]:size-3.5">{icon}{label}</span><strong className={`mt-1 block text-sm capitalize ${warning ? 'text-destructive' : ''}`}>{value}</strong></div>
}
