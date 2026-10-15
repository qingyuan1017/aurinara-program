import type { FunctionCallExpression } from '@/api/generated/model'

export type FunctionName = FunctionCallExpression['function']
export type FunctionCategory = 'Text' | 'Missing values' | 'Numeric' | 'Date and time'

export interface FunctionParameterDescriptor {
  name: string
  description: string
}

export interface FunctionDescriptor {
  category: FunctionCategory
  description: string
  parameters: readonly FunctionParameterDescriptor[]
  variadic?: boolean
  variadicParameter?: FunctionParameterDescriptor
}

const parameter = (name: string, description: string): FunctionParameterDescriptor => ({
  name,
  description,
})

/**
 * Human-facing metadata for the closed function enum generated from OpenAPI.
 * The backend remains authoritative for validation and semantics; this catalog
 * gives positional wire arguments stable clinical authoring labels.
 */
export const FUNCTION_CATALOG: Record<FunctionName, FunctionDescriptor> = {
  concat: {
    category: 'Text',
    description: 'Join values as text; missing values contribute an empty string.',
    parameters: [parameter('value 1', 'First value to join.')],
    variadic: true,
    variadicParameter: parameter('value', 'Additional value to join.'),
  },
  substring: {
    category: 'Text',
    description: 'Take a 1-based span from a text value.',
    parameters: [
      parameter('text', 'Source text.'),
      parameter('start', 'One-based starting position.'),
      parameter('length', 'Number of characters to return.'),
    ],
  },
  upper: { category: 'Text', description: 'Convert ASCII letters to upper case.', parameters: [parameter('text', 'Text to convert.')] },
  lower: { category: 'Text', description: 'Convert ASCII letters to lower case.', parameters: [parameter('text', 'Text to convert.')] },
  trim: { category: 'Text', description: 'Remove leading and trailing whitespace.', parameters: [parameter('text', 'Text to trim.')] },
  length: { category: 'Text', description: 'Count characters in a text value.', parameters: [parameter('text', 'Text to measure.')] },
  contains: { category: 'Text', description: 'Test whether text contains a value.', parameters: [parameter('text', 'Text to inspect.'), parameter('search', 'Text to find.')] },
  startswith: { category: 'Text', description: 'Test whether text starts with a prefix.', parameters: [parameter('text', 'Text to inspect.'), parameter('prefix', 'Required prefix.')] },
  endswith: { category: 'Text', description: 'Test whether text ends with a suffix.', parameters: [parameter('text', 'Text to inspect.'), parameter('suffix', 'Required suffix.')] },
  replace: { category: 'Text', description: 'Replace every matching text fragment.', parameters: [parameter('text', 'Source text.'), parameter('search', 'Text to replace.'), parameter('replacement', 'Replacement text.')] },
  index_of: { category: 'Text', description: 'Return the one-based location of text.', parameters: [parameter('text', 'Text to inspect.'), parameter('search', 'Text to locate.')] },
  scan_token: { category: 'Text', description: 'Return a one-based token split by a delimiter.', parameters: [parameter('text', 'Source text.'), parameter('index', 'One-based token number.'), parameter('delimiter', 'Token delimiter.')] },
  pad_left: { category: 'Text', description: 'Pad text on the left to a target width.', parameters: [parameter('text', 'Source text.'), parameter('width', 'Target character width.'), parameter('fill', 'Padding character.')] },
  pad_right: { category: 'Text', description: 'Pad text on the right to a target width.', parameters: [parameter('text', 'Source text.'), parameter('width', 'Target character width.'), parameter('fill', 'Padding character.')] },

  coalesce: {
    category: 'Missing values',
    description: 'Return the first non-missing value.',
    parameters: [parameter('value 1', 'First candidate value.')],
    variadic: true,
    variadicParameter: parameter('value', 'Additional candidate value.'),
  },
  nullif: { category: 'Missing values', description: 'Return missing when two values are equal.', parameters: [parameter('value', 'Value to return.'), parameter('match', 'Value that causes a missing result.')] },
  is_in: { category: 'Missing values', description: 'Test membership in a typed value list.', parameters: [parameter('value', 'Value to test.'), parameter('allowed values', 'Typed list of allowed values.')] },
  n_missing: { category: 'Missing values', description: 'Count missing values.', parameters: [parameter('value 1', 'First value to inspect.')], variadic: true, variadicParameter: parameter('value', 'Additional value to inspect.') },
  n_present: { category: 'Missing values', description: 'Count non-missing values.', parameters: [parameter('value 1', 'First value to inspect.')], variadic: true, variadicParameter: parameter('value', 'Additional value to inspect.') },

  round: { category: 'Numeric', description: 'Round half away from zero.', parameters: [parameter('number', 'Number to round.'), parameter('digits', 'Decimal places.')] },
  floor: { category: 'Numeric', description: 'Round down to an integer.', parameters: [parameter('number', 'Number to round.')] },
  ceil: { category: 'Numeric', description: 'Round up to an integer.', parameters: [parameter('number', 'Number to round.')] },
  abs: { category: 'Numeric', description: 'Return the absolute value.', parameters: [parameter('number', 'Number to convert.')] },
  modulo: { category: 'Numeric', description: 'Return the truncated-division remainder.', parameters: [parameter('dividend', 'Number being divided.'), parameter('divisor', 'Number to divide by.')] },
  min_of: { category: 'Numeric', description: 'Return the smallest present value.', parameters: [parameter('value 1', 'First numeric value.')], variadic: true, variadicParameter: parameter('value', 'Additional numeric value.') },
  max_of: { category: 'Numeric', description: 'Return the largest present value.', parameters: [parameter('value 1', 'First numeric value.')], variadic: true, variadicParameter: parameter('value', 'Additional numeric value.') },
  truncate: { category: 'Numeric', description: 'Truncate a number toward zero.', parameters: [parameter('number', 'Number to truncate.')] },
  safe_divide: { category: 'Numeric', description: 'Divide and return missing for a zero divisor.', parameters: [parameter('numerator', 'Number being divided.'), parameter('denominator', 'Number to divide by.')] },

  parse_date: { category: 'Date and time', description: 'Parse a complete ISO date.', parameters: [parameter('text', 'YYYY-MM-DD text.')] },
  year: { category: 'Date and time', description: 'Extract the calendar year.', parameters: [parameter('date', 'Parsed date.')] },
  month: { category: 'Date and time', description: 'Extract the calendar month.', parameters: [parameter('date', 'Parsed date.')] },
  day: { category: 'Date and time', description: 'Extract the day of month.', parameters: [parameter('date', 'Parsed date.')] },
  date_diff_days: { category: 'Date and time', description: 'Return whole days between two dates.', parameters: [parameter('end date', 'Later or ending date.'), parameter('start date', 'Earlier or starting date.')] },
  parse_datetime: { category: 'Date and time', description: 'Parse an ISO date-time without an offset.', parameters: [parameter('text', 'ISO date-time text.')] },
  hour: { category: 'Date and time', description: 'Extract the hour.', parameters: [parameter('datetime', 'Parsed date-time.')] },
  minute: { category: 'Date and time', description: 'Extract the minute.', parameters: [parameter('datetime', 'Parsed date-time.')] },
  second: { category: 'Date and time', description: 'Extract the second.', parameters: [parameter('datetime', 'Parsed date-time.')] },
  study_day: { category: 'Date and time', description: 'Calculate CDISC study day with no day zero.', parameters: [parameter('event date', 'Subject event date.'), parameter('reference date', 'Study reference date.')] },
  date_add_days: { category: 'Date and time', description: 'Add whole days to a date.', parameters: [parameter('date', 'Starting date.'), parameter('days', 'Signed number of days.')] },
  date_diff_months: { category: 'Date and time', description: 'Return completed whole months between dates.', parameters: [parameter('end date', 'Later or ending date.'), parameter('start date', 'Earlier or starting date.')] },
}

export const FUNCTION_CATEGORIES: readonly FunctionCategory[] = [
  'Text',
  'Missing values',
  'Numeric',
  'Date and time',
]

export function functionParameter(
  functionName: FunctionName,
  index: number,
): FunctionParameterDescriptor {
  const descriptor = FUNCTION_CATALOG[functionName]
  return (
    descriptor.parameters[index] ?? {
      name: `${descriptor.variadicParameter?.name ?? 'value'} ${index + 1}`,
      description: descriptor.variadicParameter?.description ?? 'Additional argument.',
    }
  )
}
