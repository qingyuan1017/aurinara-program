import * as React from 'react'
import type { AxiosError } from 'axios'
import { useQueryClient } from '@tanstack/react-query'
import { AlertTriangle, Loader2, Save } from 'lucide-react'

import { PageHeader } from '@/components/layout/page-header'
import { EmptyState, ErrorState } from '@/components/data/states'
import { StatusBadge } from '@/components/data/status-badge'
import { IssueList } from '@/components/data/issue-list'
import type { ValidationIssue } from '@/components/data/issue-list'
import { Button } from '@/components/ui/button'
import { Badge } from '@/components/ui/badge'
import { Label } from '@/components/ui/label'
import { Input } from '@/components/ui/input'
import { Textarea } from '@/components/ui/textarea'
import { Skeleton } from '@/components/ui/skeleton'
import {
  Card,
  CardContent,
  CardDescription,
  CardHeader,
  CardTitle,
} from '@/components/ui/card'
import { toast } from '@/components/ui/sonner'
import { OperationRunner } from '@/components/workbench/operation-runner'
import { ArtifactList } from '@/components/workbench/artifact-list'
import type { ArtifactListItem } from '@/components/workbench/artifact-list'
import { useWorkbench } from '@/components/workbench/workbench-context'
import {
  OPERATION_POLL_PRESETS,
  type OperationQueryOpts,
  type OperationQueryState,
} from '@/hooks/use-operation-poll'
import { useIdempotencyKey } from '@/lib/requests'
import { parseProblem, stalenessAlert } from '@/lib/problems'
import {
  invalidateSdtmSubResource,
  invalidateSdtmOperationArtifacts,
} from '@/lib/invalidate'
import {
  getGetCsdrgQueryKey,
  useGetCsdrg,
  useInitializeCsdrg,
  usePutCsdrg,
  useValidateCsdrg,
  useCreateCsdrgArtifacts,
} from '@/api/generated/sdtm-csdrg/sdtm-csdrg'
import {
  getGetArtifactBuildQueryKey,
  useGetArtifactBuild,
} from '@/api/generated/artifact-builds/artifact-builds'
import type {
  ArtifactBuildResponse,
  CsdrgResponse,
  CsdrgNarrativeSection,
  SdtmCsdrgInitialize,
  SdtmCsdrgModel,
  ValidationRunResponse,
} from '@/api/generated/model'

/**
 * The nine required cSDRG narrative sections (Requirement 19.3, 19.4), each a
 * stable `section_id` plus a fixed heading. These mirror the backend's
 * `REQUIRED_NARRATIVE_SECTIONS` (`src/app/sdtm/csdrg.py`) EXACTLY — the order,
 * the ids, and the headings — so an initialized/validated model and this panel
 * agree on the required set.
 *
 * Exported so task 17.3's tests can assert the nine sections are rendered,
 * preserve typed content, and are never auto-populated.
 */
export const CSDRG_SECTIONS: readonly { id: string; heading: string }[] = [
  { id: 'study_data_overview', heading: 'Study Data Overview' },
  { id: 'standards_and_versions', heading: 'Standards and Versions' },
  { id: 'trial_design', heading: 'Trial Design' },
  { id: 'domain_notes', heading: 'Domain Notes' },
  { id: 'conformance_issues', heading: 'Conformance Issues' },
  { id: 'sponsor_defined_domains', heading: 'Sponsor-Defined Domains' },
  { id: 'controlled_terminology', heading: 'Controlled Terminology' },
  { id: 'data_dependencies', heading: 'Data Dependencies' },
  { id: 'reviewer_guidance', heading: 'Reviewer Guidance' },
] as const

/** The nine required section ids, for membership checks. */
const REQUIRED_SECTION_IDS: ReadonlySet<string> = new Set(
  CSDRG_SECTIONS.map((section) => section.id),
)

export interface CsdrgPanelProps {
  /** The owning SDTM workbench id (path parameter for every cSDRG call). */
  sdtmId: string
}

/** Inline destructive notice, consistent with the other SDTM panels. */
function Notice({
  title,
  detail,
  onReload,
  reloadLabel = 'Reload current cSDRG',
}: {
  title: string
  detail?: React.ReactNode
  onReload?: () => void
  reloadLabel?: string
}) {
  return (
    <div
      role="alert"
      className="border-destructive/50 text-destructive flex items-start gap-3 rounded-md border px-4 py-3 text-sm"
    >
      <AlertTriangle className="mt-0.5 size-4 shrink-0" aria-hidden />
      <div className="flex flex-col gap-1">
        <span className="font-medium">{title}</span>
        {detail && <span className="opacity-90">{detail}</span>}
        {onReload && (
          <button
            type="button"
            onClick={onReload}
            className="text-destructive mt-1 w-fit font-medium underline underline-offset-2"
          >
            {reloadLabel}
          </button>
        )}
      </div>
    </div>
  )
}

/**
 * Read the version-neutral cSDRG authoring model off the generated response.
 * The payload is modelled as an opaque `{ [key: string]: unknown }`, so it is
 * cast to the typed authoring model the panel edits and re-submits.
 */
function readModel(csdrg: CsdrgResponse): SdtmCsdrgModel {
  return csdrg.payload as unknown as SdtmCsdrgModel
}

/**
 * Join a section's stored paragraphs into the single editable text block the
 * panel presents. Paragraphs are separated by a blank line so the round-trip is
 * stable: {@link textToParagraphs} splits on the same boundary.
 */
function paragraphsToText(paragraphs: readonly string[] | undefined): string {
  return (paragraphs ?? []).join('\n\n')
}

/**
 * Split an edited text block back into stored paragraphs on blank-line
 * boundaries, preserving the user's content verbatim (no inference, no
 * auto-population). An all-whitespace block yields an empty paragraph list so
 * the saved section carries no narrative — which the validate step then flags.
 */
function textToParagraphs(text: string): string[] {
  if (text.trim() === '') return []
  return text
    .split(/\n{2,}/)
    .map((paragraph) => paragraph.trim())
    .filter((paragraph) => paragraph.length > 0)
}

export function CsdrgPanel({ sdtmId }: CsdrgPanelProps) {
  const qc = useQueryClient()
  const { ifMatch, aggregate } = useWorkbench()

  const csdrgKey = React.useMemo(() => getGetCsdrgQueryKey(sdtmId), [sdtmId])

  const query = useGetCsdrg(sdtmId, { query: { retry: false } })
  const csdrg = query.data
  const loadStatus = (query.error as AxiosError | null)?.response?.status
  const loadCode =
    loadStatus === 404 ? parseProblem(query.error as AxiosError).code : undefined
  const notSaved = loadStatus === 404 && loadCode === 'sdtm_csdrg_not_found'

  // Persistent staleness notice shown after a 409 on a write; cleared when the
  // user refreshes the current cSDRG before retrying.
  const [staleMessage, setStaleMessage] = React.useState<string | null>(null)

  const reloadCsdrg = React.useCallback(async () => {
    setStaleMessage(null)
    await qc.invalidateQueries({ queryKey: csdrgKey })
  }, [qc, csdrgKey])

  const handleStale = React.useCallback((error: AxiosError): boolean => {
    if (error.response?.status !== 409) return false
    const problem = parseProblem(error)
    setStaleMessage(
      problem.detail ??
        stalenessAlert(error) ??
        'The current cSDRG changed since you opened it. Refresh and try again.',
    )
    return true
  }, [])

  if (query.isLoading) {
    return (
      <div className="flex flex-col gap-4">
        <Skeleton className="h-24 w-full" />
        <Skeleton className="h-48 w-full" />
      </div>
    )
  }

  if (query.isError && !notSaved) {
    return <ErrorState error={query.error} resourceLabel="cSDRG" />
  }

  return (
    <div className="flex flex-col gap-6">
      <PageHeader
        title="cSDRG"
        description={
          <>
            Initialize factual structures, author the nine required narrative
            sections, validate, and build the reviewer guide via{' '}
            <code>/api/v1/sdtms/{'{sdtm_id}'}/csdrg</code>. The platform never
            infers narrative — every section is authored by you.
          </>
        }
      />

      {staleMessage && (
        <Notice
          title="The cSDRG is out of date"
          detail={staleMessage}
          onReload={() => void reloadCsdrg()}
        />
      )}

      {/* Current cSDRG summary (or unsaved empty state). */}
      {notSaved || !csdrg ? (
        <EmptyState
          title="No cSDRG yet"
          description="This SDTM workbench has no saved cSDRG. Initialize the factual structures from the current Define revision and a successful reconciliation run below."
        />
      ) : (
        <CsdrgSummary csdrg={csdrg} />
      )}

      {/* Initialize (aggregate ETag + expected revision + Define revision + recon run). */}
      <InitializeCard
        sdtmId={sdtmId}
        csdrg={csdrg ?? null}
        ifMatch={ifMatch}
        onInitialized={async () => {
          await invalidateSdtmSubResource(qc, 'csdrg', sdtmId)
          await reloadCsdrg()
        }}
        onStale={handleStale}
      />

      {/* Author + save the nine narrative sections (aggregate ETag). */}
      {csdrg && (
        <NarrativeCard
          sdtmId={sdtmId}
          csdrg={csdrg}
          ifMatch={ifMatch}
          onSaved={async () => {
            await invalidateSdtmSubResource(qc, 'csdrg', sdtmId)
          }}
          onStale={handleStale}
        />
      )}

      {/* Validate (synchronous Validation_Run + client whitespace-only check). */}
      {csdrg && <ValidateCard sdtmId={sdtmId} csdrg={csdrg} />}

      {/* Build cSDRG artifacts (2s/300s poll). */}
      {csdrg && (
        <BuildCard sdtmId={sdtmId} csdrg={csdrg} studyId={aggregate.study_id} />
      )}
    </div>
  )
}

// ---------------------------------------------------------------------------
// Current cSDRG summary
// ---------------------------------------------------------------------------

function CsdrgSummary({ csdrg }: { csdrg: CsdrgResponse }) {
  const model = readModel(csdrg)
  return (
    <Card>
      <CardHeader>
        <CardTitle className="text-base">Current cSDRG</CardTitle>
        <CardDescription className="flex flex-wrap items-center gap-2">
          <Badge variant="outline">Revision {csdrg.revision}</Badge>
          <Badge variant="secondary">
            Define rev {csdrg.define_revision}
          </Badge>
          <Badge variant="outline">
            Spec rev {csdrg.specification_revision}
          </Badge>
          <Badge variant="outline">schema {csdrg.schema_version}</Badge>
        </CardDescription>
      </CardHeader>
      <CardContent>
        <dl className="grid grid-cols-2 gap-x-6 gap-y-2 sm:grid-cols-3">
          <div>
            <dt className="text-muted-foreground text-xs">Title</dt>
            <dd className="text-sm break-all">{model.title}</dd>
          </div>
          <div>
            <dt className="text-muted-foreground text-xs">Version</dt>
            <dd className="text-sm break-all">{model.version}</dd>
          </div>
          <div>
            <dt className="text-muted-foreground text-xs">Reconciliation run</dt>
            <dd className="text-sm break-all">{csdrg.reconciliation_run_id}</dd>
          </div>
          <div>
            <dt className="text-muted-foreground text-xs">Fingerprint</dt>
            <dd className="text-sm break-all">{csdrg.fingerprint}</dd>
          </div>
          <div>
            <dt className="text-muted-foreground text-xs">Dataset facts</dt>
            <dd className="text-sm">{model.dataset_facts?.length ?? 0}</dd>
          </div>
        </dl>
      </CardContent>
    </Card>
  )
}

// ---------------------------------------------------------------------------
// Initialize
// ---------------------------------------------------------------------------

interface InitializeCardProps {
  sdtmId: string
  csdrg: CsdrgResponse | null
  ifMatch: ReturnType<typeof useWorkbench>['ifMatch']
  onInitialized: () => Promise<void> | void
  onStale: (error: AxiosError) => boolean
}

/**
 * Initialize/refresh the factual cSDRG structures (Requirement 19.2) via
 * `POST /csdrg/initialize` with the aggregate ETag, the expected cSDRG revision
 * (the current revision, or null when none exists), the current Define
 * revision, and the successful Define/XPT/aCRF reconciliation run id. This
 * refreshes dataset facts WITHOUT writing narrative; narrative is authored and
 * saved separately in {@link NarrativeCard}.
 */
function InitializeCard({
  sdtmId,
  csdrg,
  ifMatch,
  onInitialized,
  onStale,
}: InitializeCardProps) {
  const existingModel = csdrg ? readModel(csdrg) : null
  const [title, setTitle] = React.useState(existingModel?.title ?? '')
  const [version, setVersion] = React.useState(existingModel?.version ?? '')
  const [defineRevision, setDefineRevision] = React.useState(
    csdrg ? String(csdrg.define_revision) : '',
  )
  const [reconciliationRunId, setReconciliationRunId] = React.useState(
    csdrg?.reconciliation_run_id ?? '',
  )

  const idempotency = useIdempotencyKey()
  const initialize = useInitializeCsdrg({
    request: {
      headers: {
        ...ifMatch().headers,
        'Idempotency-Key': idempotency.key,
      },
    },
  })

  const defineRevisionNumber = Number.parseInt(defineRevision, 10)
  const canInitialize =
    title.trim().length > 0 &&
    version.trim().length > 0 &&
    Number.isInteger(defineRevisionNumber) &&
    defineRevisionNumber >= 1 &&
    reconciliationRunId.trim().length > 0 &&
    !initialize.isPending

  async function handleInitialize() {
    const body: SdtmCsdrgInitialize = {
      // The expected cSDRG revision guards against a concurrent change — the
      // current revision, or null for a first initialization (Requirement 19.2).
      expected_csdrg_revision: csdrg?.revision ?? null,
      title: title.trim(),
      version: version.trim(),
      define_revision: defineRevisionNumber,
      reconciliation_run_id: reconciliationRunId.trim(),
    }
    try {
      await initialize.mutateAsync({ sdtmId, data: body })
      toast.success('cSDRG initialized.')
      await onInitialized()
    } catch (error) {
      const err = error as AxiosError
      if (onStale(err)) return
      if (err.response?.status === 412) {
        toast.error(
          stalenessAlert(err) ??
            'This workbench changed since you opened it. Reload and try again.',
        )
        return
      }
      toast.error(
        parseProblem(err).detail ?? err.message ?? 'Could not initialize the cSDRG.',
      )
    }
  }

  return (
    <Card>
      <CardHeader>
        <CardTitle className="text-base">Initialize</CardTitle>
        <CardDescription>
          Refresh the factual cSDRG structures from the current Define revision
          and a successful reconciliation run. This never writes narrative.
        </CardDescription>
      </CardHeader>
      <CardContent className="flex flex-col gap-4">
        <div className="grid gap-3 sm:grid-cols-2">
          <div className="flex flex-col gap-1">
            <Label htmlFor="csdrg-title">Title</Label>
            <Input
              id="csdrg-title"
              value={title}
              onChange={(event) => setTitle(event.target.value)}
              placeholder="Clinical Study Data Reviewer's Guide"
            />
          </div>
          <div className="flex flex-col gap-1">
            <Label htmlFor="csdrg-version">Version</Label>
            <Input
              id="csdrg-version"
              value={version}
              onChange={(event) => setVersion(event.target.value)}
              placeholder="1.0"
            />
          </div>
          <div className="flex flex-col gap-1">
            <Label htmlFor="csdrg-define-revision">Define revision</Label>
            <Input
              id="csdrg-define-revision"
              type="number"
              min={1}
              step={1}
              value={defineRevision}
              onChange={(event) => setDefineRevision(event.target.value)}
              placeholder="Current Define revision"
            />
          </div>
          <div className="flex flex-col gap-1">
            <Label htmlFor="csdrg-recon-run">Reconciliation run id</Label>
            <Input
              id="csdrg-recon-run"
              value={reconciliationRunId}
              onChange={(event) => setReconciliationRunId(event.target.value)}
              placeholder="Successful Define/XPT/aCRF reconciliation run id"
            />
          </div>
        </div>

        <div>
          <Button
            type="button"
            onClick={handleInitialize}
            disabled={!canInitialize}
          >
            {initialize.isPending && (
              <Loader2 className="animate-spin" aria-hidden />
            )}
            Initialize cSDRG
          </Button>
        </div>
      </CardContent>
    </Card>
  )
}

// ---------------------------------------------------------------------------
// Narrative authoring + save
// ---------------------------------------------------------------------------

interface NarrativeCardProps {
  sdtmId: string
  csdrg: CsdrgResponse
  ifMatch: ReturnType<typeof useWorkbench>['ifMatch']
  onSaved: () => Promise<void> | void
  onStale: (error: AxiosError) => boolean
}

/**
 * Present the nine required narrative sections as editable text fields and save
 * them (Requirement 19.3) via `PUT /csdrg` with the aggregate ETag. Each field
 * is seeded ONLY from the user's previously saved content — the panel never
 * infers or auto-populates narrative. On save the authored text is round-tripped
 * into the version-neutral model under the current workbench revision.
 */
function NarrativeCard({
  sdtmId,
  csdrg,
  ifMatch,
  onSaved,
  onStale,
}: NarrativeCardProps) {
  const put = usePutCsdrg({ request: ifMatch() })

  // Seed each section's editable text from the saved paragraphs — and ONLY from
  // them. Sections the user has not authored start empty (no inference).
  const seedTexts = React.useCallback((): Record<string, string> => {
    const model = readModel(csdrg)
    const byId = new Map(
      (model.narrative_sections ?? []).map((section) => [
        section.section_id,
        section,
      ]),
    )
    const next: Record<string, string> = {}
    for (const section of CSDRG_SECTIONS) {
      next[section.id] = paragraphsToText(byId.get(section.id)?.paragraphs)
    }
    return next
  }, [csdrg])

  const [texts, setTexts] = React.useState<Record<string, string>>(seedTexts)

  // Reseed when the loaded cSDRG changes (e.g. after a save/initialize refetch
  // bumps the revision/fingerprint), so the editor reflects persisted content.
  React.useEffect(() => {
    setTexts(seedTexts())
  }, [seedTexts])

  function setSection(id: string, value: string) {
    setTexts((prev) => ({ ...prev, [id]: value }))
  }

  async function handleSave() {
    const model = readModel(csdrg)
    // Preserve any non-required authored sections verbatim, then overwrite the
    // nine required ones with the authored text, keeping headings fixed.
    const extras = (model.narrative_sections ?? []).filter(
      (section) => !REQUIRED_SECTION_IDS.has(section.section_id),
    )
    const required: CsdrgNarrativeSection[] = CSDRG_SECTIONS.map((section) => ({
      section_id: section.id,
      heading: section.heading,
      paragraphs: textToParagraphs(texts[section.id] ?? ''),
    }))
    const body: SdtmCsdrgModel = {
      ...model,
      narrative_sections: [...required, ...extras],
    }
    try {
      await put.mutateAsync({ sdtmId, data: body })
      toast.success('cSDRG saved.')
      await onSaved()
    } catch (error) {
      const err = error as AxiosError
      if (onStale(err)) return
      if (err.response?.status === 412) {
        toast.error(
          stalenessAlert(err) ??
            'This cSDRG changed since you opened it. Reload and try again.',
        )
        return
      }
      toast.error(
        parseProblem(err).detail ?? err.message ?? 'Could not save the cSDRG.',
      )
    }
  }

  return (
    <Card>
      <CardHeader>
        <CardTitle className="text-base">Narrative sections</CardTitle>
        <CardDescription>
          Author the nine required narrative sections. Content is preserved
          exactly as you write it; separate paragraphs with a blank line.
        </CardDescription>
      </CardHeader>
      <CardContent className="flex flex-col gap-5">
        {CSDRG_SECTIONS.map((section) => {
          const value = texts[section.id] ?? ''
          const empty = value.trim() === ''
          return (
            <div key={section.id} className="flex flex-col gap-1.5">
              <div className="flex items-center gap-2">
                <Label htmlFor={`csdrg-section-${section.id}`}>
                  {section.heading}
                </Label>
                {empty && (
                  <Badge variant="destructive">Required — not authored</Badge>
                )}
              </div>
              <Textarea
                id={`csdrg-section-${section.id}`}
                data-section-id={section.id}
                aria-label={section.heading}
                value={value}
                onChange={(event) =>
                  setSection(section.id, event.target.value)
                }
                rows={4}
                placeholder={`Author the ${section.heading} narrative…`}
              />
            </div>
          )
        })}

        <div>
          <Button type="button" onClick={handleSave} disabled={put.isPending}>
            {put.isPending && <Loader2 className="animate-spin" aria-hidden />}
            <Save /> Save cSDRG
          </Button>
        </div>
      </CardContent>
    </Card>
  )
}

// ---------------------------------------------------------------------------
// Validate (synchronous)
// ---------------------------------------------------------------------------

/**
 * Build a client-side error issue for a required narrative section that is
 * absent or whitespace-only (Requirement 19.4). The backend validate only flags
 * sections with no authored paragraphs; a section whose paragraphs are present
 * but blank would slip through, so the panel synthesizes the same error-severity
 * issue for every required section that is absent OR whitespace-only.
 */
function whitespaceIssue(sectionId: string, heading: string): ValidationIssue {
  return {
    id: `CLIENT_SDTM_CSDRG_REQUIRED_SECTION_MISSING:${sectionId}`,
    code: 'SDTM_CSDRG_REQUIRED_SECTION_MISSING',
    severity: 'error',
    message: `The required cSDRG narrative section "${heading}" is absent or contains only whitespace.`,
    suggestion: 'Author the required narrative section and validate a new revision.',
    module: 'sdtm',
    entity_type: 'sdtm_csdrg',
    field_path: `narrative_sections[${sectionId}]`,
  }
}

/**
 * Compute the client-side whitespace-only/absent errors for the nine required
 * sections off the currently loaded cSDRG model, de-duplicated against the
 * backend's own `narrative_sections[{id}]` findings so a section is reported
 * once. Exported indirectly through the panel's rendered issues.
 */
function clientSectionIssues(
  csdrg: CsdrgResponse,
  backendFieldPaths: ReadonlySet<string>,
): ValidationIssue[] {
  const model = readModel(csdrg)
  const byId = new Map(
    (model.narrative_sections ?? []).map((section) => [
      section.section_id,
      section,
    ]),
  )
  const issues: ValidationIssue[] = []
  for (const section of CSDRG_SECTIONS) {
    const stored = byId.get(section.id)
    const authored = (stored?.paragraphs ?? []).some(
      (paragraph) => paragraph.trim() !== '',
    )
    const fieldPath = `narrative_sections[${section.id}]`
    if (!authored && !backendFieldPaths.has(fieldPath)) {
      issues.push(whitespaceIssue(section.id, section.heading))
    }
  }
  return issues
}

/**
 * Validate the current cSDRG (Requirement 19.4). The backend returns a
 * synchronous Validation_Run flagging required sections that carry no authored
 * paragraphs; the panel ALSO applies the client-side absent/whitespace-only
 * check and merges both into the displayed issue list, recounting error
 * severity so a blank-but-present section is surfaced as an error.
 */
function ValidateCard({
  sdtmId,
  csdrg,
}: {
  sdtmId: string
  csdrg: CsdrgResponse
}) {
  const validate = useValidateCsdrg()
  const [run, setRun] = React.useState<ValidationRunResponse | null>(null)

  async function handleValidate() {
    try {
      const result = await validate.mutateAsync({ sdtmId })
      setRun(result)
    } catch (error) {
      const err = error as AxiosError
      toast.error(
        parseProblem(err).detail ?? err.message ?? 'Could not validate the cSDRG.',
      )
    }
  }

  // Merge backend issues with the client absent/whitespace-only findings.
  const merged = React.useMemo(() => {
    if (!run) return null
    const backendIssues = (run.issues ?? []) as Array<Record<string, unknown>>
    const backendFieldPaths = new Set(
      backendIssues
        .map((issue) => issue.field_path)
        .filter((path): path is string => typeof path === 'string'),
    )
    const clientIssues = clientSectionIssues(csdrg, backendFieldPaths)
    const allIssues = [...backendIssues, ...clientIssues]
    const errorCount = allIssues.filter(
      (issue) => issue.severity === 'error',
    ).length
    const warningCount = allIssues.filter(
      (issue) => issue.severity === 'warning',
    ).length
    const infoCount = allIssues.filter(
      (issue) => issue.severity === 'info',
    ).length
    return { allIssues, errorCount, warningCount, infoCount }
  }, [run, csdrg])

  return (
    <Card>
      <CardHeader>
        <CardTitle className="text-base">Validate</CardTitle>
        <CardDescription>
          Validate the current cSDRG. Any required narrative section that is
          absent or whitespace-only is reported as an error.
        </CardDescription>
      </CardHeader>
      <CardContent className="flex flex-col gap-4">
        <div>
          <Button
            type="button"
            onClick={handleValidate}
            disabled={validate.isPending}
          >
            {validate.isPending && (
              <Loader2 className="animate-spin" aria-hidden />
            )}
            Validate cSDRG
          </Button>
        </div>

        {run && merged && (
          <div className="flex flex-col gap-3">
            <div className="flex flex-wrap items-center gap-2">
              <StatusBadge status={run.status} />
              <Badge variant="destructive">Error: {merged.errorCount}</Badge>
              <Badge variant="secondary">Warning: {merged.warningCount}</Badge>
              <Badge variant="outline">Info: {merged.infoCount}</Badge>
            </div>
            <IssueList
              issues={merged.allIssues}
              emptyTitle="No cSDRG issues"
              emptyDescription="All nine required narrative sections are authored and this validation run produced no issues."
            />
          </div>
        )}
      </CardContent>
    </Card>
  )
}

// ---------------------------------------------------------------------------
// Build
// ---------------------------------------------------------------------------

/** Adapter around the generated artifact-build query for {@link OperationRunner}. */
function useCsdrgBuildOperation(
  buildId: string,
  opts: OperationQueryOpts,
): OperationQueryState<ArtifactBuildResponse> {
  const query = useGetArtifactBuild(buildId, { query: opts.query })
  return { data: query.data, error: query.error as AxiosError | null }
}

function CompletedCsdrgBuild({
  build,
  sdtmId,
  studyId,
}: {
  build: ArtifactBuildResponse
  sdtmId: string
  studyId: string
}) {
  const qc = useQueryClient()
  React.useEffect(() => {
    // A completed `202` build produces artifacts and advances the aggregate's
    // latest-run state: reload the study-scoped artifact collection + aggregate
    // (shared operation helper) and the cSDRG sub-resource view, plus the
    // polled build resource (R21.6).
    invalidateSdtmOperationArtifacts(qc, sdtmId, studyId)
    invalidateSdtmSubResource(qc, 'csdrg', sdtmId)
    void qc.invalidateQueries({ queryKey: getGetArtifactBuildQueryKey(build.id) })
  }, [qc, sdtmId, studyId, build.id])

  const artifacts: ArtifactListItem[] = build.result_artifact_ids.map((id) => ({
    id,
  }))

  return (
    <ArtifactList
      artifacts={artifacts}
      title="cSDRG artifact"
      emptyTitle="No artifact produced"
      emptyDescription="The build completed but produced no downloadable artifact."
    />
  )
}

/**
 * Build the cSDRG artifact (Requirements 19.5, 19.6): `POST /csdrg/artifacts`
 * with an `Idempotency-Key`, then poll the resulting build at a fixed 2s
 * interval to a terminal state or 300s via {@link OperationRunner}. A failed
 * terminal or a client timeout names the affected build and presents no
 * artifact. The build pins the current cSDRG fingerprint as the expected input
 * fingerprint; a stale one is rejected by the server (409) and surfaced on start.
 */
function BuildCard({
  sdtmId,
  csdrg,
  studyId,
}: {
  sdtmId: string
  csdrg: CsdrgResponse
  studyId: string
}) {
  const [buildId, setBuildId] = React.useState<string | null>(null)
  const idempotency = useIdempotencyKey()

  const create = useCreateCsdrgArtifacts({ request: idempotency.requestConfig })

  async function handleStart() {
    idempotency.begin()
    try {
      const build = await create.mutateAsync({
        sdtmId,
        data: { expected_input_fingerprint: csdrg.fingerprint },
      })
      setBuildId(build.id)
    } catch (error) {
      const problem = parseProblem(error as AxiosError)
      toast.error(problem.title ?? 'cSDRG build could not be started', {
        description: problem.detail,
      })
    }
  }

  return (
    <Card>
      <CardHeader>
        <CardTitle className="text-base">cSDRG artifact</CardTitle>
        <CardDescription>
          Build the reviewer guide artifact. The build polls every 2s up to
          300s.
        </CardDescription>
      </CardHeader>
      <CardContent className="flex flex-col gap-3">
        <OperationRunner<ArtifactBuildResponse>
          operationLabel="cSDRG build"
          operationId={buildId}
          useGetOperation={useCsdrgBuildOperation}
          intervalMs={OPERATION_POLL_PRESETS.build.intervalMs}
          timeoutMs={OPERATION_POLL_PRESETS.build.timeoutMs}
          onStart={handleStart}
          startLabel="Build cSDRG artifact"
          startDisabled={create.isPending}
          renderResult={(build) => (
            <CompletedCsdrgBuild
              build={build}
              sdtmId={sdtmId}
              studyId={studyId}
            />
          )}
        />
      </CardContent>
    </Card>
  )
}

export default CsdrgPanel
