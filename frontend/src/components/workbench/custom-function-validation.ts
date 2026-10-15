import type { CustomFunctionDefinition } from '@/api/generated/model'

const IDENTIFIER = /^[a-z][a-z0-9_]{0,62}$/

export function customFunctionIssues(
  definition: CustomFunctionDefinition,
  allFunctions: readonly CustomFunctionDefinition[],
  index: number,
): string[] {
  const issues: string[] = []
  if (!IDENTIFIER.test(definition.id)) issues.push('invalid function ID')
  if (allFunctions.some((item, itemIndex) => itemIndex !== index && item.id === definition.id)) {
    issues.push('duplicate function ID')
  }
  if (definition.parameters.some((item) => !IDENTIFIER.test(item))) issues.push('invalid parameter name')
  if (new Set(definition.parameters).size !== definition.parameters.length) issues.push('duplicate parameter')
  if (definition.implementations.length === 0) issues.push('language body required')
  if (definition.implementations.some((item) => !item.source.trim())) issues.push('empty language body')
  if (new Set(definition.implementations.map((item) => item.language)).size !== definition.implementations.length) {
    issues.push('duplicate language')
  }
  return issues
}

export function validateCustomFunctions(functions: readonly CustomFunctionDefinition[]): string | null {
  for (const [index, definition] of functions.entries()) {
    const issues = customFunctionIssues(definition, functions, index)
    if (issues.length > 0) return `${definition.id || `Function ${index + 1}`}: ${issues.join(', ')}.`
  }
  return null
}
