import type { SourceFileResponse } from '@/api/generated/model'
import { Input } from '@/components/ui/input'
import { Label } from '@/components/ui/label'
import { FormMessage } from '@/components/ui/form'
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from '@/components/ui/select'
import type { BulkImportRow, RowFieldErrors } from './raw-bulk-import'

export interface RawBulkImportTableProps {
  /** The authoring rows, one per uploaded source file (phase-2 state). */
  rows: BulkImportRow[]
  /** All source files uploaded this session; the per-row Select options. */
  files: SourceFileResponse[]
  /** Per-row field errors keyed by `BulkImportRow.id`. */
  rowErrors: Record<string, RowFieldErrors>
  /** Apply a partial edit to one row. */
  onChange: (id: string, patch: Partial<BulkImportRow>) => void
  /** Disable every control (e.g. while submitting). */
  disabled?: boolean
}

/**
 * The editable import-entry table (phase 2). Presentational and controlled: it
 * renders one row per {@link BulkImportRow}, surfaces per-field validation
 * messages, and reports edits through `onChange`. It holds no network state.
 *
 * Source files are referenced by `filename` and `media_type` only — never by an
 * object-store key or internal path (the API returns none).
 */
export function RawBulkImportTable({
  rows,
  files,
  rowErrors,
  onChange,
  disabled,
}: RawBulkImportTableProps) {
  return (
    <div className="overflow-x-auto">
      <table className="w-full border-collapse text-sm">
        <thead>
          <tr className="border-b text-left">
            <th className="px-2 py-2 font-medium">Code</th>
            <th className="px-2 py-2 font-medium">Label</th>
            <th className="px-2 py-2 font-medium">Description</th>
            <th className="px-2 py-2 font-medium">Source file</th>
            <th className="px-2 py-2 font-medium">Initialize variables</th>
          </tr>
        </thead>
        <tbody>
          {rows.map((row) => {
            const errors = rowErrors[row.id] ?? {}
            const codeId = `bulk-code-${row.id}`
            const labelId = `bulk-label-${row.id}`
            const descriptionId = `bulk-description-${row.id}`
            const sourceId = `bulk-source-${row.id}`
            const initId = `bulk-init-${row.id}`
            return (
              <tr key={row.id} className="border-b align-top">
                <td className="px-2 py-2">
                  <Input
                    id={codeId}
                    aria-label="Dataset code"
                    aria-invalid={!!errors.code}
                    value={row.code}
                    disabled={disabled}
                    onChange={(e) => onChange(row.id, { code: e.target.value })}
                  />
                  <FormMessage>{errors.code}</FormMessage>
                </td>
                <td className="px-2 py-2">
                  <Input
                    id={labelId}
                    aria-label="Dataset label"
                    aria-invalid={!!errors.label}
                    value={row.label}
                    disabled={disabled}
                    onChange={(e) => onChange(row.id, { label: e.target.value })}
                  />
                  <FormMessage>{errors.label}</FormMessage>
                </td>
                <td className="px-2 py-2">
                  <Input
                    id={descriptionId}
                    aria-label="Dataset description"
                    value={row.description}
                    disabled={disabled}
                    onChange={(e) =>
                      onChange(row.id, { description: e.target.value })
                    }
                  />
                </td>
                <td className="px-2 py-2">
                  <Select
                    value={row.source_file_id}
                    disabled={disabled}
                    onValueChange={(value) =>
                      onChange(row.id, { source_file_id: value })
                    }
                  >
                    <SelectTrigger
                      id={sourceId}
                      aria-label="Source file"
                      aria-invalid={!!errors.sourceFile}
                      className="w-full"
                    >
                      <SelectValue placeholder="Select a source file" />
                    </SelectTrigger>
                    <SelectContent>
                      {files.map((file) => (
                        <SelectItem key={file.id} value={file.id}>
                          {file.filename} ({file.media_type})
                        </SelectItem>
                      ))}
                    </SelectContent>
                  </Select>
                  <FormMessage>{errors.sourceFile}</FormMessage>
                </td>
                <td className="px-2 py-2">
                  <Label htmlFor={initId} className="gap-2">
                    <input
                      id={initId}
                      type="checkbox"
                      className="size-4"
                      checked={row.initialize_variables}
                      disabled={disabled}
                      onChange={(e) =>
                        onChange(row.id, {
                          initialize_variables: e.target.checked,
                        })
                      }
                    />
                    <span className="sr-only">Initialize variables</span>
                  </Label>
                </td>
              </tr>
            )
          })}
        </tbody>
      </table>
    </div>
  )
}
