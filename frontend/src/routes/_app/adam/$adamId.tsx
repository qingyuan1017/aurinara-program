import { createFileRoute, Link, useNavigate } from '@tanstack/react-router'
import { Button } from '@/components/ui/button'
import { useCurrentStudy } from '@/components/study-provider'
import { WorkbenchDetailShell, type WorkbenchTab } from '@/components/workbench/workbench-detail-shell'
import { AdamAdrgPanel, AdamContextPanel, AdamDefinePanel, AdamDependenciesPanel, AdamInputSelectionPanel, AdamOperationsPanel, AdamPlanPanel, AdamSpecificationPanel, AdamValidationPanel } from '@/components/workbench/adam-panels'
import { useGetAdamAggregate } from '@/api/generated/adam/adam'

const TABS = ['inputs', 'specification', 'plans', 'context', 'validation', 'operations', 'define', 'adrg', 'dependencies'] as const
type Tab = (typeof TABS)[number]
export const Route = createFileRoute('/_app/adam/$adamId')({ validateSearch: (search: Record<string, unknown>): { tab: Tab } => ({ tab: typeof search.tab === 'string' && TABS.includes(search.tab as Tab) ? search.tab as Tab : 'inputs' }), component: AdamDetailPage })

function AdamDetailPage() {
  const { adamId } = Route.useParams(); const { tab } = Route.useSearch(); const navigate = useNavigate(); const { currentStudyId } = useCurrentStudy(); const query = useGetAdamAggregate(adamId, { query: { enabled: !!currentStudyId } }); const aggregate = query.data
  const tabs: WorkbenchTab[] = aggregate ? [
    { value: 'inputs', label: 'SDTM inputs', render: () => <AdamInputSelectionPanel aggregate={aggregate} /> },
    { value: 'specification', label: 'Specification', render: () => <AdamSpecificationPanel aggregate={aggregate} /> },
    { value: 'plans', label: 'Derivation plans', render: () => <AdamPlanPanel aggregate={aggregate} /> },
    { value: 'context', label: 'Context & lineage', render: () => <AdamContextPanel aggregate={aggregate} /> },
    { value: 'validation', label: 'Validation', render: () => <AdamValidationPanel aggregate={aggregate} /> },
    { value: 'operations', label: 'Build & execute', render: () => <AdamOperationsPanel aggregate={aggregate} /> },
    { value: 'define', label: 'Define-XML', render: () => <AdamDefinePanel aggregate={aggregate} /> },
    { value: 'adrg', label: 'ADRG', render: () => <AdamAdrgPanel aggregate={aggregate} /> },
    { value: 'dependencies', label: 'Dependencies', render: () => <AdamDependenciesPanel aggregate={aggregate} /> },
  ] : []
  return <div className="flex flex-col gap-6"><Button asChild variant="ghost" className="w-fit"><Link to="/adam">Back to ADaM workbenches</Link></Button><WorkbenchDetailShell query={query} resourceLabel="ADaM workbench" tabs={tabs} activeTab={tab} defaultTab="inputs" onTabChange={(value) => navigate({ to: '/adam/$adamId', params: { adamId }, search: { tab: value as Tab }, replace: true })} /></div>
}
