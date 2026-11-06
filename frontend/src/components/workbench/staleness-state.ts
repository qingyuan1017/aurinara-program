export type StalenessState =
  | 'dependency_refresh_required'
  | 'input_refresh_required'

export function isStale(state: StalenessState | null | undefined): boolean {
  return state === 'dependency_refresh_required' || state === 'input_refresh_required'
}
