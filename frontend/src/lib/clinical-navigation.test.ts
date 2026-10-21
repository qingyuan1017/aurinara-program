import { describe, expect, it } from 'vitest'
import {
  WORKSPACE_MODULES,
  resolveActiveTab,
  resolveDetailNavigation,
  resolveWorkspaceModule,
} from './clinical-navigation'

describe('clinical navigation', () => {
  it('keeps only clinical modules available in the module selector', () => {
    expect(WORKSPACE_MODULES.map((module) => module.key)).toEqual([
      'reference',
      'raw',
      'documents',
      'sdtm',
      'adam',
      'tlf',
    ])
  })

  it.each([
    ['/', 'portfolio'],
    ['/repository', 'portfolio'],
    ['/standards/releases/one', 'portfolio'],
    ['/reference', 'reference'],
    ['/raw/workbench-1', 'raw'],
    ['/documents/document-1', 'documents'],
    ['/sdtm/workbench-1', 'sdtm'],
    ['/adam/workbench-1', 'adam'],
    ['/tlf/workbench-1', 'tlf'],
  ] as const)('resolves %s to the %s workspace', (pathname, expected) => {
    expect(resolveWorkspaceModule(pathname)).toBe(expected)
  })

  it('exposes contextual tabs only for aggregate detail routes', () => {
    expect(resolveDetailNavigation('/raw')).toBeNull()
    expect(resolveDetailNavigation('/reference')).toBeNull()

    const detail = resolveDetailNavigation('/documents/document-1')
    expect(detail).toMatchObject({
      module: 'documents',
      id: 'document-1',
      label: 'Current document',
    })
    expect(detail?.tabs.map((tab) => tab.value)).toContain('protocol-context')
  })

  it('uses the first valid tab when a detail link has no recognized tab', () => {
    const detail = resolveDetailNavigation('/sdtm/workbench-1')
    expect(resolveActiveTab(detail, 'define')).toBe('define')
    expect(resolveActiveTab(detail, 'unknown')).toBe('input-selection')
    expect(resolveActiveTab(detail, undefined)).toBe('input-selection')
  })
})
