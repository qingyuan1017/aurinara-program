// @vitest-environment jsdom
//
// Component + unit tests for the SDTM derivation preview / inline-validation /
// read-only lineage panel (`derivation-preview-lineage-panel.tsx`) — task 13.3.
//
// Coverage:
//   Preview (Requirements 13.1, 13.2, 13.3, 13.4, 13.5):
//     * the limit is CONSTRAINED to 1-200 before the request is sent (R13.2);
//     * produced per-domain outputs render together with the resolved
//       specification / plan / input-selection revisions (R13.1, R13.3);
//     * a requested domain that produced zero rows shows an explicit
//       per-domain empty indication (R13.3);
//     * a `422 sdtm_preview_domain_unknown` lists which requested domains the
//       plan did not produce (R13.4);
//     * rows live only in local state — unmount/remount shows no stale rows and
//       re-issues no request (no persistence/caching beyond the view, R13.5).
//   Lineage (Requirement 12.7, exercised here as the read-only graph):
//     * `lineageToGraph` is unit-tested as a pure transform (nodes/edges);
//     * the panel renders a read-only React Flow graph (no connect handles).
//   Validation (Requirements 14.1-14.5): covered in the sibling SDTM validation
//     panel suite.
//
// Mirrors the established generated-hook mock pattern (no MSW in the repo): the
// three plan hooks are mocked with faithful fakes and the REAL panel is driven
// over them. The jsdom harness installs ResizeObserver + element-dimension
// mocks so React Flow's lineage canvas measures without a layout engine.
import {
  fireEvent,
  render,
  screen,
  waitFor,
  within,
} from '@testing-library/react'
import {
  afterEach,
  beforeAll,
  beforeEach,
  describe,
  expect,
  it,
  vi,
} from 'vitest'
import type { ReactNode } from 'react'
import type { AxiosError } from 'axios'
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'

import { installJsdomHarness } from '@/test/jsdom-harness'

beforeAll(() => {
  installJsdomHarness()
})

// ---------------------------------------------------------------------------
// Mutable fixtures the generated-hook stubs read through.
// ---------------------------------------------------------------------------
interface PreviewCall {
  sdtmId: string
  data: { limit?: number; domains?: string[] }
}

const sdtmApi: {
  previewImpl: (vars: PreviewCall) => Promise<unknown>
  previewCalls: PreviewCall[]
  previewRequests: unknown[]
  validateImpl: (vars: { sdtmId: string }) => Promise<unknown>
  validateCalls: Array<{ sdtmId: string }>
  lineage: { data?: unknown; isLoading: boolean; isError: boolean; error: unknown }
  lineageEnabled: boolean[]
} = {
  previewImpl: async () => makePreviewResult(),
  previewCalls: [],
  previewRequests: [],
  validateImpl: async () => ({ status: 'valid', ir_fingerprint: 'ir-abc' }),
  validateCalls: [],
  lineage: { data: undefined, isLoading: false, isError: false, error: null },
  lineageEnabled: [],
}

/**
 * A minimal `UseMutationResult`-shaped object whose `mutateAsync` runs the
 * scripted impl, so the panel's `await mutateAsync(...)` + local-state path
 * exercises for real (the panel uses a mutation, never a query — the no-cache
 * guarantee).
 */
function makeMutationResult(impl: (vars: never) => Promise<unknown>) {
  return {
    isPending: false,
    error: null as AxiosError | null,
    mutate: () => {},
    mutateAsync: async (vars: never) => impl(vars),
  }
}

vi.mock('@/api/generated/sdtm/sdtm', () => {
  const usePreviewPlan = (options?: { request?: unknown }) => {
    sdtmApi.previewRequests.push(options?.request)
    return makeMutationResult((vars: PreviewCall) => {
      sdtmApi.previewCalls.push(vars)
      return sdtmApi.previewImpl(vars)
    })
  }

  const useValidatePlan = () =>
    makeMutationResult((vars: { sdtmId: string }) => {
      sdtmApi.validateCalls.push(vars)
      return sdtmApi.validateImpl(vars)
    })

  const useGetLineage = (
    _sdtmId: string,
    options?: { query?: { enabled?: boolean } },
  ) => {
    sdtmApi.lineageEnabled.push(options?.query?.enabled ?? true)
    return sdtmApi.lineage
  }

  return { usePreviewPlan, useValidatePlan, useGetLineage }
})

// ---------------------------------------------------------------------------
// Import AFTER the mock so the panel binds to the stubs. `lineageToGraph` and
// `unknownFromProblem` are pure exports and unaffected by the mock.
// ---------------------------------------------------------------------------
import {
  DerivationPreviewLineagePanel,
  lineageToGraph,
  unknownFromProblem,
} from './derivation-preview-lineage-panel'
import { jsonRequest } from '@/lib/requests'

function renderWithClient(ui: ReactNode) {
  const qc = new QueryClient({
    defaultOptions: { queries: { retry: false }, mutations: { retry: false } },
  })
  return render(<QueryClientProvider client={qc}>{ui}</QueryClientProvider>)
}

interface PreviewResultShape {
  specification_revision?: number
  plan_revision?: number
  input_selection_revision?: number
  limit?: number
  ir_fingerprint?: string
  outputs: Record<string, Array<Record<string, unknown>>>
}

function makePreviewResult(
  overrides: Partial<PreviewResultShape> = {},
): PreviewResultShape {
  return {
    specification_revision: 4,
    plan_revision: 7,
    input_selection_revision: 2,
    limit: 50,
    ir_fingerprint: 'ir-123',
    outputs: {
      DM: [
        { USUBJID: '001', AGE: 42 },
        { USUBJID: '002', AGE: 37 },
      ],
    },
    ...overrides,
  }
}

function problemError(
  status: number,
  body: Record<string, unknown>,
): AxiosError {
  return {
    isAxiosError: true,
    message: 'Request failed',
    response: { status, data: body },
  } as unknown as AxiosError
}

beforeEach(() => {
  sdtmApi.previewImpl = async () => makePreviewResult()
  sdtmApi.previewCalls = []
  sdtmApi.previewRequests = []
  sdtmApi.validateImpl = async () => ({ status: 'valid', ir_fingerprint: 'ir-abc' })
  sdtmApi.validateCalls = []
  sdtmApi.lineage = { data: undefined, isLoading: false, isError: false, error: null }
  sdtmApi.lineageEnabled = []
})

afterEach(() => {
  vi.clearAllMocks()
})

function renderPanel(disabled = false) {
  return renderWithClient(
    <DerivationPreviewLineagePanel sdtmId="sdtm-1" disabled={disabled} />,
  )
}

// ===========================================================================
// Preview: constrained limit + rendered outputs/revisions (Req 13.1, 13.2, 13.3)
// ===========================================================================
describe('Preview constrains the limit and renders outputs + revisions (Req 13.1-13.3)', () => {
  it('clamps an over-ceiling limit to 200 before sending and omits domains when none chosen', async () => {
    sdtmApi.previewImpl = vi.fn(async () =>
      makePreviewResult({ limit: 200 }),
    )

    renderPanel()

    // Over-ceiling limit is constrained on submit (R13.2).
    fireEvent.change(screen.getByLabelText(/limit/i), {
      target: { value: '5000' },
    })
    fireEvent.click(screen.getByRole('button', { name: /^preview$/i }))

    await waitFor(() => expect(sdtmApi.previewCalls.length).toBe(1))
    const call = sdtmApi.previewCalls[0]
    expect(call.sdtmId).toBe('sdtm-1')
    // limit clamped 5000 -> 200; no `domains` key sent when the field is blank.
    expect(call.data).toEqual({ limit: 200 })
    expect('domains' in call.data).toBe(false)
    // The preview hook was wired with the JSON request config.
    expect(sdtmApi.previewRequests.at(-1)).toEqual(jsonRequest())

    // Produced domain output + resolved revisions render (R13.1, R13.3).
    await waitFor(() => expect(screen.getByText('001')).toBeTruthy())
    expect(screen.getByText('002')).toBeTruthy()
    const revs = screen.getByText('Specification revision').closest('dl') as HTMLElement
    expect(within(revs).getByText('Specification revision')).toBeTruthy()
    expect(within(revs).getByText('Plan revision')).toBeTruthy()
    expect(within(revs).getByText('Input Selection revision')).toBeTruthy()
    // The pinned revision values are shown.
    expect(within(revs).getByText('4')).toBeTruthy()
    expect(within(revs).getByText('7')).toBeTruthy()
    expect(within(revs).getByText('2')).toBeTruthy()
  })

  it('clamps a sub-floor limit up to 1 and sends the optional domain selection', async () => {
    sdtmApi.previewImpl = vi.fn(async () =>
      makePreviewResult({ limit: 1, outputs: { DM: [{ USUBJID: '001' }] } }),
    )

    renderPanel()

    fireEvent.change(screen.getByLabelText(/limit/i), { target: { value: '0' } })
    fireEvent.change(screen.getByLabelText(/domains/i), {
      target: { value: 'DM, LB' },
    })
    fireEvent.click(screen.getByRole('button', { name: /^preview$/i }))

    await waitFor(() => expect(sdtmApi.previewCalls.length).toBe(1))
    // limit 0 -> 1 (R13.2); trimmed domain selection included (R13.1).
    expect(sdtmApi.previewCalls[0].data).toEqual({
      limit: 1,
      domains: ['DM', 'LB'],
    })
  })
})

// ===========================================================================
// Preview: per-domain empty-result indication (Req 13.3)
// ===========================================================================
describe('Preview per-domain empty indication (Req 13.3)', () => {
  it('renders an explicit empty-result message for a requested domain with zero rows', async () => {
    // LB produces no rows; DM produces one. Both were explicitly requested.
    sdtmApi.previewImpl = vi.fn(async () =>
      makePreviewResult({
        outputs: { DM: [{ USUBJID: '001' }], LB: [] },
      }),
    )

    renderPanel()
    fireEvent.change(screen.getByLabelText(/domains/i), {
      target: { value: 'DM, LB' },
    })
    fireEvent.click(screen.getByRole('button', { name: /^preview$/i }))

    await waitFor(() => expect(screen.getByText('001')).toBeTruthy())
    // The empty domain renders its explicit per-domain empty indication.
    const emptyNotes = document.querySelectorAll('[data-slot="domain-empty"]')
    expect(emptyNotes.length).toBe(1)
    expect(emptyNotes[0].textContent).toMatch(/no rows for/i)
    // Both requested domains are shown with their row-count badges.
    expect(screen.getByText('0 rows')).toBeTruthy()
    expect(screen.getByText('1 rows')).toBeTruthy()
  })
})

// ===========================================================================
// Preview: 422 sdtm_preview_domain_unknown lists unproduced domains (Req 13.4)
// ===========================================================================
describe('Preview 422 unknown-domain report (Req 13.4)', () => {
  it('lists which requested domains the plan did not produce', async () => {
    sdtmApi.previewImpl = vi.fn(async () => {
      throw problemError(422, {
        title: 'Unprocessable Entity',
        code: 'sdtm_preview_domain_unknown',
        detail: 'The plan did not produce: LB, VS.',
      })
    })

    renderPanel()
    fireEvent.change(screen.getByLabelText(/domains/i), {
      target: { value: 'DM, LB, VS' },
    })
    fireEvent.click(screen.getByRole('button', { name: /^preview$/i }))

    await waitFor(() => expect(screen.getByRole('alert')).toBeTruthy())
    // The problem detail is surfaced…
    expect(screen.getByText(/did not produce: LB, VS/i)).toBeTruthy()
    // …and the unproduced domains are listed individually (R13.4).
    const alert = screen.getByRole('alert')
    const items = within(alert).getAllByRole('listitem')
    expect(items.length).toBe(2)
    expect(items[0].textContent).toContain('LB')
    expect(items[1].textContent).toContain('VS')
    // No output table rendered on the failed preview.
    expect(screen.queryByText('001')).toBeNull()
  })
})

// ===========================================================================
// Preview: no persistence/caching beyond the view (Req 13.5)
// ===========================================================================
describe('Preview rows are not cached beyond the view (Req 13.5)', () => {
  it('unmounting then remounting shows no stale rows and issues no request', async () => {
    sdtmApi.previewImpl = vi.fn(async () => makePreviewResult())

    const first = renderPanel()
    fireEvent.click(screen.getByRole('button', { name: /^preview$/i }))
    await waitFor(() => expect(screen.getByText('001')).toBeTruthy())

    first.unmount()

    const callsBeforeRemount = sdtmApi.previewCalls.length
    renderPanel()
    // Nothing from the prior preview survives (R13.5).
    expect(screen.queryByText('001')).toBeNull()
    expect(screen.getByText(/no preview loaded/i)).toBeTruthy()
    // No new preview request was issued on remount.
    expect(sdtmApi.previewCalls.length).toBe(callsBeforeRemount)
  })
})

// ===========================================================================
// Preview is disabled when the plan is misaligned (Req 12.4 gate)
// ===========================================================================
describe('Preview/validate controls honour the alignment gate', () => {
  it('disables the preview and validate buttons when disabled', () => {
    renderPanel(true)
    expect(
      (screen.getByRole('button', { name: /^preview$/i }) as HTMLButtonElement)
        .disabled,
    ).toBe(true)
    expect(
      (screen.getByRole('button', { name: /validate plan/i }) as HTMLButtonElement)
        .disabled,
    ).toBe(true)
  })
})

// ===========================================================================
// Lineage: read-only graph (Req 12.7) + pure lineageToGraph transform
// ===========================================================================
describe('lineageToGraph pure transform', () => {
  it('returns no nodes/edges for a null or empty lineage', () => {
    expect(lineageToGraph(null)).toEqual({ nodes: [], edges: [] })
    expect(lineageToGraph({ outputs: {} })).toEqual({ nodes: [], edges: [] })
  })

  it('maps datasets + ancestors to read-only, non-connectable nodes and ancestor->dataset edges', () => {
    const { nodes, edges } = lineageToGraph({
      outputs: {
        DM: ['raw_dm', 'raw_sv'],
        LB: ['raw_lb'],
      },
    })

    const ids = nodes.map((n) => n.id).sort()
    // Every referenced id becomes a node: 2 datasets + 3 distinct ancestors.
    expect(ids).toEqual(['DM', 'LB', 'raw_dm', 'raw_lb', 'raw_sv'])
    // Nodes are read-only (not draggable, not connectable).
    for (const node of nodes) {
      expect(node.draggable).toBe(false)
      expect(node.connectable).toBe(false)
    }

    // One edge per ancestor->dataset relationship.
    const edgeIds = edges.map((e) => e.id).sort()
    expect(edgeIds).toEqual(['raw_dm->DM', 'raw_lb->LB', 'raw_sv->DM'])
    for (const edge of edges) {
      // The target is always a produced dataset.
      expect(['DM', 'LB']).toContain(edge.target)
    }
  })
})

describe('Lineage renders a read-only graph (Req 12.7)', () => {
  it('renders the React Flow lineage graph when lineage data is present and the plan is aligned', async () => {
    sdtmApi.lineage = {
      data: { ir_fingerprint: 'ir-9', outputs: { DM: ['raw_dm'] } },
      isLoading: false,
      isError: false,
      error: null,
    }

    const { container } = renderPanel(false)

    // Lineage query is enabled only while the plan is aligned (not disabled).
    expect(sdtmApi.lineageEnabled.every((e) => e === true)).toBe(true)
    // The read-only React Flow canvas renders (aria-label from the panel).
    await waitFor(() =>
      expect(
        container.querySelector(
          '[aria-label="Derivation plan lineage graph (read-only)"]',
        ),
      ).toBeTruthy(),
    )
  })

  it('gates the lineage query off and shows the unavailable state when the plan is misaligned', () => {
    sdtmApi.lineage = {
      data: { outputs: { DM: ['raw_dm'] } },
      isLoading: false,
      isError: false,
      error: null,
    }
    renderPanel(true)
    // The lineage query is gated off (enabled=false) when disabled/misaligned.
    expect(sdtmApi.lineageEnabled.every((e) => e === false)).toBe(true)
    expect(screen.getByText(/lineage unavailable/i)).toBeTruthy()
  })
})

// ===========================================================================
// unknownFromProblem pure helper
// ===========================================================================
describe('unknownFromProblem', () => {
  it('intersects the parsed unproduced names with the requested domains', () => {
    expect(
      unknownFromProblem('The plan did not produce: LB, VS.', ['DM', 'LB', 'VS']),
    ).toEqual(['LB', 'VS'])
  })

  it('falls back to the requested set when the detail cannot be parsed', () => {
    expect(unknownFromProblem(undefined, ['DM', 'LB'])).toEqual(['DM', 'LB'])
    expect(unknownFromProblem('nothing matches here', ['DM'])).toEqual(['DM'])
  })
})
