/**
 * Pure adapters between the typed SDTM Derivation Plan body (api/generated/model)
 * and the React Flow graph view model used by `DerivationPlanGraph`.
 *
 * These functions are intentionally free of React and side effects so they can be
 * unit-tested as a round-trip (task 12.4). They never read or write the DOM, never
 * call hooks, and never mutate their inputs.
 *
 * Design invariants (see .kiro/specs/raw-sdtm-frontend/design.md "Serialize / deserialize round-trip"):
 *  - A React Flow node's `type` is the typed discriminant `node_type`, and its `data`
 *    is ALWAYS the exact typed operator object from api/generated/model — never a
 *    free-text / arbitrary-field bag.
 *  - Node layout (`position`) is client-only view state. It round-trips from a
 *    backend-provided layout when one is supplied; otherwise a deterministic
 *    auto-layout computes positions. Positions are NEVER written back into the
 *    typed Derivation Plan body by `graphToPlan`.
 */
import type { Edge, Node } from '@xyflow/react'

import type {
  CustomFunctionDefinition,
  PlanEdge,
  SdtmDerivationPlan,
  SdtmDerivationPlanNodesItem,
} from '@/api/generated/model'

/**
 * The React Flow node `type` for a plan node is the typed `node_type` discriminant
 * (`'raw_read' | 'filter' | 'derive' | ...`). Using the discriminant keeps the
 * node `data` a complete, typed operator object and makes the round-trip lossless.
 */
export type PlanNodeType = SdtmDerivationPlanNodesItem['node_type']

/**
 * The node `data` payload. It is the full typed plan node (so inspector and
 * renderers bind only typed operator parameters); the `& Record<string,
 * unknown>` satisfies React Flow 12's `Node<T extends Record<string, unknown>>`
 * constraint without widening what the editor code actually reads — every typed
 * member of the union is still present and discriminated by `node_type`.
 */
export type PlanGraphNodeData = SdtmDerivationPlanNodesItem & Record<string, unknown>

/**
 * A React Flow node whose `data` is the full typed plan node. The typed object
 * carries its own `id` and `node_type`; React Flow's own `id`/`type` mirror them.
 */
export type PlanGraphNode = Node<PlanGraphNodeData, PlanNodeType>

/** A React Flow edge mirroring a typed {@link PlanEdge} (`source_node` -> `target_node`). */
export type PlanGraphEdge = Edge

/** React Flow view model produced by {@link planToGraph}. */
export interface PlanGraph {
  nodes: PlanGraphNode[]
  edges: PlanGraphEdge[]
}

/** Client-only node layout, keyed by typed node id. Never part of the typed plan body. */
export type PlanNodeLayout = Record<string, { x: number; y: number }>

export interface PlanToGraphOptions {
  /**
   * Node positions sourced from a persisted backend layout, keyed by node id. When a
   * node id is present here its stored position round-trips; otherwise a deterministic
   * auto-layout position is used. Either way the position is client-only view state.
   */
  layout?: PlanNodeLayout
}

export interface GraphToPlanMeta {
  /** The SDTM domain this per-domain plan produces (the plan's natural key). */
  domain: string
  /** Pinned specification revision the plan is authored against. */
  specificationRevision: number
  /** Pinned input-selection revision the plan is authored against. */
  inputSelectionRevision: number
  /** Schema version to stamp on the body; defaults to the only supported value. */
  schemaVersion?: SdtmDerivationPlan['schema_version']
  /** Manually authored custom functions retained outside the visual graph. */
  customFunctions?: CustomFunctionDefinition[]
}

const DEFAULT_SCHEMA_VERSION: SdtmDerivationPlan['schema_version'] = '1.2.0'

// Deterministic auto-layout spacing (px). Columns are dependency layers (left -> right),
// rows are nodes within a layer, both in a stable order derived from node/edge order.
const COLUMN_SPACING = 260
const ROW_SPACING = 120
const ORIGIN_X = 0
const ORIGIN_Y = 0

/**
 * Compute a deterministic layer index per node id from the edge set.
 *
 * The layer of a node is the length of the longest dependency chain ending at it,
 * so sources sit at layer 0 and writes land to the right. The computation is a
 * stable longest-path relaxation that ignores edges participating in a cycle
 * (cycles are rejected at edit time by the editor; here we simply avoid looping).
 */
function computeLayers(
  nodeIds: readonly string[],
  edges: readonly PlanEdge[],
): Map<string, number> {
  const layer = new Map<string, number>()
  for (const id of nodeIds) layer.set(id, 0)

  // Relax at most |nodes| times; this converges for any DAG and terminates for
  // cyclic input without looping forever.
  const incoming = new Map<string, string[]>()
  for (const id of nodeIds) incoming.set(id, [])
  for (const edge of edges) {
    if (incoming.has(edge.target_node) && layer.has(edge.source_node)) {
      incoming.get(edge.target_node)!.push(edge.source_node)
    }
  }

  for (let pass = 0; pass < nodeIds.length; pass += 1) {
    let changed = false
    for (const id of nodeIds) {
      const sources = incoming.get(id) ?? []
      let best = 0
      for (const source of sources) {
        const candidate = (layer.get(source) ?? 0) + 1
        if (candidate > best) best = candidate
      }
      if (best !== layer.get(id)) {
        layer.set(id, best)
        changed = true
      }
    }
    if (!changed) break
  }

  return layer
}

/**
 * Deterministic auto-layout: assign each node a position from its dependency layer
 * (column) and its stable order within that layer (row). Pure and order-stable:
 * identical inputs always produce identical positions.
 */
function autoLayout(
  nodes: readonly SdtmDerivationPlanNodesItem[],
  edges: readonly PlanEdge[],
): PlanNodeLayout {
  const nodeIds = nodes.map((node) => node.id)
  const layers = computeLayers(nodeIds, edges)

  const rowCursor = new Map<number, number>()
  const layout: PlanNodeLayout = {}

  for (const node of nodes) {
    const column = layers.get(node.id) ?? 0
    const row = rowCursor.get(column) ?? 0
    rowCursor.set(column, row + 1)
    layout[node.id] = {
      x: ORIGIN_X + column * COLUMN_SPACING,
      y: ORIGIN_Y + row * ROW_SPACING,
    }
  }

  return layout
}

/**
 * Convert a typed Derivation Plan body into React Flow `nodes`/`edges`.
 *
 * Each node's React Flow `type` is the typed `node_type` and its `data` is the full
 * typed operator object, so the editor binds only typed parameters. Positions come
 * from `options.layout` when present for a node id (backend layout round-trip) and
 * otherwise from a deterministic auto-layout; in both cases the position is
 * client-only view state and is never part of the typed body.
 */
export function planToGraph(
  plan: SdtmDerivationPlan,
  options: PlanToGraphOptions = {},
): PlanGraph {
  const planNodes = plan.nodes ?? []
  const planEdges = plan.edges ?? []

  const computed = autoLayout(planNodes, planEdges)
  const stored = options.layout ?? {}

  const nodes: PlanGraphNode[] = planNodes.map((node) => {
    const position = stored[node.id] ?? computed[node.id] ?? { x: ORIGIN_X, y: ORIGIN_Y }
    return {
      id: node.id,
      type: node.node_type,
      position: { x: position.x, y: position.y },
      data: node as PlanGraphNodeData,
    }
  })

  const edges: PlanGraphEdge[] = planEdges.map((edge) => ({
    id: planEdgeId(edge),
    source: edge.source_node,
    target: edge.target_node,
  }))

  return { nodes, edges }
}

/**
 * Reconstruct the typed Derivation Plan body from React Flow `nodes`/`edges`.
 *
 * The typed node is read straight from each node's `data` (never re-synthesized from
 * free-text fields), so only operator-parameter objects from api/generated/model can
 * round-trip. Node `position` is deliberately dropped: layout is client-only view
 * state and must not be invented into the typed body. The pinned specification /
 * input-selection revisions and schema version are supplied by the caller.
 */
export function graphToPlan(
  nodes: readonly PlanGraphNode[],
  edges: readonly PlanGraphEdge[],
  meta: GraphToPlanMeta,
): SdtmDerivationPlan {
  const planNodes: SdtmDerivationPlanNodesItem[] = nodes.map((node) => node.data)

  const planEdges: PlanEdge[] = edges.map((edge) => ({
    source_node: edge.source,
    target_node: edge.target,
  }))

  const body: SdtmDerivationPlan = {
    schema_version: meta.schemaVersion ?? DEFAULT_SCHEMA_VERSION,
    domain: meta.domain,
    specification_revision: meta.specificationRevision,
    input_selection_revision: meta.inputSelectionRevision,
    custom_functions: meta.customFunctions ?? [],
    nodes: planNodes,
    edges: planEdges,
  }

  return body
}

/** Stable React Flow edge id for a typed plan edge. */
export function planEdgeId(edge: PlanEdge): string {
  return `${edge.source_node}->${edge.target_node}`
}

/** Extract a client-only layout snapshot (node id -> position) from graph nodes. */
export function layoutFromGraph(nodes: readonly PlanGraphNode[]): PlanNodeLayout {
  const layout: PlanNodeLayout = {}
  for (const node of nodes) {
    layout[node.id] = { x: node.position.x, y: node.position.y }
  }
  return layout
}
