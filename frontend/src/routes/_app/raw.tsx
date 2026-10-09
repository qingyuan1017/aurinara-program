import { Outlet, createFileRoute } from '@tanstack/react-router'

// Layout route for the Raw subtree. The index (list + create workbench) lives
// in raw/index.tsx; the detail route (raw/$rawId, tabbed workbench detail)
// renders here via the Outlet.
export const Route = createFileRoute('/_app/raw')({
  component: () => <Outlet />,
})
