import { createContext, useContext } from 'react'
import type { AggregateResponse } from '@/api/generated/model'
import { ifMatchRequest } from '@/lib/requests'

/**
 * Value exposed to every child panel of a {@link WorkbenchDetailShell}.
 *
 * The whole point of this context is to make the *current* aggregate revision
 * the single source of the optimistic-concurrency token (Requirement 21.1):
 * every conditional write (`PATCH`/`PUT`) a tab panel issues must carry
 * `If-Match: "revision-{N}"` for the revision the shell last loaded, so a
 * refetch after any mutation automatically flows the new token to the panels.
 */
export interface WorkbenchContextValue {
  /** The loaded aggregate (identity envelope: id/study/code/name/status/revision). */
  aggregate: AggregateResponse
  /** The current aggregate revision — the concurrency token source. */
  revision: number
  /** The study the aggregate belongs to (always equals the selected study). */
  studyId: string
  /**
   * Per-call axios config carrying `If-Match: "revision-{N}"` for the current
   * aggregate revision. Pass this as the `request` option of any conditional
   * write hook so the write uses the token the shell currently holds.
   */
  ifMatch: () => ReturnType<typeof ifMatchRequest>
}

const WorkbenchContext = createContext<WorkbenchContextValue | undefined>(
  undefined,
)

export const WorkbenchContextProvider = WorkbenchContext.Provider

/**
 * Read the enclosing workbench aggregate context. Throws if used outside a
 * {@link WorkbenchDetailShell}, so a panel can rely on a loaded aggregate and
 * a live concurrency token.
 */
// eslint-disable-next-line react-refresh/only-export-components
export function useWorkbench(): WorkbenchContextValue {
  const context = useContext(WorkbenchContext)
  if (context === undefined) {
    throw new Error('useWorkbench must be used within a WorkbenchDetailShell')
  }
  return context
}
