import type { QueryClient } from '@tanstack/react-query'

import {
  getGetRawAggregateQueryKey,
  getGetRawDependenciesQueryKey,
  getGetDatasetQueryKey,
  getGetVariableQueryKey,
  getListDatasetsQueryKey,
  getListRawAggregatesQueryKey,
  getListVariablesQueryKey,
} from '@/api/generated/raw/raw'
import {
  getGetSdtmAggregateQueryKey,
  getGetSdtmDependenciesQueryKey,
  getGetInputSelectionQueryKey,
  getGetRawContextQueryKey,
  getGetSpecificationQueryKey,
  getGetPlanQueryKey,
  getGetLineageQueryKey,
} from '@/api/generated/sdtm/sdtm'
import { getGetDefineQueryKey } from '@/api/generated/sdtm-define/sdtm-define'
import { getGetCsdrgQueryKey } from '@/api/generated/sdtm-csdrg/sdtm-csdrg'
import {
  getGetCoverageQueryKey,
  getListAnnotationsQueryKey,
} from '@/api/generated/sdtm-acrf/sdtm-acrf'
import { getListArtifactsQueryKey } from '@/api/generated/artifacts/artifacts'

/**
 * Grouped per-aggregate query-key invalidation (Requirement 21.6).
 *
 * Each mutation `onSuccess` calls one of these helpers so the affected
 * aggregate key and its dependent collection keys are invalidated together,
 * instead of every screen repeating the exact key lists.
 *
 * All generated list-key helpers return `[path, ...params]`; invoking them
 * WITHOUT their params yields the bare `[path]` prefix. TanStack Query matches
 * query keys by prefix on `invalidateQueries`, so a bare-path key invalidates
 * every paginated/filtered variant of that collection.
 */

/** Invalidate a set of query keys through one QueryClient. */
function invalidateKeys(qc: QueryClient, keys: readonly (readonly unknown[])[]): void {
  for (const queryKey of keys) {
    void qc.invalidateQueries({ queryKey })
  }
}

// ---------------------------------------------------------------------------
// Raw
// ---------------------------------------------------------------------------

/**
 * Raw workbench aggregate edit (name/status PATCH): reload the aggregate detail
 * and the study-scoped aggregate list whose revision/status column changed.
 */
export function invalidateRawAggregate(
  qc: QueryClient,
  rawId: string,
  studyId?: string,
): void {
  invalidateKeys(qc, [
    getGetRawAggregateQueryKey(rawId),
    getListRawAggregatesQueryKey(studyId),
  ])
}

/**
 * Raw dataset create / rebind / retire: reload the aggregate's dataset
 * collection (and the specific dataset detail when a dataset id is known).
 */
export function invalidateRawDataset(
  qc: QueryClient,
  rawId: string,
  datasetId?: string,
): void {
  const keys: (readonly unknown[])[] = [getListDatasetsQueryKey(rawId)]
  if (datasetId) keys.push(getGetDatasetQueryKey(datasetId))
  invalidateKeys(qc, keys)
}

/**
 * Raw variable create / patch / delete / reorder / initialize: reload the
 * dataset's variable collection, the owning dataset detail (its revision/ETag
 * is bumped by variable writes and initialize), and the specific variable
 * detail when a variable id is known.
 */
export function invalidateRawVariable(
  qc: QueryClient,
  datasetId: string,
  variableId?: string,
): void {
  const keys: (readonly unknown[])[] = [
    getListVariablesQueryKey(datasetId),
    getGetDatasetQueryKey(datasetId),
  ]
  if (variableId) keys.push(getGetVariableQueryKey(variableId))
  invalidateKeys(qc, keys)
}

/**
 * Raw dependency replacement: reload the dependencies selection and the
 * aggregate detail (its revision/ETag changes with the selection).
 */
export function invalidateRawDependencies(qc: QueryClient, rawId: string): void {
  invalidateKeys(qc, [
    getGetRawDependenciesQueryKey(rawId),
    getGetRawAggregateQueryKey(rawId),
  ])
}

/**
 * Completed Raw `202` operation (reconcile / artifact build): reload the
 * study-scoped artifact collection so newly produced artifacts appear, plus the
 * aggregate detail whose latest-run state is reflected.
 */
export function invalidateRawOperationArtifacts(
  qc: QueryClient,
  rawId: string,
  studyId?: string,
): void {
  invalidateKeys(qc, [
    getListArtifactsQueryKey(studyId),
    getGetRawAggregateQueryKey(rawId),
  ])
}

// ---------------------------------------------------------------------------
// SDTM
// ---------------------------------------------------------------------------

/** The SDTM sub-resource whose write triggered the invalidation. */
export type SdtmSubResource =
  | 'input-selection'
  | 'specification'
  | 'derivation-plan'
  | 'define'
  | 'csdrg'
  | 'acrf'

function sdtmSubResourceKeys(
  subResource: SdtmSubResource,
  sdtmId: string,
  domainCode?: string,
): (readonly unknown[])[] {
  switch (subResource) {
    case 'input-selection':
      return [getGetInputSelectionQueryKey(sdtmId)]
    case 'specification':
      return [getGetSpecificationQueryKey(sdtmId)]
    case 'derivation-plan':
      // The derivation plan is per-domain. Invalidate the exact per-domain plan
      // key when a domain is known; otherwise fall back to the bare path prefix
      // (which TanStack Query matches against every per-domain variant).
      return [
        domainCode === undefined
          ? getGetPlanQueryKey(sdtmId)
          : getGetPlanQueryKey(sdtmId, domainCode),
      ]
    case 'define':
      return [getGetDefineQueryKey(sdtmId)]
    case 'csdrg':
      return [getGetCsdrgQueryKey(sdtmId)]
    case 'acrf':
      return [getListAnnotationsQueryKey(sdtmId), getGetCoverageQueryKey(sdtmId)]
  }
}

/**
 * SDTM authoring write (input-selection / specification / derivation-plan /
 * define / csdrg / aCRF): invalidate the specific sub-resource key AND the
 * aggregate detail (its revision/ETag is bumped server-side). When the write
 * changes inputs (input-selection), also reload the lineage and raw-context so
 * stale/alignment state reloads.
 *
 * @param withInputContext - force lineage/raw-context invalidation (defaults to
 *   true for `input-selection`, false otherwise). A derivation-plan save may set
 *   this when its graph changes lineage-affecting structure.
 * @param domainCode - for the per-domain `derivation-plan` sub-resource, the
 *   domain whose plan key should be invalidated. Omitted for every other
 *   sub-resource.
 */
export function invalidateSdtmSubResource(
  qc: QueryClient,
  subResource: SdtmSubResource,
  sdtmId: string,
  withInputContext: boolean = subResource === 'input-selection',
  domainCode?: string,
): void {
  const keys: (readonly unknown[])[] = [
    ...sdtmSubResourceKeys(subResource, sdtmId, domainCode),
    getGetSdtmAggregateQueryKey(sdtmId),
  ]
  if (withInputContext) {
    keys.push(getGetLineageQueryKey(sdtmId), getGetRawContextQueryKey(sdtmId))
  }
  invalidateKeys(qc, keys)
}

/**
 * SDTM dependency replacement: reload the dependencies selection and the
 * aggregate detail (its revision/ETag changes with the selection).
 */
export function invalidateSdtmDependencies(qc: QueryClient, sdtmId: string): void {
  invalidateKeys(qc, [
    getGetSdtmDependenciesQueryKey(sdtmId),
    getGetSdtmAggregateQueryKey(sdtmId),
  ])
}

/**
 * Completed SDTM `202` operation (validate / compile / execute / reconcile /
 * build): reload the study-scoped artifact collection so new program/report
 * artifacts appear, plus the aggregate detail whose latest-run state changed.
 */
export function invalidateSdtmOperationArtifacts(
  qc: QueryClient,
  sdtmId: string,
  studyId?: string,
): void {
  invalidateKeys(qc, [
    getListArtifactsQueryKey(studyId),
    getGetSdtmAggregateQueryKey(sdtmId),
  ])
}
