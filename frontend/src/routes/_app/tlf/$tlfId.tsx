import { createFileRoute, Link, useNavigate } from '@tanstack/react-router'
import { Button } from '@/components/ui/button'
import { AiProposalReview } from '@/components/workbench/ai-proposal-review'
import { useCurrentStudy } from '@/components/study-context'
import {
  WorkbenchDetailShell,
  type WorkbenchTab,
} from '@/components/workbench/workbench-detail-shell'
import {
  TlfBuildPanel,
  TlfDependenciesPanel,
  TlfExecutionPanel,
  TlfInventoryPanel,
  TlfInputSelectionPanel,
  TlfAnalysisAuthoringPanel,
  TlfProgramPlanPanel,
  TlfValidationPanel,
} from '@/features/tlf/components/panels'
import { useGetTlfAggregate } from '@/api/generated/tlf/tlf'

const TABS = [
  'sources',
  'inventory',
  'analysis',
  'programming',
  'validation',
  'build',
  'execution',
  'readiness',
] as const
type Tab = (typeof TABS)[number]

export const Route = createFileRoute('/_app/tlf/$tlfId')({
  validateSearch: (search: Record<string, unknown>): { tab: Tab } => ({
    tab:
      typeof search.tab === 'string' && TABS.includes(search.tab as Tab)
        ? (search.tab as Tab)
        : 'sources',
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
    { value: 'sources', label: '1 · Sources', render: () => <div className="flex flex-col gap-6"><TlfInputSelectionPanel tlfId={tlfId} /><TlfDependenciesPanel tlfId={tlfId} /></div> },
    { value: 'inventory', label: '2 · Output inventory', render: () => <AiProposalReview module="tlf" aggregateId={tlfId} proposalType="tlf_output_inventory" title="Output table of contents review" description="Review the source-grounded study-wide inventory of tables, listings, and figures. Conventional proposals remain explicitly labeled and blocked where evidence is missing." manualEditor={<TlfInventoryPanel tlfId={tlfId} />} /> },
    { value: 'analysis', label: '3 · Analysis & display', render: () => <AiProposalReview module="tlf" aggregateId={tlfId} proposalType="tlf_analysis_shells" title="Analysis and display shell review" description="Review populations, methods, exact ADaM schema links, rows, columns, figures, display rules, assumptions, and ARS coverage for every accepted output." manualEditor={<TlfAnalysisAuthoringPanel tlfId={tlfId} />} /> },
    { value: 'programming', label: '4 · Programming', render: () => <AiProposalReview module="tlf" aggregateId={tlfId} proposalType="tlf_programming_plan" title="Typed programming review" description="Review ARS-linked, language-neutral ProgramPlans. Python, R, and SAS are compiled deterministically only after acceptance." manualEditor={<TlfProgramPlanPanel tlfId={tlfId} />} /> },
    { value: 'validation', label: '5 · Validation', render: () => <TlfValidationPanel tlfId={tlfId} /> },
    { value: 'build', label: '6–7 · Compile & render', render: () => <TlfBuildPanel tlfId={tlfId} /> },
    { value: 'execution', label: 'Execution', render: () => <TlfExecutionPanel tlfId={tlfId} /> },
    { value: 'readiness', label: '8 · Readiness', render: () => <TlfDependenciesPanel tlfId={tlfId} /> },
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
        defaultTab="sources"
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
