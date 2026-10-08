import * as React from 'react'
import type { AxiosError } from 'axios'
import { useQueryClient } from '@tanstack/react-query'
import { Loader2, Save } from 'lucide-react'
import { PageHeader } from '@/components/layout/page-header'
import { DetailHeader } from '@/components/data/detail-header'
import { ErrorState } from '@/components/data/states'
import { StatusBadge } from '@/components/data/status-badge'
import { IssueList } from '@/components/data/issue-list'
import { Button } from '@/components/ui/button'
import { Label } from '@/components/ui/label'
import { Textarea } from '@/components/ui/textarea'
import { Skeleton } from '@/components/ui/skeleton'
import { toast } from '@/components/ui/sonner'
import {
  StalenessBanner,
  isStale,
  type StalenessState,
} from '@/components/workbench/staleness-banner'
import { useWorkbench } from '@/components/workbench/workbench-context'
import {
  useGetRawDependencies,
  useReplaceRawDependencies,
} from '@/api/generated/raw/raw'
import type {
  DependencySelectionInput,
  DependencySelectionResponse,
} from '@/api/generated/model'
import { invalidateRawDependencies } from '@/lib/invalidate'
import { parseProblem, stalenessAlert } from '@/lib/problems'

export interface DependenciesPanelProps {
  /** The owning Raw workbench id (path parameter for the GET/PUT). */
  rawId: string
}

/**
 * The dependency-selection replacement body the editor authors. Only the four
 * manually-authored selection arrays plus the optional reaffirmation reason are
 * sent; `revision`/`state`/`fingerprint` are server-maintained response fields.
 */
const SELECTION_KEYS = [
  'standards',
  'terminology',
  'references',
  'templates',
  'reaffirmation_reason',
] as const

/** Pull the editable selection body out of the persisted response snapshot. */
function toInput(
  selection: DependencySelectionResponse | undefined,
): DependencySelectionInput {
  if (!selection) return {}
  const body: DependencySelectionInput = {}
  for (const key of SELECTION_KEYS) {
    const value = selection[key]
    if (value !== undefined && value !== null) {
      // eslint-disable-next-line @typescript-eslint/no-explicit-any
      ;(body as any)[key] = value
    }
  }
  return body
}

/**
 * Raw Dependencies tab body (Requirement 20).
 *
 * Flows:
 * - View the current exact selection and its revision/state via
 *   `GET /api/v1/raw/{raw_id}/dependencies` (R20.1).
 * - Replace the whole selection via `PUT .../dependencies` carrying the
 *   aggregate ETag from the workbench context (R20.2). The body is a typed
 *   {@link DependencySelectionInput} authored as structured JSON — there is no
 *   free-text/code path; the user edits the exact typed selection arrays.
 * - A 422 `dependency_selection_invalid` / `dependency_selection_incomplete`
 *   renders each incompatibility (message + suggestion) through the shared
 *   {@link IssueList} (R20.3).
 * - A 412 shows a concurrency message and reloads the current revision before a
 *   retry (R20.4).
 * - A `dependency_refresh_required` selection state shows the persistent
 *   {@link StalenessBanner} and disables the start-operation (save) control
 *   until the selection is refreshed/reaffirmed (R20.5).
 */
export function DependenciesPanel({ rawId }: DependenciesPanelProps) {
  const qc = useQueryClient()
  const { ifMatch } = useWorkbench()

  const query = useGetRawDependencies(rawId)
  const selection = query.data

  // Local editor buffer seeded from the loaded selection. Re-seed whenever a
  // fresh selection arrives (initial load, or a reload after 412/success) so
  // the editor reflects the current server revision.
  const [draft, setDraft] = React.useState('')
  const [parseError, setParseError] = React.useState<string | null>(null)
  const seededRevision = React.useRef<number | null>(null)

  React.useEffect(() => {
    if (!selection) return
    if (seededRevision.current === selection.revision) return
    seededRevision.current = selection.revision
    setDraft(JSON.stringify(toInput(selection), null, 2))
    setParseError(null)
  }, [selection])

  const state = (selection?.state ?? null) as StalenessState | null
  const refreshRequired = isStale(state)

  const replace = useReplaceRawDependencies({
    mutation: {
      onSuccess: () => invalidateRawDependencies(qc, rawId),
    },
    // Aggregate ETag — the single concurrency token exposed by the workbench
    // shell. Rebinds on every render so a post-412 reload carries the fresh
    // token (R20.2, R20.4).
    request: ifMatch(),
  })

  // 422 incompatibilities (R20.3). Only populated for the invalid/incomplete
  // selection codes; any other failure surfaces as the top-level alert.
  const [incompatibilities, setIncompatibilities] = React.useState<
    ReadonlyArray<Record<string, unknown>>
  >([])
  const [formError, setFormError] = React.useState<string | null>(null)

  async function handleSave() {
    setFormError(null)
    setIncompatibilities([])

    let body: DependencySelectionInput
    try {
      const parsed: unknown = draft.trim() === '' ? {} : JSON.parse(draft)
      if (typeof parsed !== 'object' || parsed === null || Array.isArray(parsed)) {
        throw new Error('The selection must be a JSON object.')
      }
      body = parsed as DependencySelectionInput
      setParseError(null)
    } catch (error) {
      setParseError(
        error instanceof Error ? error.message : 'The selection is not valid JSON.',
      )
      return
    }

    try {
      await replace.mutateAsync({ rawId, data: body })
      toast.success('Dependency selection replaced.')
    } catch (error) {
      const axiosError = error as AxiosError
      const status = axiosError.response?.status
      const problem = parseProblem(axiosError)

      if (
        status === 422 &&
        (problem.code === 'dependency_selection_invalid' ||
          problem.code === 'dependency_selection_incomplete')
      ) {
        // Render each incompatibility (message + suggestion) via IssueList.
        setIncompatibilities(problem.issues ?? [])
        setFormError(problem.detail ?? 'The dependency selection is invalid.')
        return
      }

      if (status === 412) {
        // Concurrency: reload the current revision before any retry (R20.4).
        // The reload re-seeds the editor via the effect above once the new
        // revision arrives.
        seededRevision.current = null
        await qc.invalidateQueries({
          queryKey: query.queryKey,
        })
        setFormError(
          stalenessAlert(axiosError) ??
            'This selection changed since you opened it. Reload and try again.',
        )
        return
      }

      // Any other failure: surface the problem title/detail.
      setFormError(
        stalenessAlert(axiosError) ??
          problem.detail ??
          axiosError.message ??
          'Failed to replace the dependency selection.',
      )
    }
  }

  if (query.isError) {
    return <ErrorState error={query.error} resourceLabel="dependency selection" />
  }

  return (
    <div className="flex flex-col gap-6">
      <PageHeader
        title="Dependencies"
        description={
          <>
            Exact dependency selection from{' '}
            <code>GET /api/v1/raw/{'{raw_id}'}/dependencies</code>.
          </>
        }
      />

      {/* Persistent refresh-required notice; disables the save control below. */}
      <StalenessBanner
        state={state}
        onReload={() => {
          seededRevision.current = null
          void qc.invalidateQueries({ queryKey: query.queryKey })
        }}
      />

      {query.isLoading || !selection ? (
        <Skeleton className="h-28 w-full" />
      ) : (
        <DetailHeader
          fields={[
            { label: 'Revision', value: selection.revision },
            {
              label: 'State',
              value: <StatusBadge status={selection.state} />,
            },
            {
              label: 'Fingerprint',
              value: <code className="break-all text-xs">{selection.fingerprint}</code>,
            },
          ]}
        />
      )}

      <div className="flex flex-col gap-2">
        <Label htmlFor="raw-dependency-selection">Exact dependency selection</Label>
        <Textarea
          id="raw-dependency-selection"
          value={draft}
          spellCheck={false}
          rows={16}
          className="font-mono text-xs"
          aria-invalid={parseError ? true : undefined}
          disabled={query.isLoading || !selection}
          onChange={(event) => setDraft(event.target.value)}
        />
        <p className="text-muted-foreground text-xs">
          Author the exact standards, terminology, reference, and template
          selections as typed JSON. Replacing the selection pins the exact
          revisions this workbench consumes.
        </p>
        {parseError && (
          <p className="text-destructive text-sm" role="alert">
            {parseError}
          </p>
        )}
      </div>

      {formError && (
        <p className="text-destructive text-sm" role="alert">
          {formError}
        </p>
      )}

      {incompatibilities.length > 0 && (
        <IssueList
          issues={incompatibilities}
          emptyTitle="No incompatibilities"
          emptyDescription="The dependency selection resolved without incompatibilities."
        />
      )}

      <div className="flex justify-end">
        <Button
          onClick={handleSave}
          // Disabled while a refresh is required (R20.5) so no replacement can
          // start until the selection is refreshed/reaffirmed, and while a save
          // is in flight.
          disabled={refreshRequired || replace.isPending || query.isLoading}
        >
          {replace.isPending ? <Loader2 className="animate-spin" /> : <Save />}
          Replace selection
        </Button>
      </div>
    </div>
  )
}
