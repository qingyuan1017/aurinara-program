import type { AxiosError } from 'axios'
import { describe, expect, it } from 'vitest'

import {
  mapProblemToFieldErrors,
  stalenessAlert,
  type ProblemDetail,
} from './problems'

/**
 * Build a minimal object shaped like the `AxiosError` fields the helpers read:
 * `response.status`, `response.data` (the `problem+json` body), and `message`.
 * The helpers only touch those paths, so a structural stand-in is sufficient
 * and avoids depending on axios's error constructor.
 */
function axiosError(
  status: number | undefined,
  data?: ProblemDetail | string | null,
  message = 'Request failed with status code',
): AxiosError {
  return {
    message,
    response: status === undefined ? undefined : { status, data },
  } as unknown as AxiosError
}

describe('stalenessAlert', () => {
  it('returns the stale-record sentence for 412 regardless of body', () => {
    expect(stalenessAlert(axiosError(412))).toBe(
      'This record changed since you opened it. Reload and try again.',
    )
    // Body is ignored for 412 — same sentence even with an unrelated code.
    expect(stalenessAlert(axiosError(412, { code: 'whatever' }))).toBe(
      'This record changed since you opened it. Reload and try again.',
    )
  })

  it('returns the missing-precondition sentence for 428 regardless of body', () => {
    expect(stalenessAlert(axiosError(428))).toBe(
      'A required precondition header was missing — please retry.',
    )
    expect(stalenessAlert(axiosError(428, { detail: 'ignored' }))).toBe(
      'A required precondition header was missing — please retry.',
    )
  })

  it('returns the idempotency sentence for 409 idempotency_key_reused', () => {
    expect(
      stalenessAlert(axiosError(409, { code: 'idempotency_key_reused' })),
    ).toBe('This action was already submitted with different inputs.')
  })

  it('returns the problem detail for a 409 with a non-idempotency code', () => {
    expect(
      stalenessAlert(
        axiosError(409, {
          code: 'duplicate_raw_dataset_code',
          detail: 'Dataset code DM already exists.',
        }),
      ),
    ).toBe('Dataset code DM already exists.')
  })

  it('falls back to a generic conflict sentence for a 409 with no detail', () => {
    expect(stalenessAlert(axiosError(409, { code: 'some_conflict' }))).toBe(
      'This change conflicts with the current state.',
    )
    // A 409 with no parseable object body still yields the generic sentence.
    expect(stalenessAlert(axiosError(409, null))).toBe(
      'This change conflicts with the current state.',
    )
  })

  it('returns null for non-staleness statuses', () => {
    expect(stalenessAlert(axiosError(200))).toBeNull()
    expect(stalenessAlert(axiosError(422, { detail: 'invalid' }))).toBeNull()
    expect(stalenessAlert(axiosError(404))).toBeNull()
    expect(stalenessAlert(axiosError(undefined))).toBeNull()
  })
})

describe('mapProblemToFieldErrors', () => {
  const fields = ['code', 'label', 'source_file_id']

  it('routes transport errors[] to the matching field (leading "body" stripped)', () => {
    const result = mapProblemToFieldErrors(
      axiosError(422, {
        errors: [
          { location: ['body', 'code'], message: 'Code is required', type: 'missing' },
          { location: ['body', 'label'], message: 'Label too long', type: 'value_error' },
        ],
      }),
      fields,
    )

    expect(result.fieldErrors).toEqual({
      code: 'Code is required',
      label: 'Label too long',
    })
    expect(result.formErrors).toEqual([])
  })

  it('routes unmatched transport errors[] to the form bucket', () => {
    const result = mapProblemToFieldErrors(
      axiosError(422, {
        errors: [
          { location: ['body', 'unknown_field'], message: 'Unexpected', type: 'extra' },
          { location: ['query', 'limit'], message: 'Bad limit', type: 'value_error' },
        ],
      }),
      fields,
    )

    expect(result.fieldErrors).toEqual({})
    expect(result.formErrors).toEqual(['Unexpected', 'Bad limit'])
  })

  it('uses the exact joined path, not a fuzzy last segment', () => {
    // `nested.code` must NOT match the top-level `code` field.
    const result = mapProblemToFieldErrors(
      axiosError(422, {
        errors: [
          { location: ['body', 'nested', 'code'], message: 'Nested problem', type: 'x' },
        ],
      }),
      fields,
    )

    expect(result.fieldErrors).toEqual({})
    expect(result.formErrors).toEqual(['Nested problem'])
  })

  it('routes application issues[] by exact field_path into field and form buckets', () => {
    const result = mapProblemToFieldErrors(
      axiosError(422, {
        detail: 'Invalid clinical content.',
        issues: [
          { code: 'required', message: 'Code missing', field_path: 'code' },
          { code: 'xref', message: 'Workbench-level problem', field_path: null },
          { code: 'other', message: 'No path at all' },
        ],
      }),
      fields,
    )

    expect(result.fieldErrors).toEqual({ code: 'Code missing' })
    expect(result.formErrors).toEqual([
      'Workbench-level problem',
      'No path at all',
    ])
  })

  it('falls back through message/code/detail for issues without a message', () => {
    const result = mapProblemToFieldErrors(
      axiosError(422, {
        issues: [{ code: 'bad_value', field_path: 'label' }],
      }),
      fields,
    )

    expect(result.fieldErrors).toEqual({ label: 'bad_value' })
    expect(result.formErrors).toEqual([])
  })

  it('combines errors[] and issues[] from the same problem body', () => {
    const result = mapProblemToFieldErrors(
      axiosError(422, {
        errors: [
          { location: ['body', 'source_file_id'], message: 'Required', type: 'missing' },
        ],
        issues: [{ code: 'dup', message: 'Duplicate', field_path: 'code' }],
      }),
      fields,
    )

    expect(result.fieldErrors).toEqual({
      source_file_id: 'Required',
      code: 'Duplicate',
    })
    expect(result.formErrors).toEqual([])
  })

  it('pushes a single form error from detail when neither errors[] nor issues[] are present', () => {
    const result = mapProblemToFieldErrors(
      axiosError(500, { detail: 'Internal server error.' }),
      fields,
    )

    expect(result.fieldErrors).toEqual({})
    expect(result.formErrors).toEqual(['Internal server error.'])
  })

  it('falls back to the axios message when the body carries no detail', () => {
    const result = mapProblemToFieldErrors(
      axiosError(503, {}, 'Network Error'),
      fields,
    )

    expect(result.fieldErrors).toEqual({})
    expect(result.formErrors).toEqual(['Network Error'])
  })
})
