// @vitest-environment jsdom
//
// Component tests for the SDTM workbench list/create screen (`sdtm/index.tsx`)
// and the tabbed SDTM workbench detail shell (`sdtm/$sdtmId.tsx`) — task 10.3.
//
// Coverage (Requirements 9.1, 9.2, 9.3, 9.4, 9.5):
//   * cursor pagination requests a limit within 1-50 and follows `next_cursor`
//     while there are more pages (9.1);
//   * a successful create refreshes the list (invalidates the list key) (9.2);
//   * a `problem+json` create retains the entered form values and does NOT
//     refresh the list (9.5);
//   * study-scope gating renders the empty state and issues NO list request
//     when no study is selected (9.4);
//   * every one of the ten SDTM tabs is individually reachable via the `?tab=`
//     search param so a refresh or deep link lands on the right section —
//     `validateSearch` narrows unknown/missing values to the first tab, and the
//     shell resolves the active tab from the param (9.3).
//
// Mirrors the Raw screen tests (`raw/-raw-screens.test.tsx`): the repo mocks the
// generated Orval hooks + study provider rather than running a network layer
// (no MSW is installed), and partially mocks `@tanstack/react-router` so the
// REAL route components render over faithful fakes. The two real panels that
// the detail shell wires (InputSelectionPanel + SpecificationPanel) are mocked
// so the shell tests stay focused on list/create/tab routing.
import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import {
  afterEach,
  beforeAll,
  beforeEach,
  describe,
  expect,
  it,
  vi,
} from "vitest";
import type { ReactNode } from "react";
import type { AxiosError } from "axios";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";

import { installJsdomHarness } from "@/test/jsdom-harness";
import type {
  AggregateCollection,
  AggregateResponse,
} from "@/api/generated/model";

beforeAll(() => {
  installJsdomHarness();
});

// ---------------------------------------------------------------------------
// Router stub. The route modules call `createFileRoute(...)({ component, ... })`,
// `useNavigate()`, `Route.useParams()`, `Route.useSearch()`, and render `<Link>`.
// jsdom has no router, so we provide the minimum surface. `createFileRoute`
// returns a factory that records the route options (so the real `validateSearch`
// is reachable) and exposes `useParams`/`useSearch` reading shared fixtures.
// ---------------------------------------------------------------------------
const navigateSpy = vi.fn();
const routeParams: { sdtmId: string } = { sdtmId: "sdtm-1" };
const routeSearch: { tab: string; domain?: string } = {
  tab: "source-review",
};

vi.mock("@tanstack/react-router", async (importOriginal) => {
  const actual =
    await importOriginal<typeof import("@tanstack/react-router")>();
  const createFileRoute = () => (opts: Record<string, unknown>) => ({
    ...opts,
    useParams: () => routeParams,
    useSearch: () => routeSearch,
  });
  const Link = ({ children, ...rest }: { children?: ReactNode }) => (
    <a {...rest}>{children}</a>
  );
  return {
    ...actual,
    createFileRoute,
    useNavigate: () => navigateSpy,
    Link,
  };
});

// ---------------------------------------------------------------------------
// Study provider stub — mutable so the "no study" gating case can flip it.
// ---------------------------------------------------------------------------
const currentStudyState: { currentStudyId: string | null; isLoading: boolean } =
  {
    currentStudyId: "study-1",
    isLoading: false,
  };
vi.mock("@/components/study-context", () => ({
  useCurrentStudy: () => currentStudyState,
}));

// Keep the toast out of the DOM/theme-provider path under jsdom.
vi.mock("@/components/ui/sonner", () => ({
  toast: { success: vi.fn(), error: vi.fn() },
}));

// ---------------------------------------------------------------------------
// Mock the two real panels the detail shell wires so the shell tests stay
// focused on list/create/tab routing. Each renders a recognizable marker.
// ---------------------------------------------------------------------------
vi.mock("@/features/sdtm/components/input-selection-panel", () => ({
  InputSelectionPanel: () => (
    <div data-testid="input-selection-panel">Input selection panel</div>
  ),
}));
vi.mock("@/features/sdtm/components/specification-panel", () => ({
  SpecificationPanel: ({ sdtmId }: { sdtmId: string }) => (
    <div data-testid="specification-panel">Specification panel {sdtmId}</div>
  ),
}));
vi.mock("@/features/sdtm/components/ai-review-workspace", () => ({
  AiReviewWorkspace: ({
    title,
    reviewPrelude,
    reviewEpilogue,
  }: {
    title: string;
    reviewPrelude?: ReactNode;
    reviewEpilogue?: ReactNode;
  }) => (
    <div data-testid="ai-review-workspace">
      {reviewPrelude}
      {title}
      {reviewEpilogue}
    </div>
  ),
  SdtmStageWorkspace: ({
    title,
    children,
  }: {
    title: string;
    children: ReactNode;
  }) => (
    <div data-testid="sdtm-stage-workspace">
      {title}
      {children}
    </div>
  ),
}));
// The aCRF panel (task 15.1) reads additional generated hooks the list/create
// shell test does not stub; mock it to a marker so the tab-routing assertion
// stays focused on `?tab=` routing (its own behaviour is covered by task 15.3).
vi.mock("@/features/sdtm/components/acrf-panel", () => ({
  AcrfPanel: ({ sdtmId }: { sdtmId: string }) => (
    <div data-testid="acrf-panel">aCRF panel {sdtmId}</div>
  ),
}));
// The remaining wired panels (tasks 12-19) each read additional generated
// hooks this list/create/tab-routing shell test does not stub; mock each to a
// marker so the `?tab=` routing assertions stay focused on routing (their own
// behaviour is covered by their per-panel task tests).
vi.mock("@/features/sdtm/components/mapping-panels", () => ({
  DomainMappingPanel: () => <div>Domain mapping panel</div>,
  VariableMappingPanel: () => <div>Variable mapping panel</div>,
  CodeWorkareasPanel: () => <div>Code workareas panel</div>,
  ProgramArtifactReadinessPanel: () => (
    <div>Program &amp; artifact readiness panel</div>
  ),
}));
vi.mock("@/features/sdtm/components/validation-panel", () => ({
  SdtmValidationPanel: ({ sdtmId }: { sdtmId: string }) => (
    <div data-testid="sdtm-validation-panel">Validation panel {sdtmId}</div>
  ),
}));
vi.mock("@/features/sdtm/components/define-panel", () => ({
  DefinePanel: ({ sdtmId }: { sdtmId: string }) => (
    <div data-testid="define-panel">Define panel {sdtmId}</div>
  ),
}));
vi.mock("@/features/sdtm/components/dependencies-panel", () => ({
  SdtmDependenciesPanel: ({ sdtmId }: { sdtmId: string }) => (
    <div data-testid="sdtm-dependencies-panel">Dependencies panel {sdtmId}</div>
  ),
}));
vi.mock("@/features/sdtm/components/csdrg-panel", () => ({
  CsdrgPanel: ({ sdtmId }: { sdtmId: string }) => (
    <div data-testid="csdrg-panel">cSDRG panel {sdtmId}</div>
  ),
}));

// ---------------------------------------------------------------------------
// Generated SDTM hook stubs. Each test installs the behaviour it needs via the
// mutable `sdtmApi` object the mock reads through.
// ---------------------------------------------------------------------------
interface ListCall {
  studyId: string;
  limit?: number;
  after?: string | null;
}

const sdtmApi: {
  listPages: Record<string, AggregateCollection>;
  listCalls: ListCall[];
  createImpl: (vars: { studyId: string; data: unknown }) => Promise<unknown>;
  aggregate: AggregateResponse | undefined;
  planHeads: { items: Array<{ id: string; domain: string }> };
  specification:
    { revision: number; payload: Record<string, unknown> } | undefined;
  specificationError: AxiosError | null;
} = {
  listPages: {},
  listCalls: [],
  createImpl: async () => ({}),
  aggregate: undefined,
  // One per-domain plan head so the Derivation plan tab's domain selector has a
  // default and mounts the (mocked) per-domain panel for routing assertions.
  planHeads: { items: [{ id: "plan-dm", domain: "DM" }] },
  // The current Specification feeds the second half of the Derivation plan
  // tab's domain union (declared domains that may have no plan yet). Default to
  // a saved spec declaring DM so the union includes the existing plan head's
  // domain without adding spurious extras.
  specification: { revision: 1, payload: { domains: [{ code: "DM" }] } },
  specificationError: null,
};

vi.mock("@/api/generated/sdtm/sdtm", () => {
  // Faithful stand-in for the generated cursor-list query hook: records every
  // (studyId, params) the component (via useCursorList) requests and returns the
  // scripted page for the requested cursor. When the hook is disabled (no study)
  // it records nothing and returns no data, modeling "no request issued".
  const useListSdtmAggregates = (
    studyId: string,
    params: { limit?: number; after?: string | null } | undefined,
    options?: { query?: { enabled?: boolean } },
  ) => {
    const enabled = options?.query?.enabled ?? true;
    if (!enabled) {
      return {
        data: undefined,
        isLoading: false,
        isFetching: false,
        isError: false,
        error: null,
      };
    }
    const after = params?.after ?? null;
    sdtmApi.listCalls.push({ studyId, limit: params?.limit, after });
    const key = after ?? "__first__";
    return {
      data: sdtmApi.listPages[key],
      isLoading: false,
      isFetching: false,
      isError: false,
      error: null,
    };
  };

  const useCreateSdtmAggregate = (options?: {
    mutation?: { onSuccess?: (data: unknown) => void };
  }) => {
    const impl = (vars: { studyId: string; data: unknown }) =>
      sdtmApi.createImpl(vars);
    return makeMutationResult(impl, options?.mutation?.onSuccess);
  };

  const useGetSdtmAggregate = (
    _sdtmId: string,
    options?: { query?: { enabled?: boolean } },
  ) => {
    const enabled = options?.query?.enabled ?? true;
    return {
      data: enabled ? sdtmApi.aggregate : undefined,
      isLoading: false,
      isFetching: false,
      isError: false,
      error: null,
    };
  };

  const useListSdtmPlans = () => ({
    data: sdtmApi.planHeads,
    isLoading: false,
    isFetching: false,
    isError: false,
    error: null,
  });

  // The Derivation plan tab reads the current Specification to union its
  // declared domains with the saved plan heads. A spec error (e.g. a 404
  // "not saved yet") is reported via isError/error and must NOT block the tab.
  const useGetSpecification = () => ({
    data: sdtmApi.specificationError ? undefined : sdtmApi.specification,
    isLoading: false,
    isFetching: false,
    isError: sdtmApi.specificationError !== null,
    error: sdtmApi.specificationError,
  });

  return {
    useListSdtmAggregates,
    getListSdtmAggregatesQueryKey: (studyId?: string) => [
      "/api/v1/studies",
      studyId,
      "sdtms",
    ],
    useCreateSdtmAggregate,
    useGetSdtmAggregate,
    getGetSdtmAggregateQueryKey: (sdtmId: string) => [
      `/api/v1/sdtm-workbenches/${sdtmId}`,
    ],
    useListSdtmPlans,
    useGetSpecification,
  };
});

/**
 * Build a minimal `UseMutationResult`-shaped object whose `mutateAsync` runs
 * the scripted impl and fires `onSuccess` on resolve (mirroring TanStack
 * Query), so the component's refresh-on-success path exercises for real.
 */
function makeMutationResult(
  impl: (vars: never) => Promise<unknown>,
  onSuccess?: (data: unknown) => void,
) {
  return {
    isPending: false,
    error: null as AxiosError | null,
    mutateAsync: async (vars: never) => {
      const data = await impl(vars);
      onSuccess?.(data);
      return data;
    },
    mutate: () => {},
  };
}

// ---------------------------------------------------------------------------
// Imports AFTER the mocks so the route modules bind to the stubs.
// ---------------------------------------------------------------------------
import { Route as SdtmListRoute } from "@/routes/_app/sdtm/index";
import { Route as SdtmDetailRoute } from "@/routes/_app/sdtm/$sdtmId";

const SdtmListPage = (
  SdtmListRoute as unknown as { component: () => ReactNode }
).component;
const SdtmDetailPage = (
  SdtmDetailRoute as unknown as { component: () => ReactNode }
).component;
// The real `validateSearch` recorded by the route factory (Requirement 9.3).
const validateSearch = (
  SdtmDetailRoute as unknown as {
    validateSearch: (search: Record<string, unknown>) => { tab: string };
  }
).validateSearch;

function renderWithClient(ui: ReactNode) {
  const qc = new QueryClient({
    defaultOptions: { queries: { retry: false }, mutations: { retry: false } },
  });
  const invalidateSpy = vi.spyOn(qc, "invalidateQueries");
  const utils = render(
    <QueryClientProvider client={qc}>{ui}</QueryClientProvider>,
  );
  return { ...utils, qc, invalidateSpy };
}

function makeAggregate(
  overrides: Partial<AggregateResponse> = {},
): AggregateResponse {
  return {
    id: "sdtm-1",
    study_id: "study-1",
    code: "SDTM1",
    name: "First SDTM workbench",
    status: "draft",
    revision: 2,
    ...overrides,
  };
}

function problemError(
  status: number,
  body: Record<string, unknown>,
): AxiosError {
  return {
    isAxiosError: true,
    response: { status, data: body },
  } as unknown as AxiosError;
}

// The mapping/code workbench tabs are individually reachable by `?tab=`.
const TAB_VALUES = [
  "source-review",
  "specification",
  "domain-mapping",
  "variable-mapping",
  "program-review",
  "execution",
  "acrf",
  "define-validation",
  "csdrg-submission",
] as const;

const TAB_LABELS: Record<string, string> = {
  "source-review": "1 Source review",
  specification: "2 Specification",
  "domain-mapping": "3 Domain mapping",
  "variable-mapping": "4 Variable & VLM",
  "program-review": "5 Program review",
  execution: "6 Execution",
  acrf: "7 aCRF",
  "define-validation": "8 Define & validation",
  "csdrg-submission": "9 cSDRG & submission",
};

beforeEach(() => {
  sdtmApi.listPages = {};
  sdtmApi.listCalls = [];
  sdtmApi.createImpl = async () => ({});
  sdtmApi.aggregate = makeAggregate();
  sdtmApi.planHeads = { items: [{ id: "plan-dm", domain: "DM" }] };
  sdtmApi.specification = {
    revision: 1,
    payload: { domains: [{ code: "DM" }] },
  };
  sdtmApi.specificationError = null;
  currentStudyState.currentStudyId = "study-1";
  currentStudyState.isLoading = false;
  routeParams.sdtmId = "sdtm-1";
  routeSearch.tab = "source-review";
  routeSearch.domain = undefined;
  navigateSpy.mockReset();
});

afterEach(() => {
  vi.clearAllMocks();
});

// ===========================================================================
// SDTM list: cursor pagination (Requirement 9.1)
// ===========================================================================
describe("SDTM list cursor pagination (Req 9.1)", () => {
  it("requests the first page with a limit within 1-50", () => {
    sdtmApi.listPages = {
      __first__: { items: [makeAggregate({ id: "a" })], next_cursor: null },
    };

    renderWithClient(<SdtmListPage />);

    expect(sdtmApi.listCalls.length).toBeGreaterThan(0);
    const first = sdtmApi.listCalls[0];
    expect(first.studyId).toBe("study-1");
    expect(first.limit).toBeGreaterThanOrEqual(1);
    expect(first.limit).toBeLessThanOrEqual(50);
  });

  it("follows next_cursor while there are more pages and accumulates them", async () => {
    sdtmApi.listPages = {
      __first__: {
        items: [makeAggregate({ id: "a", code: "A" })],
        next_cursor: "cursor-1",
      },
      "cursor-1": {
        items: [makeAggregate({ id: "b", code: "B" })],
        next_cursor: null,
      },
    };

    renderWithClient(<SdtmListPage />);

    // First page rendered; a next cursor means a "Load more" control is shown.
    expect(screen.getByText("A")).toBeTruthy();
    const loadMore = screen.getByRole("button", { name: /load more/i });

    fireEvent.click(loadMore);

    // The follow-up request carries the previous page's next_cursor…
    await waitFor(() => {
      expect(sdtmApi.listCalls.some((c) => c.after === "cursor-1")).toBe(true);
    });
    // …and the second page is accumulated into the table.
    await waitFor(() => {
      expect(screen.getByText("B")).toBeTruthy();
    });
    // The final page has no next cursor, so paging stops (no Load more).
    expect(screen.queryByRole("button", { name: /load more/i })).toBeNull();
  });
});

// ===========================================================================
// SDTM create (Requirements 9.2, 9.5)
// ===========================================================================
describe("SDTM create", () => {
  it("refreshes the list on a successful create (invalidates the list key) (Req 9.2)", async () => {
    sdtmApi.listPages = { __first__: { items: [], next_cursor: null } };
    sdtmApi.createImpl = vi.fn(async () => makeAggregate({ id: "new" }));

    const { invalidateSpy } = renderWithClient(<SdtmListPage />);

    fireEvent.click(screen.getByRole("button", { name: /new workbench/i }));
    fireEvent.change(screen.getByLabelText(/code/i), {
      target: { value: "SDTM9" },
    });
    fireEvent.change(screen.getByLabelText(/^name/i), {
      target: { value: "Ninth" },
    });
    fireEvent.click(screen.getByRole("button", { name: /create workbench/i }));

    await waitFor(() => {
      expect(sdtmApi.createImpl).toHaveBeenCalledTimes(1);
    });
    // onSuccess invalidated the list query key -> list refreshes (Req 9.2).
    await waitFor(() => {
      expect(invalidateSpy).toHaveBeenCalledWith({
        queryKey: ["/api/v1/studies", "study-1", "sdtms"],
      });
    });
    // The create payload carried the entered values.
    expect(
      (sdtmApi.createImpl as ReturnType<typeof vi.fn>).mock.calls[0][0],
    ).toMatchObject({
      studyId: "study-1",
      data: { code: "SDTM9", name: "Ninth" },
    });
  });

  it("on a problem+json retains the form values and does NOT refresh (Req 9.5)", async () => {
    sdtmApi.listPages = { __first__: { items: [], next_cursor: null } };
    sdtmApi.createImpl = vi.fn(async () => {
      throw problemError(422, {
        title: "Invalid workbench",
        detail: "Code is already taken.",
      });
    });

    const { invalidateSpy } = renderWithClient(<SdtmListPage />);

    fireEvent.click(screen.getByRole("button", { name: /new workbench/i }));
    fireEvent.change(screen.getByLabelText(/code/i), {
      target: { value: "DUPE" },
    });
    fireEvent.change(screen.getByLabelText(/^name/i), {
      target: { value: "Taken" },
    });
    fireEvent.click(screen.getByRole("button", { name: /create workbench/i }));

    await waitFor(() => {
      expect(sdtmApi.createImpl).toHaveBeenCalledTimes(1);
    });
    // The problem detail is surfaced…
    await waitFor(() => {
      expect(screen.getByText("Code is already taken.")).toBeTruthy();
    });
    // …the entered values are retained (dialog stays open with the inputs)…
    expect((screen.getByLabelText(/code/i) as HTMLInputElement).value).toBe(
      "DUPE",
    );
    expect((screen.getByLabelText(/^name/i) as HTMLInputElement).value).toBe(
      "Taken",
    );
    // …and the list query key was NOT invalidated (no refresh, Req 9.5).
    expect(invalidateSpy).not.toHaveBeenCalledWith({
      queryKey: ["/api/v1/studies", "study-1", "sdtms"],
    });
  });
});

// ===========================================================================
// Study-scope empty state (Requirement 9.4)
// ===========================================================================
describe("SDTM study-scope gating (Req 9.4)", () => {
  it("renders the empty state and issues NO list request when no study is selected", () => {
    currentStudyState.currentStudyId = null;
    currentStudyState.isLoading = false;
    sdtmApi.listPages = {
      __first__: { items: [makeAggregate()], next_cursor: null },
    };

    renderWithClient(<SdtmListPage />);

    // No study -> the "No study selected" empty state is shown…
    expect(screen.getByText(/no study selected/i)).toBeTruthy();
    // …and NO list request was issued (the hook was disabled).
    expect(sdtmApi.listCalls).toHaveLength(0);
  });
});

// ===========================================================================
// Detail shell: each tab reachable via `?tab=` (Requirement 9.3)
// ===========================================================================
describe("SDTM detail shell tab routing (Req 9.3)", () => {
  // validateSearch narrows the raw `?tab=` value so refresh/links land on a
  // real section (missing/unknown falls back to the first tab).
  it("validateSearch keeps every known tab and falls back to the first for unknown/missing", () => {
    for (const value of TAB_VALUES) {
      expect(validateSearch({ tab: value })).toEqual({ tab: value });
    }
    expect(validateSearch({})).toEqual({ tab: "source-review" });
    expect(validateSearch({ tab: "not-a-tab" })).toEqual({
      tab: "source-review",
    });
    expect(validateSearch({ tab: 42 })).toEqual({ tab: "source-review" });
  });

  it("uses the application sidebar instead of duplicating stage tabs in the main panel", () => {
    renderWithClient(<SdtmDetailPage />);

    expect(screen.queryAllByRole("tab")).toHaveLength(0);
    expect(
      screen.getByRole("region", { name: TAB_LABELS["source-review"] }),
    ).toBeTruthy();
  });

  it.each(TAB_VALUES)(
    "resolves the active section when ?tab=%s so a refresh/link lands there",
    (value) => {
      routeSearch.tab = value;

      renderWithClient(<SdtmDetailPage />);

      // Only the section selected by the sidebar-backed ?tab= route is mounted.
      const panel = screen.getByRole("region", { name: TAB_LABELS[value] });
      expect(panel.textContent?.trim().length).toBeGreaterThan(0);

      if (value === "source-review") {
        expect(screen.getByTestId("input-selection-panel")).toBeTruthy();
      }
    },
  );
});
