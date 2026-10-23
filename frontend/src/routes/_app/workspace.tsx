import { createFileRoute } from '@tanstack/react-router'
import { PageHeader } from '@/components/layout/page-header'
import { Workspace } from '@/components/workspace'

export const Route = createFileRoute('/_app/workspace')({
  component: WorkspacePage,
})

function WorkspacePage() {
  return (
    <div className="flex flex-col gap-6">
      <PageHeader title="Workspace" description="Open your private Aurinara development environment." />
      <Workspace />
    </div>
  )
}
