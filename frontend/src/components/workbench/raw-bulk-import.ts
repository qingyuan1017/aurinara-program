import type {
  RawDatasetImportEntry,
  RawDatasetImportRequest,
  SourceFileResponse,
} from '@/api/generated/model'

/**
 * Pure helpers for the Raw bulk-import flow: client-side validation and the
 * request builder. Kept I/O-free (no React, no network) so the full behavior is
 * unit-testable in isolation; the backend remains authoritative for every rule.
 */

/**
 * The dataset-code pattern mirrored from the generated `RawDatasetImportEntry`
 * contract (`^[A-Za-z][A-Za-z0-9_]{0,63}$`): a leading letter followed by up to
 * 63 more letters, digits, or underscores (64 characters total).
 */
export const CODE_PATTERN = /^[A-Za-z][A-Za-z0-9_]{0,63}$/

/** Max entries the backend accepts in one import (generated `@maxItems`). */
export const MAX_ENTRIES = 500

/** Max label length (generated `@maxLength`). */
export const MAX_LABEL_LENGTH = 255

/** One editable authoring row in the import table. */
export interface BulkImportRow {
  /** Stable local key (not sent to the server). */
  id: string
  code: string
  label: string
  description: string
  /** The uploaded source file this row binds; defaults to its own upload. */
  source_file_id: string
  initialize_variables: boolean
}

/** Per-row field errors surfaced in the table. */
export interface RowFieldErrors {
  code?: string
  label?: string
  sourceFile?: string
}

export interface RowValidation {
  /** Keyed by `BulkImportRow.id`. */
  rowErrors: Record<string, RowFieldErrors>
  /** A top-level error (entry count out of range), or `null` when none. */
  formError: string | null
}

const CODE_MESSAGE =
  'Code must start with a letter and use only letters, digits, or underscore (max 64).'
const LABEL_MESSAGE = 'Label is required (max 255).'
const DUPLICATE_MESSAGE = 'Duplicate code within this batch.'
const UNKNOWN_SOURCE_MESSAGE = 'Select a source file for this dataset.'

/**
 * Validate the authoring rows before enabling submit. Enforces the code
 * pattern, label length, a known bound source file, exact (case-sensitive)
 * intra-batch duplicate-code detection flagging every member of a duplicate
 * group, and the 1-500 entry-count bound as a top-level error.
 */
export function validateRows(
  rows: BulkImportRow[],
  files: SourceFileResponse[],
): RowValidation {
  const rowErrors: Record<string, RowFieldErrors> = {}
  const knownFileIds = new Set(files.map((file) => file.id))

  // Group rows by their exact trimmed code to flag duplicates (case-sensitive).
  const codeGroups = new Map<string, string[]>()
  for (const row of rows) {
    const code = row.code.trim()
    if (!code) continue
    const group = codeGroups.get(code)
    if (group) group.push(row.id)
    else codeGroups.set(code, [row.id])
  }
  const duplicateRowIds = new Set<string>()
  for (const group of codeGroups.values()) {
    if (group.length > 1) {
      for (const id of group) duplicateRowIds.add(id)
    }
  }

  for (const row of rows) {
    const errors: RowFieldErrors = {}
    const code = row.code.trim()
    if (!code || !CODE_PATTERN.test(code)) {
      errors.code = CODE_MESSAGE
    } else if (duplicateRowIds.has(row.id)) {
      errors.code = DUPLICATE_MESSAGE
    }

    const label = row.label.trim()
    if (!label || label.length > MAX_LABEL_LENGTH) {
      errors.label = LABEL_MESSAGE
    }

    if (!row.source_file_id || !knownFileIds.has(row.source_file_id)) {
      errors.sourceFile = UNKNOWN_SOURCE_MESSAGE
    }

    if (Object.keys(errors).length > 0) {
      rowErrors[row.id] = errors
    }
  }

  let formError: string | null = null
  if (rows.length === 0) {
    formError = 'Upload at least one source file to import.'
  } else if (rows.length > MAX_ENTRIES) {
    formError = `A single import accepts at most ${MAX_ENTRIES} datasets.`
  }

  return { rowErrors, formError }
}

/** `true` when the rows have no field or form errors (safe to submit). */
export function rowsAreValid(validation: RowValidation): boolean {
  return (
    validation.formError === null &&
    Object.keys(validation.rowErrors).length === 0
  )
}

/**
 * Seed one authoring row per uploaded file, in upload order, defaulting each
 * row's bound source file to its own upload and `initialize_variables` to
 * `false`. The `code`/`label` are left blank for the user to author.
 */
export function seedRowsFromUpload(
  items: SourceFileResponse[],
): BulkImportRow[] {
  return items.map((item) => ({
    id: item.id,
    code: '',
    label: '',
    description: '',
    source_file_id: item.id,
    initialize_variables: false,
  }))
}

/**
 * Build the versioned import request from the authoring rows, preserving row
 * order. Trims `code`/`label`, omits `description` when blank, and defaults
 * `initialize_variables` to `false`. `expected_raw_revision` is intentionally
 * omitted in Release 1.
 */
export function buildImportRequest(
  rows: BulkImportRow[],
): RawDatasetImportRequest {
  const entries: RawDatasetImportEntry[] = rows.map((row) => {
    const entry: RawDatasetImportEntry = {
      code: row.code.trim(),
      label: row.label.trim(),
      source_file_id: row.source_file_id,
      initialize_variables: row.initialize_variables ?? false,
    }
    const description = row.description.trim()
    if (description) {
      entry.description = description
    }
    return entry
  })

  return { schema_version: '1.0.0', entries }
}
