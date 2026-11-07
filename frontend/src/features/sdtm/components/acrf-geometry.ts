/** A normalized top-left rectangle plus its one-based page number. */
export interface RectInput {
  x: number
  y: number
  width: number
  height: number
  page: number
}

export type RectField = 'x' | 'y' | 'width' | 'height' | 'page'

export interface RectValidationError {
  field: RectField
  message: string
}

export const RECT_FIELD_LABEL: Record<Exclude<RectField, 'page'>, string> = {
  x: 'X',
  y: 'Y',
  width: 'Width',
  height: 'Height',
}

export function validateRect(input: RectInput): RectValidationError | null {
  const { x, y, width, height, page } = input
  if (!Number.isInteger(page) || page < 1) {
    return { field: 'page', message: 'Page number must be an integer of 1 or greater.' }
  }
  const unit: { field: Exclude<RectField, 'page'>; value: number }[] = [
    { field: 'x', value: x },
    { field: 'y', value: y },
    { field: 'width', value: width },
    { field: 'height', value: height },
  ]
  for (const { field, value } of unit) {
    if (!Number.isFinite(value) || value < 0 || value > 1) {
      return {
        field,
        message: `${RECT_FIELD_LABEL[field]} must be a decimal between 0 and 1 inclusive.`,
      }
    }
  }
  if (x + width > 1) {
    return {
      field: 'width',
      message: 'The rectangle overflows the page: x + width must not exceed 1.',
    }
  }
  if (y + height > 1) {
    return {
      field: 'height',
      message: 'The rectangle overflows the page: y + height must not exceed 1.',
    }
  }
  return null
}
