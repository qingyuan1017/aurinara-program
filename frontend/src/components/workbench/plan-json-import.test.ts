import { describe, expect, it } from 'vitest'

import { parsePlanJsonImport } from './plan-json-import'

const validPlan = JSON.stringify({
  domain: 'DM',
  schema_version: '1.1.0',
  specification_revision: 3,
  input_selection_revision: 2,
  nodes: [{ id: 'n1', node_type: 'raw_read' }],
  edges: [{ source_node: 'n1', target_node: 'n2' }],
})

describe('parsePlanJsonImport', () => {
  it('accepts valid JSON whose domain matches and returns nodes/edges', () => {
    const result = parsePlanJsonImport(validPlan, 'DM')
    expect(result.ok).toBe(true)
    if (result.ok) {
      expect(result.value.nodes).toHaveLength(1)
      expect(result.value.edges).toHaveLength(1)
    }
  })

  it('defaults edges to an empty array when the field is absent', () => {
    const text = JSON.stringify({ domain: 'DM', nodes: [{ id: 'n1' }] })
    const result = parsePlanJsonImport(text, 'DM')
    expect(result.ok).toBe(true)
    if (result.ok) {
      expect(result.value.edges).toEqual([])
    }
  })

  it('rejects empty input with a friendly message', () => {
    const result = parsePlanJsonImport('   ', 'DM')
    expect(result).toEqual({
      ok: false,
      error: 'Paste or upload a derivation plan JSON first.',
    })
  })

  it('rejects malformed JSON without throwing', () => {
    const result = parsePlanJsonImport('{ not json', 'DM')
    expect(result.ok).toBe(false)
    if (!result.ok) {
      expect(result.error).toMatch(/not valid json/i)
    }
  })

  it('rejects a non-object top level (array/number)', () => {
    expect(parsePlanJsonImport('[1,2,3]', 'DM').ok).toBe(false)
    expect(parsePlanJsonImport('42', 'DM').ok).toBe(false)
  })

  it('rejects a domain mismatch before submit', () => {
    const result = parsePlanJsonImport(validPlan, 'AE')
    expect(result.ok).toBe(false)
    if (!result.ok) {
      expect(result.error).toMatch(/domain "DM".*editor is for "AE"/i)
    }
  })

  it('rejects a missing or non-string domain', () => {
    const text = JSON.stringify({ nodes: [{ id: 'n1' }] })
    const result = parsePlanJsonImport(text, 'DM')
    expect(result.ok).toBe(false)
    if (!result.ok) {
      expect(result.error).toMatch(/missing a string "domain"/i)
    }
  })

  it('rejects when nodes is not an array', () => {
    const text = JSON.stringify({ domain: 'DM', nodes: {} })
    expect(parsePlanJsonImport(text, 'DM').ok).toBe(false)
  })

  it('rejects an empty nodes array', () => {
    const text = JSON.stringify({ domain: 'DM', nodes: [] })
    const result = parsePlanJsonImport(text, 'DM')
    expect(result.ok).toBe(false)
    if (!result.ok) {
      expect(result.error).toMatch(/no nodes/i)
    }
  })

  it('rejects a non-array edges field when present', () => {
    const text = JSON.stringify({
      domain: 'DM',
      nodes: [{ id: 'n1' }],
      edges: 'nope',
    })
    expect(parsePlanJsonImport(text, 'DM').ok).toBe(false)
  })
})
