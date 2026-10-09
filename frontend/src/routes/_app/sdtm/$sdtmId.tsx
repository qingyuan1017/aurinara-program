import * as React from 'react'
import { createFileRoute, Link, useNavigate } from '@tanstack/react-router'
import { Button } from '@/components/ui/button'
import { Label } from '@/components/ui/label'
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from '@/components/ui/select'
import { Skeleton } from '@/components/ui/skeleton'
import { EmptyState, ErrorState } from '@/components/data/states'
import {
  WorkbenchDetailShell,
  type WorkbenchTab,
} from '@/components/workbench/workbench-detail-shell'
import { InputSelectionPanel } from '@/components/workbench/input-selection-panel'
import { useCurrentStudy } from '@/components/study-provider'
import { SpecificationPanel } from '@/components/workbench/specification-panel'
import { DerivationPlanPanel } from '@/components/workbench/derivation-plan-panel'
import { SdtmValidationPanel } from '@/components/workbench/sdtm-validation-panel'
import { DefinePanel } from '@/components/workbench/define-panel'
import { CompilePanel } from '@/components/workbench/compile-panel'
import { ExecutionPanel } from '@/components/workbench/execution-panel'
import { SdtmDependenciesPanel } from '@/components/workbench/sdtm-dependencies-panel'
import { AcrfPanel } from '@/components/workbench/acrf-panel'
import { CsdrgPanel } from '@/components/workbench/csdrg-panel'
import { useGetSdtmAggregate, useListSdtmPlans } from '@/api/generated/sdtm/sdtm'

/**
 * The ten SDTM workbench tabs. Each `value` doubles as the `?tab=` search-param
 * value so refresh/links land on the right section. The panel bodies are
 * delivered by tasks 11-17; this shell renders placeholders and wires the
 * header, `?tab=` routing, and tab structure (Requirement 9.3).
 */
const SDTM_TABS: readonly { value: string; label: string }[] = [
  { value: 'input-selection', label: 'Input selection' },
  { value: 'specification', label: 'Specification' },
  { value: 'acrf', label: 'aCRF' },
  { value: 'derivation-plan', label: 'Derivation plan' },
  { value: 'execution', label: 'Execution' },
  { value: 'define', label: 'Define' },
  { value: 'csdrg', label: 'cSDRG' },
  { value: 'validation', label: 'Validation' },
  { value: 'compile', label: 'Compile & artifacts' },
  { value: 'dependencies', label: 'Dependencies' },
] as const

const DEFAULT_TAB = SDTM_TABS[0].value
const TAB_VALUES = SDTM_TABS.map((tab) => tab.value)

export const Route = createFileRoute('/_app/sdtm/$sdtmId')({
  // Narrow the `?tab=` search param to a known tab value so a refresh or a
  // deep link always resolves to a real section; unknown/missing falls back to
  // the first tab (TanStack Router validateSearch). `?domain=` deep-links the
  // Derivation plan tab to one per-domain plan and is kept as an opaque string
  // (the available domains are resolved from the plan head list at render).
  validateSearch: (
    search: Record<string, unknown>,
  ): { tab: string; domain?: string } => {
    const tab =
      typeof search.tab === 'string' && TAB_VALUES.includes(search.tab)
        ? search.tab
        : DEFAULT_TAB
    const domain =
      typeof search.domain === 'string' && search.domain.length > 0
        ? search.domain
        : undefined
    return { tab, domain }
  },
  component: SdtmDetailPage,
})

/**
 * Placeholder panel body. Replaced by the real panels in tasks 11-17; for now
 * it confirms the tab is individually reachable via `?tab=`.
 */
function TabPlaceholder({ label }: { label: string }) {
  return (
    <EmptyState
      title={label}
      description="This panel will be implemented in a later task."
    />
  )
}

/**
 * Derivation plan tab body. SDTM derivation plans are one-per-domain, so this
 * wrapper resolves the available domains from the plan head list
 * (`GET /sdtms/{sdtm_id}/derivation-plans`), lets the user pick which domain's
 * plan to edit, and mounts {@link DerivationPlanPanel} scoped to that domain.
 *
 * The selected domain is driven by the `?domain=` search param (so refresh and
 * deep links are stable, exactly like `?tab=`); it defaults to the first plan
 * head. When the workbench has no plan heads yet, a guidance empty state is
 * shown instead of the editor.
 */
function DerivationPlanTab({
  sdtmId,
  domain,
  onDomainChange,
}: {
  sdtmId: string
  domain: string | undefined
  onDomainChange: (domain: string) => void
}) {
  const query = useListSdtmPlans(sdtmId)
  const heads = React.useMemo(() => query.data?.items ?? [], [query.data])

  // Resolve the active domain: the `?domain=` value when it names a known plan
  // head, otherwise the first head. Kept as a derived value so a stale deep
  // link falls back gracefully.
  const domains = React.useMemo(() => heads.map((head) => head.domain), [heads])
  const activeDomain =
    domain !== undefined && domains.includes(domain) ? domain : domains[0]

  if (query.isLoading) {
    return (
      <div className="flex flex-col gap-4">
        <Skeleton className="h-9 w-64" />
        <Skeleton className="h-[32rem] w-full" />
      </div>
    )
  }

  if (query.isError) {
    return <ErrorState error={query.error} resourceLabel="SDTM derivation plans" />
  }

  if (domains.length === 0 || activeDomain === undefined) {
    return (
      <EmptyState
        title="No derivation plan yet"
        description="This SDTM workbench has no per-domain derivation plans. Save a current Specification and Input Selection, then author a domain plan here."
      />
    )
  }

  return (
    <div className="flex flex-col gap-4">
      <div className="flex items-center gap-2">
        <Label htmlFor="derivation-plan-domain" className="text-sm font-medium">
          Domain
        </Label>
        <Select value={activeDomain} onValueChange={onDomainChange}>
          <SelectTrigger
            id="derivation-plan-domain"
            size="sm"
            className="w-48"
            aria-label="Derivation plan domain"
          >
            <SelectValue />
          </SelectTrigger>
          <SelectContent>
            {heads.map((head) => (
              <SelectItem key={head.id} value={head.domain}>
                {head.domain}
              </SelectItem>
            ))}
          </SelectContent>
        </Select>
      </div>

      {/*
        Remount the panel when the domain changes so its per-domain plan query,
        local canvas state, and per-plan ETag reset cleanly for the new domain.
      */}
      <DerivationPlanPanel
        key={activeDomain}
        sdtmId={sdtmId}
        domainCode={activeDomain}
      />
    </div>
  )
}

function SdtmDetailPage() {
  const { sdtmId } = Route.useParams()
  const { tab, domain } = Route.useSearch()
  const navigate = useNavigate()
  const { currentStudyId } = useCurrentStudy()

  // The caller owns the aggregate query and gates it on study scope so no
  // request is issued when no study is selected (Requirements 9.3, 9.4). The
  // shell renders the "no study selected" empty state in that case.
  const query = useGetSdtmAggregate(sdtmId, {
    query: { enabled: !!currentStudyId },
  })

  const tabs: WorkbenchTab[] = SDTM_TABS.map((entry) => ({
    value: entry.value,
    label: entry.label,
    render: () => {
      // The panels read the aggregate ETag from the shell's workbench context
      // for their conditional writes; they are only rendered inside the shell.
      if (entry.value === 'input-selection') {
        return <InputSelectionPanel />
      }
      if (entry.value === 'specification') {
        // View/save/import/export/variable-ordering + the 412 reload path
        // (Requirement 11).
        return <SpecificationPanel sdtmId={sdtmId} />
      }
      if (entry.value === 'derivation-plan') {
        // Plans are per-domain: pick the domain (from the plan head list and a
        // `?domain=` deep link), then render the editor + save/alignment-gating/
        // conflict handling for that domain (Requirement 12.1-12.4).
        return (
          <DerivationPlanTab
            sdtmId={sdtmId}
            domain={domain}
            onDomainChange={(next) =>
              navigate({
                to: '/sdtm/$sdtmId',
                params: { sdtmId },
                search: { tab: 'derivation-plan', domain: next },
                replace: true,
              })
            }
          />
        )
      }
      if (entry.value === 'validation') {
        // 202 + poll the returned validation-run to terminal (passed/failed),
        // render status + per-severity counts + full IssueList + validator
        // name/version; problem+json surfaces title/detail + issues[]
        // (Requirement 14).
        return <SdtmValidationPanel sdtmId={sdtmId} />
      }
      if (entry.value === 'acrf') {
        // aCRF annotations/links/coverage/build: create with the aggregate
        // ETag + client rect-bounds validation; edit/delete/link with the
        // per-annotation ETag; link building via dnd-kit drag with an explicit
        // add-link fallback; coverage's four count/list groups; a 2s/300s build
        // poll naming the build with no artifact on failure/timeout
        // (Requirement 17).
        return <AcrfPanel sdtmId={sdtmId} />
      }
      if (entry.value === 'define') {
        // Define lifecycle: view/initialize/save/validate/render/reconcile/
        // build with the aggregate ETag; validate returns a synchronous
        // Validation_Run; render is a non-persisting XML preview; reconcile and
        // build poll at 2s to terminal/300s; a 409 staleness response refreshes
        // the current Define model before retry (Requirement 18).
        return <DefinePanel sdtmId={sdtmId} />
      }
      if (entry.value === 'csdrg') {
        // cSDRG lifecycle: view/initialize/save/validate/build with the
        // aggregate ETag; the nine required narrative sections (CSDRG_SECTIONS)
        // are editable text fields preserving user content without inference;
        // validate treats any absent/whitespace-only required section as an
        // error; the build polls at 2s to terminal/300s naming the build with
        // no artifact on failure/timeout (Requirement 19).
        return <CsdrgPanel sdtmId={sdtmId} />
      }
      if (entry.value === 'compile') {
        // Compile the aligned plan into a python/r/sas program and build extra
        // metadata/report artifact types; poll each build to terminal via
        // OperationRunner, listing produced artifacts on success and the typed
        // failure (no partial artifacts) on failure; a 409
        // backend_capability_missing on compile is surfaced inline
        // (Requirement 15).
        return <CompilePanel sdtmId={sdtmId} />
      }
      if (entry.value === 'execution') {
        // Author the full pinned execution body (language, program artifact id,
        // input artifact ids, validation-run id, pinned input-selection/
        // specification/plan revisions, compiler fingerprint, expected input
        // fingerprint, accepted limits), submit via useExecuteSdtm with an
        // Idempotency-Key, poll the returned execution run to terminal, and
        // render status/timing/metrics + logs + outputs; runner_not_configured
        // keeps the generated program available while any other failure shows
        // the typed failure plus captured logs (Requirement 16).
        return <ExecutionPanel sdtmId={sdtmId} />
      }
      if (entry.value === 'dependencies') {
        // Mirror the Raw dependencies pattern: view the exact selection with
        // revision/state, replace via PUT with the aggregate ETag, render 422
        // incompatibilities (message + suggestion), reload on 412 before retry,
        // and disable the start-operation (save) control while a
        // dependency_refresh_required state is pending (Requirement 20).
        return <SdtmDependenciesPanel sdtmId={sdtmId} />
      }
      return <TabPlaceholder label={entry.label} />
    },
  }))

  return (
    <div className="flex flex-col gap-6">
      <Button asChild variant="ghost" className="w-fit">
        <Link to="/sdtm">Back to SDTM workbenches</Link>
      </Button>

      <WorkbenchDetailShell
        query={query}
        resourceLabel="SDTM workbench"
        tabs={tabs}
        activeTab={tab}
        defaultTab={DEFAULT_TAB}
        onTabChange={(value) =>
          // Persist the active tab to `?tab=` (replace so tab switches do not
          // stack history). The aggregate ETag from the shell context remains
          // the single concurrency source for every child conditional write.
          navigate({
            to: '/sdtm/$sdtmId',
            params: { sdtmId },
            // Preserve the chosen `?domain=` across tab switches so returning to
            // the Derivation plan tab lands back on the same per-domain plan.
            search: { tab: value, domain },
            replace: true,
          })
        }
      />
    </div>
  )
}
