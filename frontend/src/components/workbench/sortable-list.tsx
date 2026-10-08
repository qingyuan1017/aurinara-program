import * as React from 'react'
import {
  DndContext,
  KeyboardSensor,
  PointerSensor,
  closestCenter,
  useSensor,
  useSensors,
  type DragEndEvent,
} from '@dnd-kit/core'
import {
  SortableContext,
  arrayMove,
  sortableKeyboardCoordinates,
  useSortable,
  verticalListSortingStrategy,
} from '@dnd-kit/sortable'
import { CSS } from '@dnd-kit/utilities'
import { ChevronDown, ChevronUp, GripVertical } from 'lucide-react'
import { Button } from '@/components/ui/button'
import { Input } from '@/components/ui/input'
import { cn } from '@/lib/utils'

export interface SortableListProps<T> {
  /** Items in their current order. */
  items: readonly T[]
  /** Stable string id for an item (must be unique within the list). */
  getId: (item: T) => string
  /**
   * Called whenever the order changes, by pointer drag, keyboard drag, the
   * move-up/down buttons, or the numeric ordinal field. Receives the fully
   * reordered item array plus the single moved item and its 0-based indices, so
   * the consumer can issue the same typed persistence request regardless of
   * which affordance produced the move.
   */
  onReorder: (
    nextItems: T[],
    moved: { item: T; fromIndex: number; toIndex: number },
  ) => void
  /** Render the item body (drag handle and ordinal controls are added around it). */
  renderItem: (item: T, index: number) => React.ReactNode
  disabled?: boolean
  /** Accessible label for the list region. */
  ariaLabel?: string
  className?: string
}

/**
 * Thin dnd-kit wrapper that gives a list a consistent, accessible reorder shape.
 *
 * Pointer and keyboard sensors are both enabled (arrow keys + space/enter via
 * dnd-kit's keyboard sensor), and every row additionally exposes move-up /
 * move-down buttons and a numeric ordinal input as explicit non-pointer
 * fallbacks. All paths funnel through {@link SortableListProps.onReorder} with
 * the same reordered array, so a drag and its fallback produce an identical
 * typed request. No free-text code path is introduced.
 */
export function SortableList<T>({
  items,
  getId,
  onReorder,
  renderItem,
  disabled = false,
  ariaLabel = 'Sortable list',
  className,
}: SortableListProps<T>) {
  const sensors = useSensors(
    useSensor(PointerSensor),
    useSensor(KeyboardSensor, {
      coordinateGetter: sortableKeyboardCoordinates,
    }),
  )

  const ids = React.useMemo(() => items.map(getId), [items, getId])

  const move = React.useCallback(
    (fromIndex: number, toIndex: number) => {
      if (
        fromIndex === toIndex ||
        fromIndex < 0 ||
        toIndex < 0 ||
        fromIndex >= items.length ||
        toIndex >= items.length
      ) {
        return
      }
      const next = arrayMove([...items], fromIndex, toIndex)
      onReorder(next, { item: items[fromIndex], fromIndex, toIndex })
    },
    [items, onReorder],
  )

  function handleDragEnd(event: DragEndEvent) {
    const { active, over } = event
    if (!over || active.id === over.id) return
    const fromIndex = ids.indexOf(String(active.id))
    const toIndex = ids.indexOf(String(over.id))
    move(fromIndex, toIndex)
  }

  return (
    <DndContext
      sensors={sensors}
      collisionDetection={closestCenter}
      onDragEnd={handleDragEnd}
    >
      <SortableContext items={ids} strategy={verticalListSortingStrategy}>
        <ol
          aria-label={ariaLabel}
          className={cn('flex list-none flex-col gap-1', className)}
        >
          {items.map((item, index) => (
            <SortableRow
              key={getId(item)}
              id={getId(item)}
              index={index}
              count={items.length}
              disabled={disabled}
              onMove={move}
            >
              {renderItem(item, index)}
            </SortableRow>
          ))}
        </ol>
      </SortableContext>
    </DndContext>
  )
}

interface SortableRowProps {
  id: string
  index: number
  count: number
  disabled: boolean
  onMove: (fromIndex: number, toIndex: number) => void
  children: React.ReactNode
}

function SortableRow({
  id,
  index,
  count,
  disabled,
  onMove,
  children,
}: SortableRowProps) {
  const {
    attributes,
    listeners,
    setNodeRef,
    transform,
    transition,
    isDragging,
  } = useSortable({ id, disabled })

  const style: React.CSSProperties = {
    transform: CSS.Transform.toString(transform),
    transition,
  }

  function handleOrdinalChange(event: React.ChangeEvent<HTMLInputElement>) {
    const parsed = Number.parseInt(event.target.value, 10)
    if (Number.isNaN(parsed)) return
    // Numeric field is 1-based; clamp into range then move.
    const target = Math.min(Math.max(parsed, 1), count) - 1
    onMove(index, target)
  }

  return (
    <li
      ref={setNodeRef}
      style={style}
      data-dragging={isDragging || undefined}
      className={cn(
        'bg-background flex items-center gap-2 rounded-md border px-2 py-1.5',
        isDragging && 'ring-ring/50 relative z-10 ring-2',
      )}
    >
      <button
        type="button"
        aria-label="Drag to reorder"
        disabled={disabled}
        className="text-muted-foreground hover:text-foreground cursor-grab touch-none disabled:cursor-not-allowed disabled:opacity-50"
        {...attributes}
        {...listeners}
      >
        <GripVertical className="size-4" aria-hidden="true" />
      </button>

      <div className="min-w-0 flex-1">{children}</div>

      <div className="flex items-center gap-1">
        <Input
          type="number"
          min={1}
          max={count}
          value={index + 1}
          disabled={disabled}
          onChange={handleOrdinalChange}
          aria-label="Position"
          className="h-8 w-16"
        />
        <Button
          type="button"
          variant="ghost"
          size="icon"
          aria-label="Move up"
          disabled={disabled || index === 0}
          onClick={() => onMove(index, index - 1)}
        >
          <ChevronUp className="size-4" aria-hidden="true" />
        </Button>
        <Button
          type="button"
          variant="ghost"
          size="icon"
          aria-label="Move down"
          disabled={disabled || index === count - 1}
          onClick={() => onMove(index, index + 1)}
        >
          <ChevronDown className="size-4" aria-hidden="true" />
        </Button>
      </div>
    </li>
  )
}
