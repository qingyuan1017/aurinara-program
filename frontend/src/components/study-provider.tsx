import {
  useCallback,
  useEffect,
  useMemo,
  useState,
} from 'react'
import { useListStudies } from '@/api/generated/studies/studies'
import { useAuth } from '@/components/auth-provider'
import {
  CurrentStudyContext,
  type CurrentStudyContextValue,
} from '@/components/study-context'

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

export function StudyProvider({ children }: { children: React.ReactNode }) {
  // Gate the query on the REACTIVE auth state (not a one-shot localStorage
  // read) so it re-fires automatically the moment the user signs in, without
  // needing a page refresh.
  const { isAuthenticated } = useAuth()
  const { data, isLoading, isError } = useListStudies(undefined, {
    query: {
      enabled: isAuthenticated,
      refetchInterval: isAuthenticated ? 30_000 : false,
      refetchIntervalInBackground: false,
    },
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
