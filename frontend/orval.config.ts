import { defineConfig } from 'orval'

/**
 * Orval generates a fully typed API layer from the backend OpenAPI document.
 *
 * - `openapi.json` is produced by `npm run api:export` (reads the FastAPI app).
 * - Output is split per OpenAPI tag into `src/api/generated`.
 * - Each operation becomes a TanStack Query hook (useQuery / useMutation).
 * - All requests go through the custom axios instance in
 *   `src/api/axios-instance.ts`, which injects the base URL + auth token.
 */
export default defineConfig({
  aurinara: {
    input: {
      target: './openapi.json',
    },
    output: {
      mode: 'tags-split',
      target: './src/api/generated',
      schemas: './src/api/generated/model',
      client: 'react-query',
      httpClient: 'axios',
      clean: true,
      prettier: false,
      override: {
        mutator: {
          path: './src/api/axios-instance.ts',
          name: 'customInstance',
        },
        query: {
          useQuery: true,
          useInfinite: false,
          signal: true,
        },
        // FastAPI emits verbose operationIds like
        // `list_studies_api_v1_studies_get`. Strip the `_api_v1_...` suffix so
        // generated hooks read as `useListStudies`, `useCreateStudy`, etc.
        //
        // Hooks are split per OpenAPI tag, so same-named operations across
        // tags (e.g. `get_plan` on both `sdtm` and `adam`) coexist in separate
        // files. The one exception is an operation that also emits a *named
        // query-param model*: those models share the single `model/` folder,
        // so two tags producing the same params type (here `list_plans`, which
        // carries `limit`/`after` pagination params) would collide. Prefix the
        // tag for that one operation so the derived param models stay distinct
        // (`ListSdtmPlansParams` / `ListAdamPlansParams`) without renaming any
        // other hook.
        operationName: (operation, route, verb) => {
          const raw = operation.operationId ?? `${verb}_${route}`
          const cleaned = raw.replace(/_api_v1_.*$/, '')
          const tag = operation.tags?.[0]
          const disambiguated =
            cleaned === 'list_plans' && tag
              ? `list_${tag}_plans`
              : cleaned
          return disambiguated
            .replace(/[^a-zA-Z0-9]+(.)/g, (_m, chr: string) =>
              chr.toUpperCase(),
            )
            .replace(/^(.)/, (_m, chr: string) => chr.toLowerCase())
        },
      },
    },

  },
})
