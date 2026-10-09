import type { AxiosError } from 'axios'

/**
 * The backend returns `application/problem+json` (RFC 9457), NOT the generated
 * `HTTPValidationError` 422 shape. Application errors fill `issues[]`; transport
 * 422 validation fills `errors[]` with stringified `location` arrays.
 * (Verified in `src/app/common/problems.py`.)
 */

export interface ProblemIssue {
  code?: string
  severity?: string
  message?: string
  field_path?: string | null
  [key: string]: unknown
}

export interface ProblemTransportError {
  location: (string | number)[] | string[]
  message: string
  type: string
}

export interface ProblemDetail {
  type?: string
  title?: string
  status?: number
  detail?: string
  code?: string
  issues?: ProblemIssue[]
  errors?: ProblemTransportError[]
}

/** Read the problem body defensively — it may be absent (network/500) or a string. */
export function parseProblem(error: AxiosError): ProblemDetail {
  const data = error.response?.data
  return data && typeof data === 'object' ? (data as ProblemDetail) : {}
}

/**
 * 412/428 are detected by status ALONE (body-independent). 409 variants are
 * distinguished by the problem `code`, falling back to `detail`. Checked BEFORE
 * generic field mapping; when non-null, render as the sole top-level alert.
 */
export function stalenessAlert(error: AxiosError): string | null {
  const status = error.response?.status
  if (status === 412)
    return 'This record changed since you opened it. Reload and try again.'
  if (status === 428)
    return 'A required precondition header was missing — please retry.'
  if (status === 409) {
    const problem = parseProblem(error)
    if (problem.code === 'idempotency_key_reused')
      return 'This action was already submitted with different inputs.'
    return problem.detail ?? 'This change conflicts with the current state.'
  }
  return null
}

/**
 * EXACT field matching (no fuzzy last-segment):
 * - errors[]: strip a leading "body" segment, join the remainder with "." and
 *   compare the whole joined path to a descriptor field name.
 * - issues[]: compare `field_path` exactly to a descriptor name.
 * Anything that does not match a field goes to the top-level alert.
 */
export function mapProblemToFieldErrors(
  error: AxiosError,
  fieldNames: string[],
): { fieldErrors: Record<string, string>; formErrors: string[] } {
  const problem = parseProblem(error)
  const fieldErrors: Record<string, string> = {}
  const formErrors: string[] = []

  if (problem.errors?.length) {
    for (const entry of problem.errors) {
      const loc = entry.location.map(String)
      const rest = loc[0] === 'body' ? loc.slice(1) : loc
      const path = rest.join('.')
      if (path && fieldNames.includes(path)) {
        fieldErrors[path] = entry.message
      } else {
        formErrors.push(entry.message)
      }
    }
  }

  if (problem.issues?.length) {
    for (const issue of problem.issues) {
      const path = issue.field_path
      if (typeof path === 'string' && fieldNames.includes(path)) {
        fieldErrors[path] = issue.message ?? issue.code ?? 'Invalid.'
      } else {
        formErrors.push(
          issue.message ?? problem.detail ?? issue.code ?? 'Request failed.',
        )
      }
    }
  }

  if (!problem.errors?.length && !problem.issues?.length) {
    formErrors.push(problem.detail ?? error.message ?? 'Request failed.')
  }

  return { fieldErrors, formErrors }
}
