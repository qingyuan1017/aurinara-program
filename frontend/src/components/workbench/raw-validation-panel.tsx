import type { AxiosError } from 'axios'
import { Loader2 } from 'lucide-react'
import { PageHeader } from '@/components/layout/page-header'
import { EmptyState } from '@/components/data/states'
import { StatusBadge } from '@/components/data/status-badge'
import { IssueList } from '@/components/data/issue-list'
import { Button } from '@/components/ui/button'
import { Badge } from '@/components/ui/badge'
import {
  Card,
  CardContent,
  CardDescription,
  CardHeader,
  CardTitle,
} from '@/components/ui/card'
import { useValidateRaw } from '@/api/generated/raw/raw'
import type { ValidationRunResponse } from '@/api/generated/model'
import { parseProblem } from '@/lib/problems'

export interface RawValidationPanelProps {
  /** The Raw workbench id to validate (path parameter for the POST). */
  rawId: string
}

/**
 * Render a single Validation_Run: status, per-severity counts, and the full
 * common-issue list (with its own empty state when there are no issues).
 *
 * The identifier remains internal; the user works with the validation result
 * created from this workbench.
 */
function ValidationRunView({ run }: { run: ValidationRunResponse }) {
  const isFailed = run.status.toLowerCase() === 'failed'
  return (
    <div className="flex flex-col gap-4">
      <Card>
        <CardHeader>
          <CardTitle className="text-base">Validation run</CardTitle>
          <CardDescription className="flex flex-wrap items-center gap-2">
            <StatusBadge status={run.status} />
            <Badge variant="destructive">Error: {run.error_count}</Badge>
            <Badge variant="secondary">Warning: {run.warning_count}</Badge>
            <Badge variant="outline">Info: {run.info_count}</Badge>
          </CardDescription>
        </CardHeader>
        <CardContent className="text-muted-foreground text-xs">
          <span className="font-medium">Validator: </span>
          {run.validator_name} {run.validator_version}
        </CardContent>
      </Card>

      {/* While a run status is `failed`, show a persistent block notice stating
          error-severity issues block Raw artifact generation (R6.3). */}
      {isFailed && (
        <Card className="border-destructive">
          <CardHeader>
            <CardTitle className="text-destructive text-base">
              Artifact generation blocked
            </CardTitle>
            <CardDescription>
              This workbench has error-severity issues. Error-severity issues
              block Raw artifact generation until they are resolved.
            </CardDescription>
          </CardHeader>
        </Card>
      )}

      <IssueList
        issues={run.issues}
        emptyDescription="This validation run produced no issues."
      />
    </div>
  )
}

/**
 * Raw Validation tab body (Requirement 6).
 *
 * Flows:
 * - Trigger validation (R6.1): `POST /api/v1/raw/{raw_id}/validate` returns a
 *   SYNCHRONOUS `200` ValidationRun (no polling). On success the run status and
 *   per-severity counts render immediately alongside the {@link IssueList}
 *   (R6.1, R6.2), which shows its own empty state when the run has no issues.
 * - A `failed` run shows a persistent notice that error-severity issues block
 *   Raw artifact generation (R6.3).
 */
export function RawValidationPanel({ rawId }: RawValidationPanelProps) {
  const validate = useValidateRaw()
  const result = validate.data

  const validateProblem = validate.error
    ? parseProblem(validate.error as AxiosError)
    : null

  return (
    <div className="flex flex-col gap-6">
      <PageHeader
        title="Validation"
        description="Run validation for this workbench and review the resulting issues."
        actions={
          <Button
            size="sm"
            onClick={() => validate.mutate({ rawId })}
            disabled={validate.isPending}
          >
            {validate.isPending && <Loader2 className="animate-spin" />}
            Run validation
          </Button>
        }
      />

      {validateProblem && (
        <Card className="border-destructive">
          <CardHeader>
            <CardTitle className="text-destructive text-base">
              {validateProblem.detail ?? 'Validation failed to run'}
            </CardTitle>
          </CardHeader>
        </Card>
      )}

      {validate.isPending && !result ? (
        <EmptyState
          title="Validating…"
          description="Running Raw validation."
        />
      ) : result ? (
        <ValidationRunView run={result} />
      ) : (
        !validateProblem && (
          <EmptyState
            title="No validation run yet"
            description="Run validation to see the status, issue counts, and issues."
          />
        )
      )}
    </div>
  )
}
