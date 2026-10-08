import { Handle, Position, type NodeProps } from '@xyflow/react'

import type { PlanGraphNode } from '../plan-graph-adapters'
import { descriptorFor } from './operator-catalog'

/**
 * A single custom React Flow node renderer shared by every operator type. It
 * reads the typed operator descriptor to draw the node's typed input ports
 * (left handles), its output port when the operator emits one (right handle),
 * a category-coloured header, and the compact parameter summary chips. One
 * renderer parameterised by the descriptor keeps all 14 operator node types
 * visually and behaviourally consistent.
 */
export function OperatorNode({ data, selected }: NodeProps<PlanGraphNode>) {
  const descriptor = descriptorFor(data)
  const summary = descriptor.summary(data)

  return (
    <div
      className={[
        'min-w-44 rounded-md border bg-background shadow-sm',
        selected ? 'ring-2 ring-primary' : '',
      ].join(' ')}
      data-node-type={data.node_type}
    >
      {/* Typed input ports on the left edge. */}
      {descriptor.inputs.map((input, index) => (
        <Handle
          key={input.key}
          id={input.key}
          type="target"
          position={Position.Left}
          style={inputHandleStyle(index, descriptor.inputs.length)}
          aria-label={`${descriptor.label} input ${input.label}`}
        />
      ))}

      <div className="border-b px-3 py-1.5">
        <div className="text-xs font-medium">{descriptor.label}</div>
        <div className="text-[10px] text-muted-foreground">{data.id}</div>
      </div>
      <div className="flex flex-col gap-0.5 px-3 py-2">
        {summary.map((chip, index) => (
          <span key={index} className="text-[11px] text-muted-foreground">
            {chip}
          </span>
        ))}
      </div>

      {/* Output port on the right edge, only when the operator emits a dataset. */}
      {descriptor.hasOutput && (
        <Handle
          id="out"
          type="source"
          position={Position.Right}
          aria-label={`${descriptor.label} output`}
        />
      )}
    </div>
  )
}

/** Spread multiple input handles vertically along the left edge. */
function inputHandleStyle(index: number, count: number): React.CSSProperties {
  if (count <= 1) return {}
  const step = 100 / (count + 1)
  return { top: `${step * (index + 1)}%` }
}
