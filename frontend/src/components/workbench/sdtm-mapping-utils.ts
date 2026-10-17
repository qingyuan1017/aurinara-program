interface TransferLink {
  sourceId: string;
  targetId: string;
}

export function resolveSelectedWorkarea<T extends { id: string }>(
  items: readonly T[],
  selectedId: string,
  isCreating: boolean,
): T | undefined {
  if (isCreating) return undefined;
  return items.find((item) => item.id === selectedId) ?? items[0];
}

export function outputArtifactSelections(
  payload: unknown,
): Record<string, string> {
  if (!payload || typeof payload !== "object") return {};
  const items = (payload as { items?: unknown }).items;
  if (!Array.isArray(items)) return {};
  const selections: Record<string, string> = {};
  for (const item of items) {
    if (!item || typeof item !== "object") continue;
    const domain = (item as { domain?: unknown }).domain;
    const artifactId = (item as { xpt_artifact_id?: unknown }).xpt_artifact_id;
    if (typeof domain === "string" && typeof artifactId === "string") {
      selections[domain] = artifactId;
    }
  }
  return selections;
}

export function appendUniqueCsvToken(value: string, token: string): string {
  const items = value
    .split(",")
    .map((item) => item.trim())
    .filter(Boolean);
  if (!items.some((item) => item.toUpperCase() === token.toUpperCase())) {
    items.push(token);
  }
  return items.join(", ");
}

export function applyDomainMappingTransfer(
  state: { rawDatasets: string; upstreamDomains: string },
  { sourceId, targetId }: TransferLink,
): { rawDatasets: string; upstreamDomains: string } {
  const prefix = "domain-source:";
  if (!sourceId.startsWith(prefix)) return state;
  const [, sourceType, code] = sourceId.split(":");
  if (!code) return state;
  if (sourceType === "raw" && targetId === "domain-target:raw") {
    return {
      ...state,
      rawDatasets: appendUniqueCsvToken(state.rawDatasets, code),
    };
  }
  if (sourceType === "sdtm" && targetId === "domain-target:sdtm") {
    return {
      ...state,
      upstreamDomains: appendUniqueCsvToken(state.upstreamDomains, code),
    };
  }
  return state;
}

export function applyVariableMappingTransfer(
  cells: Record<string, string>,
  { sourceId, targetId }: TransferLink,
): Record<string, string> {
  const sourcePrefix = "variable-source:";
  const targetPrefix = "variable-cell:";
  if (
    !sourceId.startsWith(sourcePrefix) ||
    !targetId.startsWith(targetPrefix)
  ) {
    return cells;
  }
  const source = sourceId.slice(sourcePrefix.length);
  const key = targetId.slice(targetPrefix.length);
  return {
    ...cells,
    [key]: appendUniqueCsvToken(cells[key] ?? "", source),
  };
}
