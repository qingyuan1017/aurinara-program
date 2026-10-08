import * as React from 'react'
import type { AxiosError } from 'axios'
import { Loader2 } from 'lucide-react'
import { PageHeader } from '@/components/layout/page-header'
import { EmptyState, ErrorState } from '@/components/data/states'
import { StatusBadge } from '@/components/data/status-badge'
import { IssueList } from '@/components/data/issue-list'
import { Button } from '@/components/ui/button'
import { Input } from '@/components/ui/input'
import { Badge } from '@/components/ui/badge'
import {
  Card,
  CardContent,
  CardDescription,
  CardHeader,
  CardTitle,
} from '@/components/ui/card'
import {
  FormControl,
  FormDescription,
  FormItem,
  FormLabel,
} from '@/components/ui/form'
import { useValidateRaw } from '@/api/generated/raw/raw'
import { useGetValidationRun } from '@/api/generated/validation/validation'
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
 * Shared by both the synchronous validate result and the open-by-id lookup so
 * the two surfaces render identically (Requirements 6.1, 6.2, 6.4).
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
 * - Open-by-id (R6.4): looking up `GET /api/v1/validation-runs/{id}` renders
 *   the referenced run's status/counts/issues. A `404` shows a not-found notice
 *   and NO stale run content (R6.5).
 */
export function RawValidationPanel({ rawId }: RawValidationPanelProps) {
  const validate = useValidateRaw()
  const result = validate.data

  const [lookupInput, setLookupInput] = React.useState('')
  // The id actually being looked up; set only on explicit submit so typing
  // does not fire a request per keystroke.
  const [lookupId, setLookupId] = React.useState<string | null>(null)

  const lookupQuery = useGetValidationRun(lookupId ?? '', {
    query: { enabled: !!lookupId, retry: false },
  })

  const validateProblem = validate.error
    ? parseProblem(validate.error as AxiosError)
    : null

  const lookupStatus = (lookupQuery.error as AxiosError | null)?.response?.status
  const lookupIsNotFound = lookupStatus === 404

  function handleLookup(event: React.FormEvent) {
    event.preventDefault()
    const trimmed = lookupInput.trim()
    setLookupId(trimmed || null)
  }

  return (
    <div className="flex flex-col gap-6">
      <PageHeader
        title="Validation"
        description={
          <>
            Run Raw validation (<code>POST /api/v1/raw/{'{raw_id}'}/validate</code>
            ) and review the resulting issues.
          </>
        }
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

      <Card>
        <CardHeader>
          <CardTitle className="text-base">Open a validation run by ID</CardTitle>
          <CardDescription>
            Look up a previously recorded validation run by its identifier.
          </CardDescription>
        </CardHeader>
        <CardContent className="flex flex-col gap-4">
          <form className="flex items-end gap-2" onSubmit={handleLookup}>
            <FormItem className="flex-1">
              <FormLabel htmlFor="validation-run-id">Validation run ID</FormLabel>
              <FormControl>
                <Input
                  id="validation-run-id"
                  value={lookupInput}
                  onChange={(event) => setLookupInput(event.target.value)}
                  placeholder="Validation run UUID"
                />
              </FormControl>
              <FormDescription>
                Retrieves <code>GET /api/v1/validation-runs/{'{id}'}</code>.
              </FormDescription>
            </FormItem>
            <Button type="submit" variant="outline" disabled={!lookupInput.trim()}>
              Open
            </Button>
          </form>

          {lookupId &&
            (lookupIsNotFound ? (
              // 404: show a not-found notice and NO stale run content (R6.5).
              <EmptyState
                title="Validation run not found"
                description="The referenced validation run is unavailable."
              />
            ) : lookupQuery.isError ? (
              <ErrorState
                error={lookupQuery.error as AxiosError}
                resourceLabel="validation run"
              />
            ) : lookupQuery.isLoading ? (
              <EmptyState title="Loading…" description="Fetching the validation run." />
            ) : lookupQuery.data ? (
              <ValidationRunView run={lookupQuery.data} />
            ) : null)}
        </CardContent>
      </Card>
    </div>
  )
}
