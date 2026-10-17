import * as React from 'react'
import {
  DndContext,
  KeyboardSensor,
  PointerSensor,
  useDraggable,
  useDroppable,
  useSensor,
  useSensors,
  type DragEndEvent,
} from '@dnd-kit/core'
import { CSS } from '@dnd-kit/utilities'
import { cn } from '@/lib/utils'

/**
 * Context for source-to-target transfer DnD (e.g. assigning datasets to a
 * Domain Mapping or qualified source variables to Variable Mapping cells).
 *
 * The pointer drag and the explicit "add link"/select fallback both call
 * {@link TransferContextProps.onTransfer} with the same `{ sourceId, targetId }`
 * pair, so a dropped link and a clicked link issue the identical typed request.
 */
export interface TransferContextProps {
  /**
   * Called when a source is transferred onto a target, by pointer drop, keyboard
   * drop, or the explicit non-pointer control. Consumers map the id pair to a
   * typed command (never a free-text payload).
   */
  onTransfer: (link: { sourceId: string; targetId: string }) => void
  children: React.ReactNode
}

export function TransferContext({ onTransfer, children }: TransferContextProps) {
  const sensors = useSensors(
    useSensor(PointerSensor),
    useSensor(KeyboardSensor),
  )

  function handleDragEnd(event: DragEndEvent) {
    const { active, over } = event
    if (!over) return
    onTransfer({ sourceId: String(active.id), targetId: String(over.id) })
  }

  return (
    <DndContext sensors={sensors} onDragEnd={handleDragEnd}>
      {children}
    </DndContext>
  )
}

export interface DraggableItemProps {
  /** Stable id of the source; becomes `sourceId` in the transfer callback. */
  id: string
  disabled?: boolean
  ariaLabel?: string
  className?: string
  children: React.ReactNode
}

/**
 * A draggable source chip usable with pointer or keyboard (dnd-kit keyboard
 * sensor). Must be rendered inside a {@link TransferContext}. The accessible
 * non-pointer fallback for completing a transfer is provided by the consumer
 * (an explicit "add link"/select control that calls the same `onTransfer`).
 */
export function DraggableItem({
  id,
  disabled = false,
  ariaLabel,
  className,
  children,
}: DraggableItemProps) {
  const { attributes, listeners, setNodeRef, transform, isDragging } =
    useDraggable({ id, disabled })

  const style: React.CSSProperties = {
    transform: CSS.Translate.toString(transform),
  }

  return (
    <button
      type="button"
      ref={setNodeRef}
      style={style}
      disabled={disabled}
      aria-label={ariaLabel}
      data-dragging={isDragging || undefined}
      className={cn(
        'bg-background inline-flex cursor-grab touch-none items-center gap-2 rounded-md border px-2 py-1 text-sm outline-none',
        'focus-visible:border-ring focus-visible:ring-ring/50 focus-visible:ring-[3px]',
        isDragging && 'ring-ring/50 relative z-10 ring-2',
        disabled && 'cursor-not-allowed opacity-50',
        className,
      )}
      {...attributes}
      {...listeners}
    >
      {children}
    </button>
  )
}

export interface DropTargetProps {
  /** Stable id of the target; becomes `targetId` in the transfer callback. */
  id: string
  disabled?: boolean
  ariaLabel?: string
  className?: string
  children: React.ReactNode
}

/**
 * A drop target that accepts a {@link DraggableItem}. Must be rendered inside a
 * {@link TransferContext}. Highlights while a draggable hovers over it.
 */
export function DropTarget({
  id,
  disabled = false,
  ariaLabel,
  className,
  children,
}: DropTargetProps) {
  const { setNodeRef, isOver } = useDroppable({ id, disabled })

  return (
    <div
      ref={setNodeRef}
      aria-label={ariaLabel}
      data-over={isOver || undefined}
      className={cn(
        'rounded-md border border-dashed px-3 py-2 transition-colors',
        isOver && 'border-ring bg-accent/60',
        disabled && 'opacity-50',
        className,
      )}
    >
      {children}
    </div>
  )
}
