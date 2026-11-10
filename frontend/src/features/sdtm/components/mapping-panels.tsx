import * as React from "react";
import { useQuery, useQueryClient } from "@tanstack/react-query";
import type { AxiosError } from "axios";
import {
  ArrowRight,
  Database,
  GripVertical,
  Loader2,
  Play,
  Plus,
  Save,
  Trash2,
} from "lucide-react";
import { toast } from "sonner";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import {
  Card,
  CardContent,
  CardDescription,
  CardHeader,
  CardTitle,
} from "@/components/ui/card";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select";
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from "@/components/ui/table";
import { Textarea } from "@/components/ui/textarea";
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/dialog";
import { useWorkbench } from "@/components/workbench/workbench-context";
import { ImportedSdtmDomainPanel } from "@/features/sdtm/components/imported-domain-panel";
import { ReviewStageHeader } from "@/features/sdtm/components/review-stage-header";
import { useListArtifacts } from "@/api/generated/artifacts/artifacts";
import {
  DraggableItem,
  DropTarget,
  TransferContext,
} from "@/components/workbench/transfer";
import {
  applyDomainMappingTransfer,
  applyVariableMappingTransfer,
  appendUniqueCsvToken,
  domainsFrom,
  outputArtifactSelections,
  parseSources,
  removeCsvToken,
  resolveSelectedWorkarea,
  type SpecDomain,
} from "@/features/sdtm/components/mapping-model";
import {
  createWorkarea,
  generateWorkarea,
  getCodeRun,
  getGetSdtmAggregateQueryKey,
  putDomainMapping,
  putOutputSelection,
  putVariableMapping,
  testWorkarea,
  updateWorkarea,
  useGetDomainMapping,
  useGetOutputSelection,
  useGetProgramArtifactReadiness,
  useGetRawContext,
  useGetSpecification,
  useGetVariableMapping,
  useListWorkareas,
} from "@/api/generated/sdtm/sdtm";
import type {
  SdtmOutputSelectionItem,
  SdtmQualifiedSource,
} from "@/api/generated/model";
import { parseProblem } from "@/lib/problems";
import { invalidateSdtmSubResource } from "@/lib/invalidate";

function DomainPicker({
  domains,
  value,
  onChange,
}: {
  domains: SpecDomain[];
  value: string;
  onChange: (value: string) => void;
}) {
  return (
    <div className="flex items-center gap-2">
      <Label>Domain</Label>
      <Select value={value} onValueChange={onChange}>
        <SelectTrigger className="w-56">
          <SelectValue placeholder="Select domain" />
        </SelectTrigger>
        <SelectContent>
          {domains.map((domain) => (
            <SelectItem key={domain.code} value={domain.code}>
              {domain.code} · {domain.label ?? domain.code}
            </SelectItem>
          ))}
        </SelectContent>
      </Select>
    </div>
  );
}

function csv(value: string): string[] {
  return value
    .split(",")
    .map((item) => item.trim().toUpperCase())
    .filter(Boolean);
}

interface RawContextVariable {
  name: string;
  label?: string;
}

interface RawContextDataset {
  code: string;
  variables?: RawContextVariable[];
}

function rawContextDatasets(data: unknown): RawContextDataset[] {
  if (!data || typeof data !== "object") return [];
  const datasets = (data as { datasets?: unknown }).datasets;
  return Array.isArray(datasets) ? (datasets as RawContextDataset[]) : [];
}

function SourceInventoryItem({
  code,
  sourceType,
  detail,
  onAdd,
}: {
  code: string;
  sourceType: "raw" | "sdtm";
  detail: string;
  onAdd: () => void;
}) {
  const sourceLabel = sourceType === "raw" ? "Raw dataset" : "Existing SDTM";
  return (
    <div className="flex items-stretch gap-2">
      <DraggableItem
        id={`domain-source:${sourceType}:${code}`}
        ariaLabel={`Drag ${sourceLabel.toLowerCase()} ${code}`}
        className="min-w-0 flex-1 justify-start rounded-lg p-3 text-left"
      >
        <GripVertical className="text-muted-foreground size-4" />
        <span className="min-w-0">
          <span className="block truncate font-mono text-xs font-semibold">
            {code}
          </span>
          <span className="text-muted-foreground mt-0.5 block text-[10px] font-semibold uppercase tracking-wide">
            {sourceLabel} · {detail}
          </span>
        </span>
      </DraggableItem>
      <Button
        type="button"
        variant="outline"
        size="icon"
        aria-label={`Add ${sourceLabel.toLowerCase()} ${code}`}
        onClick={onAdd}
      >
        <Plus />
      </Button>
    </div>
  );
}

function SelectedDomainSource({
  code,
  sourceType,
  targetDomain,
  onRemove,
}: {
  code: string;
  sourceType: "raw" | "sdtm";
  targetDomain: string;
  onRemove: () => void;
}) {
  return (
    <div className="bg-background grid gap-3 rounded-lg border p-3 sm:grid-cols-[minmax(0,1fr)_auto] sm:items-center">
      <div className="flex min-w-0 flex-wrap items-center gap-2">
        <span className="font-mono text-xs font-semibold">{code}</span>
        <ArrowRight className="text-muted-foreground size-3.5" />
        <span className="text-primary font-mono text-xs font-semibold">
          {targetDomain}
        </span>
        <Badge variant={sourceType === "raw" ? "secondary" : "outline"}>
          {sourceType === "raw" ? "Raw input" : "SDTM read"}
        </Badge>
      </div>
      <Button
        type="button"
        variant="ghost"
        size="icon"
        aria-label={`Remove ${code} from ${targetDomain}`}
        onClick={onRemove}
      >
        <Trash2 />
      </Button>
    </div>
  );
}

export function DomainMappingPanel({ sdtmId }: { sdtmId: string }) {
  const qc = useQueryClient();
  const workbench = useWorkbench();
  const specification = useGetSpecification(sdtmId);
  const raw = useGetRawContext(sdtmId, { query: { retry: false } });
  const domains = domainsFrom(
    specification.data?.payload as Record<string, unknown> | undefined,
  );
  const [domain, setDomain] = React.useState("");
  const active = domain || domains[0]?.code || "";
  const mapping = useGetDomainMapping(sdtmId, active, {
    query: { retry: false, enabled: !!active },
  });
  const [rawDatasets, setRawDatasets] = React.useState("");
  const [upstreamDomains, setUpstreamDomains] = React.useState("");
  const [saving, setSaving] = React.useState(false);
  const [error, setError] = React.useState<string | null>(null);
  const rawContext = rawContextDatasets(raw.data);

  React.useEffect(() => {
    const payload = mapping.data?.payload;
    setRawDatasets(
      Array.isArray(payload?.raw_datasets)
        ? payload.raw_datasets.join(", ")
        : "",
    );
    setUpstreamDomains(
      Array.isArray(payload?.upstream_domains)
        ? payload.upstream_domains.join(", ")
        : "",
    );
  }, [mapping.data]);

  const availableRaw = rawContext.map((item) => item.code);
  const upstreamCandidates = domains
    .map((item) => item.code)
    .filter((code) => code !== active);

  function handleTransfer({
    sourceId,
    targetId,
  }: {
    sourceId: string;
    targetId: string;
  }) {
    const next = applyDomainMappingTransfer(
      { rawDatasets, upstreamDomains },
      { sourceId, targetId },
    );
    setRawDatasets(next.rawDatasets);
    setUpstreamDomains(next.upstreamDomains);
  }

  async function save() {
    if (!active) return;
    setSaving(true);
    setError(null);
    try {
      await putDomainMapping(
        sdtmId,
        active,
        {
          schema_version: "1.0.0",
          raw_datasets: csv(rawDatasets),
          upstream_domains: csv(upstreamDomains),
        },
        workbench.ifMatch(),
      );
      await qc.invalidateQueries({ queryKey: mapping.queryKey });
      await qc.invalidateQueries({
        queryKey: getGetSdtmAggregateQueryKey(sdtmId),
      });
      toast.success(`${active} Domain Mapping saved.`);
    } catch (caught) {
      setError(
        parseProblem(caught as AxiosError).detail ??
          "Could not save Domain Mapping.",
      );
    } finally {
      setSaving(false);
    }
  }

  const selectedRaw = csv(rawDatasets);
  const selectedUpstream = csv(upstreamDomains);
  const selectedCount = selectedRaw.length + selectedUpstream.length;

  return (
    <div className="flex flex-col gap-4">
      <Card className="overflow-hidden">
        <CardHeader className="border-b">
          <div className="flex flex-wrap items-start justify-between gap-4">
            <div>
              <CardTitle>Domain mapping review</CardTitle>
              <CardDescription className="mt-1 max-w-3xl">
                Drag exact Raw datasets or already-produced SDTM domains onto
                the target. The Derivation Plan remains authoritative for joins,
                stacks, filters, and other record-building operations.
              </CardDescription>
            </div>
            <div className="flex flex-wrap items-center gap-2">
              {mapping.data && (
                <Badge
                  variant={
                    mapping.data.state === "aligned" ? "default" : "destructive"
                  }
                >
                  Revision {mapping.data.revision} · {mapping.data.state}
                </Badge>
              )}
              <DomainPicker domains={domains} value={active} onChange={setDomain} />
            </div>
          </div>
        </CardHeader>
        <CardContent className="p-4">
          <TransferContext onTransfer={handleTransfer}>
            <div className="grid gap-5 xl:grid-cols-[300px_minmax(0,1fr)]">
              <aside className="bg-muted/20 rounded-xl border p-4">
                <div className="flex items-center gap-2">
                  <Database className="text-muted-foreground size-4" />
                  <h3 className="text-xs font-semibold uppercase tracking-wide">
                    Source datasets
                  </h3>
                </div>
                <p className="text-muted-foreground mt-1 text-xs leading-5">
                  Drag a source onto {active || "the selected target domain"}.
                </p>
                <div className="mt-4 space-y-4">
                  <section className="space-y-2">
                    <p className="text-muted-foreground text-[10px] font-semibold uppercase tracking-wide">
                      Raw context
                    </p>
                    {availableRaw.length > 0 ? (
                      availableRaw.map((code) => {
                        const variableCount =
                          rawContext.find((item) => item.code === code)?.variables
                            ?.length ?? 0;
                        return (
                          <SourceInventoryItem
                            key={`raw-${code}`}
                            code={code}
                            sourceType="raw"
                            detail={`${variableCount} variables`}
                            onAdd={() =>
                              handleTransfer({
                                sourceId: `domain-source:raw:${code}`,
                                targetId: "domain-target:inputs",
                              })
                            }
                          />
                        );
                      })
                    ) : (
                      <p className="text-muted-foreground rounded-lg border border-dashed p-3 text-xs">
                        No current Raw context.
                      </p>
                    )}
                  </section>
                  <section className="space-y-2 border-t pt-4">
                    <p className="text-muted-foreground text-[10px] font-semibold uppercase tracking-wide">
                      Existing SDTM domains
                    </p>
                    {upstreamCandidates.length > 0 ? (
                      upstreamCandidates.map((code) => {
                        const variableCount =
                          domains.find((item) => item.code === code)?.variables
                            .length ?? 0;
                        return (
                          <SourceInventoryItem
                            key={`sdtm-${code}`}
                            code={code}
                            sourceType="sdtm"
                            detail={`${variableCount} variables`}
                            onAdd={() =>
                              handleTransfer({
                                sourceId: `domain-source:sdtm:${code}`,
                                targetId: "domain-target:inputs",
                              })
                            }
                          />
                        );
                      })
                    ) : (
                      <p className="text-muted-foreground rounded-lg border border-dashed p-3 text-xs">
                        No sibling domains are available.
                      </p>
                    )}
                  </section>
                </div>
              </aside>

              <section className="space-y-3">
                <div className="grid gap-2 rounded-xl border p-3 text-xs md:grid-cols-2">
                  <p>
                    <span className="font-semibold">Raw input</span>
                    <span className="text-muted-foreground block">
                      Reads an exact dataset from the selected Raw context.
                    </span>
                  </p>
                  <p>
                    <span className="font-semibold">SDTM read</span>
                    <span className="text-muted-foreground block">
                      Pins an aligned sibling domain revision; cycles are rejected.
                    </span>
                  </p>
                </div>
                <DropTarget
                  id="domain-target:inputs"
                  ariaLabel={`${active} source dataset drop target`}
                  className="border-primary/30 bg-primary/[0.02] min-h-72 rounded-xl p-4"
                >
                  <div className="flex flex-wrap items-start justify-between gap-3">
                    <div>
                      <div className="text-primary font-mono text-lg font-semibold">
                        {active || "Select a domain"}
                      </div>
                      <p className="text-muted-foreground mt-1 text-xs">
                        {domains.find((item) => item.code === active)?.label ??
                          "Generated SDTM target"}
                      </p>
                    </div>
                    <Badge variant="outline">{selectedCount} selected inputs</Badge>
                  </div>
                  <div className="mt-4 space-y-2">
                    {selectedRaw.map((code) => (
                      <SelectedDomainSource
                        key={`selected-raw-${code}`}
                        code={code}
                        sourceType="raw"
                        targetDomain={active}
                        onRemove={() =>
                          setRawDatasets((current) => removeCsvToken(current, code))
                        }
                      />
                    ))}
                    {selectedUpstream.map((code) => (
                      <SelectedDomainSource
                        key={`selected-sdtm-${code}`}
                        code={code}
                        sourceType="sdtm"
                        targetDomain={active}
                        onRemove={() =>
                          setUpstreamDomains((current) =>
                            removeCsvToken(current, code),
                          )
                        }
                      />
                    ))}
                    {selectedCount === 0 && (
                      <p className="text-muted-foreground rounded-lg border border-dashed p-8 text-center text-sm">
                        Drop a Raw or SDTM source dataset here.
                      </p>
                    )}
                  </div>
                </DropTarget>

                <details className="rounded-lg border p-3">
                  <summary className="cursor-pointer text-sm font-medium">
                    Direct text entry
                  </summary>
                  <p className="text-muted-foreground mt-1 text-xs">
                    Accessible fallback for entering ordered dataset identifiers.
                  </p>
                  <div className="mt-3 grid gap-3 md:grid-cols-2">
                    <div className="space-y-1.5">
                      <Label htmlFor="domain-raw">Raw datasets</Label>
                      <Input
                        id="domain-raw"
                        value={rawDatasets}
                        onChange={(event) => setRawDatasets(event.target.value)}
                        placeholder="RAWDM, SITE"
                      />
                    </div>
                    <div className="space-y-1.5">
                      <Label htmlFor="domain-upstream">Upstream SDTM domains</Label>
                      <Input
                        id="domain-upstream"
                        value={upstreamDomains}
                        onChange={(event) =>
                          setUpstreamDomains(event.target.value)
                        }
                        placeholder="DM, SV"
                      />
                    </div>
                  </div>
                </details>

                {error && (
                  <p className="text-destructive text-sm" role="alert">
                    {error}
                  </p>
                )}
                <div className="flex justify-end">
                  <Button onClick={save} disabled={!active || saving}>
                    {saving ? <Loader2 className="animate-spin" /> : <Save />}
                    Save Domain Mapping
                  </Button>
                </div>
              </section>
            </div>
          </TransferContext>
        </CardContent>
      </Card>
      {active && specification.data && (
        <ImportedSdtmDomainPanel
          sdtmId={sdtmId}
          domainCode={active}
          specificationRevision={specification.data.revision}
        />
      )}
    </div>
  );
}

function sourceText(source: SdtmQualifiedSource): string {
  return `${source.source_type}:${source.dataset}.${source.variable}`;
}

export function VariableMappingPanel({ sdtmId }: { sdtmId: string }) {
  const qc = useQueryClient();
  const workbench = useWorkbench();
  const specification = useGetSpecification(sdtmId);
  const domains = domainsFrom(
    specification.data?.payload as Record<string, unknown> | undefined,
  );
  const [domain, setDomain] = React.useState("");
  const active = domain || domains[0]?.code || "";
  const definition = domains.find((item) => item.code === active);
  const domainMapping = useGetDomainMapping(sdtmId, active, {
    query: { retry: false, enabled: !!active },
  });
  const raw = useGetRawContext(sdtmId, { query: { retry: false } });
  const mapping = useGetVariableMapping(sdtmId, active, {
    query: { retry: false, enabled: !!active },
  });
  const [cells, setCells] = React.useState<Record<string, string>>({});
  const [saving, setSaving] = React.useState(false);
  const [error, setError] = React.useState<string | null>(null);
  const [sourceFilter, setSourceFilter] = React.useState("");
  const [selectedCell, setSelectedCell] = React.useState<{
    key: string;
    variable: string;
    contextLabel: string;
  } | null>(null);
  const [sourceToAdd, setSourceToAdd] = React.useState("");
  const contexts = definition?.value_contexts ?? [];

  const declaredRaw = new Set(
    Array.isArray(domainMapping.data?.payload?.raw_datasets)
      ? domainMapping.data.payload.raw_datasets.map(String)
      : [],
  );
  const declaredSdtm = new Set(
    Array.isArray(domainMapping.data?.payload?.upstream_domains)
      ? domainMapping.data.payload.upstream_domains.map(String)
      : [],
  );
  const allAvailableSources: SdtmQualifiedSource[] = [
    ...rawContextDatasets(raw.data).flatMap((dataset) =>
      declaredRaw.has(dataset.code)
        ? (dataset.variables ?? []).map((variable) => ({
            source_type: "raw" as const,
            dataset: dataset.code,
            variable: variable.name,
          }))
        : [],
    ),
    ...domains.flatMap((sourceDomain) =>
      declaredSdtm.has(sourceDomain.code)
        ? sourceDomain.variables.map((variable) => ({
            source_type: "sdtm" as const,
            dataset: sourceDomain.code,
            variable: variable.name,
          }))
        : [],
    ),
  ];
  const availableSources = allAvailableSources.filter((source) =>
    sourceText(source)
      .toLowerCase()
      .includes(sourceFilter.trim().toLowerCase()),
  );
  const sourceGroups = availableSources.reduce<
    Array<{ key: string; sources: SdtmQualifiedSource[] }>
  >((groups, source) => {
    const key = `${source.source_type}:${source.dataset}`;
    const existing = groups.find((group) => group.key === key);
    if (existing) existing.sources.push(source);
    else groups.push({ key, sources: [source] });
    return groups;
  }, []);

  React.useEffect(() => {
    const next: Record<string, string> = {};
    const existing = mapping.data?.payload?.cells;
    if (Array.isArray(existing)) {
      for (const item of existing) {
        const cell = item as {
          target_variable: string;
          context_id?: string | null;
          sources: SdtmQualifiedSource[];
        };
        next[`${cell.target_variable}|${cell.context_id ?? ""}`] = cell.sources
          .map(sourceText)
          .join(", ");
      }
    }
    setCells(next);
  }, [mapping.data]);

  function handleTransfer({
    sourceId,
    targetId,
  }: {
    sourceId: string;
    targetId: string;
  }) {
    setCells((current) =>
      applyVariableMappingTransfer(current, { sourceId, targetId }),
    );
  }

  function addSourceToCell(key: string, source: string) {
    if (!source) return;
    setCells((current) => ({
      ...current,
      [key]: appendUniqueCsvToken(current[key] ?? "", source),
    }));
  }

  function removeSourceFromCell(key: string, source: string) {
    setCells((current) => ({
      ...current,
      [key]: removeCsvToken(current[key] ?? "", source),
    }));
  }

  async function save() {
    if (!active || !definition) return;
    setSaving(true);
    setError(null);
    try {
      const payloadCells = Object.entries(cells)
        .filter(([, value]) => value.trim())
        .map(([key, value]) => {
          const [target_variable, context] = key.split("|");
          return {
            target_variable,
            context_id: context || null,
            sources: parseSources(value),
          };
        });
      await putVariableMapping(
        sdtmId,
        active,
        { schema_version: "1.0.0", cells: payloadCells },
        workbench.ifMatch(),
      );
      await qc.invalidateQueries({ queryKey: mapping.queryKey });
      await qc.invalidateQueries({
        queryKey: getGetSdtmAggregateQueryKey(sdtmId),
      });
      toast.success(`${active} Variable Mapping saved.`);
    } catch (caught) {
      setError(
        caught instanceof Error && !(caught as AxiosError).isAxiosError
          ? caught.message
          : (parseProblem(caught as AxiosError).detail ??
              "Could not save Variable Mapping."),
      );
    } finally {
      setSaving(false);
    }
  }

  return (
    <div className="flex flex-col gap-4">
      <Card className="overflow-hidden">
        <CardHeader className="border-b">
          <div className="flex flex-wrap items-start justify-between gap-4">
            <div>
              <CardTitle>Variable &amp; VLM mapping matrix</CardTitle>
              <CardDescription className="mt-1 max-w-4xl">
                Rows are SDTM variables. The Default mapping and every reusable
                Specification-owned value context are shared columns. Drop exact
                source variables into cells, then review ordered lineage before saving.
              </CardDescription>
            </div>
            <div className="flex flex-wrap items-center gap-2">
              {mapping.data && (
                <Badge
                  variant={
                    mapping.data.state === "aligned" ? "default" : "destructive"
                  }
                >
                  Revision {mapping.data.revision} · {mapping.data.state}
                </Badge>
              )}
              <Badge variant="outline">{contexts.length} VLM contexts</Badge>
              <DomainPicker domains={domains} value={active} onChange={setDomain} />
            </div>
          </div>
        </CardHeader>
        <CardContent className="p-4">
          <TransferContext onTransfer={handleTransfer}>
            <div className="grid gap-5 xl:grid-cols-[280px_minmax(0,1fr)]">
              <aside className="bg-muted/20 self-start rounded-xl border p-4 xl:sticky xl:top-4">
                <Label htmlFor="variable-source-filter">Source variables</Label>
                <p className="text-muted-foreground mt-1 text-xs leading-5">
                  Only datasets accepted by the current Domain Mapping are shown.
                </p>
                <Input
                  id="variable-source-filter"
                  className="mt-3"
                  aria-label="Filter source variables"
                  value={sourceFilter}
                  onChange={(event) => setSourceFilter(event.target.value)}
                  placeholder="Filter DATASET.VARIABLE"
                />
                <div className="mt-4 max-h-[34rem] space-y-3 overflow-y-auto pr-1">
                  {sourceGroups.map((group) => {
                    const first = group.sources[0];
                    return (
                      <section key={group.key} className="rounded-lg border p-2">
                        <div className="mb-2 flex items-center justify-between gap-2 px-1">
                          <span className="font-mono text-xs font-semibold">
                            {first?.dataset}
                          </span>
                          <Badge variant="outline">
                            {first?.source_type === "raw" ? "Raw" : "SDTM"}
                          </Badge>
                        </div>
                        <div className="flex flex-wrap gap-1.5">
                          {group.sources.map((source) => {
                            const text = sourceText(source);
                            return (
                              <DraggableItem
                                key={text}
                                id={`variable-source:${text}`}
                                ariaLabel={`Drag source variable ${text}`}
                                className="font-mono text-xs"
                              >
                                <GripVertical className="size-3" />
                                {source.variable}
                              </DraggableItem>
                            );
                          })}
                        </div>
                      </section>
                    );
                  })}
                  {sourceGroups.length === 0 && (
                    <p className="text-muted-foreground rounded-lg border border-dashed p-4 text-center text-xs">
                      Save an aligned Domain Mapping with source datasets, or
                      adjust the filter.
                    </p>
                  )}
                </div>
              </aside>

              <section className="min-w-0 overflow-hidden rounded-xl border">
                <div className="border-b px-4 py-3">
                  <div className="flex flex-wrap items-start justify-between gap-3">
                    <div>
                      <p className="text-primary font-mono text-sm font-semibold">
                        {active || "Domain"} variable lineage
                      </p>
                      <p className="text-muted-foreground mt-1 text-xs">
                        Click a cell to edit exact ordered sources. Empty cells are valid.
                      </p>
                    </div>
                    <Badge variant="secondary">
                      {definition?.variables.length ?? 0} variables
                    </Badge>
                  </div>
                </div>
                <div className="overflow-x-auto">
                  <Table className="border-collapse">
                    <TableHeader>
                      <TableRow className="bg-muted/30">
                        <TableHead className="bg-background sticky left-0 z-10 min-w-56 border-r">
                          SDTM variable
                        </TableHead>
                        <TableHead className="min-w-72 border-r align-top">
                          <span className="font-semibold">Default</span>
                          <span className="text-muted-foreground mt-1 block text-xs font-normal">
                            Base mapping
                          </span>
                        </TableHead>
                        {contexts.map((context) => (
                          <TableHead
                            key={context.id}
                            className="min-w-72 border-r align-top last:border-r-0"
                          >
                            <span className="font-semibold">{context.label}</span>
                            <span className="text-primary mt-1 block whitespace-normal font-mono text-[10px] font-normal">
                              {context.discriminator_variable} {context.operator}{" "}
                              {context.values.join(", ")}
                            </span>
                          </TableHead>
                        ))}
                      </TableRow>
                    </TableHeader>
                    <TableBody>
                      {definition?.variables.map((variable) => (
                        <TableRow key={variable.name} className="group">
                          <TableCell className="bg-background group-hover:bg-muted/30 sticky left-0 z-[5] border-r align-top">
                            <div className="font-mono text-sm font-semibold text-primary">
                              {variable.name}
                            </div>
                            <div className="text-muted-foreground mt-1 text-xs">
                              {variable.label}
                            </div>
                          </TableCell>
                          {[null, ...contexts].map((context) => {
                            const contextId = context?.id ?? null;
                            const contextLabel = context?.label ?? "Default";
                            const key = `${variable.name}|${contextId ?? ""}`;
                            const tokens = (cells[key] ?? "")
                              .split(",")
                              .map((item) => item.trim())
                              .filter(Boolean);
                            return (
                              <TableCell
                                key={key}
                                className="border-r p-0 align-top last:border-r-0"
                              >
                                <DropTarget
                                  id={`variable-cell:${key}`}
                                  ariaLabel={`${variable.name} ${contextLabel} source drop zone`}
                                  className="min-h-24 rounded-none border-0 p-3"
                                >
                                  <div className="space-y-1.5">
                                    {tokens.map((token) => (
                                      <div
                                        key={token}
                                        className="bg-background flex items-center justify-between gap-2 rounded-md border px-2 py-1.5"
                                      >
                                        <span className="min-w-0 truncate font-mono text-xs">
                                          {token}
                                        </span>
                                        <button
                                          type="button"
                                          aria-label={`Remove ${variable.name} source ${token} from ${contextLabel}`}
                                          className="text-muted-foreground hover:text-destructive"
                                          onClick={() => removeSourceFromCell(key, token)}
                                        >
                                          <Trash2 className="size-3.5" />
                                        </button>
                                      </div>
                                    ))}
                                    {tokens.length === 0 && (
                                      <span className="text-muted-foreground block py-1 text-xs">
                                        Empty cell
                                      </span>
                                    )}
                                  </div>
                                  <Button
                                    type="button"
                                    variant="ghost"
                                    size="sm"
                                    className="mt-2"
                                    aria-label={`Edit ${variable.name} ${contextLabel} mapping`}
                                    onClick={() => {
                                      setSourceToAdd("");
                                      setSelectedCell({
                                        key,
                                        variable: variable.name,
                                        contextLabel,
                                      });
                                    }}
                                  >
                                    <Plus /> Edit sources
                                  </Button>
                                </DropTarget>
                              </TableCell>
                            );
                          })}
                        </TableRow>
                      ))}
                    </TableBody>
                  </Table>
                </div>
                {!definition?.variables.length && (
                  <p className="text-muted-foreground p-8 text-center text-sm">
                    No SDTM variables are available for review.
                  </p>
                )}
              </section>
            </div>
          </TransferContext>

          {error && (
            <p className="text-destructive mt-4 text-sm" role="alert">
              {error}
            </p>
          )}
          <div className="mt-4 flex justify-end">
            <Button onClick={save} disabled={!definition || saving}>
              {saving ? <Loader2 className="animate-spin" /> : <Save />}
              Save Variable &amp; VLM Mapping
            </Button>
          </div>
        </CardContent>
      </Card>

      <Dialog
        open={selectedCell !== null}
        onOpenChange={(open) => {
          if (!open) setSelectedCell(null);
        }}
      >
        <DialogContent className="sm:max-w-2xl">
          <DialogHeader>
            <DialogTitle className="font-mono">
              {selectedCell?.variable} · {selectedCell?.contextLabel}
            </DialogTitle>
            <DialogDescription>
              Maintain ordered, qualified source lineage for this matrix cell.
              Use only datasets declared by the current Domain Mapping.
            </DialogDescription>
          </DialogHeader>
          {selectedCell && (
            <div className="space-y-4">
              <div className="grid gap-2 sm:grid-cols-[minmax(0,1fr)_auto]">
                <Select value={sourceToAdd} onValueChange={setSourceToAdd}>
                  <SelectTrigger aria-label="Source variable to add">
                    <SelectValue placeholder="Choose a qualified source" />
                  </SelectTrigger>
                  <SelectContent>
                    {allAvailableSources.map((source) => {
                      const text = sourceText(source);
                      return (
                        <SelectItem key={text} value={text}>
                          {text}
                        </SelectItem>
                      );
                    })}
                  </SelectContent>
                </Select>
                <Button
                  type="button"
                  variant="outline"
                  disabled={!sourceToAdd}
                  onClick={() => {
                    addSourceToCell(selectedCell.key, sourceToAdd);
                    setSourceToAdd("");
                  }}
                >
                  <Plus /> Add source
                </Button>
              </div>
              <div className="space-y-2">
                <Label htmlFor="mapping-cell-sources">Ordered source lineage</Label>
                <Input
                  id="mapping-cell-sources"
                  aria-label={`${selectedCell.variable} ${selectedCell.contextLabel} sources`}
                  value={cells[selectedCell.key] ?? ""}
                  onChange={(event) =>
                    setCells((current) => ({
                      ...current,
                      [selectedCell.key]: event.target.value,
                    }))
                  }
                  placeholder="raw:DATASET.VAR, sdtm:DOMAIN.VAR"
                />
                <p className="text-muted-foreground text-xs">
                  Order is preserved and becomes part of the immutable mapping revision.
                </p>
              </div>
            </div>
          )}
          <DialogFooter>
            <Button type="button" onClick={() => setSelectedCell(null)}>
              Done
            </Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>
    </div>
  );
}

export function CodeWorkareasPanel({
  sdtmId,
  reviewOnly = false,
}: {
  sdtmId: string;
  reviewOnly?: boolean;
}) {
  const qc = useQueryClient();
  const workbench = useWorkbench();
  const specification = useGetSpecification(sdtmId);
  const domains = domainsFrom(
    specification.data?.payload as Record<string, unknown> | undefined,
  );
  const workareas = useListWorkareas(sdtmId);
  const availableArtifacts = useListArtifacts(
    workbench.studyId,
    { limit: 200 },
    { query: { retry: false } },
  );
  const outputSelection = useGetOutputSelection(sdtmId, {
    query: { retry: false },
  });
  const [selectedId, setSelectedId] = React.useState("");
  const [isCreating, setIsCreating] = React.useState(false);
  const selected = resolveSelectedWorkarea(
    workareas.data?.items ?? [],
    selectedId,
    isCreating,
  );
  const [name, setName] = React.useState("");
  const [domain, setDomain] = React.useState("");
  const [language, setLanguage] = React.useState<"python" | "r" | "sas">(
    "python",
  );
  const [source, setSource] = React.useState("");
  const [upstreamArtifacts, setUpstreamArtifacts] = React.useState<
    Record<string, string>
  >({});
  const [busy, setBusy] = React.useState(false);
  const [error, setError] = React.useState<string | null>(null);
  const [runId, setRunId] = React.useState<string | null>(null);
  const activeWorkareaDomain = selected?.domain ?? domain;
  const domainMapping = useGetDomainMapping(sdtmId, activeWorkareaDomain, {
    query: {
      retry: false,
      enabled: !!selected && !!activeWorkareaDomain,
    },
  });
  const requiredUpstreamDomains = React.useMemo(
    () =>
      Array.isArray(domainMapping.data?.payload?.upstream_domains)
        ? domainMapping.data.payload.upstream_domains.map(String)
        : [],
    [domainMapping.data?.payload?.upstream_domains],
  );
  const selectedOutputArtifacts = React.useMemo(
    () => outputArtifactSelections(outputSelection.data?.payload),
    [outputSelection.data?.payload],
  );
  const upstreamComplete = requiredUpstreamDomains.every((upstreamDomain) =>
    Boolean(upstreamArtifacts[upstreamDomain]),
  );
  const run = useQuery({
    queryKey: ["sdtm-code-run", runId],
    queryFn: () => getCodeRun(runId!),
    enabled: !!runId,
    refetchInterval: (query) =>
      ["queued", "running"].includes(String(query.state.data?.status))
        ? 2000
        : false,
  });

  React.useEffect(() => {
    if (!selected) return;
    setSelectedId(selected.id);
    setName(selected.name);
    setDomain(selected.domain);
    setLanguage(selected.language as "python" | "r" | "sas");
    setSource(selected.source);
  }, [selected]);

  React.useEffect(() => {
    setUpstreamArtifacts(
      Object.fromEntries(
        requiredUpstreamDomains.map((upstreamDomain) => [
          upstreamDomain,
          selectedOutputArtifacts[upstreamDomain] ?? "",
        ]),
      ),
    );
  }, [
    selected?.id,
    selected?.revision,
    domainMapping.data?.revision,
    outputSelection.data?.revision,
    requiredUpstreamDomains,
    selectedOutputArtifacts,
  ]);

  async function handleMutationError(caught: unknown, fallback: string) {
    const axiosError = caught as AxiosError;
    if (axiosError.response?.status === 412) {
      await qc.invalidateQueries({
        queryKey: getGetSdtmAggregateQueryKey(sdtmId),
      });
      setError(
        "This SDTM workbench changed while you were editing. The current revision has been reloaded; review your changes and save again.",
      );
      return;
    }
    setError(parseProblem(axiosError).detail ?? fallback);
  }

  async function create() {
    setBusy(true);
    setError(null);
    try {
      const created = await createWorkarea(
        sdtmId,
        { name: name || `${domain}-${language}`, domain, language, source },
        workbench.ifMatch(),
      );
      setSelectedId(created.id);
      setIsCreating(false);
      await invalidateSdtmSubResource(qc, "code-workareas", sdtmId);
      toast.success("Code Workarea created.");
    } catch (caught) {
      await handleMutationError(caught, "Could not create workarea.");
    } finally {
      setBusy(false);
    }
  }
  async function save() {
    if (!selected) return;
    setBusy(true);
    setError(null);
    try {
      await updateWorkarea(
        sdtmId,
        selected.id,
        { name, source },
        workbench.ifMatch(),
      );
      await invalidateSdtmSubResource(qc, "code-workareas", sdtmId);
      toast.success("Code revision saved.");
    } catch (caught) {
      await handleMutationError(caught, "Could not save code.");
    } finally {
      setBusy(false);
    }
  }
  async function runCode(purpose: "test" | "generate") {
    if (!selected) return;
    const missingUpstream = requiredUpstreamDomains.filter(
      (upstreamDomain) => !upstreamArtifacts[upstreamDomain],
    );
    if (missingUpstream.length > 0) {
      setError(
        `Select an exact XPT artifact for: ${missingUpstream.join(", ")}.`,
      );
      return;
    }
    setBusy(true);
    setError(null);
    try {
      const body = {
        upstream_artifacts: requiredUpstreamDomains.map((upstreamDomain) => ({
          domain: upstreamDomain,
          artifact_id: upstreamArtifacts[upstreamDomain],
        })),
      };
      const options = { headers: { "Idempotency-Key": crypto.randomUUID() } };
      const result =
        purpose === "test"
          ? await testWorkarea(sdtmId, selected.id, body, options)
          : await generateWorkarea(sdtmId, selected.id, body, options);
      setRunId(String(result.id));
      toast.success(purpose === "test" ? "Test queued." : "Generation queued.");
    } catch (caught) {
      setError(
        caught instanceof Error && !(caught as AxiosError).isAxiosError
          ? caught.message
          : (parseProblem(caught as AxiosError).detail ??
              "Could not start run."),
      );
    } finally {
      setBusy(false);
    }
  }

  const workareaCount = workareas.data?.items.length ?? 0;
  const executionStatus = run.data?.status
    ? String(run.data.status).replaceAll("_", " ")
    : "Not run in this session";

  return (
    <div className="space-y-4">
      <ReviewStageHeader
        eyebrow={reviewOnly ? "Execution evidence" : "Rule & code review"}
        title={
          reviewOnly
            ? "Execute an accepted program"
            : "Review the exact program revision"
        }
        description={
          reviewOnly
            ? "Select an accepted workarea, confirm its pinned upstream XPT inputs, then run it in isolation. Preview rows and sanitized errors remain attached to the immutable run."
            : "Review or edit the exact Python, R, or SAS source for one domain. AI changes arrive as proposals; a saved human edit creates the same versioned workarea evidence."
        }
        status={reviewOnly ? executionStatus : "Human review required"}
        metrics={[
          { label: "Programs", value: workareaCount },
          { label: "Selected domain", value: activeWorkareaDomain || "None" },
          {
            label: "Language",
            value:
              selected?.language?.toUpperCase() ?? language.toUpperCase(),
          },
          {
            label: reviewOnly ? "Run state" : "Program revision",
            value: reviewOnly
              ? executionStatus
              : selected
                ? `Revision ${selected.revision}`
                : "Unsaved",
            tone:
              run.data?.status === "completed"
                ? "success"
                : run.data?.status === "failed"
                  ? "danger"
                  : run.data?.status
                    ? "warning"
                    : "default",
          },
        ]}
      />

      <div className="grid gap-4 lg:grid-cols-[18rem_minmax(0,1fr)]">
        <Card>
          <CardHeader>
            <CardTitle>
              {reviewOnly ? "Accepted programs" : "Program inventory"}
            </CardTitle>
          <CardDescription>
            Select one exact domain and language revision. Multiple named
            programs may use the same domain and language.
          </CardDescription>
        </CardHeader>
        <CardContent className="space-y-2">
          {workareaCount === 0 && (
            <p className="text-muted-foreground rounded-md border border-dashed p-4 text-center text-sm">
              No program revisions exist yet.
            </p>
          )}
          {workareas.data?.items.map((item) => (
            <Button
              key={item.id}
              variant={selected?.id === item.id ? "secondary" : "ghost"}
              className="w-full justify-start"
              onClick={() => {
                setIsCreating(false);
                setSelectedId(item.id);
              }}
            >
              {item.domain} · {item.language} · {item.name}
            </Button>
          ))}
          {!reviewOnly && (
            <Button
              variant="outline"
              className="w-full"
              onClick={() => {
                setIsCreating(true);
                setSelectedId("");
                setName("");
                setDomain(domains[0]?.code ?? "");
                setLanguage("python");
                setSource("");
              }}
            >
              <Plus /> New workarea
            </Button>
          )}
        </CardContent>
        </Card>
        <Card>
        <CardHeader>
          <div className="flex flex-wrap items-center justify-between gap-2">
            <CardTitle>{selected ? name : "New Code Workarea"}</CardTitle>
            {selected && (
              <div className="flex flex-wrap gap-2">
                <Badge variant="outline">{selected.domain}</Badge>
                  <Badge variant="secondary">
                    {selected.language.toUpperCase()}
                  </Badge>
                <Badge variant="outline">Revision {selected.revision}</Badge>
              </div>
            )}
          </div>
          <CardDescription>
            The program reads declared datasets from <code>inputs/</code> and
            must write exactly <code>outputs/{domain || "DOMAIN"}.csv</code>.
          </CardDescription>
        </CardHeader>
        <CardContent className="space-y-4">
          <div className="grid gap-3 sm:grid-cols-3">
            <div className="space-y-2">
              <Label>Name</Label>
              <Input
                value={name}
                onChange={(event) => setName(event.target.value)}
                disabled={reviewOnly}
              />
            </div>
            <div className="space-y-2">
              <Label>Domain</Label>
              <Select
                value={domain}
                onValueChange={setDomain}
                disabled={reviewOnly || !!selected}
              >
                <SelectTrigger>
                  <SelectValue />
                </SelectTrigger>
                <SelectContent>
                  {domains.map((item) => (
                    <SelectItem key={item.code} value={item.code}>
                      {item.code}
                    </SelectItem>
                  ))}
                </SelectContent>
              </Select>
            </div>
            <div className="space-y-2">
              <Label>Language</Label>
              <Select
                value={language}
                onValueChange={(value) => setLanguage(value as typeof language)}
                disabled={reviewOnly || !!selected}
              >
                <SelectTrigger>
                  <SelectValue />
                </SelectTrigger>
                <SelectContent>
                  <SelectItem value="python">Python</SelectItem>
                  <SelectItem value="r">R</SelectItem>
                  <SelectItem value="sas">SAS</SelectItem>
                </SelectContent>
              </Select>
            </div>
          </div>
          <div className="overflow-hidden rounded-md border">
            <div className="flex flex-wrap items-center justify-between gap-2 border-b bg-muted/40 px-3 py-2">
              <Label>Exact program source</Label>
              <span className="text-muted-foreground text-xs">
                {selected
                  ? `${selected.domain} · ${selected.language.toUpperCase()} · r${selected.revision}`
                  : 'Unsaved draft'}
              </span>
            </div>
            <Textarea
              className="min-h-[32rem] resize-y rounded-none border-0 bg-muted/10 font-mono text-xs leading-5 shadow-none focus-visible:ring-0"
              value={source}
              onChange={(event) => setSource(event.target.value)}
              spellCheck={false}
              readOnly={reviewOnly}
            />
          </div>
          <div className="space-y-3">
            <div>
              <Label>Exact upstream XPT selections</Label>
              <p className="text-muted-foreground text-xs">
                Choose one immutable XPT for every upstream domain declared by
                Domain Mapping. The current Output Selection is preselected when
                available.
              </p>
            </div>
            {requiredUpstreamDomains.length === 0 ? (
              <p className="rounded-md border border-dashed p-3 text-sm">
                This domain has no upstream SDTM inputs.
              </p>
            ) : (
              <div className="grid gap-3 sm:grid-cols-2">
                {requiredUpstreamDomains.map((upstreamDomain) => {
                  const expectedName =
                    domains.find((item) => item.code === upstreamDomain)
                      ?.expected_output_name ??
                    `${upstreamDomain.toLowerCase()}.xpt`;
                  const candidates = (
                    availableArtifacts.data?.items ?? []
                  ).filter(
                    (artifact) =>
                      artifact.module === "sdtm" &&
                      artifact.owner_type === "sdtm_workbench" &&
                      artifact.owner_id === sdtmId &&
                      artifact.artifact_type === "sdtm_dataset_xpt" &&
                      artifact.status === "available" &&
                      artifact.filename.toLowerCase() ===
                        expectedName.toLowerCase(),
                  );
                  return (
                    <div key={upstreamDomain} className="space-y-2">
                      <Label>{upstreamDomain}</Label>
                      <Select
                        value={upstreamArtifacts[upstreamDomain] ?? ""}
                        onValueChange={(artifactId) =>
                          setUpstreamArtifacts((current) => ({
                            ...current,
                            [upstreamDomain]: artifactId,
                          }))
                        }
                      >
                        <SelectTrigger
                          aria-label={`${upstreamDomain} upstream XPT artifact`}
                        >
                          <SelectValue placeholder="Select exact XPT" />
                        </SelectTrigger>
                        <SelectContent>
                          {candidates.map((artifact) => (
                            <SelectItem key={artifact.id} value={artifact.id}>
                              {artifact.filename} ·{' '}
                              {new Date(artifact.created_at).toLocaleString()}
                            </SelectItem>
                          ))}
                        </SelectContent>
                      </Select>
                      {candidates.length === 0 && (
                        <p className="text-muted-foreground text-xs">
                          Generate or import an available {upstreamDomain} XPT
                          first.
                        </p>
                      )}
                    </div>
                  );
                })}
              </div>
            )}
          </div>
          {error && (
            <p className="text-destructive text-sm" role="alert">
              {error}
            </p>
          )}
          <div className="flex flex-wrap gap-2">
            {!reviewOnly &&
              (selected ? (
                <Button onClick={save} disabled={busy}>
                  <Save /> Save revision
                </Button>
              ) : (
                <Button onClick={create} disabled={busy || !name || !domain}>
                  <Plus /> Create
                </Button>
              ))}
            <Button
              variant="outline"
              onClick={() => runCode("test")}
              disabled={!selected || busy || !upstreamComplete}
            >
              <Play /> Run Test
            </Button>
            <Button
              onClick={() => runCode("generate")}
              disabled={!selected || busy || !upstreamComplete}
            >
              <Play /> Generate artifacts
            </Button>
          </div>
          {run.data && (
            <div className="overflow-hidden rounded-md border text-sm">
              <div className="flex flex-wrap items-center justify-between gap-2 border-b bg-muted/30 px-3 py-2">
                <div className="flex items-center gap-2">
                  <Badge>{String(run.data.status).replaceAll("_", " ")}</Badge>
                  <span className="font-medium">
                    {String(run.data.purpose)} run evidence
                  </span>
                </div>
                <span className="text-muted-foreground font-mono text-xs">
                  {String(run.data.id ?? runId).slice(0, 12)}
                </span>
              </div>
              <div className="p-3">
                {run.data.status === "queued" && (
                  <p className="text-muted-foreground text-xs">
                    Waiting for an execution worker to claim this run. If this
                    status persists, verify execution-dispatcher capacity.
                  </p>
                )}
                {Array.isArray(run.data.preview) &&
                  run.data.preview.length > 0 && (
                    <div className="mt-3 space-y-2">
                      <p className="text-muted-foreground text-[10px] font-semibold uppercase tracking-wider">
                        Output preview
                      </p>
                      <pre className="bg-muted max-h-64 overflow-auto rounded-md p-3 text-xs">
                        {JSON.stringify(run.data.preview, null, 2)}
                      </pre>
                    </div>
                  )}
                {Boolean(run.data.stderr) && (
                  <details className="mt-3" open>
                    <summary className="text-destructive cursor-pointer text-xs font-medium">
                      Sanitized runner errors
                    </summary>
                    <pre className="bg-destructive/5 text-destructive mt-2 max-h-40 overflow-auto rounded-md p-3 text-xs">
                      {String(run.data.stderr)}
                    </pre>
                  </details>
                )}
              </div>
            </div>
          )}
        </CardContent>
        </Card>
      </div>
    </div>
  );
}

export function ProgramArtifactReadinessPanel({ sdtmId }: { sdtmId: string }) {
  const workbench = useWorkbench();
  const qc = useQueryClient();
  const readiness = useGetProgramArtifactReadiness(sdtmId, {
    query: { retry: false },
  });
  const [selection, setSelection] = React.useState("");
  const [error, setError] = React.useState<string | null>(null);
  async function saveSelection() {
    try {
      const items = JSON.parse(selection) as SdtmOutputSelectionItem[];
      await putOutputSelection(
        sdtmId,
        { schema_version: "1.0.0", items },
        workbench.ifMatch(),
      );
      await qc.invalidateQueries({ queryKey: readiness.queryKey });
      await qc.invalidateQueries({
        queryKey: getGetSdtmAggregateQueryKey(sdtmId),
      });
      toast.success("Exact Output Selection saved.");
    } catch (caught) {
      setError(
        caught instanceof SyntaxError
          ? "Enter a JSON array of output selections."
          : (parseProblem(caught as AxiosError).detail ??
              "Could not save Output Selection."),
      );
    }
  }
  const data = readiness.data as
    | {
        ready?: boolean;
        output_selection_revision?: number | null;
        domains?: Array<{
          domain: string;
          ready: boolean;
          provider?: string | null;
        }>;
      }
    | undefined;
  return (
    <div className="space-y-4">
      <Card>
        <CardHeader>
          <CardTitle>Program & artifact readiness</CardTitle>
          <CardDescription>
            Programs come only from successful Code Workarea generations. This
            view checks the explicit all-domain output set and is the entry
            point for non-program deliverables.
          </CardDescription>
        </CardHeader>
        <CardContent className="space-y-3">
          <Badge variant={data?.ready ? "default" : "destructive"}>
            {data?.ready ? "Ready" : "Output selection required"}
          </Badge>
          <div className="grid gap-2 sm:grid-cols-3">
            {data?.domains?.map((item) => (
              <div key={item.domain} className="rounded-md border p-3 text-sm">
                <strong>{item.domain}</strong>
                <div className="text-muted-foreground">
                  {item.ready ? item.provider : "Not selected"}
                </div>
              </div>
            ))}
          </div>
        </CardContent>
      </Card>
      <Card>
        <CardHeader>
          <CardTitle>Exact Output Selection</CardTitle>
          <CardDescription>
            Select one successful generation run or imported revision and its
            exact XPT artifact for every domain. Coherence is validated
            server-side; “latest” is never inferred.
          </CardDescription>
        </CardHeader>
        <CardContent className="space-y-3">
          <Textarea
            className="min-h-44 font-mono text-xs"
            value={selection}
            onChange={(event) => setSelection(event.target.value)}
            placeholder={
              '[{"domain":"DM","provider_type":"generation","provider_revision_id":"run-uuid","xpt_artifact_id":"artifact-uuid"}]'
            }
          />
          {error && <p className="text-destructive text-sm">{error}</p>}
          <Button onClick={saveSelection}>
            <Save /> Save Output Selection
          </Button>
        </CardContent>
      </Card>
    </div>
  );
}
