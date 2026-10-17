import { createFileRoute, Link, useNavigate } from "@tanstack/react-router";
import { Button } from "@/components/ui/button";
import {
  WorkbenchDetailShell,
  type WorkbenchTab,
} from "@/components/workbench/workbench-detail-shell";
import { InputSelectionPanel } from "@/components/workbench/input-selection-panel";
import { useCurrentStudy } from "@/components/study-provider";
import { SpecificationPanel } from "@/components/workbench/specification-panel";
import { SdtmValidationPanel } from "@/components/workbench/sdtm-validation-panel";
import { DefinePanel } from "@/components/workbench/define-panel";
import { SdtmDependenciesPanel } from "@/components/workbench/sdtm-dependencies-panel";
import { AcrfPanel } from "@/components/workbench/acrf-panel";
import { CsdrgPanel } from "@/components/workbench/csdrg-panel";
import {
  CodeWorkareasPanel,
  DomainMappingPanel,
  ProgramArtifactReadinessPanel,
  VariableMappingPanel,
} from "@/components/workbench/sdtm-mapping-panels";
import { useGetSdtmAggregate } from "@/api/generated/sdtm/sdtm";

const SDTM_TABS = [
  { value: "input-selection", label: "Input selection" },
  { value: "specification", label: "Specification" },
  { value: "acrf", label: "aCRF" },
  { value: "domain-mapping", label: "Domain mapping" },
  { value: "variable-mapping", label: "Variable mapping" },
  { value: "code-workareas", label: "Code workareas" },
  { value: "define", label: "Define" },
  { value: "csdrg", label: "cSDRG" },
  { value: "validation", label: "Validation" },
  { value: "readiness", label: "Program & artifact readiness" },
  { value: "dependencies", label: "Dependencies" },
] as const;

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
        case "input-selection":
          return <InputSelectionPanel />;
        case "specification":
          return <SpecificationPanel sdtmId={sdtmId} />;
        case "acrf":
          return <AcrfPanel sdtmId={sdtmId} />;
        case "domain-mapping":
          return <DomainMappingPanel sdtmId={sdtmId} />;
        case "variable-mapping":
          return <VariableMappingPanel sdtmId={sdtmId} />;
        case "code-workareas":
          return <CodeWorkareasPanel sdtmId={sdtmId} />;
        case "define":
          return <DefinePanel sdtmId={sdtmId} />;
        case "csdrg":
          return <CsdrgPanel sdtmId={sdtmId} />;
        case "validation":
          return <SdtmValidationPanel sdtmId={sdtmId} />;
        case "readiness":
          return <ProgramArtifactReadinessPanel sdtmId={sdtmId} />;
        case "dependencies":
          return <SdtmDependenciesPanel sdtmId={sdtmId} />;
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
        onTabChange={(value) =>
          navigate({
            to: "/sdtm/$sdtmId",
            params: { sdtmId },
            search: { tab: value },
            replace: true,
          })
        }
      />
    </div>
  );
}
