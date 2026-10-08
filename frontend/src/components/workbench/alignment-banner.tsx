import { AlertTriangle } from 'lucide-react'
import { cn } from '@/lib/utils'

/**
 * Server-computed alignment of a Derivation Plan against its pinned Specification
 * and Input Selection revisions (Requirement 12.4).
 */
export type AlignmentState = 'aligned' | 'misaligned'

/**
 * Returns true when the plan is misaligned and therefore read-only. Callers
 * derive the disabled state of validate/preview/compile/execute (and the plan
 * editor's write controls) from the same predicate they pass to
 * {@link AlignmentBanner}, so the notice and the disabled controls stay in sync.
 */
export function isMisaligned(
  state: AlignmentState | null | undefined,
): boolean {
  return state === 'misaligned'
}

export interface AlignmentBannerProps {
  /**
   * The current Alignment_State. The banner renders a persistent notice while
   * the plan is `misaligned` and renders nothing otherwise, so it is safe to
   * mount unconditionally.
   */
  state: AlignmentState | null | undefined
  className?: string
}

/**
 * Persistent misalignment notice for a Derivation Plan. While shown, the plan is
 * read-only and validate/preview/compile/execute are disabled; parent panels
 * gate those controls on {@link isMisaligned} using the same `state` value.
 */
export function AlignmentBanner({ state, className }: AlignmentBannerProps) {
  if (!isMisaligned(state)) return null
  return (
    <div
      role="alert"
      data-slot="alignment-banner"
      data-state={state ?? undefined}
      className={cn(
        'border-destructive/50 text-destructive flex items-start gap-3 rounded-md border px-4 py-3 text-sm',
        className,
      )}
    >
      <AlertTriangle className="mt-0.5 size-4 shrink-0" aria-hidden />
      <div className="flex flex-col gap-1">
        <span className="font-medium">Derivation plan is misaligned</span>
        <span className="text-destructive/90">
          The plan&apos;s pinned specification or input-selection revision no
          longer matches current inputs. The plan is read-only, and validation,
          preview, compilation, and execution are disabled until an updated plan
          revision restores alignment.
        </span>
      </div>
    </div>
  )
}
