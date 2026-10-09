import * as React from 'react'
import { Badge } from '@/components/ui/badge'
import {
  Card,
  CardContent,
  CardDescription,
  CardHeader,
  CardTitle,
} from '@/components/ui/card'
import { EmptyState } from '@/components/data/states'

/**
 * The common validation/reconciliation issue model, mirroring the backend
 * `ValidationIssue` contract (`src/app/validation/contracts.py`). The Orval
 * generator models each issue as an opaque `{ [key: string]: unknown }`
 * dictionary, so this component declares the typed shape it renders.
 */
export type IssueSeverity = 'error' | 'warning' | 'info'

export interface ValidationIssue {
  id: string
  code: string
  severity: IssueSeverity
  message: string
  suggestion?: string | null
  module?: string | null
  entity_type?: string | null
  entity_id?: string | null
  field_path?: string | null
  dataset?: string | null
  variable?: string | null
  artifact_id?: string | null
}

export interface IssueListProps {
  /**
   * The common-issue-model entries to render. Accepts both the opaque generated
   * dictionary shape and the typed {@link ValidationIssue} (e.g. client-side
   * findings merged with backend issues).
   */
  issues: ReadonlyArray<Record<string, unknown> | ValidationIssue>
  /**
   * Message shown when there are no issues. Defaults to a generic "no issues"
   * empty state.
   */
  emptyTitle?: string
  emptyDescription?: React.ReactNode
}

const SEVERITY_ORDER: readonly IssueSeverity[] = ['error', 'warning', 'info']

const SEVERITY_VARIANT: Record<IssueSeverity, 'destructive' | 'secondary' | 'outline'> = {
  error: 'destructive',
  warning: 'secondary',
  info: 'outline',
}

const SEVERITY_LABEL: Record<IssueSeverity, string> = {
  error: 'Error',
  warning: 'Warning',
  info: 'Info',
}

function asIssue(input: Record<string, unknown> | ValidationIssue): ValidationIssue {
  const raw = input as Record<string, unknown>
  const severity = String(raw.severity ?? 'info') as IssueSeverity
  return {
    id: String(raw.id ?? ''),
    code: String(raw.code ?? ''),
    severity: SEVERITY_ORDER.includes(severity) ? severity : 'info',
    message: String(raw.message ?? ''),
    suggestion: (raw.suggestion as string | null | undefined) ?? null,
    module: (raw.module as string | null | undefined) ?? null,
    entity_type: (raw.entity_type as string | null | undefined) ?? null,
    entity_id: (raw.entity_id as string | null | undefined) ?? null,
    field_path: (raw.field_path as string | null | undefined) ?? null,
    dataset: (raw.dataset as string | null | undefined) ?? null,
    variable: (raw.variable as string | null | undefined) ?? null,
    artifact_id: (raw.artifact_id as string | null | undefined) ?? null,
  }
}

interface MetaField {
  label: string
  value: string | null | undefined
}

function IssueMeta({ fields }: { fields: MetaField[] }) {
  const present = fields.filter((field) => field.value)
  if (present.length === 0) return null
  return (
    <dl className="text-muted-foreground mt-2 grid grid-cols-2 gap-x-6 gap-y-1 text-xs sm:grid-cols-3">
      {present.map((field) => (
        <div key={field.label}>
          <dt className="inline font-medium">{field.label}: </dt>
          <dd className="inline break-all">{field.value}</dd>
        </div>
      ))}
    </dl>
  )
}

function IssueRow({ issue }: { issue: ValidationIssue }) {
  return (
    <li className="border-border border-b py-3 last:border-b-0">
      <div className="flex items-start gap-2">
        <Badge variant={SEVERITY_VARIANT[issue.severity]}>
          {SEVERITY_LABEL[issue.severity]}
        </Badge>
        <div className="min-w-0 flex-1">
          <div className="flex flex-wrap items-baseline gap-2">
            <code className="text-xs font-semibold">{issue.code}</code>
          </div>
          <p className="text-sm">{issue.message}</p>
          {issue.suggestion && (
            <p className="text-muted-foreground mt-1 text-sm">
              <span className="font-medium">Suggestion: </span>
              {issue.suggestion}
            </p>
          )}
          <IssueMeta
            fields={[
              { label: 'Entity type', value: issue.entity_type },
              { label: 'Entity ID', value: issue.entity_id },
              { label: 'Field path', value: issue.field_path },
              { label: 'Dataset', value: issue.dataset },
              { label: 'Variable', value: issue.variable },
            ]}
          />
        </div>
      </div>
    </li>
  )
}

/**
 * Renders the common validation/reconciliation issue model with a per-severity
 * count summary and an empty state. Shared by Raw, SDTM, Define, and cSDRG
 * validation and reconciliation result views (Requirements 6.2, 14.3).
 */
export function IssueList({
  issues,
  emptyTitle = 'No issues',
  emptyDescription = 'This run produced no validation issues.',
}: IssueListProps) {
  const parsed = React.useMemo(() => issues.map(asIssue), [issues])

  const counts = React.useMemo(() => {
    const base: Record<IssueSeverity, number> = { error: 0, warning: 0, info: 0 }
    for (const issue of parsed) {
      base[issue.severity] += 1
    }
    return base
  }, [parsed])

  if (parsed.length === 0) {
    return <EmptyState title={emptyTitle} description={emptyDescription} />
  }

  return (
    <Card>
      <CardHeader>
        <CardTitle className="text-base">Issues</CardTitle>
        <CardDescription className="flex flex-wrap gap-2" aria-label="Issue counts by severity">
          {SEVERITY_ORDER.map((severity) => (
            <Badge key={severity} variant={SEVERITY_VARIANT[severity]}>
              {SEVERITY_LABEL[severity]}: {counts[severity]}
            </Badge>
          ))}
        </CardDescription>
      </CardHeader>
      <CardContent>
        <ul className="list-none">
          {parsed.map((issue, index) => (
            <IssueRow key={issue.id || `${issue.code}-${index}`} issue={issue} />
          ))}
        </ul>
      </CardContent>
    </Card>
  )
}
