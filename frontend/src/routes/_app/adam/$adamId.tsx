import { createFileRoute, Link, useNavigate } from '@tanstack/react-router'
import { Button } from '@/components/ui/button'
import { useCurrentStudy } from '@/components/study-context'
import { WorkbenchDetailShell, type WorkbenchTab } from '@/components/workbench/workbench-detail-shell'
import { AiProposalReview } from '@/components/workbench/ai-proposal-review'
import { AdamAdrgPanel, AdamContextPanel, AdamDefinePanel, AdamDependenciesPanel, AdamInputSelectionPanel, AdamOperationsPanel, AdamPlanPanel, AdamSpecificationPanel, AdamValidationPanel } from '@/features/adam/components/panels'
import { useGetAdamAggregate } from '@/api/generated/adam/adam'

const TABS = ['evidence', 'specification', 'plans', 'validation', 'operations', 'define', 'adrg', 'readiness'] as const
type Tab = (typeof TABS)[number]
export const Route = createFileRoute('/_app/adam/$adamId')({ validateSearch: (search: Record<string, unknown>): { tab: Tab } => ({ tab: typeof search.tab === 'string' && TABS.includes(search.tab as Tab) ? search.tab as Tab : 'evidence' }), component: AdamDetailPage })

function AdamDetailPage() {
  const { adamId } = Route.useParams(); const { tab } = Route.useSearch(); const navigate = useNavigate(); const { currentStudyId } = useCurrentStudy(); const query = useGetAdamAggregate(adamId, { query: { enabled: !!currentStudyId } }); const aggregate = query.data
  const tabs: WorkbenchTab[] = aggregate ? [
    { value: 'evidence', label: '1 · Evidence', render: () => <div className="flex flex-col gap-6"><AdamInputSelectionPanel aggregate={aggregate} /><AdamDependenciesPanel aggregate={aggregate} /><AdamContextPanel aggregate={aggregate} /></div> },
    { value: 'specification', label: '2 · Specification', render: () => <AiProposalReview module="adam" aggregateId={adamId} proposalType="adam_specification" title="ADaM Specification review" description="Generate and review all datasets, variables, parameters, origins, methods, terminology bindings, and trace targets as one typed proposal." targetFields={[{ key: 'sap_content_id', label: 'Exact SAP content ID', placeholder: 'UUID' }]} manualEditor={<AdamSpecificationPanel aggregate={aggregate} />} /> },
    { value: 'plans', label: '3 · Dataset plans', render: () => <AiProposalReview module="adam" aggregateId={adamId} proposalType="adam_derivation_plan" title="Per-dataset Derivation Plan review" description="Review a typed SDTM/predecessor-to-analysis DAG. Each accepted plan produces only its target dataset." targetFields={[{ key: 'dataset', label: 'Dataset code', defaultValue: 'ADSL', uppercase: true }]} manualEditor={<AdamPlanPanel aggregate={aggregate} />} /> },
    { value: 'validation', label: '4 · Validation', render: () => <AdamValidationPanel aggregate={aggregate} /> },
    { value: 'operations', label: '5–6 · Build & execute', render: () => <AdamOperationsPanel aggregate={aggregate} /> },
    { value: 'define', label: '7 · Define', render: () => <AiProposalReview module="adam" aggregateId={adamId} proposalType="adam_define" title="ADaM Define review" description="Review version-neutral Define metadata grounded in accepted Specification, plans, and exact output evidence." manualEditor={<AdamDefinePanel aggregate={aggregate} />} /> },
    { value: 'adrg', label: '8 · ADRG', render: () => <AiProposalReview module="adam" aggregateId={adamId} proposalType="adam_adrg" title="ADRG review" description="Review evidence-grounded ADRG narrative while deterministic dataset and execution facts remain authoritative." manualEditor={<AdamAdrgPanel aggregate={aggregate} />} /> },
    { value: 'readiness', label: 'Readiness', render: () => <div className="flex flex-col gap-6"><AdamContextPanel aggregate={aggregate} /><AdamDependenciesPanel aggregate={aggregate} /></div> },
  ] : []
  return <div className="flex flex-col gap-6"><Button asChild variant="ghost" className="w-fit"><Link to="/adam">Back to ADaM workbenches</Link></Button><WorkbenchDetailShell query={query} resourceLabel="ADaM workbench" tabs={tabs} activeTab={tab} defaultTab="evidence" onTabChange={(value) => navigate({ to: '/adam/$adamId', params: { adamId }, search: { tab: value as Tab }, replace: true })} /></div>
}
