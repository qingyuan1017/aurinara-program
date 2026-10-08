import * as React from 'react'
import type { AxiosError } from 'axios'
import { Loader2 } from 'lucide-react'
import { PageHeader } from '@/components/layout/page-header'
import { EmptyState } from '@/components/data/states'
import { Button } from '@/components/ui/button'
import { Input } from '@/components/ui/input'
import {
  FormControl,
  FormDescription,
  FormItem,
  FormLabel,
} from '@/components/ui/form'
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from '@/components/ui/table'
import { usePreviewDataset } from '@/api/generated/raw/raw'
import type {
  RawPreviewRequest,
  RawPreviewResponse,
} from '@/api/generated/model'
import { jsonRequest } from '@/lib/requests'
import { parseProblem } from '@/lib/problems'

/** Minimum rows the backend accepts for a preview `limit`. */
export const MIN_PREVIEW_LIMIT = 1
/** Maximum rows the backend accepts for a preview `limit`. */
export const MAX_PREVIEW_LIMIT = 200
/** Default preview page size requested when the field is empty/invalid. */
export const DEFAULT_PREVIEW_LIMIT = 50

/**
 * Clamp a requested preview `limit` into the backend-accepted 1-200 window
 * before the request is sent (Requirement 5.2, 5.3).
 *
 * Below the floor clamps up to {@link MIN_PREVIEW_LIMIT}; above the ceiling
 * clamps down to {@link MAX_PREVIEW_LIMIT}; an in-range value is floored and
 * passed through unchanged. A `NaN`/undefined value falls back to the default.
 */
export function clampLimit(limit: number | undefined): number {
  if (limit === undefined || Number.isNaN(limit)) {
    return DEFAULT_PREVIEW_LIMIT
  }
  const floored = Math.floor(limit)
  return Math.min(Math.max(floored, MIN_PREVIEW_LIMIT), MAX_PREVIEW_LIMIT)
}

/**
 * Clamp a requested preview `offset` to a non-negative integer before the
 * request is sent (Requirement 5.2). A negative value clamps up to 0; a
 * `NaN`/undefined value falls back to 0.
 */
export function clampOffset(offset: number | undefined): number {
  if (offset === undefined || Number.isNaN(offset)) {
    return 0
  }
  const floored = Math.floor(offset)
  return Math.max(floored, 0)
}

export interface PreviewPanelProps {
  /** The dataset whose rows are previewed (path parameter for the POST). */
  datasetId: string
  /** The dataset code, shown in the header for context. */
  datasetCode: string
}

/**
 * Preview panel body for a Raw dataset drill-in (Requirement 5).
 *
 * Flows:
 * - Request a bounded window of rows via `usePreviewDataset`
 *   (`POST /api/v1/raw-datasets/{dataset_id}/preview`) with an optional column
 *   selection (R5.1).
 * - The client clamps `limit` to 1-200 and `offset` to >= 0 BEFORE sending
 *   (R5.2, R5.3) using {@link clampLimit}/{@link clampOffset}.
 * - Render the returned `columns`/`rows` plus `offset`/`limit`/`total_rows`
 *   (R5.4). A zero-row response still shows those counts alongside a message
 *   (R5.5).
 * - Preview rows live only in local component state for the lifetime of this
 *   view; nothing is written to the query cache, so the rows are discarded when
 *   the panel unmounts (R5.6).
 */
export function PreviewPanel({ datasetId, datasetCode }: PreviewPanelProps) {
  // The last successful preview response, held in LOCAL state only so rows are
  // never persisted/cached beyond this view's lifetime (R5.6).
  const [result, setResult] = React.useState<RawPreviewResponse | null>(null)
  const [error, setError] = React.useState<string | null>(null)

  // Raw text inputs; parsed + clamped on submit so partial typing never fires a
  // request and the user keeps full control of the window.
  const [limitText, setLimitText] = React.useState(String(DEFAULT_PREVIEW_LIMIT))
  const [offsetText, setOffsetText] = React.useState('0')
  const [columnsText, setColumnsText] = React.useState('')

  // A mutation (not a query) means TanStack Query never caches the rows: the
  // response is read once and copied into local state (R5.6).
  const preview = usePreviewDataset({ request: jsonRequest() })

  async function handleSubmit(event: React.FormEvent) {
    event.preventDefault()
    setError(null)

    const limit = clampLimit(Number.parseInt(limitText, 10))
    const offset = clampOffset(Number.parseInt(offsetText, 10))
    // Reflect the clamped values back so the user sees the window actually sent.
    setLimitText(String(limit))
    setOffsetText(String(offset))

    const columns = columnsText
      .split(',')
      .map((c) => c.trim())
      .filter((c) => c.length > 0)

    const body: RawPreviewRequest = { limit, offset }
    // Optional column selection: omit the key entirely when none is chosen so
    // the backend returns all columns (R5.1).
    if (columns.length > 0) {
      body.columns = columns
    }

    try {
      const response = await preview.mutateAsync({ datasetId, data: body })
      setResult(response)
    } catch (err) {
      const axiosError = err as AxiosError
      setResult(null)
      setError(
        parseProblem(axiosError).detail ??
          axiosError.message ??
          'Could not load the preview.',
      )
    }
  }

  return (
    <div className="flex flex-col gap-6">
      <PageHeader
        title="Preview"
        description={
          <>
            Preview rows for dataset <code>{datasetCode}</code> from{' '}
            <code>POST /api/v1/raw-datasets/{'{dataset_id}'}/preview</code>.
          </>
        }
      />

      <form
        onSubmit={handleSubmit}
        className="grid gap-4 sm:grid-cols-[8rem_8rem_1fr_auto] sm:items-end"
      >
        <FormItem>
          <FormLabel htmlFor="preview-limit">Limit</FormLabel>
          <FormControl>
            <Input
              id="preview-limit"
              inputMode="numeric"
              value={limitText}
              onChange={(e) => setLimitText(e.target.value)}
            />
          </FormControl>
          <FormDescription>1–200</FormDescription>
        </FormItem>

        <FormItem>
          <FormLabel htmlFor="preview-offset">Offset</FormLabel>
          <FormControl>
            <Input
              id="preview-offset"
              inputMode="numeric"
              value={offsetText}
              onChange={(e) => setOffsetText(e.target.value)}
            />
          </FormControl>
          <FormDescription>≥ 0</FormDescription>
        </FormItem>

        <FormItem>
          <FormLabel htmlFor="preview-columns">Columns (optional)</FormLabel>
          <FormControl>
            <Input
              id="preview-columns"
              placeholder="Leave blank for all columns"
              value={columnsText}
              onChange={(e) => setColumnsText(e.target.value)}
            />
          </FormControl>
          <FormDescription>Comma-separated column names.</FormDescription>
        </FormItem>

        <Button type="submit" disabled={preview.isPending} className="w-fit">
          {preview.isPending && <Loader2 className="animate-spin" />}
          {preview.isPending ? 'Loading…' : 'Preview rows'}
        </Button>
      </form>

      {error && <ErrorStateInline message={error} />}

      {result && <PreviewResult result={result} />}

      {!result && !error && !preview.isPending && (
        <EmptyState
          title="No preview loaded"
          description="Choose a window and preview rows. Rows are shown for this view only and are not cached."
        />
      )}
    </div>
  )
}

/** Render the returned columns/rows plus the window counts (R5.4, R5.5). */
function PreviewResult({ result }: { result: RawPreviewResponse }) {
  const { columns, rows, offset, limit, total_rows } = result

  return (
    <div className="flex flex-col gap-3">
      <WindowSummary offset={offset} limit={limit} totalRows={total_rows} />

      {rows.length === 0 ? (
        // Zero-row response: a message while the window counts stay visible
        // above (R5.5).
        <EmptyState
          title="No rows in this window"
          description="The dataset returned no rows for the requested offset and limit."
        />
      ) : (
        <div className="rounded-md border">
          <Table>
            <TableHeader>
              <TableRow>
                {columns.map((column) => (
                  <TableHead key={column}>{column}</TableHead>
                ))}
              </TableRow>
            </TableHeader>
            <TableBody>
              {rows.map((row, rowIndex) => (
                <TableRow key={rowIndex}>
                  {columns.map((column) => (
                    <TableCell key={column}>{formatCell(row[column])}</TableCell>
                  ))}
                </TableRow>
              ))}
            </TableBody>
          </Table>
        </div>
      )}
    </div>
  )
}

interface WindowSummaryProps {
  offset: number
  limit: number
  totalRows: number
}

/** The offset/limit/total_rows summary, always shown with any result (R5.4). */
function WindowSummary({ offset, limit, totalRows }: WindowSummaryProps) {
  return (
    <dl className="text-muted-foreground flex flex-wrap gap-x-6 gap-y-1 text-sm">
      <div className="flex gap-1">
        <dt className="font-medium">Offset</dt>
        <dd>{offset}</dd>
      </div>
      <div className="flex gap-1">
        <dt className="font-medium">Limit</dt>
        <dd>{limit}</dd>
      </div>
      <div className="flex gap-1">
        <dt className="font-medium">Total rows</dt>
        <dd>{totalRows}</dd>
      </div>
    </dl>
  )
}

/** Inline error notice for a failed preview request. */
function ErrorStateInline({ message }: { message: string }) {
  return (
    <div
      role="alert"
      className="border-destructive/50 bg-destructive/10 text-destructive rounded-md border px-3 py-2 text-sm"
    >
      {message}
    </div>
  )
}

/** Render a single cell value; nullish values show an em dash. */
function formatCell(value: unknown): React.ReactNode {
  if (value === null || value === undefined) return '—'
  if (typeof value === 'object') return JSON.stringify(value)
  return String(value)
}
