export type AlignmentState = 'aligned' | 'misaligned'

export function isMisaligned(
  state: AlignmentState | null | undefined,
): boolean {
  return state === 'misaligned'
}
