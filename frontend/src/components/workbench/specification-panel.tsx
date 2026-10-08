import * as React from 'react'
import type { AxiosError, AxiosRequestConfig } from 'axios'
import { useQueryClient } from '@tanstack/react-query'
import { Download, Save, Upload } from 'lucide-react'
import { toast } from 'sonner'
import {
  Card,
  CardContent,
  CardDescription,
  CardHeader,
  CardTitle,
} from '@/components/ui/card'
import { Button } from '@/components/ui/button'
import { Skeleton } from '@/components/ui/skeleton'
import { EmptyState, ErrorState } from '@/components/data/states'
import { IssueList } from '@/components/data/issue-list'
import { FileDropzone } from '@/components/workbench/file-dropzone'
import { SortableList } from '@/components/workbench/sortable-list'
import { useWorkbench } from '@/components/workbench/workbench-context'
import { useDownload } from '@/hooks/use-download'
import { useIdempotencyKey } from '@/lib/requests'
import { parseProblem, stalenessAlert } from '@/lib/problems'
import { invalidateSdtmSubResource } from '@/lib/invalidate'
import {
  getGetSpecificationQueryKey,
  useGetSpecification,
  useImportSpecification,
  usePutSpecification,
} from '@/api/generated/sdtm/sdtm'
import type {
  SdtmDomain,
  SdtmSpecification,
  SpecificationResponse,
} from '@/api/generated/model'

/**
 * SDTM Specification panel (Requirements 11.1-11.7).
 *
 * - View the current Specification revision + schema version from
 *   `GET /specification`; a `404 sdtm_specification_required` renders an
 *   unsaved empty state (11.1, 11.2).
 * - Save the whole Specification via `PUT /specification` with the SDTM
 *   workbench ETag as `If-Match`; variable ordering within a domain is driven
 *   by {@link SortableList} and persisted through that same save `PUT`
 *   (11.3, 11.4).
 * - Import a Specification file via {@link FileDropzone} through
 *   `POST /specification/import` carrying the aggregate ETag and a stable
 *   `Idempotency-Key`; a `422 sdtm_specification_import_invalid` renders the
 *   problem `detail` + `issues[]` (11.4, 11.5).
 * - Export the Specification as `json`/`xlsx` via {@link useDownload} (11.6).
 * - A `412` on save surfaces a concurrency message and a reload action that
 *   re-fetches the current Specification revision before a retry (11.7).
 */
export function SpecificationPanel({ sdtmId }: { sdtmId: string }) {
  const qc = useQueryClient()
  const { ifMatch } = useWorkbench()
  const download = useDownload()
  const importKey = useIdempotencyKey()

  const specKey = React.useMemo(
    () => getGetSpecificationQueryKey(sdtmId),
    [sdtmId],
  )

  // View current Specification. The generated 404 is surfaced as an AxiosError;
  // `sdtm_specification_required` is the "not yet authored" signal, which the
  // panel renders as an unsaved empty state rather than an error (11.1, 11.2).
  const query = useGetSpecification(sdtmId)
  const spec = query.data

  // The in-memory domains the panel edits. Seeded from the loaded Specification
  // payload and re-seeded whenever the server revision changes (e.g. after a
  // save, an import, or a 412 reload) so the editor always reflects the latest
  // persisted order before the user reorders again (11.3, 11.4, 11.7).
  const [domains, setDomains] = React.useState<SdtmDomain[]>([])
  const seededRevision = React.useRef<number | null>(null)

  React.useEffect(() => {
    if (!spec) return
    if (seededRevision.current === spec.revision) return
    seededRevision.current = spec.revision
    setDomains(domainsFromPayload(spec.payload))
  }, [spec])

  // A persistent concurrency notice shown after a 412 on save. Cleared when the
  // user reloads the current Specification revision before retrying (11.7).
  const [concurrency, setConcurrency] = React.useState<string | null>(null)
  const [importProblem, setImportProblem] = React.useState<AxiosError | null>(
    null,
  )

  const put = usePutSpecification({
    mutation: {
      onSuccess: () => invalidateSdtmSubResource(qc, 'specification', sdtmId),
    },
    request: ifMatch(),
  })

  // Import carries a dynamic per-attempt request (the raw file bytes, the
  // content type inferred from the file, the aggregate ETag, and a stable
  // Idempotency-Key). The generated hook only forwards a hook-level `request`
  // to the mutator, so the config is held in a ref read when the hook is
  // instantiated and the mutation is fired from an effect once a re-render has
  // picked up the pending config (keeping JSON/XLSX branching + headers intact).
  const importRequestRef = React.useRef<AxiosRequestConfig | undefined>(
    undefined,
  )
  const [pendingImport, setPendingImport] = React.useState<File | null>(null)
  const importSpec = useImportSpecification({
    request: importRequestRef.current,
  })

  const status = query.error?.response?.status
  const notFoundCode =
    status === 404 ? parseProblem(query.error as AxiosError).code : undefined

  // ---- save ---------------------------------------------------------------

  async function handleSave() {
    setConcurrency(null)
    const body: SdtmSpecification = {
      schema_version: '1.0.0',
      domains,
    }
    try {
      await put.mutateAsync({ sdtmId, data: body })
      toast.success('Specification saved.')
    } catch (error) {
      const err = error as AxiosError
      if (err.response?.status === 412) {
        // Concurrency conflict: show the message and require a reload of the
        // current Specification revision before the user can retry (11.7).
        setConcurrency(
          stalenessAlert(err) ??
            'This Specification changed since you opened it. Reload and try again.',
        )
        return
      }
      toast.error(
        parseProblem(err).detail ?? err.message ?? 'Could not save the Specification.',
      )
    }
  }

  async function reloadCurrentRevision() {
    setConcurrency(null)
    // Force the editor to re-seed from the freshly fetched revision.
    seededRevision.current = null
    await qc.invalidateQueries({ queryKey: specKey })
  }

  // ---- import -------------------------------------------------------------

  function handleImportFiles(files: File[]) {
    const file = files[0]
    if (!file) return
    setImportProblem(null)
    // One stable Idempotency-Key per import attempt, held across retries.
    const key = importKey.begin()
    const contentType = inferImportContentType(file)
    // The backend reads the raw request body and branches on content type
    // (JSON vs XLSX). Send the file bytes directly with the aggregate ETag and
    // the stable Idempotency-Key. Stashing the config in the ref and bumping
    // `pendingImport` re-renders the hook with this request before the effect
    // below fires the mutation.
    importRequestRef.current = {
      data: file,
      headers: {
        ...ifMatch().headers,
        'Content-Type': contentType,
        'Idempotency-Key': key,
      },
    }
    setPendingImport(file)
  }

  const runImport = React.useCallback(async () => {
    try {
      await importSpec.mutateAsync({ sdtmId })
      await invalidateSdtmSubResource(qc, 'specification', sdtmId)
      // Re-seed the editor from the imported revision.
      seededRevision.current = null
      await qc.invalidateQueries({ queryKey: specKey })
      toast.success('Specification imported.')
    } catch (error) {
      const err = error as AxiosError
      if (err.response?.status === 422) {
        // sdtm_specification_import_invalid: render detail + issues[] inline.
        setImportProblem(err)
        return
      }
      if (err.response?.status === 412) {
        setConcurrency(
          stalenessAlert(err) ??
            'This workbench changed since you opened it. Reload and try again.',
        )
        return
      }
      toast.error(
        parseProblem(err).detail ?? err.message ?? 'Could not import the Specification.',
      )
    } finally {
      importRequestRef.current = undefined
      setPendingImport(null)
    }
  }, [importSpec, sdtmId, qc, specKey])

  // Fire the import once a re-render has instantiated the mutation hook with
  // the pending request config captured by `handleImportFiles`.
  React.useEffect(() => {
    if (!pendingImport || !importRequestRef.current) return
    void runImport()
    // Only re-run when a new import is queued; `runImport` reads the latest ref.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [pendingImport])

  // ---- export -------------------------------------------------------------

  async function handleExport(format: 'json' | 'xlsx') {
    try {
      await download.downloadSpecificationExport(sdtmId, format)
    } catch (error) {
      const err = error as AxiosError
      toast.error(
        parseProblem(err).detail ?? err.message ?? 'Could not export the Specification.',
      )
    }
  }

  // ---- render -------------------------------------------------------------

  if (query.isLoading) {
    return (
      <div className="flex flex-col gap-4">
        <Skeleton className="h-24 w-full" />
        <Skeleton className="h-48 w-full" />
      </div>
    )
  }

  // 404 sdtm_specification_required -> unsaved empty state (11.2). Still offer
  // an import dropzone so the user can author the first revision from a file.
  if (status === 404 && notFoundCode === 'sdtm_specification_required') {
    return (
      <div className="flex flex-col gap-4">
        <EmptyState
          title="No Specification yet"
          description="This SDTM workbench has no saved Specification. Save one below, or import a Specification file to create the first revision."
        />
        <ConcurrencyNotice message={concurrency} onReload={reloadCurrentRevision} />
        <ImportCard
          onFiles={handleImportFiles}
          isPending={importSpec.isPending}
          problem={importProblem}
        />
        <SaveCard
          domains={domains}
          onReorder={setDomains}
          onSave={handleSave}
          isSaving={put.isPending}
          saveDisabled={domains.length === 0}
        />
      </div>
    )
  }

  // Any other load error (not the "not yet authored" 404).
  if (query.isError) {
    return <ErrorState error={query.error} resourceLabel="SDTM Specification" />
  }

  if (!spec) {
    return (
      <EmptyState
        title="No Specification"
        description="The Specification is unavailable."
      />
    )
  }

  return (
    <div className="flex flex-col gap-4">
      <Card>
        <CardHeader>
          <CardTitle className="text-base">Specification</CardTitle>
          <CardDescription>
            Revision {spec.revision} · schema version {spec.schema_version}
          </CardDescription>
        </CardHeader>
        <CardContent className="flex flex-wrap gap-2">
          <Button
            type="button"
            variant="outline"
            size="sm"
            onClick={() => handleExport('json')}
            disabled={download.isPending}
          >
            <Download /> Export JSON
          </Button>
          <Button
            type="button"
            variant="outline"
            size="sm"
            onClick={() => handleExport('xlsx')}
            disabled={download.isPending}
          >
            <Download /> Export XLSX
          </Button>
        </CardContent>
      </Card>

      <ConcurrencyNotice message={concurrency} onReload={reloadCurrentRevision} />

      <ImportCard
        onFiles={handleImportFiles}
        isPending={importSpec.isPending}
        problem={importProblem}
      />

      <SaveCard
        domains={domains}
        onReorder={setDomains}
        onSave={handleSave}
        isSaving={put.isPending}
        saveDisabled={domains.length === 0}
      />
    </div>
  )
}

// ---------------------------------------------------------------------------
// Sub-components
// ---------------------------------------------------------------------------

interface ConcurrencyNoticeProps {
  message: string | null
  onReload: () => void
}

/** Persistent 412 concurrency notice with a reload action (11.7). */
function ConcurrencyNotice({ message, onReload }: ConcurrencyNoticeProps) {
  if (!message) return null
  return (
    <div
      role="alert"
      className="border-destructive/50 text-destructive flex flex-col gap-2 rounded-md border px-4 py-3 text-sm"
    >
      <span className="font-medium">Specification changed</span>
      <span className="text-destructive/90">{message}</span>
      <button
        type="button"
        onClick={onReload}
        className="text-destructive w-fit text-sm font-medium underline underline-offset-2"
      >
        Reload current Specification revision
      </button>
    </div>
  )
}

interface ImportCardProps {
  onFiles: (files: File[]) => void
  isPending: boolean
  problem: AxiosError | null
}

/** Import a Specification file; renders a 422 import-invalid detail + issues. */
function ImportCard({ onFiles, isPending, problem }: ImportCardProps) {
  const parsed = problem ? parseProblem(problem) : null
  const issues = (parsed?.issues ?? []) as Record<string, unknown>[]
  return (
    <Card>
      <CardHeader>
        <CardTitle className="flex items-center gap-2 text-base">
          <Upload className="size-4" aria-hidden /> Import
        </CardTitle>
        <CardDescription>
          Replace the Specification from a JSON or XLSX file. The import is
          atomic and uses the current workbench revision.
        </CardDescription>
      </CardHeader>
      <CardContent className="flex flex-col gap-3">
        <FileDropzone
          onFiles={onFiles}
          disabled={isPending}
          accept=".json,.xlsx,application/json,application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
          ariaLabel="Specification import drop target"
          label="Drag a Specification file here, or browse"
          description="Accepted formats: JSON (.json) or Excel (.xlsx)"
        />
        {parsed && (
          <div className="flex flex-col gap-2">
            <p className="text-destructive text-sm font-medium" role="alert">
              {parsed.detail ?? 'The Specification import is invalid.'}
            </p>
            {issues.length > 0 && (
              <IssueList
                issues={issues}
                emptyTitle="No import issues"
                emptyDescription="The import reported no field-level issues."
              />
            )}
          </div>
        )}
      </CardContent>
    </Card>
  )
}

interface SaveCardProps {
  domains: SdtmDomain[]
  onReorder: (next: SdtmDomain[]) => void
  onSave: () => void
  isSaving: boolean
  saveDisabled: boolean
}

/**
 * Edit variable ordering within each domain via {@link SortableList} and
 * persist the whole Specification through the save `PUT` (11.3, 11.4). Variable
 * reordering mutates the in-memory domains; nothing is sent until Save.
 */
function SaveCard({
  domains,
  onReorder,
  onSave,
  isSaving,
  saveDisabled,
}: SaveCardProps) {
  function reorderVariables(domainIndex: number, nextVariables: SdtmDomain['variables']) {
    const next = domains.map((domain, index) =>
      index === domainIndex ? { ...domain, variables: nextVariables } : domain,
    )
    onReorder(next)
  }

  return (
    <Card>
      <CardHeader>
        <CardTitle className="text-base">Variable ordering</CardTitle>
        <CardDescription>
          Reorder variables within each domain by dragging, using the move
          controls, or editing the position field. Changes are persisted when
          you save.
        </CardDescription>
      </CardHeader>
      <CardContent className="flex flex-col gap-6">
        {domains.length === 0 ? (
          <EmptyState
            title="No domains"
            description="This Specification has no domains to order."
          />
        ) : (
          domains.map((domain, domainIndex) => (
            <div key={domain.code} className="flex flex-col gap-2">
              <div className="text-sm font-medium">
                {domain.code} <span className="text-muted-foreground">{domain.label}</span>
              </div>
              <SortableList
                items={domain.variables}
                getId={(variable) => variable.name}
                ariaLabel={`${domain.code} variables`}
                onReorder={(nextVariables) =>
                  reorderVariables(domainIndex, nextVariables)
                }
                renderItem={(variable) => (
                  <div className="flex items-baseline gap-2 text-sm">
                    <code className="font-semibold">{variable.name}</code>
                    <span className="text-muted-foreground truncate">
                      {variable.label}
                    </span>
                  </div>
                )}
              />
            </div>
          ))
        )}
        <div>
          <Button
            type="button"
            onClick={onSave}
            disabled={isSaving || saveDisabled}
          >
            <Save /> Save Specification
          </Button>
        </div>
      </CardContent>
    </Card>
  )
}

// ---------------------------------------------------------------------------
// Helpers
// ---------------------------------------------------------------------------

/**
 * Read the domains out of the opaque Specification payload. The generated
 * payload is `{ [key: string]: unknown }`, so the panel reads the `domains`
 * array defensively and keeps the typed {@link SdtmDomain} shape it edits.
 */
function domainsFromPayload(
  payload: SpecificationResponse['payload'],
): SdtmDomain[] {
  const raw = (payload as { domains?: unknown }).domains
  if (!Array.isArray(raw)) return []
  return raw as SdtmDomain[]
}

/**
 * Decide the request content type from the file so the backend branches to the
 * JSON or XLSX parser. JSON files are sent as `application/json`; everything
 * else is sent as the XLSX media type.
 */
function inferImportContentType(file: File): string {
  const name = file.name.toLowerCase()
  if (name.endsWith('.json') || file.type === 'application/json') {
    return 'application/json'
  }
  return 'application/vnd.openxmlformats-officedocument.spreadsheetml.sheet'
}

export default SpecificationPanel
