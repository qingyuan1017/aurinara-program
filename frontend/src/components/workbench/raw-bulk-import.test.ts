import { describe, expect, it } from 'vitest'

import type { SourceFileResponse } from '@/api/generated/model'
import {
  CODE_PATTERN,
  buildImportRequest,
  seedRowsFromUpload,
  validateRows,
  type BulkImportRow,
} from './raw-bulk-import'

function makeFile(id: string, filename = `${id}.xpt`): SourceFileResponse {
  return {
    id,
    study_id: 'study-1',
    artifact_id: `artifact-${id}`,
    filename,
    media_type: 'application/x-sas-xport',
    sha256: 'a'.repeat(64),
    size: 1024,
    created_by: 'user-1',
    created_at: '2024-01-01T00:00:00Z',
  }
}

function makeRow(overrides: Partial<BulkImportRow> = {}): BulkImportRow {
  return {
    id: 'row-1',
    code: 'DM',
    label: 'Demographics',
    description: '',
    source_file_id: 'file-1',
    initialize_variables: false,
    ...overrides,
  }
}

describe('CODE_PATTERN', () => {
  it('accepts a single letter', () => {
    expect(CODE_PATTERN.test('A')).toBe(true)
  })

  it('rejects a leading digit', () => {
    expect(CODE_PATTERN.test('1DM')).toBe(false)
  })

  it('accepts letters, digits, and underscores after a leading letter', () => {
    expect(CODE_PATTERN.test('A_1b2')).toBe(true)
  })

  it('rejects illegal characters', () => {
    expect(CODE_PATTERN.test('DM-1')).toBe(false)
    expect(CODE_PATTERN.test('DM 1')).toBe(false)
    expect(CODE_PATTERN.test('déjà')).toBe(false)
  })

  it('accepts a 64-character code and rejects 65', () => {
    const sixtyFour = 'A' + 'b'.repeat(63)
    const sixtyFive = 'A' + 'b'.repeat(64)
    expect(sixtyFour).toHaveLength(64)
    expect(CODE_PATTERN.test(sixtyFour)).toBe(true)
    expect(CODE_PATTERN.test(sixtyFive)).toBe(false)
  })
})

describe('validateRows duplicate detection', () => {
  const files = [makeFile('file-1'), makeFile('file-2'), makeFile('file-3')]

  it('flags no duplicates when all codes are distinct', () => {
    const rows = [
      makeRow({ id: 'r1', code: 'DM', source_file_id: 'file-1' }),
      makeRow({ id: 'r2', code: 'AE', source_file_id: 'file-2' }),
    ]
    const { rowErrors } = validateRows(rows, files)
    expect(rowErrors.r1?.code).toBeUndefined()
    expect(rowErrors.r2?.code).toBeUndefined()
  })

  it('flags both members of a single duplicate pair', () => {
    const rows = [
      makeRow({ id: 'r1', code: 'DM', source_file_id: 'file-1' }),
      makeRow({ id: 'r2', code: 'DM', source_file_id: 'file-2' }),
    ]
    const { rowErrors } = validateRows(rows, files)
    expect(rowErrors.r1?.code).toBe('Duplicate code within this batch.')
    expect(rowErrors.r2?.code).toBe('Duplicate code within this batch.')
  })

  it('flags every member of multiple duplicate groups', () => {
    const rows = [
      makeRow({ id: 'r1', code: 'DM', source_file_id: 'file-1' }),
      makeRow({ id: 'r2', code: 'DM', source_file_id: 'file-2' }),
      makeRow({ id: 'r3', code: 'AE', source_file_id: 'file-3' }),
      makeRow({ id: 'r4', code: 'AE', source_file_id: 'file-1' }),
    ]
    const { rowErrors } = validateRows(rows, files)
    expect(rowErrors.r1?.code).toBe('Duplicate code within this batch.')
    expect(rowErrors.r2?.code).toBe('Duplicate code within this batch.')
    expect(rowErrors.r3?.code).toBe('Duplicate code within this batch.')
    expect(rowErrors.r4?.code).toBe('Duplicate code within this batch.')
  })

  it('treats codes case-sensitively (AB and ab are distinct)', () => {
    const rows = [
      makeRow({ id: 'r1', code: 'AB', source_file_id: 'file-1' }),
      makeRow({ id: 'r2', code: 'ab', source_file_id: 'file-2' }),
    ]
    const { rowErrors } = validateRows(rows, files)
    expect(rowErrors.r1?.code).toBeUndefined()
    expect(rowErrors.r2?.code).toBeUndefined()
  })
})

describe('validateRows field rules', () => {
  const files = [makeFile('file-1')]

  it('rejects an empty label and a 256-character label but accepts 255', () => {
    const base = { id: 'r1', code: 'DM', source_file_id: 'file-1' }
    const empty = validateRows([makeRow({ ...base, label: '' })], files)
    expect(empty.rowErrors.r1?.label).toBe('Label is required (max 255).')

    const over = validateRows(
      [makeRow({ ...base, label: 'x'.repeat(256) })],
      files,
    )
    expect(over.rowErrors.r1?.label).toBe('Label is required (max 255).')

    const atLimit = validateRows(
      [makeRow({ ...base, label: 'x'.repeat(255) })],
      files,
    )
    expect(atLimit.rowErrors.r1?.label).toBeUndefined()
  })

  it('flags an invalid code via the pattern', () => {
    const { rowErrors } = validateRows(
      [makeRow({ id: 'r1', code: '1bad', source_file_id: 'file-1' })],
      files,
    )
    expect(rowErrors.r1?.code).toBe(
      'Code must start with a letter and use only letters, digits, or underscore (max 64).',
    )
  })

  it('flags a row bound to an unknown source file', () => {
    const { rowErrors } = validateRows(
      [makeRow({ id: 'r1', code: 'DM', source_file_id: 'missing' })],
      files,
    )
    expect(rowErrors.r1?.sourceFile).toBe(
      'Select a source file for this dataset.',
    )
  })
})

describe('validateRows entry-count bounds', () => {
  it('produces a top-level error for zero entries', () => {
    const { formError } = validateRows([], [])
    expect(formError).toBe('Upload at least one source file to import.')
  })

  it('produces a top-level error for more than 500 entries', () => {
    const files = Array.from({ length: 501 }, (_, i) => makeFile(`file-${i}`))
    const rows = files.map((file, i) =>
      makeRow({ id: `r${i}`, code: `D${i}`, source_file_id: file.id }),
    )
    const { formError } = validateRows(rows, files)
    expect(formError).toBe('A single import accepts at most 500 datasets.')
  })
})

describe('seedRowsFromUpload', () => {
  it('creates one row per uploaded file in order defaulting its own source', () => {
    const items = [makeFile('file-1'), makeFile('file-2')]
    const rows = seedRowsFromUpload(items)
    expect(rows).toHaveLength(2)
    expect(rows[0]).toMatchObject({
      source_file_id: 'file-1',
      code: '',
      label: '',
      initialize_variables: false,
    })
    expect(rows[1].source_file_id).toBe('file-2')
  })
})

describe('buildImportRequest', () => {
  it('builds the versioned envelope with entries in row order', () => {
    const rows = [
      makeRow({ id: 'r1', code: 'DM', label: 'Demographics', source_file_id: 'file-1' }),
      makeRow({ id: 'r2', code: 'AE', label: 'Adverse Events', source_file_id: 'file-2' }),
    ]
    const request = buildImportRequest(rows)
    expect(request.schema_version).toBe('1.0.0')
    expect(request.entries.map((e) => e.code)).toEqual(['DM', 'AE'])
    expect(request).not.toHaveProperty('expected_raw_revision')
  })

  it('defaults initialize_variables to false and trims code/label', () => {
    const rows = [
      makeRow({
        id: 'r1',
        code: '  DM  ',
        label: '  Demographics  ',
        source_file_id: 'file-1',
      }),
    ]
    const [entry] = buildImportRequest(rows).entries
    expect(entry.code).toBe('DM')
    expect(entry.label).toBe('Demographics')
    expect(entry.initialize_variables).toBe(false)
  })

  it('omits description when blank and includes it when present', () => {
    const blank = buildImportRequest([
      makeRow({ id: 'r1', code: 'DM', source_file_id: 'file-1', description: '   ' }),
    ])
    expect(blank.entries[0]).not.toHaveProperty('description')

    const present = buildImportRequest([
      makeRow({
        id: 'r1',
        code: 'DM',
        source_file_id: 'file-1',
        description: 'A note',
      }),
    ])
    expect(present.entries[0].description).toBe('A note')
  })
})
