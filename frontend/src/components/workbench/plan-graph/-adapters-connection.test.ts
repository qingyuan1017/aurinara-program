// Pure-function tests for the SDTM Derivation Plan graph editor's typed
// adapters and connection rules — task 12.4.
//
// These exercise the React-free units directly (no DOM, no harness):
//   * `evaluateConnection` / `wouldCreateCycle` permit only typed-model-allowed
//     edges and reject any edge that would introduce a cycle, keeping the
//     authoring graph a raw-to-domain DAG (Requirements 12.1, 12.2).
//   * `planToGraph` / `graphToPlan` round-trip an equivalent typed plan, with
//     node positions treated as client-only view state: a backend layout
//     round-trips, otherwise a deterministic auto-layout is used, and positions
//     are never written back into the typed body (Requirement 12.1).
import { describe, expect, it } from 'vitest'

import type {
  PlanEdge,
  SdtmDerivationPlan,
  SdtmDerivationPlanNodesItem,
} from '@/api/generated/model'

import {
  graphToPlan,
  layoutFromGraph,
  planToGraph,
  type PlanGraphNode,
} from '../plan-graph-adapters'
import { createNode } from './operator-catalog'
import {
  evaluateConnection,
  wouldCreateCycle,
} from './connection-rules'

// ---------------------------------------------------------------------------
// Helpers
// ---------------------------------------------------------------------------

/** Build a `{ id, data }` lookup entry for the connection-rule helpers. */
function nodeEntry(
  node: SdtmDerivationPlanNodesItem,
): { id: string; data: SdtmDerivationPlanNodesItem } {
  return { id: node.id, data: node }
}

/** A small, valid raw -> ... -> domain plan body for round-trip tests. */
function makePlan(): SdtmDerivationPlan {
  const read = createNode('raw_read', 'read1')
  const filter = createNode('filter', 'filter1')
  const write = createNode('domain_write', 'write1')
  const nodes: SdtmDerivationPlanNodesItem[] = [read, filter, write]
  const edges: PlanEdge[] = [
    { source_node: 'read1', target_node: 'filter1' },
    { source_node: 'filter1', target_node: 'write1' },
  ]
  return {
    schema_version: '1.2.0',
    domain: 'DM',
    specification_revision: 3,
    input_selection_revision: 2,
    nodes,
    edges,
  }
}

// ===========================================================================
// Connection rules (Requirements 12.1, 12.2)
// ===========================================================================
describe('wouldCreateCycle', () => {
  it('rejects a self-loop', () => {
    expect(wouldCreateCycle('a', 'a', [])).toBe(true)
  })

  it('is false for a fresh edge in an acyclic graph', () => {
    const edges = [{ source: 'a', target: 'b' }]
    // b -> c does not close a cycle.
    expect(wouldCreateCycle('b', 'c', edges)).toBe(false)
  })

  it('detects a back-edge that would close a cycle', () => {
    // a -> b -> c already exists; adding c -> a would create a cycle.
    const edges = [
      { source: 'a', target: 'b' },
      { source: 'b', target: 'c' },
    ]
    expect(wouldCreateCycle('c', 'a', edges)).toBe(true)
  })

  it('allows a diamond (shared descendant is not a cycle)', () => {
    const edges = [
      { source: 'a', target: 'b' },
      { source: 'a', target: 'c' },
    ]
    // b -> d and c -> d both land on the same descendant without a cycle.
    expect(wouldCreateCycle('b', 'd', edges)).toBe(false)
    expect(wouldCreateCycle('c', 'd', [...edges, { source: 'b', target: 'd' }])).toBe(
      false,
    )
  })
})

describe('evaluateConnection — typed-model permission', () => {
  const read = createNode('raw_read', 'read1')
  const filter = createNode('filter', 'filter1')
  const write = createNode('domain_write', 'write1')
  const nodes = [read, filter, write].map(nodeEntry)

  it('permits a typed-model-allowed edge (source output -> target input)', () => {
    const decision = evaluateConnection(
      { source: 'read1', target: 'filter1', targetHandle: 'in' },
      nodes,
      [],
    )
    expect(decision.ok).toBe(true)
    expect(decision.reason).toBeUndefined()
  })

  it('rejects connecting FROM a node that produces no output (domain_write)', () => {
    const decision = evaluateConnection(
      { source: 'write1', target: 'filter1', targetHandle: 'in' },
      nodes,
      [],
    )
    expect(decision.ok).toBe(false)
    expect(decision.reason).toMatch(/do not produce an output/i)
  })

  it('rejects connecting INTO a source node that accepts no input (raw_read)', () => {
    const decision = evaluateConnection(
      { source: 'filter1', target: 'read1', targetHandle: 'in' },
      nodes,
      [],
    )
    expect(decision.ok).toBe(false)
    expect(decision.reason).toMatch(/do not accept an input/i)
  })

  it('rejects an edge that lands on a non-existent input port', () => {
    const decision = evaluateConnection(
      { source: 'read1', target: 'filter1', targetHandle: 'nope' },
      nodes,
      [],
    )
    expect(decision.ok).toBe(false)
    expect(decision.reason).toMatch(/no input port/i)
  })

  it('rejects a second edge into an already-occupied single-arity port', () => {
    const other = createNode('raw_read', 'read2')
    const decision = evaluateConnection(
      { source: 'read2', target: 'filter1', targetHandle: 'in' },
      [...nodes, nodeEntry(other)],
      [{ source: 'read1', target: 'filter1', targetHandle: 'in' }],
    )
    expect(decision.ok).toBe(false)
    expect(decision.reason).toMatch(/already has a connection/i)
  })

  it('allows many inputs into a multi-arity port (union)', () => {
    const read2 = createNode('raw_read', 'read2')
    const union = createNode('union', 'union1')
    const graphNodes = [read, read2, union].map(nodeEntry)
    const decision = evaluateConnection(
      { source: 'read2', target: 'union1', targetHandle: 'in' },
      graphNodes,
      [{ source: 'read1', target: 'union1', targetHandle: 'in' }],
    )
    expect(decision.ok).toBe(true)
  })

  it('permits sdtm_read as a connection SOURCE (it has an output)', () => {
    const sdtmRead = createNode('sdtm_read', 'sread1')
    const decision = evaluateConnection(
      { source: 'sread1', target: 'filter1', targetHandle: 'in' },
      [...nodes, nodeEntry(sdtmRead)],
      [],
    )
    expect(decision.ok).toBe(true)
    expect(decision.reason).toBeUndefined()
  })

  it('rejects sdtm_read as a connection TARGET (a source accepts no input)', () => {
    const sdtmRead = createNode('sdtm_read', 'sread1')
    const decision = evaluateConnection(
      { source: 'filter1', target: 'sread1', targetHandle: 'in' },
      [...nodes, nodeEntry(sdtmRead)],
      [],
    )
    expect(decision.ok).toBe(false)
    expect(decision.reason).toMatch(/do not accept an input/i)
  })

  it("permits each of a join's two distinct single-arity ports", () => {
    const read2 = createNode('raw_read', 'read2')
    const join = createNode('join', 'join1')
    const graphNodes = [read, read2, join].map(nodeEntry)
    const left = evaluateConnection(
      { source: 'read1', target: 'join1', targetHandle: 'left' },
      graphNodes,
      [],
    )
    const right = evaluateConnection(
      { source: 'read2', target: 'join1', targetHandle: 'right' },
      graphNodes,
      [{ source: 'read1', target: 'join1', targetHandle: 'left' }],
    )
    expect(left.ok).toBe(true)
    expect(right.ok).toBe(true)
  })
})

describe('evaluateConnection — DAG preservation (Req 12.2)', () => {
  it('rejects an edge that would create a cycle', () => {
    // union has a multi-arity input port, so the back-edge is tested against the
    // cycle rule rather than being short-circuited by port occupancy.
    const union = createNode('union', 'union1')
    const filter = createNode('filter', 'filter1')
    const sort = createNode('sort', 'sort1')
    const nodes = [union, filter, sort].map(nodeEntry)
    // union1 -> filter1 -> sort1 exists; sort1 -> union1 would close a cycle.
    const decision = evaluateConnection(
      { source: 'sort1', target: 'union1', targetHandle: 'in' },
      nodes,
      [
        { source: 'union1', target: 'filter1', targetHandle: 'in' },
        { source: 'filter1', target: 'sort1', targetHandle: 'in' },
      ],
    )
    expect(decision.ok).toBe(false)
    expect(decision.reason).toMatch(/cycle/i)
  })

  it('rejects a direct self-loop', () => {
    const filter = createNode('filter', 'filter1')
    const decision = evaluateConnection(
      { source: 'filter1', target: 'filter1', targetHandle: 'in' },
      [nodeEntry(filter)],
      [],
    )
    expect(decision.ok).toBe(false)
    expect(decision.reason).toMatch(/cycle/i)
  })

  it('requires both endpoints', () => {
    const decision = evaluateConnection({ source: null, target: 'filter1' }, [], [])
    expect(decision.ok).toBe(false)
    expect(decision.reason).toMatch(/source and a target/i)
  })
})

// ===========================================================================
// planToGraph / graphToPlan round-trip (Requirement 12.1)
// ===========================================================================
describe('planToGraph / graphToPlan round-trip', () => {
  it('maps each typed node to a React Flow node carrying the exact typed data', () => {
    const plan = makePlan()
    const { nodes, edges } = planToGraph(plan)

    expect(nodes).toHaveLength(3)
    for (const node of nodes) {
      // React Flow `type` mirrors the typed discriminant and `data` is the full
      // typed operator object (never a free-text bag).
      expect(node.type).toBe(node.data.node_type)
      expect(node.id).toBe(node.data.id)
    }
    expect(edges.map((e) => [e.source, e.target])).toEqual([
      ['read1', 'filter1'],
      ['filter1', 'write1'],
    ])
  })

  it('round-trips to an equivalent typed plan body (nodes + edges preserved)', () => {
    const plan = makePlan()
    const graph = planToGraph(plan)

    const back = graphToPlan(graph.nodes, graph.edges, {
      domain: plan.domain,
      specificationRevision: plan.specification_revision,
      inputSelectionRevision: plan.input_selection_revision,
      schemaVersion: '1.2.0',
    })

    expect(back.nodes).toEqual(plan.nodes)
    expect(back.edges).toEqual(plan.edges)
    expect(back.domain).toBe(plan.domain)
    expect(back.specification_revision).toBe(plan.specification_revision)
    expect(back.input_selection_revision).toBe(plan.input_selection_revision)
    expect(back.schema_version).toBe('1.2.0')
  })

  it('never writes node positions into the typed body (layout is view-only)', () => {
    const plan = makePlan()
    const graph = planToGraph(plan)

    const back = graphToPlan(graph.nodes, graph.edges, {
      domain: plan.domain,
      specificationRevision: plan.specification_revision,
      inputSelectionRevision: plan.input_selection_revision,
    })

    // The serialized body has no `position`/`x`/`y` anywhere — positions are
    // client-only view state.
    const serialized = JSON.stringify(back)
    expect(serialized).not.toMatch(/"position"/)
    for (const node of back.nodes) {
      expect(node).not.toHaveProperty('position')
      expect(node).not.toHaveProperty('x')
      expect(node).not.toHaveProperty('y')
    }
  })

  it('uses a deterministic auto-layout when no backend layout is supplied', () => {
    const plan = makePlan()
    const first = planToGraph(plan)
    const second = planToGraph(plan)

    const firstPositions = first.nodes.map((n) => n.position)
    const secondPositions = second.nodes.map((n) => n.position)
    // Identical inputs produce identical positions.
    expect(secondPositions).toEqual(firstPositions)

    // Dependency layers flow left-to-right: read (source) is left of filter,
    // which is left of the domain_write sink.
    const byId = Object.fromEntries(first.nodes.map((n) => [n.id, n.position]))
    expect(byId.read1.x).toBeLessThan(byId.filter1.x)
    expect(byId.filter1.x).toBeLessThan(byId.write1.x)
  })

  it('round-trips a stored backend layout and drops it from the typed body', () => {
    const plan = makePlan()
    const layout = {
      read1: { x: 11, y: 22 },
      filter1: { x: 33, y: 44 },
      write1: { x: 55, y: 66 },
    }
    const graph = planToGraph(plan, { layout })

    // Stored positions round-trip into the view model…
    expect(layoutFromGraph(graph.nodes)).toEqual(layout)

    // …but the typed body produced from the graph still carries no positions.
    const back = graphToPlan(graph.nodes, graph.edges, {
      domain: plan.domain,
      specificationRevision: plan.specification_revision,
      inputSelectionRevision: plan.input_selection_revision,
    })
    expect(JSON.stringify(back)).not.toMatch(/"position"/)
    expect(back.nodes).toEqual(plan.nodes)
  })

  it('falls back to auto-layout for node ids missing from a partial backend layout', () => {
    const plan = makePlan()
    const graph = planToGraph(plan, { layout: { read1: { x: 7, y: 9 } } })
    const byId: Record<string, PlanGraphNode> = Object.fromEntries(
      graph.nodes.map((n) => [n.id, n]),
    )
    // The pinned node keeps its stored position…
    expect(byId.read1.position).toEqual({ x: 7, y: 9 })
    // …and the others still receive a deterministic auto-layout position.
    expect(byId.filter1.position).not.toEqual({ x: 7, y: 9 })
  })
})
