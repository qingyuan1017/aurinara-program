import { createFileRoute, Link, useNavigate } from '@tanstack/react-router'
import { Button } from '@/components/ui/button'
import { useCurrentStudy } from '@/components/study-provider'
import {
  WorkbenchDetailShell,
  type WorkbenchTab,
} from '@/components/workbench/workbench-detail-shell'
import {
  TlfArsPanel,
  TlfAssumptionsPanel,
  TlfBindingsPanel,
  TlfBuildPanel,
  TlfDependenciesPanel,
  TlfExecutionPanel,
  TlfProgramPlanPanel,
  TlfShellPanel,
  TlfValidationPanel,
} from '@/components/workbench/tlf-panels'
import { useGetTlfAggregate } from '@/api/generated/tlf/tlf'

const TABS = [
  'shell',
  'bindings',
  'assumptions',
  'ars',
  'program-plan',
  'validation',
  'build',
  'execution',
  'dependencies',
] as const
type Tab = (typeof TABS)[number]

export const Route = createFileRoute('/_app/tlf/$tlfId')({
  validateSearch: (search: Record<string, unknown>): { tab: Tab } => ({
    tab:
      typeof search.tab === 'string' && TABS.includes(search.tab as Tab)
        ? (search.tab as Tab)
        : 'shell',
  }),
  component: TlfDetailPage,
})

function TlfDetailPage() {
  const { tlfId } = Route.useParams()
  const { tab } = Route.useSearch()
  const navigate = useNavigate()
  const { currentStudyId } = useCurrentStudy()
  const query = useGetTlfAggregate(tlfId, {
    query: { enabled: !!currentStudyId },
  })
  const tabs: WorkbenchTab[] = [
    { value: 'shell', label: 'Shell', render: () => <TlfShellPanel tlfId={tlfId} /> },
    { value: 'bindings', label: 'Bindings', render: () => <TlfBindingsPanel tlfId={tlfId} /> },
    { value: 'assumptions', label: 'Assumptions', render: () => <TlfAssumptionsPanel tlfId={tlfId} /> },
    { value: 'ars', label: 'ARS', render: () => <TlfArsPanel tlfId={tlfId} /> },
    { value: 'program-plan', label: 'ProgramPlan', render: () => <TlfProgramPlanPanel tlfId={tlfId} /> },
    { value: 'validation', label: 'Validation', render: () => <TlfValidationPanel tlfId={tlfId} /> },
    { value: 'build', label: 'Compile & render', render: () => <TlfBuildPanel tlfId={tlfId} /> },
    { value: 'execution', label: 'Execution', render: () => <TlfExecutionPanel tlfId={tlfId} /> },
    { value: 'dependencies', label: 'Dependencies', render: () => <TlfDependenciesPanel tlfId={tlfId} /> },
  ]

  return (
    <div className="flex flex-col gap-6">
      <Button asChild variant="ghost" className="w-fit">
        <Link to="/tlf">Back to TLF workbenches</Link>
      </Button>
      <WorkbenchDetailShell
        query={query}
        resourceLabel="TLF workbench"
        tabs={tabs}
        activeTab={tab}
        defaultTab="shell"
        onTabChange={(value) =>
          navigate({
            to: '/tlf/$tlfId',
            params: { tlfId },
            search: { tab: value as Tab },
            replace: true,
          })
        }
      />
    </div>
  )
}
