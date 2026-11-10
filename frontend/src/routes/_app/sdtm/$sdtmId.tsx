import { createFileRoute, Link, useNavigate } from "@tanstack/react-router";
import { Button } from "@/components/ui/button";
import {
  WorkbenchDetailShell,
  type WorkbenchTab,
} from "@/components/workbench/workbench-detail-shell";
import { InputSelectionPanel } from "@/features/sdtm/components/input-selection-panel";
import { useCurrentStudy } from "@/components/study-context";
import { SdtmValidationPanel } from "@/features/sdtm/components/validation-panel";
import { DefinePanel } from "@/features/sdtm/components/define-panel";
import { SdtmDependenciesPanel } from "@/features/sdtm/components/dependencies-panel";
import { AcrfPanel } from "@/features/sdtm/components/acrf-panel";
import { CsdrgPanel } from "@/features/sdtm/components/csdrg-panel";
import {
  CodeWorkareasPanel,
  DomainMappingPanel,
  ProgramArtifactReadinessPanel,
  VariableMappingPanel,
} from "@/features/sdtm/components/mapping-panels";
import { SpecificationPanel } from "@/features/sdtm/components/specification-panel";
import {
  AiReviewWorkspace,
  SdtmStageWorkspace,
} from "@/features/sdtm/components/ai-review-workspace";
import { useGetSdtmAggregate } from "@/api/generated/sdtm/sdtm";
import { SDTM_TABS } from "@/lib/clinical-navigation";

const DEFAULT_TAB = SDTM_TABS[0].value;
const TAB_VALUES = SDTM_TABS.map((tab) => tab.value);

export const Route = createFileRoute("/_app/sdtm/$sdtmId")({
  validateSearch: (search: Record<string, unknown>): { tab: string } => ({
    tab:
      typeof search.tab === "string" && TAB_VALUES.includes(search.tab as never)
        ? search.tab
        : DEFAULT_TAB,
  }),
  component: SdtmDetailPage,
});

function SdtmDetailPage() {
  const { sdtmId } = Route.useParams();
  const { tab } = Route.useSearch();
  const navigate = useNavigate();
  const { currentStudyId } = useCurrentStudy();
  const query = useGetSdtmAggregate(sdtmId, {
    query: { enabled: !!currentStudyId },
  });

  const tabs: WorkbenchTab[] = SDTM_TABS.map((entry) => ({
    value: entry.value,
    label: entry.label,
    render: () => {
      switch (entry.value) {
        case "source-review":
          return (
            <SdtmStageWorkspace
              title="Source review"
              description="Confirm the exact validated source evidence and dependencies used for SDTM generation."
              agentMessage="The agent is monitoring source readiness. Resolve any source, validation, or dependency findings before drafting the SDTM Specification."
              actionLabel="Open Specification review"
              unframed
              onAction={() =>
                navigate({
                  to: "/sdtm/$sdtmId",
                  params: { sdtmId },
                  search: { tab: "specification" },
                })
              }
            >
              <div className="flex flex-col gap-6">
                <InputSelectionPanel />
                <SdtmDependenciesPanel sdtmId={sdtmId} />
              </div>
            </SdtmStageWorkspace>
          );
        case "specification":
          return (
            <AiReviewWorkspace
              sdtmId={sdtmId}
              proposalType="sdtm_specification"
              title="SDTM Specification proposal"
              description="AI drafts the aggregate domain, variable, terminology, key, sort, and value-level metadata contract from the pinned source metadata. A human reviewer must accept it before it becomes active."
              reviewPrelude={<SpecificationPanel sdtmId={sdtmId} />}
            />
          );
        case "acrf":
          return (
            <SdtmStageWorkspace
              title="Annotated CRF review"
              description="Review deterministic annotations against the accepted SDTM specification and variable mappings."
              agentMessage="The agent monitors annotation evidence here. Mapping changes are proposed and reviewed in the Variable & VLM stage."
              actionLabel="Open Variable & VLM review"
              unframed
              onAction={() =>
                navigate({
                  to: "/sdtm/$sdtmId",
                  params: { sdtmId },
                  search: { tab: "variable-mapping" },
                })
              }
            >
              <AcrfPanel sdtmId={sdtmId} />
            </SdtmStageWorkspace>
          );
        case "domain-mapping":
          return (
            <AiReviewWorkspace
              sdtmId={sdtmId}
              proposalType="sdtm_domain_mapping"
              title="Domain Mapping proposal"
              description="AI selects exact Raw and upstream SDTM sources for one target domain. Review the evidence and diff before accepting."
              needsDomain
              reviewPrelude={<DomainMappingPanel sdtmId={sdtmId} />}
            />
          );
        case "variable-mapping":
          return (
            <AiReviewWorkspace
              sdtmId={sdtmId}
              proposalType="sdtm_variable_mapping"
              title="Variable and value-level mapping proposal"
              description="AI maps every target variable and value context to qualified, pinned source metadata. Unresolved mappings remain visible for reviewer direction."
              needsDomain
              reviewPrelude={<VariableMappingPanel sdtmId={sdtmId} />}
            />
          );
        case "program-review":
          return (
            <AiReviewWorkspace
              sdtmId={sdtmId}
              proposalType="sdtm_program"
              title="Program proposal"
              description="AI generates a typed program revision against the accepted Specification and mappings. The program cannot execute until a human accepts it."
              needsDomain
              needsLanguage
              reviewPrelude={<CodeWorkareasPanel sdtmId={sdtmId} />}
            />
          );
        case "execution":
          return (
            <SdtmStageWorkspace
              title="Execution review"
              description="Review executable readiness and results produced from accepted program revisions."
              agentMessage="The agent monitors accepted program readiness and execution evidence. Program changes must return through proposal review."
              actionLabel="Open Program review"
              unframed
              onAction={() =>
                navigate({
                  to: "/sdtm/$sdtmId",
                  params: { sdtmId },
                  search: { tab: "program-review" },
                })
              }
            >
              <CodeWorkareasPanel sdtmId={sdtmId} reviewOnly />
            </SdtmStageWorkspace>
          );
        case "define-validation":
          return (
            <AiReviewWorkspace
              sdtmId={sdtmId}
              proposalType="sdtm_define"
              title="Define metadata proposal"
              description="AI drafts version-neutral Define metadata from the accepted Specification and exact current output selection. Initialization, validation, rendering, and reconciliation remain deterministic operations."
              reviewPrelude={<DefinePanel sdtmId={sdtmId} />}
              reviewEpilogue={<SdtmValidationPanel sdtmId={sdtmId} />}
            />
          );
        case "csdrg-submission":
          return (
            <AiReviewWorkspace
              sdtmId={sdtmId}
              proposalType="sdtm_csdrg"
              title="cSDRG narrative proposal"
              description="After deterministic factual initialization, AI drafts the reviewer-guide narrative over the exact Define, reconciliation, and output evidence for human acceptance."
              reviewPrelude={<CsdrgPanel sdtmId={sdtmId} />}
              reviewEpilogue={<ProgramArtifactReadinessPanel sdtmId={sdtmId} />}
            />
          );
      }
    },
  }));

  return (
    <div className="flex flex-col gap-6">
      <Button asChild variant="ghost" className="w-fit">
        <Link to="/sdtm">Back to SDTM workbenches</Link>
      </Button>
      <WorkbenchDetailShell
        query={query}
        resourceLabel="SDTM workbench"
        tabs={tabs}
        activeTab={tab}
        defaultTab={DEFAULT_TAB}
        showTabList={false}
      />
    </div>
  );
}
