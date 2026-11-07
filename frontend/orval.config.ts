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
      tsconfig: './tsconfig.app.json',
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
        // Backend operation IDs use the stable owner_resource_action form.
        // Generated client names remain action-first and omit the tag-owned
        // prefix because each tag already has its own module.
        operationName: (operation, route, verb) => {
          const raw = operation.operationId ?? `${verb}_${route}`
          const tagParts = (operation.tags?.[0] ?? 'api')
            .replace(/[^a-zA-Z0-9]+/g, '_')
            .toLowerCase()
            .split('_')
          const owner = tagParts[0]
          const scope = tagParts.slice(1)
          const parts = raw.split('_')
          if (parts[0] === owner) parts.shift()
          const action = parts.pop() ?? verb
          if (
            scope.length > 0 &&
            parts.length > scope.length &&
            scope.every((part, index) => parts[index] === part) &&
            !['artifact', 'artifacts'].includes(parts[scope.length])
          ) {
            parts.splice(0, scope.length)
          }

          let resource = parts.join('_')
          if (resource === 'root') {
            resource = action === 'list' ? tagParts.join('_') : owner.replace(/s$/, '')
          }
          if (resource === 'workbench') {
            resource = action === 'list' ? `${owner}_aggregates` : `${owner}_aggregate`
          }
          if (resource === 'dependencies' && ['raw', 'sdtm', 'adam', 'tlf'].includes(owner)) {
            resource = `${owner}_dependencies`
          }
          if (resource === 'artifacts' && ['raw', 'sdtm', 'adam', 'tlf'].includes(owner)) {
            resource = `${owner}_artifacts`
          }
          if (resource === 'artifact_fingerprint' && owner === 'raw') {
            resource = 'raw_artifact_fingerprint'
          }
          if (resource === 'source_schema' && owner === 'raw') resource = 'raw_source_schema'
          if (resource === 'build' && owner === 'artifact') resource = 'artifact_build'
          if (resource === 'run' && ['validation', 'execution'].includes(owner)) {
            resource = `${owner}_run`
          }
          if (resource === 'issues' && owner === 'reconciliation') {
            resource = 'reconciliation_issues'
          }
          if (['item', 'items'].includes(resource) && owner === 'review') {
            resource = `review_${resource}`
          }
          if (resource === 'artifacts' && owner === 'documents') {
            resource = 'document_artifacts'
          }
          if (resource === 'endpoint' && owner === 'documents') {
            resource = 'document_endpoint'
          }
          if (resource === 'plans' && ['sdtm', 'adam'].includes(owner)) {
            resource = `${owner}_plans`
          }
          if (resource === 'specification' && action === 'export' && ['sdtm', 'adam'].includes(owner)) {
            resource = `${owner}_specification`
          }
          if (resource === 'define' && action === 'render' && ['sdtm', 'adam'].includes(owner)) {
            resource = `${owner}_define`
          }
          if (
            owner === 'adam' &&
            ((['dataset', 'lineage'].includes(resource) &&
              ['validate', 'preview', 'get'].includes(action)) ||
              (resource === 'plan' && ['validate', 'preview'].includes(action)))
          ) {
            resource = `${owner}_${resource}`
          }
          const normalized = `${action}_${resource}`
          return normalized
            .replace(/[^a-zA-Z0-9]+(.)/g, (_m, chr: string) =>
              chr.toUpperCase(),
            )
            .replace(/^(.)/, (_m, chr: string) => chr.toLowerCase())
        },
      },
    },

  },
})
