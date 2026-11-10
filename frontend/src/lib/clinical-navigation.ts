export type ClinicalModuleKey =
  | 'reference'
  | 'raw'
  | 'documents'
  | 'sdtm'
  | 'adam'
  | 'tlf'

export type WorkspaceModuleKey = 'portfolio' | ClinicalModuleKey

export interface WorkspaceModule {
  key: ClinicalModuleKey
  label: string
  description: string
  landingPath:
    | '/reference'
    | '/raw'
    | '/documents'
    | '/sdtm'
    | '/adam'
    | '/tlf'
}

export interface NavigationTab {
  value: string
  label: string
}

export const WORKSPACE_MODULES: readonly WorkspaceModule[] = [
  {
    key: 'reference',
    label: 'Reference',
    description: 'Clinical module',
    landingPath: '/reference',
  },
  {
    key: 'raw',
    label: 'Raw',
    description: 'Clinical module',
    landingPath: '/raw',
  },
  {
    key: 'documents',
    label: 'Documents',
    description: 'Clinical module',
    landingPath: '/documents',
  },
  {
    key: 'sdtm',
    label: 'SDTM',
    description: 'Clinical module',
    landingPath: '/sdtm',
  },
  {
    key: 'adam',
    label: 'ADaM',
    description: 'Clinical module',
    landingPath: '/adam',
  },
  {
    key: 'tlf',
    label: 'TLF',
    description: 'Clinical module',
    landingPath: '/tlf',
  },
] as const

export const RAW_TABS = [
  { value: 'datasets', label: 'Datasets' },
  { value: 'dependencies', label: 'Dependencies' },
  { value: 'validation', label: 'Validation' },
  { value: 'reconciliation', label: 'Reconciliation' },
  { value: 'artifacts', label: 'Artifacts' },
] as const satisfies readonly NavigationTab[]

export const DOCUMENT_TABS = [
  { value: 'metadata', label: 'Metadata' },
  { value: 'content', label: 'Content' },
  { value: 'usdm', label: 'USDM' },
  { value: 'evidence', label: 'Evidence' },
  { value: 'protocol-context', label: 'Protocol context' },
  { value: 'validation', label: 'Validation' },
  { value: 'artifacts', label: 'Artifacts' },
  { value: 'dependencies', label: 'Dependencies' },
] as const satisfies readonly NavigationTab[]

export const SDTM_TABS = [
  { value: 'source-review', label: '1 Source review' },
  { value: 'specification', label: '2 Specification' },
  { value: 'domain-mapping', label: '3 Domain mapping' },
  { value: 'variable-mapping', label: '4 Variable & VLM' },
  { value: 'program-review', label: '5 Program review' },
  { value: 'execution', label: '6 Execution' },
  { value: 'acrf', label: '7 aCRF' },
  { value: 'define-validation', label: '8 Define & validation' },
  { value: 'csdrg-submission', label: '9 cSDRG & submission' },
] as const satisfies readonly NavigationTab[]

export const ADAM_TABS = [
  { value: 'evidence', label: '1 · Evidence' },
  { value: 'specification', label: '2 · Specification' },
  { value: 'plans', label: '3 · Dataset plans' },
  { value: 'validation', label: '4 · Validation' },
  { value: 'operations', label: '5–6 · Build & execute' },
  { value: 'define', label: '7 · Define' },
  { value: 'adrg', label: '8 · ADRG' },
  { value: 'readiness', label: 'Readiness' },
] as const satisfies readonly NavigationTab[]

export const TLF_TABS = [
  { value: 'sources', label: '1 · Sources' },
  { value: 'inventory', label: '2 · Output inventory' },
  { value: 'analysis', label: '3 · Analysis & display' },
  { value: 'programming', label: '4 · Programming' },
  { value: 'validation', label: '5 · Validation' },
  { value: 'build', label: '6–7 · Compile & render' },
  { value: 'execution', label: 'Execution' },
  { value: 'readiness', label: '8 · Readiness' },
] as const satisfies readonly NavigationTab[]

export type RawTab = (typeof RAW_TABS)[number]['value']
export type DocumentTab = (typeof DOCUMENT_TABS)[number]['value']
export type SdtmTab = (typeof SDTM_TABS)[number]['value']
export type AdamTab = (typeof ADAM_TABS)[number]['value']
export type TlfTab = (typeof TLF_TABS)[number]['value']

export type DetailNavigation =
  | { module: 'raw'; id: string; label: 'Current workbench'; tabs: typeof RAW_TABS }
  | { module: 'documents'; id: string; label: 'Current document'; tabs: typeof DOCUMENT_TABS }
  | { module: 'sdtm'; id: string; label: 'Current workbench'; tabs: typeof SDTM_TABS }
  | { module: 'adam'; id: string; label: 'Current workbench'; tabs: typeof ADAM_TABS }
  | { module: 'tlf'; id: string; label: 'Current workbench'; tabs: typeof TLF_TABS }

const CLINICAL_MODULE_PREFIXES: readonly [ClinicalModuleKey, string][] = [
  ['reference', '/reference'],
  ['documents', '/documents'],
  ['sdtm', '/sdtm'],
  ['adam', '/adam'],
  ['tlf', '/tlf'],
  ['raw', '/raw'],
]

/** Resolve the visible navigation scope from the URL, including direct links. */
export function resolveWorkspaceModule(pathname: string): WorkspaceModuleKey {
  return (
    CLINICAL_MODULE_PREFIXES.find(([, prefix]) =>
      pathname === prefix || pathname.startsWith(`${prefix}/`),
    )?.[0] ?? 'portfolio'
  )
}

/** Resolve a module detail route into the contextual tab navigation. */
export function resolveDetailNavigation(pathname: string): DetailNavigation | null {
  const parts = pathname.split('/').filter(Boolean)
  if (parts.length !== 2) return null

  const [module, id] = parts
  if (!id) return null

  switch (module) {
    case 'raw':
      return { module, id, label: 'Current workbench', tabs: RAW_TABS }
    case 'documents':
      return { module, id, label: 'Current document', tabs: DOCUMENT_TABS }
    case 'sdtm':
      return { module, id, label: 'Current workbench', tabs: SDTM_TABS }
    case 'adam':
      return { module, id, label: 'Current workbench', tabs: ADAM_TABS }
    case 'tlf':
      return { module, id, label: 'Current workbench', tabs: TLF_TABS }
    default:
      return null
  }
}

export function resolveActiveTab(
  detail: DetailNavigation | null,
  requestedTab: unknown,
): string | null {
  if (!detail) return null
  if (
    typeof requestedTab === 'string' &&
    detail.tabs.some((tab) => tab.value === requestedTab)
  ) {
    return requestedTab
  }
  return detail.tabs[0].value
}
