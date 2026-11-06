import { AlertTriangle } from 'lucide-react'
import {
  type AlignmentState,
  isMisaligned,
} from '@/components/workbench/alignment-state'
import { cn } from '@/lib/utils'

export interface AlignmentBannerProps {
  /**
   * The current Alignment_State. The banner renders a persistent notice while
   * the plan is `misaligned` and renders nothing otherwise, so it is safe to
   * mount unconditionally.
   */
  state: AlignmentState | null | undefined
  reasons?: readonly string[]
  draftActive?: boolean
  className?: string
}

/**
 * Persistent misalignment notice for a Derivation Plan. Parent panels keep
 * validate/preview/compile/execute gated on the saved plan state even while an
 * editable alignment draft is open.
 */
export function AlignmentBanner({
  state,
  reasons = [],
  draftActive = false,
  className,
}: AlignmentBannerProps) {
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
          {draftActive
            ? 'An editable alignment draft is open. Validation, preview, compilation, and execution remain disabled until the reviewed draft is saved as a new aligned revision.'
            : 'The saved plan no longer matches its current dependencies. Start an alignment revision to review and update a copy; the saved revision remains immutable.'}
        </span>
        {reasons.length > 0 && (
          <span className="text-xs text-destructive/90">
            Reason{reasons.length === 1 ? '' : 's'}:{' '}
            {reasons.map(alignmentReasonLabel).join(', ')}
          </span>
        )}
      </div>
    </div>
  )
}

function alignmentReasonLabel(reason: string): string {
  switch (reason) {
    case 'specification_changed':
      return 'Specification changed'
    case 'input_changed':
      return 'Raw input selection changed'
    case 'upstream_plan_changed':
      return 'upstream SDTM plan changed'
    default:
      return reason.replaceAll('_', ' ')
  }
}
