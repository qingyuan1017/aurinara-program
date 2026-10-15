import type { SdtmDerivationPlan } from '@/api/generated/model'

/**
 * Pure parsing + validation for the SDTM Derivation Plan JSON import
 * affordance. Kept I/O-free (no React, no network) so the behavior is
 * unit-testable in isolation.
 *
 * The import only populates the on-canvas graph (nodes/edges); the existing
 * "Save plan" flow remains authoritative for revision pinning, If-Match, and
 * full backend validation. This helper therefore validates just enough to load
 * the canvas safely: the text is valid JSON, it is an object, its `domain`
 * matches the domain being edited, and its `nodes`/`edges` are arrays.
 */

/** The node/edge arrays extracted from an imported plan, ready for the canvas. */
export interface ImportedPlanGraph {
  customFunctions: SdtmDerivationPlan['custom_functions']
  nodes: SdtmDerivationPlan['nodes']
  edges: SdtmDerivationPlan['edges']
}

export type PlanJsonImportResult =
  | { ok: true; value: ImportedPlanGraph }
  | { ok: false; error: string }

function isRecord(value: unknown): value is Record<string, unknown> {
  return typeof value === 'object' && value !== null && !Array.isArray(value)
}

/**
 * Parse and validate pasted/uploaded plan JSON for the given domain. Returns
 * the typed node/edge arrays on success, or a friendly, user-facing error
 * message on failure. The backend remains authoritative for full plan
 * validation; this never throws on malformed input.
 *
 * @param text The raw pasted/uploaded JSON text.
 * @param domainCode The domain currently being edited (the plan's natural key).
 */
export function parsePlanJsonImport(
  text: string,
  domainCode: string,
): PlanJsonImportResult {
  const trimmed = text.trim()
  if (!trimmed) {
    return { ok: false, error: 'Paste or upload a derivation plan JSON first.' }
  }

  let parsed: unknown
  try {
    parsed = JSON.parse(trimmed)
  } catch {
    return {
      ok: false,
      error: 'That is not valid JSON. Check for a missing comma or bracket.',
    }
  }

  if (!isRecord(parsed)) {
    return {
      ok: false,
      error: 'The plan JSON must be an object with a "domain" and "nodes".',
    }
  }

  const domain = parsed.domain
  if (typeof domain !== 'string' || domain.length === 0) {
    return {
      ok: false,
      error: 'The plan JSON is missing a string "domain" field.',
    }
  }
  if (domain !== domainCode) {
    return {
      ok: false,
      error: `The plan JSON is for domain "${domain}", but this editor is for "${domainCode}". Import it from the matching domain.`,
    }
  }

  if (!Array.isArray(parsed.nodes)) {
    return { ok: false, error: 'The plan JSON must contain a "nodes" array.' }
  }
  if (parsed.nodes.length === 0) {
    return {
      ok: false,
      error: 'The plan JSON has no nodes. A plan needs at least one node.',
    }
  }
  if (parsed.edges !== undefined && !Array.isArray(parsed.edges)) {
    return {
      ok: false,
      error: 'The plan JSON "edges" field must be an array when present.',
    }
  }
  if (
    parsed.custom_functions !== undefined &&
    !Array.isArray(parsed.custom_functions)
  ) {
    return {
      ok: false,
      error: 'The plan JSON "custom_functions" field must be an array when present.',
    }
  }

  return {
    ok: true,
    value: {
      customFunctions: (parsed.custom_functions ?? []) as SdtmDerivationPlan['custom_functions'],
      nodes: parsed.nodes as SdtmDerivationPlan['nodes'],
      edges: (parsed.edges ?? []) as SdtmDerivationPlan['edges'],
    },
  }
}
