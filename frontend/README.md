# Aurinara Frontend

Admin UI for the Clinical Artifact Platform. The entire API layer (types +
hooks) is generated from the backend's OpenAPI document, so the frontend stays
in sync with FastAPI.

## Stack

- **Vite 5** + **React 18** + **TypeScript**
- **TanStack Router** (file-based routing, `src/routes`)
- **TanStack Query** for data fetching/caching
- **Orval** to generate a typed axios + react-query client from the backend
  OpenAPI spec
- **Tailwind CSS v4** + **shadcn/ui** (new-york style, zinc base), themed and
  laid out after [shadcn-admin](https://github.com/satnaing/shadcn-admin):
  collapsible sidebar, sticky header, light/dark/system theme toggle

## Getting started

```powershell
npm install
npm run dev
```

The dev server runs on <http://localhost:5173> and proxies `/api` to the
backend at `http://127.0.0.1:18000` (override with `VITE_API_PROXY_TARGET`).
Start the backend first (see `../docs/local-development.md`).

Copy `.env.example` to `.env` to change the API base or proxy target.

## Syncing the API client

The generated client lives in `src/api/generated` and must not be edited by
hand. Regenerate it whenever the backend contract changes:

```powershell
# 1. Export the OpenAPI document from the FastAPI app (via `uv`)
npm run api:export

# 2. Generate the typed client + hooks with Orval
npm run api:generate

# Or both at once:
npm run api:sync
```

`api:export` runs the FastAPI app factory in test mode and writes
`openapi.json`. No running server is required.

Orval config lives in `orval.config.ts`. All requests flow through the custom
axios instance in `src/api/axios-instance.ts`, which injects the base URL and
the bearer token from `src/lib/auth.ts`.

### Generated hook names

FastAPI emits verbose operation IDs (e.g. `list_studies_api_v1_studies_get`).
The Orval `operationName` override trims the `_api_v1_...` suffix, so hooks read
cleanly: `useListStudies`, `useCreateStudy`, `useGetStudy`, etc.

## Authentication

Release 1 relies on an external identity provider (Amazon Cognito in
production, the dev JWT issuer locally). The frontend only stores and attaches
the token — it does not mint it. Set a token for local testing:

```js
// in the browser console
localStorage.setItem('aurinara.auth.token', '<jwt>')
```

Request a local token from the dev issuer as described in
`../docs/local-development.md` (section 7).

## Scripts

| Script              | Purpose                                   |
| ------------------- | ----------------------------------------- |
| `npm run dev`       | Start the Vite dev server                 |
| `npm run build`     | Type-check (`tsc -b`) and bundle          |
| `npm run preview`   | Preview the production build              |
| `npm run lint`      | Run ESLint                                |
| `npm run typecheck` | Type-check without emitting               |
| `npm run api:sync`  | Export OpenAPI + regenerate the client    |

## Structure

```text
src/
  api/
    axios-instance.ts     # shared axios + auth mutator for Orval
    generated/            # GENERATED — do not edit
  components/
    layout/               # app sidebar, header, user nav
    ui/                   # shadcn/ui primitives
    theme-provider.tsx    # light/dark/system theme
  hooks/
  lib/
    auth.ts               # bearer-token storage
    query-client.ts
    utils.ts              # cn()
  routes/                 # TanStack Router file-based routes
  styles/globals.css      # Tailwind v4 + shadcn theme tokens
```
