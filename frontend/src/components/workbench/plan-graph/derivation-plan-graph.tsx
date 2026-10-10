import * as React from 'react'
import { Trash2 } from 'lucide-react'
import {
  Background,
  Controls,
  ReactFlow,
  ReactFlowProvider,
  addEdge,
  applyEdgeChanges,
  applyNodeChanges,
  useReactFlow,
  type Connection,
  type EdgeChange,
  type NodeChange,
  type NodeTypes,
  type ReactFlowInstance,
} from '@xyflow/react'

import type { SdtmDerivationPlanNodesItem } from '@/api/generated/model'

import type {
  PlanGraphEdge,
  PlanGraphNode,
  PlanGraphNodeData,
  PlanNodeType,
} from '../plan-graph-adapters'
import {
  OPERATOR_CATALOG,
  PALETTE_ORDER,
  createNode,
} from './operator-catalog'
import { makeIsValidConnection } from './connection-rules'
import { OperatorNode } from './operator-node'
import { NodeInspector } from './node-inspector'

/**
 * The body of the SDTM "Derivation plan" tab: a React Flow editor over the
 * typed raw-to-domain DAG.
 *
 * Responsibilities owned by this component (task 12.2):
 *  - render one custom node type per typed Dataflow operator (see
 *    {@link PLAN_OPERATOR_TYPES}) with typed ports and a compact parameter
 *    summary;
 *  - a node inspector that binds the selected node's typed operator parameters
 *    from `api/generated/model` (the `derive`/`filter`/`assert` operators use a
 *    structured typed-expression builder — never a free-text code field);
 *  - palette drag-to-create and port-to-port edge creation via React Flow's own
 *    built-in drag;
 *  - `isValidConnection` that permits only typed-model-allowed edges and rejects
 *    any edge that would introduce a cycle, refused at drop time with an inline
 *    reason and no request.
 *
 * This component is the editor surface only. Serializing the graph back to the
 * typed plan body and the save / alignment / conflict wiring belong to task
 * 12.3; this component stays a controlled editor driven by `nodes`/`edges`
 * props and change callbacks so the owning panel can supply persistence.
 */

/**
 * The custom React Flow node-type map. Every typed operator discriminant maps
 * to the shared {@link OperatorNode} renderer, which reads the typed descriptor
 * for its ports and summary. Exported so the lineage view (read-only) can reuse
 * the exact same node rendering.
 */
export const PLAN_OPERATOR_TYPES: NodeTypes = Object.fromEntries(
  (Object.keys(OPERATOR_CATALOG) as PlanNodeType[]).map((nodeType) => [
    nodeType,
    OperatorNode,
  ]),
) as NodeTypes

const PALETTE_MIME = 'application/x-plan-operator'

export interface DerivationPlanGraphProps {
  nodes: PlanGraphNode[]
  edges: PlanGraphEdge[]
  onNodesChange: (nodes: PlanGraphNode[]) => void
  onEdgesChange: (edges: PlanGraphEdge[]) => void
  /**
   * Read-only mode (plan misaligned or otherwise not editable): disables the
   * palette, edge creation, repositioning-to-save and inspector writes.
   */
  readOnly?: boolean
  /** Mint a unique id for a newly created node. Defaults to a counter+random id. */
  generateNodeId?: (nodeType: PlanNodeType) => string
}

/** Default node-id generator: operator-prefixed, collision-resistant. */
function defaultNodeId(nodeType: PlanNodeType): string {
  const suffix = Math.random().toString(36).slice(2, 8)
  return `${nodeType}_${suffix}`
}

export function DerivationPlanGraph(props: DerivationPlanGraphProps) {
  return (
    <ReactFlowProvider>
      <DerivationPlanGraphInner {...props} />
    </ReactFlowProvider>
  )
}

function DerivationPlanGraphInner({
  nodes,
  edges,
  onNodesChange,
  onEdgesChange,
  readOnly = false,
  generateNodeId = defaultNodeId,
}: DerivationPlanGraphProps) {
  const flow = useReactFlow<PlanGraphNode, PlanGraphEdge>()
  const [instance, setInstance] =
    React.useState<ReactFlowInstance<PlanGraphNode, PlanGraphEdge> | null>(null)
  const [selectedId, setSelectedId] = React.useState<string | null>(null)
  const [rejection, setRejection] = React.useState<string | null>(null)

  // Keep refs so the stable isValidConnection closure always sees current state.
  const nodesRef = React.useRef(nodes)
  const edgesRef = React.useRef(edges)
  nodesRef.current = nodes
  edgesRef.current = edges

  const selectedNode =
    nodes.find((node) => node.id === selectedId)?.data ?? null

  const isValidConnection = React.useMemo(
    () =>
      makeIsValidConnection(
        () => nodesRef.current,
        () => edgesRef.current,
        (reason) => setRejection(reason),
      ),
    [],
  )

  // ---- React Flow change handlers ----------------------------------------

  const handleNodesChange = React.useCallback(
    (changes: NodeChange<PlanGraphNode>[]) => {
      // In read-only mode only selection changes are honoured; position and
      // removal changes are dropped so the plan cannot be edited.
      //
      // Node removals are owned exclusively by onNodesDelete (deleteNodes),
      // which also cleans up incident edges, so 'remove' changes are filtered
      // out here to keep a single removal path and avoid dangling edges.
      const effective = (
        readOnly
          ? changes.filter((change) => change.type === 'select')
          : changes
      ).filter((change) => change.type !== 'remove')
      if (effective.length === 0) return
      // Delegate geometry to React Flow's pure helper, then emit the resulting
      // controlled array upward.
      const applied = applyNodeChanges(effective, flow.getNodes())
      onNodesChange(applied)
      // React Flow emits selection as a batch of per-node 'select' changes:
      // switching nodes yields both a deselect (selected:false) of the old node
      // and a select (selected:true) of the new one in the same batch, in no
      // guaranteed order. Prefer the newly-selected node; only clear when the
      // batch deselects without selecting anything.
      const selectChanges = effective.filter(
        (change): change is Extract<NodeChange<PlanGraphNode>, { type: 'select' }> =>
          change.type === 'select',
      )
      if (selectChanges.length > 0) {
        const selected = selectChanges.find((change) => change.selected)
        if (selected) {
          setSelectedId(selected.id)
        } else {
          // All select changes are deselections: clear only if the currently
          // selected node is among them.
          const deselectedIds = new Set(selectChanges.map((change) => change.id))
          setSelectedId((current) =>
            current !== null && deselectedIds.has(current) ? null : current,
          )
        }
      }
    },
    [readOnly, flow, onNodesChange],
  )

  const handleEdgesChange = React.useCallback(
    (changes: EdgeChange<PlanGraphEdge>[]) => {
      if (readOnly) return
      const applied = applyEdgeChanges(changes, flow.getEdges())
      onEdgesChange(applied)
    },
    [readOnly, flow, onEdgesChange],
  )

  // ---- Node deletion ------------------------------------------------------

  // Remove the given node ids and every edge incident to them, emitting the
  // resulting controlled arrays upward. Used by both the keyboard-delete path
  // (React Flow's onNodesDelete) and the explicit toolbar button so deletion
  // works regardless of canvas focus. No-op in read-only mode.
  const deleteNodes = React.useCallback(
    (ids: readonly string[]) => {
      if (readOnly || ids.length === 0) return
      const removing = new Set(ids)
      onNodesChange(flow.getNodes().filter((node) => !removing.has(node.id)))
      onEdgesChange(
        flow
          .getEdges()
          .filter(
            (edge) => !removing.has(edge.source) && !removing.has(edge.target),
          ),
      )
      setSelectedId((current) =>
        current !== null && removing.has(current) ? null : current,
      )
    },
    [readOnly, flow, onNodesChange, onEdgesChange],
  )

  // React Flow's built-in delete (Backspace/Delete) routes deletions here.
  // We own edge cleanup so attached edges never dangle in the controlled state.
  const handleNodesDelete = React.useCallback(
    (deleted: PlanGraphNode[]) => {
      deleteNodes(deleted.map((node) => node.id))
    },
    [deleteNodes],
  )

  const handleConnect = React.useCallback(
    (connection: Connection) => {
      if (readOnly) return
      // React Flow calls isValidConnection before onConnect, so a connection
      // that reaches here already passed the typed/cycle gate.
      setRejection(null)
      const edge: PlanGraphEdge = {
        ...connection,
        id: `${connection.source}->${connection.target}`,
      }
      onEdgesChange(addEdge(edge, flow.getEdges()))
    },
    [readOnly, flow, onEdgesChange],
  )

  // ---- Palette drag-to-create (React Flow built-in drop target) ----------

  const onDragStart = React.useCallback(
    (event: React.DragEvent, nodeType: PlanNodeType) => {
      event.dataTransfer.setData(PALETTE_MIME, nodeType)
      event.dataTransfer.effectAllowed = 'move'
    },
    [],
  )

  const onDragOver = React.useCallback((event: React.DragEvent) => {
    event.preventDefault()
    event.dataTransfer.dropEffect = 'move'
  }, [])

  const onDrop = React.useCallback(
    (event: React.DragEvent) => {
      event.preventDefault()
      if (readOnly || !instance) return
      const nodeType = event.dataTransfer.getData(PALETTE_MIME) as PlanNodeType
      if (!nodeType || !(nodeType in OPERATOR_CATALOG)) return
      const position = instance.screenToFlowPosition({
        x: event.clientX,
        y: event.clientY,
      })
      const typedNode: SdtmDerivationPlanNodesItem = createNode(
        nodeType,
        generateNodeId(nodeType),
      )
      const graphNode: PlanGraphNode = {
        id: typedNode.id,
        type: typedNode.node_type,
        position,
        data: typedNode as PlanGraphNodeData,
      }
      onNodesChange([...flow.getNodes(), graphNode])
      setSelectedId(typedNode.id)
    },
    [readOnly, instance, generateNodeId, flow, onNodesChange],
  )

  // ---- Inspector binding --------------------------------------------------

  const handleInspectorChange = React.useCallback(
    (next: SdtmDerivationPlanNodesItem) => {
      if (readOnly) return
      onNodesChange(
        flow.getNodes().map((node) =>
          node.id === next.id
            ? { ...node, data: next as PlanGraphNodeData, type: next.node_type }
            : node,
        ),
      )
    },
    [readOnly, flow, onNodesChange],
  )

  return (
    <div className="flex h-[32rem] w-full overflow-hidden rounded-md border">
      {!readOnly && (
        <OperatorPalette onDragStart={onDragStart} />
      )}

      <div className="relative flex-1" onDragOver={onDragOver} onDrop={onDrop}>
        {rejection && (
          <div
            role="alert"
            className="absolute left-2 top-2 z-10 max-w-sm rounded-md border border-destructive/50 bg-background/95 px-3 py-2 text-xs text-destructive shadow"
          >
            {rejection}
          </div>
        )}
        {!readOnly && selectedId && (
          <button
            type="button"
            onClick={() => deleteNodes([selectedId])}
            className="absolute right-2 top-2 z-10 inline-flex items-center gap-1 rounded-md border border-destructive/50 bg-background/95 px-2 py-1 text-xs text-destructive shadow hover:bg-destructive/10"
            aria-label="Delete selected node"
          >
            <Trash2 className="h-3.5 w-3.5" aria-hidden="true" />
            Delete node
          </button>
        )}
        <ReactFlow
          nodes={nodes}
          edges={edges}
          nodeTypes={PLAN_OPERATOR_TYPES}
          onInit={setInstance}
          onNodesChange={handleNodesChange}
          onEdgesChange={handleEdgesChange}
          onNodesDelete={handleNodesDelete}
          onConnect={handleConnect}
          isValidConnection={isValidConnection}
          nodesConnectable={!readOnly}
          nodesDraggable={!readOnly}
          deleteKeyCode={readOnly ? null : ['Backspace', 'Delete']}
          elementsSelectable
          fitView
          proOptions={{ hideAttribution: true }}
          aria-label="Derivation plan graph editor"
        >
          <Background />
          <Controls showInteractive={!readOnly} />
        </ReactFlow>
      </div>

      <aside className="w-80 shrink-0 border-l">
        <NodeInspector
          node={selectedNode}
          onChange={handleInspectorChange}
          readOnly={readOnly}
        />
      </aside>
    </div>
  )
}

interface OperatorPaletteProps {
  onDragStart: (event: React.DragEvent, nodeType: PlanNodeType) => void
}

/** The draggable operator palette. Dragging an entry onto the canvas creates a typed node. */
function OperatorPalette({ onDragStart }: OperatorPaletteProps) {
  return (
    <div
      className="flex w-48 shrink-0 flex-col gap-1 overflow-y-auto border-r p-2"
      aria-label="Operator palette"
    >
      <span className="px-1 text-xs font-medium text-muted-foreground">
        Operators
      </span>
      {PALETTE_ORDER.map((nodeType) => {
        const descriptor = OPERATOR_CATALOG[nodeType]
        return (
          <button
            key={nodeType}
            type="button"
            draggable
            onDragStart={(event) => onDragStart(event, nodeType)}
            className="cursor-grab rounded-md border bg-background px-2 py-1 text-left text-xs hover:bg-accent"
            title={descriptor.description}
            aria-label={`Add ${descriptor.label} node`}
          >
            {descriptor.label}
          </button>
        )
      })}
    </div>
  )
}
