import { useCallback, useEffect, useState } from 'react'
import { createFileRoute } from '@tanstack/react-router'
import { Download, File, Folder, RefreshCw, Search, Share2 } from 'lucide-react'
import { toast } from 'sonner'
import { Button } from '@/components/ui/button'
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from '@/components/ui/card'
import { useCurrentStudy } from '@/components/study-context'
import { getAuthToken } from '@/lib/auth'
import { AXIOS_INSTANCE } from '@/api/axios-instance'

type Node = {
  id: string
  parent_id: string | null
  kind: 'folder' | 'file'
  display_name: string
  source_product: string
  module: string | null
  source_status: string
  classification: string
  current_version_number: number | null
  updated_at: string
}

type Version = {
  id: string
  version_number: number
  sha256: string
  size_bytes: number
  media_type: string
  created_at: string
}

const platformBase = (import.meta.env.VITE_PLATFORM_API_BASE_URL ?? '').replace(/\/$/, '')

async function platform<T>(path: string, init?: RequestInit): Promise<T> {
  const response = await fetch(`${platformBase}${path}`, {
    ...init,
    headers: { Authorization: `Bearer ${getAuthToken()}`, 'Content-Type': 'application/json', ...init?.headers },
  })
  if (!response.ok) throw new Error(`Repository request failed (${response.status})`)
  const contentType = response.headers.get('content-type') ?? ''
  if (!contentType.toLowerCase().includes('application/json')) {
    throw new Error('Repository API returned a non-JSON response. Verify that Platform is running on port 8002 and restart the Aurinara frontend.')
  }
  return response.json() as Promise<T>
}

export const Route = createFileRoute('/_app/repository')({ component: RepositoryPage })

function RepositoryPage() {
  const { currentStudyId } = useCurrentStudy()
  const [query, setQuery] = useState('')
  const [view, setView] = useState('folder')
  const [path, setPath] = useState<Node[]>([])
  const [items, setItems] = useState<Node[]>([])
  const [selected, setSelected] = useState<Node | null>(null)
  const [versions, setVersions] = useState<Version[]>([])
  const [loading, setLoading] = useState(false)
  const currentFolder = path.at(-1) ?? null

  const load = useCallback(async () => {
    if (!currentStudyId) return
    setLoading(true)
    try {
      const params = new URLSearchParams({ view, limit: '100' })
      if (view === 'folder' && currentFolder) params.set('parent_id', currentFolder.id)
      if (query.trim()) params.set('q', query.trim())
      const result = await platform<{ items: Node[] }>(`/v1/studies/${currentStudyId}/repository?${params}`)
      setItems(result.items)
      setSelected((value) => result.items.find((item) => item.id === value?.id) ?? null)
    } catch (error) { toast.error(error instanceof Error ? error.message : 'Repository unavailable') }
    finally { setLoading(false) }
  }, [currentStudyId, currentFolder, query, view])

  useEffect(() => { setPath([]); setSelected(null) }, [currentStudyId])

  useEffect(() => { void load() }, [load])
  useEffect(() => {
    if (!selected || selected.kind !== 'file') { setVersions([]); return }
    void platform<Version[]>(`/v1/repository/nodes/${selected.id}/versions`).then(setVersions).catch(() => setVersions([]))
  }, [selected])

  const download = async () => {
    if (!versions[0]) return
    const result = await platform<{ url: string }>(`/v1/repository/versions/${versions[0].id}/download`, { method: 'POST' })
    window.open(result.url, '_blank', 'noopener,noreferrer')
  }
  const addToAurinara = async () => {
    if (!currentStudyId || !versions[0]) return
    try {
      await AXIOS_INSTANCE.post(`/api/v1/studies/${currentStudyId}/source-files:bind-repository`, { version_id: versions[0].id, expected_sha256: versions[0].sha256 })
      toast.success('Repository version added as a new Aurinara source file')
    } catch { toast.error('Could not bind this Repository version') }
  }
  const openFolder = (folder: Node) => {
    setPath((value) => [...value, folder])
    setView('folder')
    setQuery('')
    setSelected(null)
  }

  return <div className="space-y-4">
    <div><h1 className="font-display text-2xl font-medium">Repository</h1><p className="text-muted-foreground text-sm">One authorized view of Platform, Aurinara, and EDC files.</p></div>
    <div className="flex flex-wrap gap-2">
      <div className="relative min-w-64 flex-1"><Search className="text-muted-foreground absolute top-2.5 left-3 size-4"/><input className="border-input bg-background h-9 w-full rounded-md border pl-9 text-sm" value={query} onChange={(event) => setQuery(event.target.value)} placeholder="Search files" /></div>
      <select className="border-input bg-background h-9 rounded-md border px-3 text-sm" value={view} onChange={(event) => { setView(event.target.value); setSelected(null) }}><option value="folder">Folders</option><option value="all">All files</option><option value="recent">Recent</option><option value="aurinara">Aurinara</option><option value="aurinara-edc">EDC</option><option value="platform">Neutral</option><option value="archived">Archived</option></select>
      <Button variant="outline" size="icon" onClick={() => void load()}><RefreshCw className={loading ? 'animate-spin' : ''}/></Button>
    </div>
    <div className="grid gap-4 lg:grid-cols-[1fr_340px]">
      <Card className="gap-0 py-0"><div className="flex items-center gap-1 border-b px-4 py-3 text-sm"><button className="text-primary" onClick={() => { setPath([]); setView('folder') }}>Repository</button>{path.map((folder, index) => <span key={folder.id} className="flex items-center gap-1"><span className="text-muted-foreground">/</span><button className="text-primary" onClick={() => setPath(path.slice(0, index + 1))}>{folder.display_name}</button></span>)}</div><div className="text-muted-foreground grid grid-cols-[1fr_110px_100px] border-b px-4 py-3 text-[11px] font-semibold uppercase"><span>Name</span><span>Source</span><span>Status</span></div>{items.map((item) => <button key={item.id} className={`grid w-full grid-cols-[1fr_110px_100px] items-center border-b px-4 py-3 text-left text-sm hover:bg-muted/50 ${selected?.id === item.id ? 'bg-muted' : ''}`} onClick={() => item.kind === 'folder' ? openFolder(item) : setSelected(item)}><span className="flex min-w-0 items-center gap-2">{item.kind === 'folder' ? <Folder className="text-amber-600 size-4"/> : <File className="text-primary size-4"/>}<span className="truncate">{item.display_name}</span></span><span className="text-muted-foreground truncate text-xs">{item.kind === 'folder' ? 'Folder' : item.source_product === 'platform' ? 'Neutral' : item.source_product}</span><span className="text-muted-foreground text-xs">{item.source_status}</span></button>)}{!loading && items.length === 0 && <div className="text-muted-foreground p-12 text-center text-sm">No authorized entries found.</div>}</Card>
      <Card><CardHeader><CardTitle>{selected?.display_name ?? 'File details'}</CardTitle><CardDescription>{selected ? `${selected.source_product} · ${selected.classification}` : 'Select a file'}</CardDescription></CardHeader>{selected?.kind === 'file' && <CardContent className="space-y-4"><div className="flex gap-2"><Button variant="outline" onClick={() => void download()}><Download/>Download</Button><Button onClick={() => void addToAurinara()}><Share2/>Use in Aurinara</Button></div><div className="space-y-2"><h3 className="text-sm font-medium">Versions</h3>{versions.map((version) => <div key={version.id} className="bg-muted rounded-md p-3 text-xs"><strong>v{version.version_number}</strong><div className="text-muted-foreground mt-1">{(version.size_bytes / 1024).toFixed(1)} KB · {new Date(version.created_at).toLocaleString()}</div></div>)}</div></CardContent>}</Card>
    </div>
  </div>
}
