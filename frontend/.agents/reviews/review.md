# Redirect to login without a token and refresh lists after mutations

Two frontend bugs are fixed in one commit (`30e981d`). First, an authenticated-layout guard now bounces users with no stored token to `/login`, and the axios response interceptor is extended so a server-rejected bearer token (401) clears the token and redirects centrally rather than leaving stale screens. Second, the cursor-pagination accumulator (`use-cursor-list.ts`) is rebuilt so a refetched first page — the one `invalidateQueries` triggers after a create/update/delete — is actually reflected in the rendered list, instead of being folded once and ignored until a full page reload. The commit touches four files and adds a focused regression test for the accumulator.

Watch for: nothing blocking. The interceptor reacts to 401 only, not 403 (confirmed) — this is the correct call for an authz-vs-authn distinction, noted below so a reviewer knows it was deliberate. The cache fix lives in the accumulator hook rather than the `invalidate.ts`/`resource-form-dialog.tsx` location the brief guessed at; that is a sounder root-cause fix (confirmed), not scope creep.

**Verdict**: APPROVED

## High-level view

The auth redirect is implemented at two layers that cover different triggers. A TanStack Router `beforeLoad` on the `_app` layout handles the "no token at all" case before any route renders, throwing a redirect to `/login` and preserving the requested path as the `redirect` search param. The axios interceptor handles the "token present but server rejected it" case: on a 401 for a request that actually carried a bearer header, it clears the token and sends the user to `/login`. Both paths are outside the `_app` subtree (`/login`, `/signup`, `/confirm` are siblings), so neither the guard nor the interceptor can trap the user on an unreachable login screen. The existing token store (`getAuthToken`/`clearAuthToken`) and the existing `redirect` search param on `login.tsx` are reused unchanged.

The cache-invalidation fix corrects a root cause the brief did not anticipate. The list screens were already invalidating the correct list query key on mutation success (`raw/index.tsx` invalidates `getListRawAggregatesQueryKey(studyId)`, the same key `useListRawAggregates` registers), so invalidation and refetch were firing. The bug was downstream: the accumulator folded each cursor's page exactly once, so when TanStack refetched the first page the new rows were discarded. The rebuilt hook keeps a per-cursor page map that is refreshed on every refetch and recomputes the accumulated list from it, so a created/updated/deleted row now surfaces live. Because every list screen drives this one hook, the fix generalizes beyond studies without per-screen changes.

The 401-only (not 403) scope of the interceptor is a deliberate authn/authz split: a 403 is a permission denial on a valid session, where clearing the token and logging the user out would be the wrong reaction.

<details>
<summary>Issues (0 blocking, 1 informational)</summary>

1. **Interceptor reacts to 401 only** (informational) — The brief phrased the trigger as "401/403-unauthenticated". The implementation redirects on 401-with-bearer only and leaves 403 alone. This is the correct behavior: 403 is an authorization failure on a valid token (e.g. study membership), and logging out on it would be wrong. No change needed; flagged so the deviation from the brief's wording is on record.

</details>

<details>
<summary>Details</summary>

### Auth guard on the `_app` layout

`_app.tsx` replaces its prior "no auth redirect, keep the shell visible when signed out" comment with a `beforeLoad` that throws `redirect({ to: '/login', search: { redirect: location.href } })` when `getAuthToken() === null`. This reverses an earlier deliberate design choice, but the reversal is exactly what the user asked for ("if token is not available it should automatically direct me to the login page"), so it is in scope rather than unrelated restructuring. The guard reuses the existing token accessor and the `redirect` search param that `login.tsx` already validates and consumes, so no new auth mechanism is introduced.

The guard sits only on `_app`. `/login`, `/signup`, and `/confirm` are route siblings outside that subtree, so an unauthenticated user is never blocked from reaching the login screen, and there is no guard-vs-interceptor redirect loop. After sign-in, `cognito.signIn` stores the ID token via `setAuthToken` inside its `onSuccess` before the promise resolves, and only then does `login.tsx` call `navigate({ to: redirect ?? '/' })`. So by the time the guard re-evaluates on `/`, the token is present and the user lands in the app. The existing login flow is preserved.

### Central 401 handling in the axios interceptor

The response interceptor already cleared the token on a 401 that carried a bearer header; the change adds a redirect to `/login` (via `window.location.assign`) in that same branch, guarded by `window.location.pathname !== '/login'` to avoid a loop when the 401 originates from the login screen itself. The `redirect` param is rebuilt from the current `pathname + search + hash` so re-authentication returns the user where they were.

This is the single central place every generated Orval call flows through, so screens never scatter their own 401 handling — which is what the brief asked for. The pre-existing guard that a 401 only triggers logout when the request *actually carried* a bearer header is retained, so an unauthenticated race (a 401 on a request with no `Authorization`) does not wipe a session, and a network/CORS error with no response is left alone.

The interceptor fires on 401 only, not 403. The brief's wording ("401/403-unauthenticated") could read as expecting 403 too, but a 403 is an authorization denial on an otherwise-valid token (study membership, scope), and reacting to it by clearing the token would log the user out of a working session on a mere permission error. 401-with-bearer is the precise signal that the token itself was refused. The narrower handling is the correct interpretation; recorded here only so the divergence from the brief's phrasing is explicit.

### Why the list bug was in the accumulator, not the mutations

The brief guessed the cache fix would land in `invalidate.ts` or `resource-form-dialog.tsx`. Reading the list screens shows the mutations were already correct: `raw/index.tsx` (and the sdtm/adam/tlf screens) invalidate the exact list key the generated list hook registers —

```
useCreateRawAggregate({ mutation: { onSuccess: () =>
  qc.invalidateQueries({ queryKey: getListRawAggregatesQueryKey(studyId) }) } })
```

— and `useCursorList` drives `useListRawAggregates`, which uses that same key. Invalidation and refetch were firing; the refetched data was being dropped. The real fault was in how the accumulator folded pages:

```
mutation success -> invalidateQueries(listKey) -> TanStack refetches first page
   -> OLD: first page (cursor null) already folded once -> refetch ignored
   -> row only appears after a full remount
```

Fixing the accumulator rather than the mutations is the correct central fix, and because every list screen shares the hook it generalizes beyond studies without touching each screen.

### The rebuilt cursor accumulator

`use-cursor-list.ts` keeps the ordered list of requested cursors (`cursorOrder`, starting at `[null]`) and a `pageItems` ref mapping each cursor to the latest items returned for it. An effect writes the current page's items into that map keyed by the active `after` cursor, and does so again on any refetch where the item references changed, bumping `pagesVersion`. The accumulated list is recomputed from the map in cursor order with id de-duplication. The net effect: a refetched first page replaces its slot in place, so created/updated/deleted rows appear without a manual reload.

The refetch-detection effect compares stored vs incoming items by per-element reference and returns early when nothing changed, so a stable render does not churn `pagesVersion` — no re-render loop. `loadMore` is gated on `isFetching` and a present next cursor, and appends the next cursor to `cursorOrder` only if not already present, so repeated clicks or a no-next-cursor terminal page are no-ops. Scope and page-size changes reset paging through the `reset` effect.

The hook also tolerates both response envelopes it may encounter: the flat `{ items, next_cursor }` the regenerated Orval client models, and the nested `{ items, page: { next_cursor, has_more } }` the API contract documents. `has_more` is honored verbatim when present and otherwise derived from a non-null next cursor. This keeps it correct against today's client and forward-compatible if the contract mismatch is reconciled.

### Test coverage

The new `use-cursor-list.test.tsx` drives the real hook over a faithful fake of a generated list hook and covers limit clamping, single-page accumulation, multi-page `loadMore` with cross-page accumulation, the `loadMore` no-op at the tail, explicit `has_more` overriding the derived value, and — the regression that matters — a refetched first page surfacing a newly created row without a remount. That last test is the direct proof of the user-reported "I have to refresh" fix.

Not tested here: the auth `beforeLoad` guard and the interceptor redirect have no new unit test in this commit. The guard is a three-line token-null check and the interceptor branch is small, but neither has an automated assertion that the redirect fires or that the `redirect` param round-trips. The commit relies on manual reasoning and the existing login tests for those two paths. Given the low complexity this is acceptable, but a router-level test asserting the unauthenticated bounce would harden it.

### Verification evidence (read, not re-run)

The commit records, with `cwd frontend`: `npm run lint` clean (10 pre-existing react-refresh warnings in untouched files), `npm run build` (`tsc -b && vite build`) passing with no type errors across 2788 modules, and `vitest run` (batched to work around a Windows single-process hang-on-exit) passing all 27 files / 271 tests, including the 10 `use-cursor-list` cases. The evidence is specific and consistent with the diff — the regression test it names is present and I have read it — so per the review instructions I did not re-run the suites and had no articulable doubt justifying a spot-check.

</details>

<details>
<summary>File map</summary>

- `src/routes/_app.tsx` — adds a `beforeLoad` guard throwing a redirect to `/login` (with the `redirect` search param) when no token is stored; removes the prior "no redirect" comment.
- `src/api/axios-instance.ts` — extends the 401-with-bearer response-interceptor branch to also redirect to `/login` (preserving the current path), skipping the redirect when already on `/login`.
- `src/hooks/use-cursor-list.ts` — new cursor-pagination accumulator keyed by a per-cursor page map that refreshes on refetch, so invalidated lists reflect created/updated/deleted rows live; tolerant of flat and nested page envelopes.
- `src/hooks/use-cursor-list.test.tsx` — new test suite including the refetched-first-page regression proof.

Full diff: `git show 30e981d`.

</details>
