import type { SdtmQualifiedSource } from '@/api/generated/model'

export interface SpecVariable {
  name: string
  label?: string
}

export interface ValueContext {
  id: string
  label: string
  discriminator_variable: string
  operator: 'eq' | 'ne' | 'in'
  values: Array<string | number | boolean>
}

export interface SpecDomain {
  code: string
  label?: string
  expected_output_name?: string
  variables: SpecVariable[]
  value_contexts?: ValueContext[]
}

export function domainsFrom(
  payload: Record<string, unknown> | undefined,
): SpecDomain[] {
  return Array.isArray(payload?.domains) ? (payload.domains as SpecDomain[]) : []
}

export function parseSources(value: string): SdtmQualifiedSource[] {
  return value
    .split(',')
    .map((token) => token.trim())
    .filter(Boolean)
    .map((token) => {
      const [sourceType, qualified = ''] = token.split(':')
      const [dataset, variable] = qualified.split('.')
      if (
        (sourceType !== 'raw' && sourceType !== 'sdtm') ||
        !dataset ||
        !variable
      ) {
        throw new Error(
          `Invalid source "${token}". Use raw:DATASET.VAR or sdtm:DOMAIN.VAR.`,
        )
      }
      return {
        source_type: sourceType,
        dataset: dataset.toUpperCase(),
        variable: variable.toUpperCase(),
      }
    })
}

interface TransferLink {
  sourceId: string
  targetId: string
}

export function resolveSelectedWorkarea<T extends { id: string }>(
  items: readonly T[],
  selectedId: string,
  isCreating: boolean,
): T | undefined {
  if (isCreating) return undefined
  return items.find((item) => item.id === selectedId) ?? items[0]
}

export function outputArtifactSelections(
  payload: unknown,
): Record<string, string> {
  if (!payload || typeof payload !== 'object') return {}
  const items = (payload as { items?: unknown }).items
  if (!Array.isArray(items)) return {}
  const selections: Record<string, string> = {}
  for (const item of items) {
    if (!item || typeof item !== 'object') continue
    const domain = (item as { domain?: unknown }).domain
    const artifactId = (item as { xpt_artifact_id?: unknown }).xpt_artifact_id
    if (typeof domain === 'string' && typeof artifactId === 'string') {
      selections[domain] = artifactId
    }
  }
  return selections
}

export function appendUniqueCsvToken(value: string, token: string): string {
  const items = value
    .split(',')
    .map((item) => item.trim())
    .filter(Boolean)
  if (!items.some((item) => item.toUpperCase() === token.toUpperCase())) {
    items.push(token)
  }
  return items.join(', ')
}

export function applyDomainMappingTransfer(
  state: { rawDatasets: string; upstreamDomains: string },
  { sourceId, targetId }: TransferLink,
): { rawDatasets: string; upstreamDomains: string } {
  const prefix = 'domain-source:'
  if (!sourceId.startsWith(prefix)) return state
  const [, sourceType, code] = sourceId.split(':')
  if (!code) return state
  if (sourceType === 'raw' && targetId === 'domain-target:raw') {
    return {
      ...state,
      rawDatasets: appendUniqueCsvToken(state.rawDatasets, code),
    }
  }
  if (sourceType === 'sdtm' && targetId === 'domain-target:sdtm') {
    return {
      ...state,
      upstreamDomains: appendUniqueCsvToken(state.upstreamDomains, code),
    }
  }
  return state
}

export function applyVariableMappingTransfer(
  cells: Record<string, string>,
  { sourceId, targetId }: TransferLink,
): Record<string, string> {
  const sourcePrefix = 'variable-source:'
  const targetPrefix = 'variable-cell:'
  if (
    !sourceId.startsWith(sourcePrefix) ||
    !targetId.startsWith(targetPrefix)
  ) {
    return cells
  }
  const source = sourceId.slice(sourcePrefix.length)
  const key = targetId.slice(targetPrefix.length)
  return {
    ...cells,
    [key]: appendUniqueCsvToken(cells[key] ?? '', source),
  }
}
