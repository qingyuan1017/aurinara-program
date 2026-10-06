import { Outlet, createFileRoute } from '@tanstack/react-router'

// Layout route for the Standards catalog subtree. The index (tabbed list)
// lives in standards/index.tsx; the detail routes (products/$standardId,
// versions/$versionId, releases/$releaseId, codelists/$codelistId,
// templates/$templateId) render here via the Outlet.
export const Route = createFileRoute('/_app/standards')({
  component: () => <Outlet />,
})
