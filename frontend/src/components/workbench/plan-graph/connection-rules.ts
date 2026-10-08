/**
 * Pure typed-connection rules for the Derivation Plan graph editor.
 *
 * These helpers decide whether a prospective port-to-port edge may join two
 * nodes. They are React-free so the editor and the tests (task 12.4) can call
 * them directly. The two rules enforced, both entirely on the client before any
 * request is issued (Requirements 12.1/12.2):
 *
 *   1. Typed-model permission — the source node must emit an output and the
 *      target node must declare the input port the edge lands on; a target
 *      input port whose arity is `single` may hold at most one incoming edge.
 *   2. Acyclicity — adding the edge must not create a cycle, so the authoring
 *      graph stays the raw-to-domain DAG the backend requires.
 *
 * Each rejected connection carries a short, human-readable reason the editor
 * surfaces inline at drop time.
 */
import type { Connection, Edge } from '@xyflow/react'

import type { SdtmDerivationPlanNodesItem } from '@/api/generated/model'

import { descriptorFor } from './operator-catalog'

export interface ConnectionDecision {
  ok: boolean
  /** Present when `ok` is false; a short inline reason for the refusal. */
  reason?: string
}

/** The subset of a prospective connection the rules read. */
export interface ProspectiveConnection {
  source: string | null
  target: string | null
  /** Target input handle id (one of the descriptor's input port keys). */
  targetHandle?: string | null
}

interface NodeLookup {
  get: (id: string) => SdtmDerivationPlanNodesItem | undefined
}

function nodeLookup(
  nodes: readonly { id: string; data: SdtmDerivationPlanNodesItem }[],
): NodeLookup {
  const byId = new Map<string, SdtmDerivationPlanNodesItem>()
  for (const node of nodes) byId.set(node.id, node.data)
  return { get: (id) => byId.get(id) }
}

/**
 * Would adding `source -> target` create a cycle? True when `target` can
 * already reach `source` through existing edges (a self-loop also counts).
 */
export function wouldCreateCycle(
  source: string,
  target: string,
  edges: readonly { source: string; target: string }[],
): boolean {
  if (source === target) return true

  // Forward adjacency over existing edges.
  const adjacency = new Map<string, string[]>()
  for (const edge of edges) {
    const list = adjacency.get(edge.source)
    if (list) list.push(edge.target)
    else adjacency.set(edge.source, [edge.target])
  }

  // The new edge is a cycle iff `target` can already reach `source`.
  const stack = [target]
  const seen = new Set<string>()
  while (stack.length > 0) {
    const current = stack.pop()!
    if (current === source) return true
    if (seen.has(current)) continue
    seen.add(current)
    for (const next of adjacency.get(current) ?? []) stack.push(next)
  }
  return false
}

/**
 * Decide a prospective connection against the typed model and the DAG rule.
 *
 * Pure: given the current nodes and edges it returns a decision with an inline
 * reason, and issues no request and mutates nothing.
 */
export function evaluateConnection(
  connection: ProspectiveConnection,
  nodes: readonly { id: string; data: SdtmDerivationPlanNodesItem }[],
  edges: readonly { source: string; target: string; targetHandle?: string | null }[],
): ConnectionDecision {
  const { source, target, targetHandle } = connection
  if (!source || !target) {
    return { ok: false, reason: 'A connection needs both a source and a target.' }
  }

  const lookup = nodeLookup(nodes)
  const sourceNode = lookup.get(source)
  const targetNode = lookup.get(target)
  if (!sourceNode || !targetNode) {
    return { ok: false, reason: 'Connection endpoints are not on the canvas.' }
  }

  const sourceDescriptor = descriptorFor(sourceNode)
  const targetDescriptor = descriptorFor(targetNode)

  // Typed-model permission: source must emit output; target must accept input.
  if (!sourceDescriptor.hasOutput) {
    return {
      ok: false,
      reason: `${sourceDescriptor.label} nodes do not produce an output to connect from.`,
    }
  }
  if (targetDescriptor.inputs.length === 0) {
    return {
      ok: false,
      reason: `${targetDescriptor.label} nodes do not accept an input.`,
    }
  }

  // The edge must land on a declared input port.
  const port =
    targetDescriptor.inputs.find((input) => input.key === targetHandle) ??
    (targetHandle == null && targetDescriptor.inputs.length === 1
      ? targetDescriptor.inputs[0]
      : undefined)
  if (!port) {
    return {
      ok: false,
      reason: `${targetDescriptor.label} has no input port "${targetHandle ?? ''}".`,
    }
  }

  // Single-arity ports hold at most one incoming edge (`union` is multi, so
  // its single port accepts many; `join`'s two ports are each single).
  if (targetDescriptor.inputArity !== 'multi') {
    const occupied = edges.some(
      (edge) =>
        edge.target === target &&
        (edge.targetHandle ?? targetDescriptor.inputs[0]?.key) === port.key,
    )
    if (occupied) {
      return {
        ok: false,
        reason: `The "${port.label}" input already has a connection.`,
      }
    }
  }

  // Acyclicity: keep the plan a DAG.
  if (wouldCreateCycle(source, target, edges)) {
    return {
      ok: false,
      reason: 'This connection would create a cycle; the plan must stay acyclic.',
    }
  }

  return { ok: true }
}

/**
 * Adapt {@link evaluateConnection} to React Flow's `isValidConnection`
 * boolean contract while routing the refusal reason to `onReject`.
 */
export function makeIsValidConnection(
  getNodes: () => readonly { id: string; data: SdtmDerivationPlanNodesItem }[],
  getEdges: () => readonly Edge[],
  onReject?: (reason: string) => void,
) {
  return (connection: Connection | Edge): boolean => {
    const decision = evaluateConnection(
      {
        source: connection.source,
        target: connection.target,
        targetHandle: connection.targetHandle,
      },
      getNodes(),
      getEdges().map((edge) => ({
        source: edge.source,
        target: edge.target,
        targetHandle: edge.targetHandle,
      })),
    )
    if (!decision.ok && decision.reason) onReject?.(decision.reason)
    return decision.ok
  }
}
