/**
 * Typed operator catalog for the SDTM Derivation Plan graph editor.
 *
 * Each entry describes one typed Dataflow operator (`node_type`) from
 * `api/generated/model`: its human label, its typed input/output ports, a
 * compact parameter-summary projection, and a factory that produces a fresh,
 * fully-typed node object. The catalog is the single source of truth that both
 * the custom node renderers and `isValidConnection` read, so port typing and
 * edge rules can never drift from the node palette.
 *
 * No entry here holds a free-text Python/R/SAS/SQL field — every operator's
 * parameters are the typed shapes the backend already defines (platform
 * boundary; see AGENTS.md "Compilation and execution").
 */
import type {
  AggregateNode,
  AssertNode,
  DeriveNode,
  DomainWriteNode,
  FilterNode,
  JoinNode,
  PivotLongerNode,
  RawReadNode,
  SdtmDerivationPlanNodesItem,
  SdtmReadNode,
  SelectNode,
  SequenceNode,
  SortNode,
  UnionNode,
} from '@/api/generated/model'

import type { PlanNodeType } from '../plan-graph-adapters'

/**
 * A typed input-port descriptor. `arity` distinguishes operators that take a
 * single upstream dataset from the few that take two named inputs (`join`) or
 * an unbounded fan-in (`union`). React Flow handle ids are derived from `key`.
 */
export interface InputPort {
  /** Stable handle key, unique within the node (`in`, `left`, `right`, ...). */
  key: string
  /** Short label rendered next to the handle. */
  label: string
}

export type PortArity = 'none' | 'single' | 'multi'

export interface OperatorDescriptor<
  TNode extends SdtmDerivationPlanNodesItem = SdtmDerivationPlanNodesItem,
> {
  /** The typed discriminant; also the React Flow node `type`. */
  nodeType: TNode['node_type']
  /** Palette label. */
  label: string
  /** One-line description shown in the palette and inspector header. */
  description: string
  /** Operator category grouping for the palette. */
  category: 'source' | 'reshape' | 'derive' | 'terminology' | 'order' | 'sink'
  /** Typed input ports. Sources declare none; sinks/most ops declare one. */
  inputs: InputPort[]
  /**
   * Fan-in arity for the primary input. `union` accepts many upstreams on its
   * single port; `join` has two distinct single-arity ports; sources have none.
   */
  inputArity: PortArity
  /** Whether this operator emits a dataset other nodes can read. */
  hasOutput: boolean
  /** Produce a fresh, fully-typed node with the given id and sensible defaults. */
  create: (id: string) => TNode
  /** Compact `key: value` chips summarising the node's typed parameters. */
  summary: (node: TNode) => string[]
}

function textList(values: readonly string[], max = 3): string {
  if (values.length === 0) return '—'
  if (values.length <= max) return values.join(', ')
  return `${values.slice(0, max).join(', ')} +${values.length - max}`
}

const rawRead: OperatorDescriptor<RawReadNode> = {
  nodeType: 'raw_read',
  label: 'Raw read',
  description: 'Read rows from a bound raw dataset.',
  category: 'source',
  inputs: [],
  inputArity: 'none',
  hasOutput: true,
  create: (id) => ({ node_type: 'raw_read', id, raw_dataset_code: '' }),
  summary: (node) => [`dataset: ${node.raw_dataset_code || '—'}`],
}

const sdtmRead: OperatorDescriptor<SdtmReadNode> = {
  nodeType: 'sdtm_read',
  label: 'SDTM read',
  description:
    'Read an already-produced SDTM domain (resolved against this workbench Specification).',
  category: 'source',
  inputs: [],
  inputArity: 'none',
  hasOutput: true,
  create: (id) => ({ node_type: 'sdtm_read', id, dataset: '' }),
  summary: (node) => [`dataset: ${node.dataset || '—'}`],
}

const select: OperatorDescriptor<SelectNode> = {
  nodeType: 'select',
  label: 'Projection',
  description: 'Keep only the listed columns.',
  category: 'reshape',
  inputs: [{ key: 'in', label: 'in' }],
  inputArity: 'single',
  hasOutput: true,
  create: (id) => ({ node_type: 'select', id, columns: [] }),
  summary: (node) => [`columns: ${textList(node.columns)}`],
}

const filter: OperatorDescriptor<FilterNode> = {
  nodeType: 'filter',
  label: 'Filter',
  description: 'Keep rows matching a typed predicate.',
  category: 'reshape',
  inputs: [{ key: 'in', label: 'in' }],
  inputArity: 'single',
  hasOutput: true,
  create: (id) => ({
    node_type: 'filter',
    id,
    predicate: { kind: 'literal', value: true },
  }),
  summary: () => ['predicate: typed expression'],
}

const join: OperatorDescriptor<JoinNode> = {
  nodeType: 'join',
  label: 'Join',
  description: 'Join two inputs on typed key pairs.',
  category: 'reshape',
  inputs: [
    { key: 'left', label: 'left' },
    { key: 'right', label: 'right' },
  ],
  inputArity: 'single',
  hasOutput: true,
  create: (id) => ({
    node_type: 'join',
    id,
    join_type: 'inner',
    left_input: '',
    right_input: '',
    keys: [],
  }),
  summary: (node) => [
    `type: ${node.join_type}`,
    `keys: ${node.keys.length}`,
  ],
}

const union: OperatorDescriptor<UnionNode> = {
  nodeType: 'union',
  label: 'Union',
  description: 'Stack rows from every upstream input.',
  category: 'reshape',
  inputs: [{ key: 'in', label: 'in (many)' }],
  inputArity: 'multi',
  hasOutput: true,
  create: (id) => ({ node_type: 'union', id }),
  summary: () => ['combines all inputs'],
}

const pivotLonger: OperatorDescriptor<PivotLongerNode> = {
  nodeType: 'pivot_longer',
  label: 'Reshape (pivot longer)',
  description: 'Pivot wide value columns into name/value rows.',
  category: 'reshape',
  inputs: [{ key: 'in', label: 'in' }],
  inputArity: 'single',
  hasOutput: true,
  create: (id) => ({
    node_type: 'pivot_longer',
    id,
    id_columns: [],
    value_columns: [],
    name_column: '',
    value_column: '',
  }),
  summary: (node) => [
    `values: ${textList(node.value_columns)}`,
    `-> ${node.name_column || '?'} / ${node.value_column || '?'}`,
  ],
}

const derive: OperatorDescriptor<DeriveNode> = {
  nodeType: 'derive',
  label: 'Derivation',
  description:
    'Assign target columns from structured typed expressions (never free-text code).',
  category: 'derive',
  inputs: [{ key: 'in', label: 'in' }],
  inputArity: 'single',
  hasOutput: true,
  create: (id) => ({
    node_type: 'derive',
    id,
    target_domain: '',
    assignments: {},
    assignment_order: [],
  }),
  summary: (node) => [
    `domain: ${node.target_domain || '—'}`,
    `assignments: ${textList(Object.keys(node.assignments))}`,
  ],
}

const aggregate: OperatorDescriptor<AggregateNode> = {
  nodeType: 'aggregate',
  label: 'Aggregation',
  description: 'Group rows and compute typed aggregations.',
  category: 'reshape',
  inputs: [{ key: 'in', label: 'in' }],
  inputArity: 'single',
  hasOutput: true,
  create: (id) => ({
    node_type: 'aggregate',
    id,
    group_by: [],
    aggregations: {},
  }),
  summary: (node) => [
    `group by: ${textList(node.group_by)}`,
    `aggs: ${textList(Object.keys(node.aggregations))}`,
  ],
}

const sequence: OperatorDescriptor<SequenceNode> = {
  nodeType: 'sequence',
  label: 'Sequencing',
  description: 'Assign a per-group sequence number by order.',
  category: 'order',
  inputs: [{ key: 'in', label: 'in' }],
  inputArity: 'single',
  hasOutput: true,
  create: (id) => ({
    node_type: 'sequence',
    id,
    order_by: [],
    target_column: '',
  }),
  summary: (node) => [
    `-> ${node.target_column || '?'}`,
    `order: ${textList(node.order_by)}`,
  ],
}

const sort: OperatorDescriptor<SortNode> = {
  nodeType: 'sort',
  label: 'Sort',
  description: 'Order rows by typed sort keys.',
  category: 'order',
  inputs: [{ key: 'in', label: 'in' }],
  inputArity: 'single',
  hasOutput: true,
  create: (id) => ({ node_type: 'sort', id, keys: [] }),
  summary: (node) => [`keys: ${textList(node.keys)}`],
}

const assertOp: OperatorDescriptor<AssertNode> = {
  nodeType: 'assert',
  label: 'Assertion',
  description: 'Raise a typed issue when a predicate fails.',
  category: 'order',
  inputs: [{ key: 'in', label: 'in' }],
  inputArity: 'single',
  hasOutput: true,
  create: (id) => ({
    node_type: 'assert',
    id,
    predicate: { kind: 'literal', value: true },
    issue_code: '',
  }),
  summary: (node) => [`issue: ${node.issue_code || '—'}`],
}

const domainWrite: OperatorDescriptor<DomainWriteNode> = {
  nodeType: 'domain_write',
  label: 'Domain write',
  description: 'Write the final rows to an SDTM domain.',
  category: 'sink',
  inputs: [{ key: 'in', label: 'in' }],
  inputArity: 'single',
  hasOutput: false,
  create: (id) => ({ node_type: 'domain_write', id, domain: '' }),
  summary: (node) => [`domain: ${node.domain || '—'}`],
}

/**
 * The complete typed operator catalog keyed by `node_type`. The entries mirror
 * the `SdtmDerivationPlanNodesItem` union exactly, so adding or removing a
 * backend operator surfaces here as a compile error.
 */
export const OPERATOR_CATALOG: {
  [K in PlanNodeType]: OperatorDescriptor<
    Extract<SdtmDerivationPlanNodesItem, { node_type: K }>
  >
} = {
  raw_read: rawRead,
  sdtm_read: sdtmRead,
  select,
  filter,
  join,
  union,
  pivot_longer: pivotLonger,
  derive,
  aggregate,
  sequence,
  sort,
  assert: assertOp,
  domain_write: domainWrite,
}

/** Stable palette order (sources first, sink last). */
export const PALETTE_ORDER: PlanNodeType[] = [
  'raw_read',
  'sdtm_read',
  'select',
  'filter',
  'join',
  'union',
  'pivot_longer',
  'aggregate',
  'derive',
  'sequence',
  'sort',
  'assert',
  'domain_write',
]

/** Look up the descriptor for a typed node, narrowed to its concrete shape. */
export function descriptorFor(
  node: SdtmDerivationPlanNodesItem,
): OperatorDescriptor {
  return OPERATOR_CATALOG[node.node_type] as OperatorDescriptor
}

/** Produce a fresh typed node of the given operator type. */
export function createNode(
  nodeType: PlanNodeType,
  id: string,
): SdtmDerivationPlanNodesItem {
  return (OPERATOR_CATALOG[nodeType] as OperatorDescriptor).create(id)
}
