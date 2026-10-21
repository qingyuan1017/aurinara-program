import * as React from 'react'
import type { AxiosError } from 'axios'
import { DetailHeader } from '@/components/data/detail-header'
import { EmptyState, ErrorState } from '@/components/data/states'
import { StatusBadge } from '@/components/data/status-badge'
import { Skeleton } from '@/components/ui/skeleton'
import { Tabs, TabsContent, TabsList, TabsTrigger } from '@/components/ui/tabs'
import { useCurrentStudy } from '@/components/study-context'
import { ifMatchRequest } from '@/lib/requests'
import type { AggregateResponse } from '@/api/generated/model'
import {
  WorkbenchContextProvider,
  type WorkbenchContextValue,
} from '@/components/workbench/workbench-context'

/** A single tab in the workbench shell. */
export interface WorkbenchTab {
  /** Stable value used for the `Tabs` state and the `?tab=` search param. */
  value: string
  /** Human-readable tab label. */
  label: string
  /**
   * Tab body. Receives the live workbench context so panels can read the
   * current aggregate/revision without a separate `useWorkbench()` call,
   * though `useWorkbench()` is also available anywhere inside the shell.
   */
  render: (ctx: WorkbenchContextValue) => React.ReactNode
}

/**
 * The subset of an Orval "get aggregate" query result the shell consumes. Both
 * `useGetRawAggregate` and `useGetSdtmAggregate` satisfy this shape.
 */
export interface AggregateQueryResult {
  data: AggregateResponse | undefined
  isLoading: boolean
  isError: boolean
  error: AxiosError | null
}

export interface WorkbenchDetailShellProps {
  /**
   * The aggregate query result. The CALLER owns the hook and MUST gate it on
   * `{ query: { enabled: !!currentStudyId } }` so no request is issued when no
   * study is selected (Requirements 9.3, 9.4). The shell independently renders
   * the "no study selected" empty state in that case.
   */
  query: AggregateQueryResult
  /** Resource label for loading/error copy, e.g. "raw workbench". */
  resourceLabel: string
  /** Extra fields appended to the standard code/name/status/revision header. */
  extraHeaderFields?: { label: string; value: React.ReactNode }[]
  /** The tabs to render. */
  tabs: WorkbenchTab[]
  /** Controlled active tab value (e.g. bound to a `?tab=` search param). */
  activeTab?: string
  /** Called when the active tab changes (persist to `?tab=`). */
  onTabChange?: (value: string) => void
  /** Default tab value when uncontrolled. Defaults to the first tab. */
  defaultTab?: string
}

/**
 * Shared tabbed detail scaffold for the Raw and SDTM workbench aggregates.
 *
 * Responsibilities:
 * - Gate on the selected study: render the shared {@link EmptyState} and issue
 *   NO request when no study is selected (the caller's query is disabled);
 *   Requirements 9.3, 9.4.
 * - Guard study isolation: once loaded, verify the aggregate's `study_id`
 *   matches the selected study and refuse to render a cross-study aggregate.
 * - Render the {@link DetailHeader} (code, name, status, revision) and the
 *   shadcn {@link Tabs}.
 * - Expose the aggregate `revision`/ETag to child panels via
 *   {@link WorkbenchContextProvider} so every conditional write uses the
 *   current token (Requirement 21.1).
 */
export function WorkbenchDetailShell({
  query,
  resourceLabel,
  extraHeaderFields,
  tabs,
  activeTab,
  onTabChange,
  defaultTab,
}: WorkbenchDetailShellProps) {
  const { currentStudyId, isLoading: studiesLoading } = useCurrentStudy()
  const { data: aggregate, isLoading, isError, error } = query

  // No study selected: show the shared empty state and issue no request. The
  // caller's query is gated on `enabled: !!currentStudyId`, so this branch is
  // purely presentational — nothing is fetched.
  if (!currentStudyId) {
    if (studiesLoading) {
      return <Skeleton className="h-40 w-full" />
    }
    return (
      <EmptyState
        title="No study selected"
        description="Select a study to open this workbench."
      />
    )
  }

  if (isError) {
    return <ErrorState error={error} resourceLabel={resourceLabel} />
  }

  if (isLoading || !aggregate) {
    return (
      <div className="flex flex-col gap-6">
        <Skeleton className="h-28 w-full" />
        <Skeleton className="h-9 w-80" />
        <Skeleton className="h-64 w-full" />
      </div>
    )
  }

  // Study-isolation guard: never render an aggregate that belongs to a
  // different study than the one currently selected.
  if (aggregate.study_id !== currentStudyId) {
    return (
      <EmptyState
        title="Not available in this study"
        description="This workbench belongs to a different study than the one selected."
      />
    )
  }

  const ctx: WorkbenchContextValue = {
    aggregate,
    revision: aggregate.revision,
    studyId: aggregate.study_id,
    ifMatch: () => ifMatchRequest(aggregate.revision),
  }

  const resolvedDefaultTab = defaultTab ?? tabs[0]?.value

  return (
    <WorkbenchContextProvider value={ctx}>
      <div className="flex flex-col gap-6">
        <DetailHeader
          fields={[
            { label: 'Code', value: aggregate.code },
            { label: 'Name', value: aggregate.name },
            {
              label: 'Status',
              value: <StatusBadge status={aggregate.status} />,
            },
            { label: 'Revision', value: aggregate.revision },
            ...(extraHeaderFields ?? []),
          ]}
        />

        <Tabs
          value={activeTab}
          defaultValue={activeTab === undefined ? resolvedDefaultTab : undefined}
          onValueChange={onTabChange}
        >
          <TabsList>
            {tabs.map((tab) => (
              <TabsTrigger key={tab.value} value={tab.value}>
                {tab.label}
              </TabsTrigger>
            ))}
          </TabsList>
          {tabs.map((tab) => (
            <TabsContent key={tab.value} value={tab.value}>
              {tab.render(ctx)}
            </TabsContent>
          ))}
        </Tabs>
      </div>
    </WorkbenchContextProvider>
  )
}
