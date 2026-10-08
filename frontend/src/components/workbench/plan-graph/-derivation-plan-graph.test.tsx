// @vitest-environment jsdom
//
// Component tests for the SDTM Derivation Plan graph editor — task 12.4.
//
// These use the shared jsdom harness (ResizeObserver + element-dimension mocks)
// so React Flow can measure its canvas. Coverage:
//   * the node inspector edits a typed operator param and reflects it back as a
//     typed node object (NodeInspector rendered directly) — Requirement 12.2;
//   * a palette drop adds a typed node to the canvas (DerivationPlanGraph) —
//     Requirements 12.1/12.2;
//   * the DerivationPlanPanel save issues the `PUT` with the aggregate `If-Match`
//     plus the pinned specification / input-selection revisions — Req 12.1;
//   * a `409 stale_input_fingerprint` identifies the drifted input and keeps the
//     on-canvas edits — Req 12.3;
//   * a `misaligned` plan renders the editor read-only with the AlignmentBanner
//     and a disabled Save — Requirements 12.2/12.4;
//   * new-plan mode: a `404 sdtm_derivation_plan_required` with a current
//     Specification + Input Selection renders the full interactive editor (first-
//     plan bootstrap); missing/not-current prerequisites keep the guidance empty
//     state; the first save pins the CURRENT spec/input revisions and the
//     aggregate If-Match; a backend rejection (e.g. zero nodes -> 422) surfaces a
//     toast.
import { fireEvent, render, screen, waitFor } from '@testing-library/react'
import {
  afterEach,
  beforeAll,
  beforeEach,
  describe,
  expect,
  it,
  vi,
} from 'vitest'
import * as React from 'react'
import type { ReactNode } from 'react'
import type { AxiosError, AxiosRequestConfig } from 'axios'
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'

import { installJsdomHarness } from '@/test/jsdom-harness'
import { ifMatchRequest } from '@/lib/requests'
import type {
  AggregateResponse,
  PlanResponse,
  RawReadNode,
  SdtmDerivationPlan,
} from '@/api/generated/model'

beforeAll(() => {
  installJsdomHarness()
})

// ---------------------------------------------------------------------------
// Keep sonner out of the jsdom/theme path.
// ---------------------------------------------------------------------------
vi.mock('sonner', () => ({
  toast: { success: vi.fn(), error: vi.fn() },
}))

// ---------------------------------------------------------------------------
// Lightweight @xyflow/react stub.
//
// React Flow's canvas depends on a real layout/viewport engine that jsdom does
// not provide, so its instance never initialises under test and the real
// `screenToFlowPosition` cannot project a drop. We stub the surface the editor
// uses with a deterministic shim: `ReactFlow` fires `onInit` with an instance
// exposing a trivial `screenToFlowPosition`, renders the native drop handlers,
// and lets the editor's own drop logic (createNode + the controlled nodes
// array) run for real. The typed node-creation path — the thing the test
// asserts — is the editor's, not React Flow's.
// ---------------------------------------------------------------------------
vi.mock('@xyflow/react', async () => {
  const React = await import('react')
  const Position = { Left: 'left', Right: 'right', Top: 'top', Bottom: 'bottom' }
  const instance = {
    screenToFlowPosition: (p: { x: number; y: number }) => ({ x: p.x, y: p.y }),
  }
  const ReactFlowProvider = ({ children }: { children: React.ReactNode }) =>
    React.createElement(React.Fragment, null, children)
  const ReactFlow = ({
    children,
    onInit,
    onDrop,
    onDragOver,
    nodes,
    'aria-label': ariaLabel,
  }: Record<string, unknown>) => {
    React.useEffect(() => {
      ;(onInit as ((i: unknown) => void) | undefined)?.(instance)
      // eslint-disable-next-line react-hooks/exhaustive-deps
    }, [])
    return React.createElement(
      'div',
      {
        className: 'react-flow',
        'aria-label': ariaLabel,
        onDrop: onDrop as React.DragEventHandler,
        onDragOver: onDragOver as React.DragEventHandler,
      },
      // Render the current node ids so assertions can see on-canvas nodes.
      ...((nodes as { id: string }[] | undefined) ?? []).map((n) =>
        React.createElement('div', { key: n.id, 'data-rf-node': n.id }, n.id),
      ),
      children as React.ReactNode,
    )
  }
  const Background = () => null
  const Controls = () => null
  const Handle = () => null
  const useReactFlow = () => ({
    getNodes: () => [],
    getEdges: () => [],
  })
  return {
    ReactFlow,
    ReactFlowProvider,
    Background,
    Controls,
    Handle,
    Position,
    useReactFlow,
    addEdge: (edge: unknown, edges: unknown[]) => [...edges, edge],
    applyNodeChanges: (_changes: unknown, nodes: unknown) => nodes,
    applyEdgeChanges: (_changes: unknown, edges: unknown) => edges,
  }
})

// ---------------------------------------------------------------------------
// Generated SDTM hook stubs. The mutable `sdtmApi` object drives the behaviour
// each test needs. These cover both the DerivationPlanPanel's own hooks and the
// nested DerivationPreviewLineagePanel's (preview/validate/lineage) so the real
// panel can render end-to-end.
// ---------------------------------------------------------------------------
interface MutationCall {
  vars: unknown
  request: unknown
}

const sdtmApi: {
  plan: PlanResponse | undefined
  planError: AxiosError | null
  spec: { revision: number } | undefined
  input: { revision: number; state?: string } | undefined
  putPlanImpl: (vars: { sdtmId: string; data: SdtmDerivationPlan }) => Promise<unknown>
  putPlanCalls: MutationCall[]
} = {
  plan: undefined,
  planError: null,
  spec: undefined,
  input: undefined,
  putPlanImpl: async () => ({}),
  putPlanCalls: [],
}

vi.mock('@/api/generated/sdtm/sdtm', () => {
  const useGetPlan = () => ({
    data: sdtmApi.plan,
    error: sdtmApi.planError,
    isLoading: false,
    isError: !!sdtmApi.planError,
  })
  const useGetSpecification = () => ({
    data: sdtmApi.spec,
    error: null,
    isLoading: false,
    isError: false,
  })
  const useGetInputSelection = () => ({
    data: sdtmApi.input,
    error: null,
    isLoading: false,
    isError: false,
  })
  const usePutPlan = (options?: {
    mutation?: { onSuccess?: (data: unknown) => void }
    request?: unknown
  }) => {
    const [isPending, setIsPending] = React.useState(false)
    return {
      isPending,
      error: null as AxiosError | null,
      reset: () => {},
      mutate: () => {},
      mutateAsync: async (vars: { sdtmId: string; data: SdtmDerivationPlan }) => {
        setIsPending(true)
        try {
          sdtmApi.putPlanCalls.push({ vars, request: options?.request })
          const data = await sdtmApi.putPlanImpl(vars)
          options?.mutation?.onSuccess?.(data)
          return data
        } finally {
          setIsPending(false)
        }
      },
    }
  }
  // Nested DerivationPreviewLineagePanel hooks (unused assertions, but needed
  // so the panel renders).
  const idleMutation = () => ({
    isPending: false,
    error: null,
    data: undefined,
    mutate: () => {},
    mutateAsync: async () => ({}),
    reset: () => {},
  })
  const useValidatePlan = () => idleMutation()
  const usePreviewPlan = () => idleMutation()
  const useGetLineage = () => ({
    data: undefined,
    error: null,
    isLoading: false,
    isError: false,
  })
  return {
    useGetPlan,
    useGetSpecification,
    useGetInputSelection,
    usePutPlan,
    useValidatePlan,
    usePreviewPlan,
    useGetLineage,
    getGetPlanQueryKey: (sdtmId: string) => ['/sdtms', sdtmId, 'derivation-plan'],
  }
})

// ---------------------------------------------------------------------------
// Imports AFTER the mocks so the components bind to the stubs.
// ---------------------------------------------------------------------------
import { NodeInspector } from './node-inspector'
import { DerivationPlanGraph } from './derivation-plan-graph'
import { createNode } from './operator-catalog'
import type { PlanGraphEdge, PlanGraphNode } from '../plan-graph-adapters'
import { DerivationPlanPanel } from '../derivation-plan-panel'
import { WorkbenchContextProvider } from '../workbench-context'
import type { WorkbenchContextValue } from '../workbench-context'

const AGGREGATE_REVISION = 7

function makeAggregate(
  overrides: Partial<AggregateResponse> = {},
): AggregateResponse {
  return {
    id: 'sdtm-1',
    study_id: 'study-1',
    code: 'SDTM1',
    name: 'First SDTM workbench',
    status: 'draft',
    revision: AGGREGATE_REVISION,
    ...overrides,
  }
}

function makeWorkbenchValue(
  aggregate: AggregateResponse,
): WorkbenchContextValue {
  return {
    aggregate,
    revision: aggregate.revision,
    studyId: aggregate.study_id,
    ifMatch: () => ifMatchRequest(aggregate.revision),
  }
}

function renderInWorkbench(
  ui: ReactNode,
  aggregate: AggregateResponse = makeAggregate(),
) {
  const qc = new QueryClient({
    defaultOptions: { queries: { retry: false }, mutations: { retry: false } },
  })
  const invalidateSpy = vi.spyOn(qc, 'invalidateQueries')
  const utils = render(
    <QueryClientProvider client={qc}>
      <WorkbenchContextProvider value={makeWorkbenchValue(aggregate)}>
        {ui}
      </WorkbenchContextProvider>
    </QueryClientProvider>,
  )
  return { ...utils, qc, invalidateSpy }
}

function problemError(status: number, body: Record<string, unknown>): AxiosError {
  return {
    isAxiosError: true,
    message: 'Request failed',
    response: { status, data: body },
  } as unknown as AxiosError
}

/** A plan with pinned spec rev 3 / input rev 2 and a 2-node body. */
function makePlan(overrides: Partial<PlanResponse> = {}): PlanResponse {
  const read = createNode('raw_read', 'read1')
  const write = createNode('domain_write', 'write1')
  return {
    id: 'plan-1',
    aggregate_id: 'sdtm-1',
    revision: 4,
    schema_version: '1.0.0',
    specification_revision: 3,
    input_selection_revision: 2,
    state: 'aligned',
    fingerprint: 'fp-plan',
    created_by: 'user-1',
    created_at: '2024-01-01T00:00:00Z',
    payload: {
      nodes: [read, write],
      edges: [{ source_node: 'read1', target_node: 'write1' }],
    } as unknown as PlanResponse['payload'],
    ...overrides,
  }
}

beforeEach(() => {
  sdtmApi.plan = undefined
  sdtmApi.planError = null
  sdtmApi.spec = { revision: 3 }
  sdtmApi.input = { revision: 2, state: 'current' }
  sdtmApi.putPlanImpl = async () => ({})
  sdtmApi.putPlanCalls = []
})

afterEach(() => {
  vi.clearAllMocks()
})

// ===========================================================================
// NodeInspector — edits a typed param and reflects it (Req 12.2)
// ===========================================================================
describe('NodeInspector', () => {
  it('edits a typed operator param and emits an updated typed node object', () => {
    const node = createNode('raw_read', 'read1') as RawReadNode
    const onChange = vi.fn()

    render(<NodeInspector node={node} onChange={onChange} />)

    const field = screen.getByLabelText(/raw dataset code/i)
    fireEvent.change(field, { target: { value: 'DM' } })

    // The inspector reflects the edit back as the SAME typed node shape, with
    // only the edited field changed (never a free-text/untyped bag).
    expect(onChange).toHaveBeenCalledTimes(1)
    const next = onChange.mock.calls[0][0] as RawReadNode
    expect(next).toEqual({ node_type: 'raw_read', id: 'read1', raw_dataset_code: 'DM' })
  })

  it('disables every field in read-only mode', () => {
    const node = createNode('raw_read', 'read1') as RawReadNode
    render(<NodeInspector node={node} onChange={vi.fn()} readOnly />)
    expect(
      (screen.getByLabelText(/raw dataset code/i) as HTMLInputElement).disabled,
    ).toBe(true)
  })
})

// ===========================================================================
// DerivationPlanGraph — palette drop adds a typed node (Req 12.1/12.2)
// ===========================================================================
describe('DerivationPlanGraph palette drop', () => {
  it('drops a palette operator onto the canvas as a typed node', async () => {
    let latestNodes: PlanGraphNode[] = []
    let latestEdges: PlanGraphEdge[] = []

    function Harness() {
      const [nodes, setNodes] = React.useState<PlanGraphNode[]>([])
      const [edges, setEdges] = React.useState<PlanGraphEdge[]>([])
      latestNodes = nodes
      latestEdges = edges
      return (
        <DerivationPlanGraph
          nodes={nodes}
          edges={edges}
          onNodesChange={setNodes}
          onEdgesChange={setEdges}
          generateNodeId={() => 'dropped-node'}
        />
      )
    }

    const { container } = render(<Harness />)

    // The palette entry for the Filter operator.
    const paletteItem = screen.getByRole('button', { name: /add filter node/i })

    // A DataTransfer whose get/setData actually round-trips the operator mime
    // (the jsdom DataTransfer shim's get/setData are no-ops, which would drop
    // the palette payload). This models the native drag the palette performs.
    const store: Record<string, string> = {}
    const dataTransfer = {
      setData: (type: string, value: string) => {
        store[type] = value
      },
      getData: (type: string) => store[type] ?? '',
      dropEffect: 'move',
      effectAllowed: 'move',
    } as unknown as DataTransfer

    fireEvent.dragStart(paletteItem, { dataTransfer })

    const canvas = container.querySelector('.react-flow') as HTMLElement
    expect(canvas).toBeTruthy()

    // Retry the drop inside waitFor until the editor's instance is ready and the
    // typed node lands on the canvas.
    await waitFor(
      () => {
        fireEvent.dragOver(canvas, { dataTransfer })
        fireEvent.drop(canvas, { dataTransfer, clientX: 120, clientY: 80 })
        expect(latestNodes).toHaveLength(1)
      },
      { timeout: 4000 },
    )
    // The dropped node is a fully-typed filter operator object.
    const dropped = latestNodes[0]
    expect(dropped.id).toBe('dropped-node')
    expect(dropped.type).toBe('filter')
    expect(dropped.data).toMatchObject({ node_type: 'filter', id: 'dropped-node' })
    expect(latestEdges).toHaveLength(0)
  })
})

// ===========================================================================
// DerivationPlanPanel — save / 409 stale / misaligned (Req 12.1/12.3/12.4)
// ===========================================================================
describe('DerivationPlanPanel', () => {
  it('save issues the PUT with the aggregate If-Match + pinned revisions (Req 12.1)', async () => {
    sdtmApi.plan = makePlan()
    sdtmApi.putPlanImpl = vi.fn(async () => makePlan({ revision: 5 }))

    renderInWorkbench(<DerivationPlanPanel sdtmId="sdtm-1" />)

    fireEvent.click(screen.getByRole('button', { name: /save plan/i }))

    await waitFor(() => {
      expect(sdtmApi.putPlanCalls.length).toBe(1)
    })

    const call = sdtmApi.putPlanCalls[0]
    expect((call.vars as { sdtmId: string }).sdtmId).toBe('sdtm-1')
    const data = (call.vars as { data: SdtmDerivationPlan }).data
    // The serialized body pins the exact spec/input revisions the plan is
    // authored against and round-trips the typed nodes/edges.
    expect(data.specification_revision).toBe(3)
    expect(data.input_selection_revision).toBe(2)
    expect(data.schema_version).toBe('1.0.0')
    expect(data.nodes.map((n) => n.id)).toEqual(['read1', 'write1'])
    expect(data.edges).toEqual([{ source_node: 'read1', target_node: 'write1' }])

    // The mutation carried the aggregate ETag as If-Match (the single SDTM
    // concurrency token).
    const request = call.request as AxiosRequestConfig
    expect(request).toEqual(ifMatchRequest(AGGREGATE_REVISION))
    expect(request.headers?.['If-Match']).toBe(`"revision-${AGGREGATE_REVISION}"`)
  })

  it('a 409 stale_input_fingerprint names the drifted input and keeps on-canvas edits (Req 12.3)', async () => {
    sdtmApi.plan = makePlan()
    // The Specification has drifted (pinned 3, now 4); the input is unchanged.
    sdtmApi.spec = { revision: 4 }
    sdtmApi.input = { revision: 2 }
    sdtmApi.putPlanImpl = vi.fn(async () => {
      throw problemError(409, {
        code: 'stale_input_fingerprint',
        detail: 'A pinned input is no longer current.',
      })
    })

    renderInWorkbench(<DerivationPlanPanel sdtmId="sdtm-1" />)

    // The canvas renders the loaded plan's nodes (edits are "on canvas").
    await waitFor(() => {
      expect(screen.getByText('read1')).toBeTruthy()
    })

    fireEvent.click(screen.getByRole('button', { name: /save plan/i }))

    await waitFor(() => {
      expect(sdtmApi.putPlanImpl).toHaveBeenCalledTimes(1)
    })

    // The stale-input notice identifies the Specification specifically…
    await waitFor(() => {
      expect(screen.getByText(/pinned input is stale/i)).toBeTruthy()
    })
    expect(screen.getByText(/the specification changed/i)).toBeTruthy()
    expect(
      screen.getByText(/your on-canvas edits are kept/i),
    ).toBeTruthy()

    // …and the on-canvas graph is retained (the loaded node is still rendered;
    // the panel did NOT re-seed/discard the edits).
    expect(screen.getByText('read1')).toBeTruthy()
    expect(screen.getByText('write1')).toBeTruthy()
  })

  it('renders the editor read-only with the AlignmentBanner when misaligned (Req 12.4)', () => {
    sdtmApi.plan = makePlan({ state: 'misaligned' })

    renderInWorkbench(<DerivationPlanPanel sdtmId="sdtm-1" />)

    // The persistent misalignment banner is shown.
    const banners = document.querySelectorAll('[data-slot="alignment-banner"]')
    expect(banners.length).toBeGreaterThan(0)
    expect(screen.getByText(/derivation plan is misaligned/i)).toBeTruthy()

    // Save is disabled while misaligned (read-only).
    expect(
      (screen.getByRole('button', { name: /save plan/i }) as HTMLButtonElement)
        .disabled,
    ).toBe(true)

    // The palette is hidden in read-only mode (no operator palette landmark).
    expect(screen.queryByLabelText(/operator palette/i)).toBeNull()
  })
})

// ===========================================================================
// DerivationPlanPanel — new-plan mode (first-plan bootstrap)
// ===========================================================================
describe('DerivationPlanPanel new-plan mode', () => {
  const planRequired = () =>
    problemError(404, {
      code: 'sdtm_derivation_plan_required',
      detail: 'SDTM Derivation Plan is not saved.',
    })

  it('404 + current spec/input renders the interactive editor (not just the empty state)', () => {
    sdtmApi.plan = undefined
    sdtmApi.planError = planRequired()
    sdtmApi.spec = { revision: 3 }
    sdtmApi.input = { revision: 2, state: 'current' }

    renderInWorkbench(<DerivationPlanPanel sdtmId="sdtm-1" />)

    // The interactive editor mounts (palette present, canvas present) instead
    // of returning early at the "No derivation plan yet" empty state.
    expect(screen.getByLabelText(/operator palette/i)).toBeTruthy()
    expect(screen.getByLabelText(/derivation plan graph editor/i)).toBeTruthy()
    expect(screen.queryByText(/no derivation plan yet/i)).toBeNull()

    // The header shows the unsaved new-plan state pinning the current revisions.
    expect(screen.getByText(/new plan \(unsaved\)/i)).toBeTruthy()

    // Save is enabled (new plans are editable, not read-only).
    expect(
      (screen.getByRole('button', { name: /save plan/i }) as HTMLButtonElement)
        .disabled,
    ).toBe(false)
  })

  it('404 + missing/not-current prerequisites keeps the guidance empty state', () => {
    sdtmApi.plan = undefined
    sdtmApi.planError = planRequired()
    // Specification present, but the input selection is NOT current.
    sdtmApi.spec = { revision: 3 }
    sdtmApi.input = { revision: 2, state: 'input_refresh_required' }

    renderInWorkbench(<DerivationPlanPanel sdtmId="sdtm-1" />)

    // The guidance empty state is kept; the editor does NOT mount.
    expect(screen.getByText(/no derivation plan yet/i)).toBeTruthy()
    expect(screen.queryByLabelText(/operator palette/i)).toBeNull()
    expect(screen.queryByLabelText(/derivation plan graph editor/i)).toBeNull()
  })

  it('404 + missing specification keeps the guidance empty state', () => {
    sdtmApi.plan = undefined
    sdtmApi.planError = planRequired()
    // No current specification yet.
    sdtmApi.spec = undefined
    sdtmApi.input = { revision: 2, state: 'current' }

    renderInWorkbench(<DerivationPlanPanel sdtmId="sdtm-1" />)

    expect(screen.getByText(/no derivation plan yet/i)).toBeTruthy()
    expect(screen.queryByLabelText(/operator palette/i)).toBeNull()
  })

  it('first save issues PUT pinned to the CURRENT spec/input revisions with the aggregate If-Match', async () => {
    sdtmApi.plan = undefined
    sdtmApi.planError = planRequired()
    sdtmApi.spec = { revision: 5 }
    sdtmApi.input = { revision: 9, state: 'current' }
    sdtmApi.putPlanImpl = vi.fn(async () => ({}))

    const { container } = renderInWorkbench(<DerivationPlanPanel sdtmId="sdtm-1" />)

    // Author the first node by dropping a palette operator onto the canvas so
    // the save body carries at least one node (the backend rejects zero nodes).
    const paletteItem = screen.getByRole('button', { name: /add raw read node/i })
    const store: Record<string, string> = {}
    const dataTransfer = {
      setData: (type: string, value: string) => {
        store[type] = value
      },
      getData: (type: string) => store[type] ?? '',
      dropEffect: 'move',
      effectAllowed: 'move',
    } as unknown as DataTransfer

    fireEvent.dragStart(paletteItem, { dataTransfer })
    const canvas = container.querySelector('.react-flow') as HTMLElement
    await waitFor(
      () => {
        fireEvent.dragOver(canvas, { dataTransfer })
        fireEvent.drop(canvas, { dataTransfer, clientX: 100, clientY: 60 })
        expect(container.querySelectorAll('[data-rf-node]').length).toBe(1)
      },
      { timeout: 4000 },
    )

    fireEvent.click(screen.getByRole('button', { name: /save plan/i }))

    await waitFor(() => {
      expect(sdtmApi.putPlanCalls.length).toBe(1)
    })

    const call = sdtmApi.putPlanCalls[0]
    const data = (call.vars as { data: SdtmDerivationPlan }).data
    // The first save pins the CURRENT Specification / Input Selection revisions
    // (there is no loaded plan to read pinned revisions from).
    expect(data.specification_revision).toBe(5)
    expect(data.input_selection_revision).toBe(9)
    expect(data.schema_version).toBe('1.0.0')
    // At least one node was authored before the save.
    expect(data.nodes.length).toBeGreaterThanOrEqual(1)

    // The mutation carried the aggregate ETag as If-Match.
    const request = call.request as AxiosRequestConfig
    expect(request).toEqual(ifMatchRequest(AGGREGATE_REVISION))
    expect(request.headers?.['If-Match']).toBe(`"revision-${AGGREGATE_REVISION}"`)
  })

  it('surfaces a toast when the backend rejects a save (e.g. zero nodes -> 422)', async () => {
    const { toast } = await import('sonner')
    sdtmApi.plan = undefined
    sdtmApi.planError = planRequired()
    sdtmApi.spec = { revision: 3 }
    sdtmApi.input = { revision: 2, state: 'current' }
    sdtmApi.putPlanImpl = vi.fn(async () => {
      throw problemError(422, {
        title: 'Invalid derivation plan',
        detail: 'A derivation plan requires at least one node.',
      })
    })

    renderInWorkbench(<DerivationPlanPanel sdtmId="sdtm-1" />)

    // Save with an empty canvas (zero nodes) -> backend 422 -> toast.
    fireEvent.click(screen.getByRole('button', { name: /save plan/i }))

    await waitFor(() => {
      expect(sdtmApi.putPlanImpl).toHaveBeenCalledTimes(1)
    })
    await waitFor(() => {
      expect(toast.error).toHaveBeenCalledWith(
        'A derivation plan requires at least one node.',
      )
    })
  })
})
