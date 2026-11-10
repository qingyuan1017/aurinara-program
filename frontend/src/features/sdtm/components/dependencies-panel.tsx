import * as React from 'react'
import type { AxiosError } from 'axios'
import { useQueryClient } from '@tanstack/react-query'
import { CircleAlert, CircleCheck, Loader2, Save, Settings2 } from 'lucide-react'
import { ErrorState } from '@/components/data/states'
import { StatusBadge } from '@/components/data/status-badge'
import { IssueList } from '@/components/data/issue-list'
import { Badge } from '@/components/ui/badge'
import { Button } from '@/components/ui/button'
import {
  Card,
  CardContent,
  CardDescription,
  CardHeader,
  CardTitle,
} from '@/components/ui/card'
import { Label } from '@/components/ui/label'
import { Textarea } from '@/components/ui/textarea'
import { Skeleton } from '@/components/ui/skeleton'
import { toast } from '@/components/ui/sonner'
import { StalenessBanner } from '@/components/workbench/staleness-banner'
import {
  isStale,
  type StalenessState,
} from '@/components/workbench/staleness-state'
import { useWorkbench } from '@/components/workbench/workbench-context'
import {
  useGetSdtmDependencies,
  useReplaceSdtmDependencies,
} from '@/api/generated/sdtm/sdtm'
import type {
  DependencySelectionInput,
  DependencySelectionResponse,
} from '@/api/generated/model'
import { invalidateSdtmDependencies } from '@/lib/invalidate'
import { parseProblem, stalenessAlert } from '@/lib/problems'

export interface SdtmDependenciesPanelProps {
  /** The owning SDTM workbench id (path parameter for the GET/PUT). */
  sdtmId: string
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
 * SDTM Dependencies tab body (Requirement 20).
 *
 * Mirrors the Raw dependencies panel: the SDTM aggregate owns the exact
 * Standards/Terminology/Reference/Template selection, authored as a typed
 * {@link DependencySelectionInput} (never a free-text/code path).
 *
 * Flows:
 * - View the current exact selection and its revision/state via
 *   `GET /api/v1/sdtm-workbenches/{sdtm_id}/dependencies` (R20.1).
 * - Replace the whole selection via `PUT .../dependencies` carrying the
 *   aggregate ETag from the workbench context (R20.2).
 * - A 422 `dependency_selection_invalid` / `dependency_selection_incomplete`
 *   renders each incompatibility (message + suggestion) through the shared
 *   {@link IssueList} (R20.3).
 * - A 412 shows a concurrency message and reloads the current revision before a
 *   retry (R20.4).
 * - A `dependency_refresh_required` selection state shows the persistent
 *   {@link StalenessBanner} and disables the start-operation (save) control
 *   until the selection is refreshed/reaffirmed (R20.5).
 */
export function SdtmDependenciesPanel({ sdtmId }: SdtmDependenciesPanelProps) {
  const qc = useQueryClient()
  const { ifMatch } = useWorkbench()

  const query = useGetSdtmDependencies(sdtmId)
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
  const dependencyGroups = selection
    ? [
        {
          label: 'Industry standards',
          items: (selection.standards ?? []).map((item) => item.purpose),
        },
        {
          label: 'Controlled terminology',
          items: (selection.terminology ?? []).map((item) => item.scope),
        },
        {
          label: 'Study reference data',
          items: (selection.references ?? []).map((item) => item.purpose),
        },
        {
          label: 'Presentation templates',
          items: (selection.templates ?? []).map((item) => item.purpose),
        },
      ]
    : []

  const replace = useReplaceSdtmDependencies({
    mutation: {
      onSuccess: () => invalidateSdtmDependencies(qc, sdtmId),
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
      await replace.mutateAsync({ sdtmId, data: body })
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
      <StalenessBanner
        state={state}
        onReload={() => {
          seededRevision.current = null
          void qc.invalidateQueries({ queryKey: query.queryKey })
        }}
      />

      <Card>
        <CardHeader>
          <div className="flex flex-wrap items-start justify-between gap-3">
            <div>
              <CardTitle className="text-base">Standards and dependencies</CardTitle>
              <CardDescription className="mt-1">
                Exact versions used by the SDTM agent and deterministic validation.
              </CardDescription>
            </div>
            {selection ? (
              <Badge variant={selection.state === 'current' ? 'default' : 'destructive'}>
                {selection.state === 'current' ? (
                  <CircleCheck />
                ) : (
                  <CircleAlert />
                )}
                {selection.state === 'current' ? 'Ready' : 'Action required'}
              </Badge>
            ) : null}
          </div>
        </CardHeader>
        <CardContent className="space-y-5">
          {query.isLoading || !selection ? (
            <Skeleton className="h-28 w-full" />
          ) : (
            <>
              <div className="grid gap-3 sm:grid-cols-2 xl:grid-cols-4">
                {dependencyGroups.map((group) => (
                  <div key={group.label} className="rounded-lg border bg-muted/20 p-3">
                    <p className="text-xs font-medium text-muted-foreground">{group.label}</p>
                    <p className="mt-1 text-2xl font-semibold">{group.items.length}</p>
                    <p className="mt-1 truncate text-xs text-muted-foreground">
                      {group.items.length
                        ? group.items.map(readablePurpose).join(', ')
                        : 'None selected'}
                    </p>
                  </div>
                ))}
              </div>

              <details className="group rounded-lg border">
                <summary className="flex cursor-pointer list-none items-center gap-2 px-4 py-3 text-sm font-medium">
                  <Settings2 className="size-4 text-muted-foreground" />
                  Technical details and dependency administration
                  <StatusBadge status={selection.state} />
                </summary>
                <div className="space-y-5 border-t p-4">
                  <div className="grid gap-3 text-sm sm:grid-cols-2">
                    <div>
                      <p className="text-xs text-muted-foreground">Selection revision</p>
                      <p>{selection.revision}</p>
                    </div>
                    <div className="min-w-0">
                      <p className="text-xs text-muted-foreground">Reproducibility fingerprint</p>
                      <code className="block truncate text-xs" title={selection.fingerprint}>
                        {selection.fingerprint}
                      </code>
                    </div>
                  </div>
                  <div className="flex flex-col gap-2">
                    <Label htmlFor="sdtm-dependency-selection">Exact dependency selection</Label>
                    <Textarea
                      id="sdtm-dependency-selection"
                      value={draft}
                      spellCheck={false}
                      rows={12}
                      className="font-mono text-xs"
                      aria-invalid={parseError ? true : undefined}
                      disabled={query.isLoading || !selection}
                      onChange={(event) => setDraft(event.target.value)}
                    />
                    <p className="text-muted-foreground text-xs">
                      Restricted administration control for replacing exact immutable pins.
                      Routine clinical content changes belong in AI proposals and human review.
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
                      disabled={refreshRequired || replace.isPending || query.isLoading}
                    >
                      {replace.isPending ? <Loader2 className="animate-spin" /> : <Save />}
                      Replace selection
                    </Button>
                  </div>
                </div>
              </details>
            </>
          )}
        </CardContent>
      </Card>
    </div>
  )
}

function readablePurpose(value: string) {
  return value.replaceAll('_', ' ')
}
