import type { CustomFunctionDefinition } from '@/api/generated/model'

/**
 * Rename a custom function and reconcile call arguments by parameter name.
 * A same-position rename preserves its expression; newly added parameters get
 * an intentionally incomplete column expression for the author to configure.
 */
export function synchronizeCustomFunctionCalls(
  value: unknown,
  previous: CustomFunctionDefinition,
  next: CustomFunctionDefinition,
): unknown {
  if (Array.isArray(value)) {
    return value.map((item) => synchronizeCustomFunctionCalls(item, previous, next))
  }
  if (value === null || typeof value !== 'object') return value
  const source = value as Record<string, unknown>
  if (source.kind === 'custom_function' && source.function_id === previous.id) {
    const arguments_ = Array.isArray(source.arguments) ? source.arguments : []
    return {
      ...source,
      function_id: next.id,
      arguments: next.parameters.map((parameter, nextIndex) => {
        const previousIndex = previous.parameters.indexOf(parameter)
        if (previousIndex >= 0 && previousIndex < arguments_.length) {
          return synchronizeCustomFunctionCalls(arguments_[previousIndex], previous, next)
        }
        const renamedInPlace =
          nextIndex < previous.parameters.length &&
          !next.parameters.includes(previous.parameters[nextIndex])
        return renamedInPlace && nextIndex < arguments_.length
          ? synchronizeCustomFunctionCalls(arguments_[nextIndex], previous, next)
          : { kind: 'column', column: '' }
      }),
    }
  }
  const renamed: Record<string, unknown> = {}
  for (const [key, item] of Object.entries(source)) {
    renamed[key] = synchronizeCustomFunctionCalls(item, previous, next)
  }
  return renamed
}
