import * as React from 'react'
import type { AxiosError } from 'axios'
import { createFileRoute } from '@tanstack/react-router'
import { useQueryClient } from '@tanstack/react-query'
import { Download, Loader2, PackagePlus } from 'lucide-react'
import { formatDate } from '@/lib/utils'
import { PageHeader } from '@/components/layout/page-header'
import { ResourceTable } from '@/components/data/resource-table'
import type { ResourceColumn } from '@/components/data/resource-table'
import { EmptyState, ErrorState } from '@/components/data/states'
import { StatusBadge } from '@/components/data/status-badge'
import { IssueList } from '@/components/data/issue-list'
import { useCurrentStudy } from '@/components/study-provider'
import { Button } from '@/components/ui/button'
import {
  Card,
  CardContent,
  CardDescription,
  CardHeader,
  CardTitle,
} from '@/components/ui/card'
import { Input } from '@/components/ui/input'
import { Label } from '@/components/ui/label'
import { useDownload } from '@/hooks/use-download'
import { useListArtifacts } from '@/api/generated/artifacts/artifacts'
import {
  getListSubmissionPackagesQueryKey,
  useCreateSubmissionPackage,
  useGetSubmissionPackage,
  useListSubmissionPackages,
} from '@/api/generated/packaging/packaging'
import type {
  ArtifactResponse,
  ModuleSelection,
  SubmissionPackageCreate,
  SubmissionPackageResponse,
} from '@/api/generated/model'
import { idempotentRequest } from '@/lib/requests'
import { parseProblem } from '@/lib/problems'

export const Route = createFileRoute('/_app/packaging')({
  component: PackagingPage,
})

const packageColumns: ResourceColumn<SubmissionPackageResponse>[] = [
  { key: 'name', header: 'Name' },
  { key: 'status', header: 'Status', cell: (row) => <StatusBadge status={row.status} /> },
  { key: 'artifact_ids', header: 'Artifacts', cell: (row) => row.artifact_ids.length },
  { key: 'created_at', header: 'Created', cell: (row) => formatDate(row.created_at) },
]

function groupSelections(
  artifacts: ArtifactResponse[],
  selectedIds: ReadonlySet<string>,
): ModuleSelection[] {
  const grouped = new Map<string, string[]>()
  for (const artifact of artifacts) {
    if (!selectedIds.has(artifact.id)) continue
    const ids = grouped.get(artifact.module) ?? []
    ids.push(artifact.id)
    grouped.set(artifact.module, ids)
  }
  return [...grouped.entries()]
    .sort(([left], [right]) => left.localeCompare(right))
    .map(([module, artifact_ids]) => ({ module, artifact_ids, options: {} }))
}

function PackageDetail({ packageId }: { packageId: string }) {
  const query = useGetSubmissionPackage(packageId)
  const download = useDownload()
  if (query.isError) return <ErrorState error={query.error} resourceLabel="submission package" />
  if (!query.data) return null
  const item = query.data
  return (
    <Card>
      <CardHeader>
        <CardTitle>{item.name}</CardTitle>
        <CardDescription>
          Package <code>{item.id}</code> · input fingerprint{' '}
          <code className="break-all">{item.input_fingerprint}</code>
        </CardDescription>
      </CardHeader>
      <CardContent className="flex flex-col gap-4">
        <dl className="grid gap-3 text-sm sm:grid-cols-3">
          <div><dt className="text-muted-foreground">Status</dt><dd><StatusBadge status={item.status} /></dd></div>
          <div><dt className="text-muted-foreground">Artifacts</dt><dd>{item.artifact_ids.length}</dd></div>
          <div><dt className="text-muted-foreground">Completed</dt><dd>{item.completed_at ? formatDate(item.completed_at) : '—'}</dd></div>
        </dl>
        {item.issues.length > 0 && <IssueList issues={item.issues} />}
        {Object.keys(item.manifest).length > 0 && (
          <pre className="max-h-80 overflow-auto rounded-md bg-muted p-4 text-xs">
            {JSON.stringify(item.manifest, null, 2)}
          </pre>
        )}
        <div>
          <Button
            disabled={item.status !== 'succeeded' || download.isPending}
            onClick={() => download.downloadSubmissionPackage(item.id, `${item.name}.zip`)}
          >
            {download.isPending ? <Loader2 className="animate-spin" /> : <Download />}
            Download ZIP
          </Button>
        </div>
      </CardContent>
    </Card>
  )
}

function PackagingPage() {
  const qc = useQueryClient()
  const { currentStudyId, isLoading: studiesLoading } = useCurrentStudy()
  const packages = useListSubmissionPackages(currentStudyId ?? '', undefined, {
    query: { enabled: !!currentStudyId },
  })
  const artifacts = useListArtifacts(currentStudyId ?? '', { limit: 200 }, {
    query: { enabled: !!currentStudyId },
  })
  const [name, setName] = React.useState('')
  const [expectedFingerprint, setExpectedFingerprint] = React.useState('')
  const [reconciliationIds, setReconciliationIds] = React.useState('')
  const [selected, setSelected] = React.useState<ReadonlySet<string>>(() => new Set())
  const [selectedPackageId, setSelectedPackageId] = React.useState<string | null>(null)
  const [error, setError] = React.useState<string | null>(null)
  const create = useCreateSubmissionPackage({ request: idempotentRequest() })

  function toggleArtifact(id: string) {
    setSelected((current) => {
      const next = new Set(current)
      if (next.has(id)) next.delete(id)
      else next.add(id)
      return next
    })
  }

  async function createPackage() {
    if (!currentStudyId) return
    const moduleSelections = groupSelections(artifacts.data?.items ?? [], selected)
    const data: SubmissionPackageCreate = {
      name,
      module_selections: moduleSelections,
      artifact_ids: [],
      reconciliation_run_ids: reconciliationIds.split(',').map((value) => value.trim()).filter(Boolean),
      expected_study_fingerprint: expectedFingerprint,
    }
    try {
      const created = await create.mutateAsync({ studyId: currentStudyId, data })
      setSelectedPackageId(created.id)
      setError(null)
      await qc.invalidateQueries({ queryKey: getListSubmissionPackagesQueryKey(currentStudyId) })
    } catch (caught) {
      const axiosError = caught as AxiosError
      setError(parseProblem(axiosError).detail ?? axiosError.message)
    }
  }

  const available = (artifacts.data?.items ?? []).filter((item) => item.status === 'available')

  return (
    <div className="flex flex-col gap-6">
      <PageHeader
        title="Submission packages"
        description="Select exact immutable artifacts, create a deterministic package, inspect its manifest, and download the completed ZIP."
      />

      {!studiesLoading && !currentStudyId ? (
        <EmptyState title="No study selected" description="Select a study to create or view submission packages." />
      ) : (
        <>
          <Card>
            <CardHeader>
              <CardTitle>Create package</CardTitle>
              <CardDescription>
                Every selected artifact remains grouped under its owning module.
                Supply the exact resolved study fingerprint; stale selections are rejected.
              </CardDescription>
            </CardHeader>
            <CardContent className="flex flex-col gap-5">
              <div className="grid gap-4 sm:grid-cols-2">
                <div className="flex flex-col gap-2"><Label htmlFor="package-name">Name</Label><Input id="package-name" value={name} onChange={(event) => setName(event.target.value)} /></div>
                <div className="flex flex-col gap-2"><Label htmlFor="package-fingerprint">Expected study fingerprint</Label><Input id="package-fingerprint" value={expectedFingerprint} onChange={(event) => setExpectedFingerprint(event.target.value)} /></div>
              </div>
              <div className="flex flex-col gap-2"><Label htmlFor="package-reconciliations">Reconciliation run IDs</Label><Input id="package-reconciliations" value={reconciliationIds} onChange={(event) => setReconciliationIds(event.target.value)} placeholder="Comma-separated UUIDs" /></div>
              <div className="flex flex-col gap-2">
                <Label>Available immutable artifacts</Label>
                {available.length === 0 ? <p className="text-muted-foreground text-sm">No available artifacts are eligible for selection.</p> : (
                  <div className="max-h-72 overflow-auto rounded-md border">
                    {available.map((artifact) => (
                      <label key={artifact.id} className="flex cursor-pointer items-start gap-3 border-b px-4 py-3 last:border-b-0">
                        <input type="checkbox" className="mt-1" checked={selected.has(artifact.id)} onChange={() => toggleArtifact(artifact.id)} />
                        <span className="min-w-0 text-sm"><span className="font-medium">{artifact.filename}</span><span className="text-muted-foreground block">{artifact.module} · {artifact.artifact_type} · <code>{artifact.sha256.slice(0, 12)}…</code></span></span>
                      </label>
                    ))}
                  </div>
                )}
              </div>
              {error && <p className="text-destructive text-sm" role="alert">{error}</p>}
              <div className="flex justify-end">
                <Button disabled={create.isPending || !name.trim() || expectedFingerprint.length !== 64 || selected.size === 0} onClick={createPackage}>
                  {create.isPending ? <Loader2 className="animate-spin" /> : <PackagePlus />} Create package
                </Button>
              </div>
            </CardContent>
          </Card>

          <ResourceTable
            columns={packageColumns}
            rows={packages.data?.items ?? []}
            getRowId={(row) => row.id}
            isLoading={packages.isLoading || studiesLoading}
            isError={packages.isError}
            error={packages.error}
            resourceLabel="submission packages"
            onRowClick={(row) => setSelectedPackageId(row.id)}
          />
          {selectedPackageId && <PackageDetail packageId={selectedPackageId} />}
        </>
      )}
    </div>
  )
}
