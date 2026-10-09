import { AlertTriangle } from 'lucide-react'
import { cn } from '@/lib/utils'

/**
 * Dependency- and input-selection staleness states surfaced by the backend on a
 * Raw/SDTM aggregate (Requirement 10.5, 20.5). When any of these holds, the
 * operations the banner guards (validation, build, execution, reconciliation,
 * dependent SDTM work) are blocked until the user refreshes the selection.
 */
export type StalenessState =
  | 'dependency_refresh_required'
  | 'input_refresh_required'

const STALENESS_COPY: Record<StalenessState, { title: string; detail: string }> =
  {
    dependency_refresh_required: {
      title: 'Dependency selection needs a refresh',
      detail:
        'A standards, terminology, reference, or template revision this workbench depends on has been superseded. New validation, build, execution, and reconciliation operations are blocked until the dependency selection is refreshed.',
    },
    input_refresh_required: {
      title: 'Input selection needs a refresh',
      detail:
        'The pinned Raw inputs are no longer current, so dependent SDTM work is stale. Refresh the input selection before starting dependent operations.',
    },
  }

/**
 * Returns true when the given state blocks guarded operations. Callers derive
 * the disabled state of their operation controls from the same predicate they
 * pass to {@link StalenessBanner}, so the notice and the disabled controls can
 * never drift apart.
 */
export function isStale(state: StalenessState | null | undefined): boolean {
  return state === 'dependency_refresh_required' || state === 'input_refresh_required'
}

export interface StalenessBannerProps {
  /**
   * The current staleness state. The banner renders a persistent notice while
   * this is a blocking state and renders nothing otherwise, so it is safe to
   * mount unconditionally.
   */
  state: StalenessState | null | undefined
  /** Optional reload action re-fetching the current revision. */
  onReload?: () => void
  /** Label for the reload action. */
  reloadLabel?: string
  className?: string
}

/**
 * Persistent notice for `dependency_refresh_required` / `input_refresh_required`.
 * Parent panels gate their operation controls on {@link isStale} using the same
 * `state` value passed here.
 */
export function StalenessBanner({
  state,
  onReload,
  reloadLabel = 'Reload current revision',
  className,
}: StalenessBannerProps) {
  if (!isStale(state)) return null
  const copy = STALENESS_COPY[state as StalenessState]
  return (
    <div
      role="alert"
      data-slot="staleness-banner"
      data-state={state ?? undefined}
      className={cn(
        'border-destructive/50 text-destructive flex items-start gap-3 rounded-md border px-4 py-3 text-sm',
        className,
      )}
    >
      <AlertTriangle className="mt-0.5 size-4 shrink-0" aria-hidden />
      <div className="flex flex-col gap-1">
        <span className="font-medium">{copy.title}</span>
        <span className="text-destructive/90">{copy.detail}</span>
        {onReload && (
          <button
            type="button"
            onClick={onReload}
            className="text-destructive mt-1 w-fit text-sm font-medium underline underline-offset-2"
          >
            {reloadLabel}
          </button>
        )}
      </div>
    </div>
  )
}
