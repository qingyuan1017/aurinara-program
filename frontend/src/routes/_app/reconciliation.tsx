import * as React from 'react'
import { createFileRoute } from '@tanstack/react-router'
import { formatDate } from '@/lib/utils'
import { Button } from '@/components/ui/button'
import { Input } from '@/components/ui/input'
import {
  Card,
  CardContent,
  CardHeader,
  CardTitle,
} from '@/components/ui/card'
import { PageHeader } from '@/components/layout/page-header'
import { ResourceTable } from '@/components/data/resource-table'
import type { ResourceColumn } from '@/components/data/resource-table'
import { EmptyState } from '@/components/data/states'
import { StatusBadge } from '@/components/data/status-badge'
import {
  useGetReconciliation,
  useListReconciliationIssues,
} from '@/api/generated/reconciliation/reconciliation'
import type { ListReconciliationIssues200Item } from '@/api/generated/model'

export const Route = createFileRoute('/_app/reconciliation')({
  component: ReconciliationPage,
})

function buildIssueColumns(
  issues: ListReconciliationIssues200Item[],
): ResourceColumn<ListReconciliationIssues200Item>[] {
  const keys = Array.from(new Set(issues.flatMap((issue) => Object.keys(issue))))

  if (keys.length === 0) {
    return [
      {
        key: 'raw',
        header: 'Issue',
        cell: (issue) => JSON.stringify(issue),
      },
    ]
  }

  return keys.map((key) => ({
    key,
    header: key,
    cell: (issue) => {
      const value = (issue as Record<string, unknown>)[key]
      if (value == null) return '—'
      return typeof value === 'object' ? JSON.stringify(value) : String(value)
    },
  }))
}

function ReconciliationPage() {
  const [inputValue, setInputValue] = React.useState('')
  const [runId, setRunId] = React.useState('')

  const run = useGetReconciliation(runId, { query: { enabled: !!runId } })
  const issues = useListReconciliationIssues(runId, {
    query: { enabled: !!runId },
  })

  const issueRows = issues.data ?? []
  const issueColumns = buildIssueColumns(issueRows)

  const handleSubmit = (event: React.FormEvent) => {
    event.preventDefault()
    setRunId(inputValue.trim())
  }

  return (
    <div className="flex flex-col gap-6">
      <PageHeader
        title="Reconciliation"
        description="Look up a reconciliation run by id to view its result and issues."
      />

      <form onSubmit={handleSubmit} className="flex items-center gap-2">
        <Input
          value={inputValue}
          onChange={(event) => setInputValue(event.target.value)}
          placeholder="Reconciliation run id"
          className="max-w-sm"
        />
        <Button type="submit" disabled={!inputValue.trim()}>
          Look up
        </Button>
      </form>

      {!runId && (
        <EmptyState
          title="No run selected"
          description="Enter a reconciliation run id to view its result."
        />
      )}

      {runId && run.data && (
        <Card>
          <CardHeader>
            <div className="flex items-center justify-between">
              <CardTitle className="text-base">
                {run.data.reconciliation_type} ·{' '}
                {run.data.reconciliation_version}
              </CardTitle>
              <StatusBadge status={run.data.status} />
            </div>
          </CardHeader>
          <CardContent className="text-muted-foreground grid gap-1 text-sm">
            <div>
              Errors {run.data.error_count} · Warnings{' '}
              {run.data.warning_count} · Info {run.data.info_count}
            </div>
            <div>Started {formatDate(run.data.started_at)}</div>
            <div>Completed {formatDate(run.data.completed_at)}</div>
          </CardContent>
        </Card>
      )}

      {runId && (
        <ResourceTable
          columns={issueColumns}
          rows={issueRows}
          getRowId={(row) => String(issueRows.indexOf(row))}
          isLoading={run.isLoading || issues.isLoading}
          isError={run.isError || issues.isError}
          error={run.error ?? issues.error}
          resourceLabel="reconciliation issues"
        />
      )}
    </div>
  )
}
