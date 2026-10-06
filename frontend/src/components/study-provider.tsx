import {
  createContext,
  useCallback,
  useContext,
  useEffect,
  useMemo,
  useState,
} from 'react'
import { useListStudies } from '@/api/generated/studies/studies'
import type { StudyResponse } from '@/api/generated/model'
import { useAuth } from '@/components/auth-provider'

const STUDY_KEY = 'aurinara.currentStudy'

function readStoredStudyId(): string | null {
  try {
    return localStorage.getItem(STUDY_KEY)
  } catch {
    return null
  }
}

function writeStoredStudyId(id: string): void {
  try {
    localStorage.setItem(STUDY_KEY, id)
  } catch {
    // ignore storage failures (private mode, etc.)
  }
}

interface CurrentStudyContextValue {
  studies: StudyResponse[]
  currentStudy: StudyResponse | null
  currentStudyId: string | null
  setCurrentStudyId: (id: string) => void
  isLoading: boolean
  isError: boolean
}

const CurrentStudyContext = createContext<CurrentStudyContextValue | undefined>(
  undefined,
)

export function StudyProvider({ children }: { children: React.ReactNode }) {
  // Gate the query on the REACTIVE auth state (not a one-shot localStorage
  // read) so it re-fires automatically the moment the user signs in, without
  // needing a page refresh.
  const { isAuthenticated } = useAuth()
  const { data, isLoading, isError } = useListStudies(undefined, {
    query: { enabled: isAuthenticated },
  })
  const studies = useMemo(() => data?.items ?? [], [data])

  const [currentStudyId, setCurrentStudyIdState] = useState<string | null>(() =>
    readStoredStudyId(),
  )

  const setCurrentStudyId = useCallback((id: string) => {
    setCurrentStudyIdState(id)
    writeStoredStudyId(id)
  }, [])

  // Resolve the selection once studies load: keep a valid persisted id,
  // otherwise fall back to the first study and rewrite storage.
  useEffect(() => {
    if (studies.length === 0) return
    const persisted = currentStudyId
    const stillValid =
      persisted != null && studies.some((study) => study.id === persisted)
    if (!stillValid) {
      const fallback = studies[0].id
      setCurrentStudyIdState(fallback)
      writeStoredStudyId(fallback)
    }
  }, [studies, currentStudyId])

  const currentStudy = useMemo(
    () => studies.find((study) => study.id === currentStudyId) ?? null,
    [studies, currentStudyId],
  )

  const value = useMemo<CurrentStudyContextValue>(
    () => ({
      studies,
      currentStudy,
      currentStudyId,
      setCurrentStudyId,
      isLoading,
      isError,
    }),
    [studies, currentStudy, currentStudyId, setCurrentStudyId, isLoading, isError],
  )

  return (
    <CurrentStudyContext.Provider value={value}>
      {children}
    </CurrentStudyContext.Provider>
  )
}

// eslint-disable-next-line react-refresh/only-export-components
export function useCurrentStudy() {
  const context = useContext(CurrentStudyContext)
  if (context === undefined) {
    throw new Error('useCurrentStudy must be used within a StudyProvider')
  }
  return context
}
