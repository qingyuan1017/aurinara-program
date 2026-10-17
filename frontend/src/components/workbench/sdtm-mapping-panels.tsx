import * as React from "react";
import { useQuery, useQueryClient } from "@tanstack/react-query";
import type { AxiosError } from "axios";
import { GripVertical, Loader2, Play, Plus, Save } from "lucide-react";
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
import { useWorkbench } from "@/components/workbench/workbench-context";
import { ImportedSdtmDomainPanel } from "@/components/workbench/imported-sdtm-domain-panel";
import { useListArtifacts } from "@/api/generated/artifacts/artifacts";
import {
  DraggableItem,
  DropTarget,
  TransferContext,
} from "@/components/workbench/transfer";
import {
  applyDomainMappingTransfer,
  applyVariableMappingTransfer,
  outputArtifactSelections,
  resolveSelectedWorkarea,
} from "@/components/workbench/sdtm-mapping-utils";
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

interface SpecVariable {
  name: string;
  label?: string;
}

interface ValueContext {
  id: string;
  label: string;
  discriminator_variable: string;
  operator: "eq" | "ne" | "in";
  values: Array<string | number | boolean>;
}

interface SpecDomain {
  code: string;
  label?: string;
  expected_output_name?: string;
  variables: SpecVariable[];
  value_contexts?: ValueContext[];
}

export function domainsFrom(
  payload: Record<string, unknown> | undefined,
): SpecDomain[] {
  return Array.isArray(payload?.domains)
    ? (payload.domains as SpecDomain[])
    : [];
}

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

  return (
    <div className="flex flex-col gap-4">
      <DomainPicker domains={domains} value={active} onChange={setDomain} />
      {active && specification.data && (
        <ImportedSdtmDomainPanel
          sdtmId={sdtmId}
          domainCode={active}
          specificationRevision={specification.data.revision}
        />
      )}
      <Card>
        <CardHeader>
          <CardTitle>Generated-domain inputs</CardTitle>
          <CardDescription>
            Declare every Raw dataset and upstream SDTM domain the authored
            program may read. Imported domains use the alternate provider above
            and need no mapping or workarea. Drag available inputs into the
            matching selection, or edit the fields directly.
          </CardDescription>
        </CardHeader>
        <CardContent>
          <TransferContext onTransfer={handleTransfer}>
            <div className="space-y-4">
              <div className="grid gap-4 lg:grid-cols-2">
                <div className="space-y-2 rounded-md border p-3">
                  <Label>Available Raw datasets</Label>
                  <div className="flex min-h-9 flex-wrap gap-2">
                    {availableRaw.length > 0 ? (
                      availableRaw.map((code) => (
                        <DraggableItem
                          key={code}
                          id={`domain-source:raw:${code}`}
                          ariaLabel={`Drag Raw dataset ${code}`}
                        >
                          <GripVertical className="size-3.5" />
                          {code}
                        </DraggableItem>
                      ))
                    ) : (
                      <span className="text-muted-foreground text-sm">
                        No current Raw context
                      </span>
                    )}
                  </div>
                </div>
                <div className="space-y-2 rounded-md border p-3">
                  <Label>Available upstream SDTM domains</Label>
                  <div className="flex min-h-9 flex-wrap gap-2">
                    {upstreamCandidates.map((code) => (
                      <DraggableItem
                        key={code}
                        id={`domain-source:sdtm:${code}`}
                        ariaLabel={`Drag upstream SDTM domain ${code}`}
                      >
                        <GripVertical className="size-3.5" />
                        {code}
                      </DraggableItem>
                    ))}
                  </div>
                </div>
              </div>
              <div className="grid gap-4 lg:grid-cols-2">
                <DropTarget
                  id="domain-target:raw"
                  ariaLabel="Selected Raw datasets drop zone"
                  className="space-y-2"
                >
                  <Label htmlFor="domain-raw">Selected Raw datasets</Label>
                  <Input
                    id="domain-raw"
                    value={rawDatasets}
                    onChange={(event) => setRawDatasets(event.target.value)}
                    placeholder="DM, SITE, EXTERNAL"
                  />
                  <p className="text-muted-foreground text-xs">
                    Drop Raw dataset chips here. Reorder or remove entries in
                    the field when needed.
                  </p>
                </DropTarget>
                <DropTarget
                  id="domain-target:sdtm"
                  ariaLabel="Selected upstream SDTM domains drop zone"
                  className="space-y-2"
                >
                  <Label htmlFor="domain-upstream">
                    Selected upstream SDTM domains
                  </Label>
                  <Input
                    id="domain-upstream"
                    value={upstreamDomains}
                    onChange={(event) => setUpstreamDomains(event.target.value)}
                    placeholder="DM, SV"
                  />
                  <p className="text-muted-foreground text-xs">
                    Drop SDTM domain chips here. Cycles and self-references are
                    rejected.
                  </p>
                </DropTarget>
              </div>
              {mapping.data && (
                <Badge
                  variant={
                    mapping.data.state === "aligned" ? "default" : "destructive"
                  }
                >
                  Revision {mapping.data.revision} · {mapping.data.state}
                </Badge>
              )}
              {error && (
                <p className="text-destructive text-sm" role="alert">
                  {error}
                </p>
              )}
              <Button onClick={save} disabled={!active || saving}>
                {saving ? <Loader2 className="animate-spin" /> : <Save />} Save
                Domain Mapping
              </Button>
            </div>
          </TransferContext>
        </CardContent>
      </Card>
    </div>
  );
}

function sourceText(source: SdtmQualifiedSource): string {
  return `${source.source_type}:${source.dataset}.${source.variable}`;
}

export function parseSources(value: string): SdtmQualifiedSource[] {
  return value
    .split(",")
    .map((token) => token.trim())
    .filter(Boolean)
    .map((token) => {
      const [sourceType, qualified = ""] = token.split(":");
      const [dataset, variable] = qualified.split(".");
      if (
        (sourceType !== "raw" && sourceType !== "sdtm") ||
        !dataset ||
        !variable
      ) {
        throw new Error(
          `Invalid source "${token}". Use raw:DATASET.VAR or sdtm:DOMAIN.VAR.`,
        );
      }
      return {
        source_type: sourceType,
        dataset: dataset.toUpperCase(),
        variable: variable.toUpperCase(),
      };
    });
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
  const availableSources: SdtmQualifiedSource[] = [
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
  ].filter((source) =>
    sourceText(source)
      .toLowerCase()
      .includes(sourceFilter.trim().toLowerCase()),
  );

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
      <DomainPicker domains={domains} value={active} onChange={setDomain} />
      <Card>
        <CardHeader>
          <CardTitle>{active || "Domain"} variable matrix</CardTitle>
          <CardDescription>
            Rows are Specification variables. Default and reusable VLM contexts
            are columns. Drag declared source variables into cells, or enter one
            or more ordered qualified sources separated by commas. Empty cells
            are valid.
          </CardDescription>
        </CardHeader>
        <CardContent>
          <TransferContext onTransfer={handleTransfer}>
            <div className="space-y-4">
              <div className="space-y-3 rounded-md border p-3">
                <div className="flex flex-wrap items-end justify-between gap-3">
                  <div>
                    <Label>Declared source variables</Label>
                    <p className="text-muted-foreground text-xs">
                      Only datasets selected by the current Domain Mapping are
                      available.
                    </p>
                  </div>
                  <Input
                    className="w-72"
                    aria-label="Filter source variables"
                    value={sourceFilter}
                    onChange={(event) => setSourceFilter(event.target.value)}
                    placeholder="Filter DATASET.VARIABLE"
                  />
                </div>
                <div className="flex max-h-44 min-h-10 flex-wrap gap-2 overflow-y-auto">
                  {availableSources.length > 0 ? (
                    availableSources.map((source) => {
                      const text = sourceText(source);
                      return (
                        <DraggableItem
                          key={text}
                          id={`variable-source:${text}`}
                          ariaLabel={`Drag source variable ${text}`}
                          className="font-mono text-xs"
                        >
                          <GripVertical className="size-3.5" />
                          {text}
                        </DraggableItem>
                      );
                    })
                  ) : (
                    <span className="text-muted-foreground text-sm">
                      Save an aligned Domain Mapping with source datasets, or
                      adjust the filter.
                    </span>
                  )}
                </div>
              </div>
              <div className="overflow-x-auto">
                <Table>
                  <TableHeader>
                    <TableRow>
                      <TableHead className="min-w-44">SDTM variable</TableHead>
                      <TableHead className="min-w-72">Default</TableHead>
                      {contexts.map((context) => (
                        <TableHead key={context.id} className="min-w-72">
                          {context.label}
                          <div className="text-muted-foreground text-xs font-normal">
                            {context.discriminator_variable} {context.operator}{" "}
                            {context.values.join(", ")}
                          </div>
                        </TableHead>
                      ))}
                    </TableRow>
                  </TableHeader>
                  <TableBody>
                    {definition?.variables.map((variable) => (
                      <TableRow key={variable.name}>
                        <TableCell>
                          <div className="font-mono font-medium">
                            {variable.name}
                          </div>
                          <div className="text-muted-foreground text-xs">
                            {variable.label}
                          </div>
                        </TableCell>
                        {[null, ...contexts.map((context) => context.id)].map(
                          (contextId) => {
                            const key = `${variable.name}|${contextId ?? ""}`;
                            return (
                              <TableCell key={key}>
                                <DropTarget
                                  id={`variable-cell:${key}`}
                                  ariaLabel={`${variable.name} ${contextId ?? "Default"} source drop zone`}
                                  className="min-w-64 p-1.5"
                                >
                                  <Input
                                    aria-label={`${variable.name} ${contextId ?? "Default"} sources`}
                                    value={cells[key] ?? ""}
                                    onChange={(event) =>
                                      setCells((current) => ({
                                        ...current,
                                        [key]: event.target.value,
                                      }))
                                    }
                                    placeholder="Drop or enter raw:DATASET.VAR"
                                  />
                                </DropTarget>
                              </TableCell>
                            );
                          },
                        )}
                      </TableRow>
                    ))}
                  </TableBody>
                </Table>
              </div>
              {error && (
                <p className="text-destructive text-sm" role="alert">
                  {error}
                </p>
              )}
              <Button onClick={save} disabled={!definition || saving}>
                {saving ? <Loader2 className="animate-spin" /> : <Save />} Save
                Variable Mapping
              </Button>
            </div>
          </TransferContext>
        </CardContent>
      </Card>
    </div>
  );
}

export function CodeWorkareasPanel({ sdtmId }: { sdtmId: string }) {
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

  return (
    <div className="grid gap-4 lg:grid-cols-[18rem_minmax(0,1fr)]">
      <Card>
        <CardHeader>
          <CardTitle>Workareas</CardTitle>
          <CardDescription>
            Multiple named programs may use the same domain and language.
          </CardDescription>
        </CardHeader>
        <CardContent className="space-y-2">
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
        </CardContent>
      </Card>
      <Card>
        <CardHeader>
          <CardTitle>{selected ? name : "New Code Workarea"}</CardTitle>
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
              />
            </div>
            <div className="space-y-2">
              <Label>Domain</Label>
              <Select
                value={domain}
                onValueChange={setDomain}
                disabled={!!selected}
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
                disabled={!!selected}
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
          <div className="space-y-2">
            <Label>Program source</Label>
            <Textarea
              className="min-h-[28rem] font-mono text-xs"
              value={source}
              onChange={(event) => setSource(event.target.value)}
              spellCheck={false}
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
                              {artifact.filename} · {artifact.id.slice(0, 8)} ·{" "}
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
            {selected ? (
              <Button onClick={save} disabled={busy}>
                <Save /> Save revision
              </Button>
            ) : (
              <Button onClick={create} disabled={busy || !name || !domain}>
                <Plus /> Create
              </Button>
            )}
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
            <div className="rounded-md border p-3 text-sm">
              <div className="flex items-center gap-2">
                <Badge>{String(run.data.status)}</Badge>
                <span>{String(run.data.purpose)}</span>
              </div>
              {run.data.status === "queued" && (
                <p className="text-muted-foreground mt-2 text-xs">
                  Waiting for an execution worker to claim this run. If this
                  status persists, verify execution-dispatcher capacity.
                </p>
              )}
              {Array.isArray(run.data.preview) &&
                run.data.preview.length > 0 && (
                  <pre className="mt-3 max-h-64 overflow-auto text-xs">
                    {JSON.stringify(run.data.preview, null, 2)}
                  </pre>
                )}
              {Boolean(run.data.stderr) && (
                <pre className="text-destructive mt-3 max-h-40 overflow-auto text-xs">
                  {String(run.data.stderr)}
                </pre>
              )}
            </div>
          )}
        </CardContent>
      </Card>
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
