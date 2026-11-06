export const MIN_PREVIEW_LIMIT = 1
export const MAX_PREVIEW_LIMIT = 200
export const DEFAULT_PREVIEW_LIMIT = 50

export function clampLimit(limit: number | undefined): number {
  if (limit === undefined || Number.isNaN(limit)) return DEFAULT_PREVIEW_LIMIT
  return Math.min(
    Math.max(Math.floor(limit), MIN_PREVIEW_LIMIT),
    MAX_PREVIEW_LIMIT,
  )
}

export function clampOffset(offset: number | undefined): number {
  if (offset === undefined || Number.isNaN(offset)) return 0
  return Math.max(Math.floor(offset), 0)
}
