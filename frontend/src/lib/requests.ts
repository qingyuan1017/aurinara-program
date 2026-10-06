import type { AxiosRequestConfig } from 'axios'

/**
 * Header helpers — the ONLY place header strings for mutations are built.
 *
 * The mutator (`src/api/axios-instance.ts`) shallow-spreads `{ ...config,
 * ...options }`, so an injected `headers` object REPLACES the generated
 * `{ 'Content-Type': 'application/json' }`. Every helper therefore re-emits
 * `Content-Type: application/json` so JSON bodies keep their content type.
 */

const JSON_CT = { 'Content-Type': 'application/json' } as const

/**
 * If-Match for a conditional write, derived from the entity revision. The
 * backend ETag is deterministically the string `"revision-{N}"` (embedded
 * double-quotes included) and is compared with `hmac.compare_digest`.
 */
export function ifMatchRequest(revision: number): AxiosRequestConfig {
  return { headers: { ...JSON_CT, 'If-Match': `"revision-${revision}"` } }
}

/**
 * Idempotency-Key for an operation-creating POST. Ships for the follow-up but
 * is wired to NO trigger this pass (see mutations plan Decision 9).
 */
export function idempotentRequest(): AxiosRequestConfig {
  return { headers: { ...JSON_CT, 'Idempotency-Key': crypto.randomUUID() } }
}

/** Plain JSON create: no conditional/idempotency header, but keep Content-Type. */
export function jsonRequest(): AxiosRequestConfig {
  return { headers: { ...JSON_CT } }
}
