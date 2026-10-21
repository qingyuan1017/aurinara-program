import { createContext, useContext } from 'react'
import type { StudyResponse } from '@/api/generated/model'

export interface CurrentStudyContextValue {
  studies: StudyResponse[]
  currentStudy: StudyResponse | null
  currentStudyId: string | null
  setCurrentStudyId: (id: string) => void
  isLoading: boolean
  isError: boolean
}

export const CurrentStudyContext = createContext<
  CurrentStudyContextValue | undefined
>(undefined)

export function useCurrentStudy(): CurrentStudyContextValue {
  const context = useContext(CurrentStudyContext)
  if (context === undefined) {
    throw new Error('useCurrentStudy must be used within a StudyProvider')
  }
  return context
}
