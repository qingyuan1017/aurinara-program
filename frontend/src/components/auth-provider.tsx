import {
  createContext,
  useCallback,
  useContext,
  useEffect,
  useMemo,
  useRef,
  useState,
} from 'react'
import {
  type AuthUser,
  restoreSession,
  signIn as cognitoSignIn,
  signOut as cognitoSignOut,
} from '@/lib/cognito'
import { onAuthChange } from '@/lib/auth'
import { clearOidcSession, restoreOidcSession } from '@/lib/oidc'

interface AuthContextValue {
  user: AuthUser | null
  isAuthenticated: boolean
  isLoading: boolean
  signIn: (username: string, password: string) => Promise<void>
  signOut: () => void
}

const AuthContext = createContext<AuthContextValue | undefined>(undefined)

export function AuthProvider({ children }: { children: React.ReactNode }) {
  const [user, setUser] = useState<AuthUser | null>(null)
  const [isLoading, setIsLoading] = useState(true)
  const authOperation = useRef(0)

  // Restore any existing Cognito session on first load.
  useEffect(() => {
    let active = true
    const operation = ++authOperation.current
    const oidcUser = restoreOidcSession()
    if (oidcUser) {
      setUser(oidcUser)
      setIsLoading(false)
      return
    }
    restoreSession()
      .then((restored) => {
        if (active && authOperation.current === operation) setUser(restored)
      })
      .finally(() => {
        if (active) setIsLoading(false)
      })
    return () => {
      active = false
    }
  }, [])

  // Keep context in sync if the token is cleared elsewhere (e.g. a 401).
  useEffect(() => {
    return onAuthChange((token) => {
      if (!token) {
        authOperation.current += 1
        setUser(null)
        setIsLoading(false)
      }
    })
  }, [])

  const signIn = useCallback(async (username: string, password: string) => {
    const operation = ++authOperation.current
    const signedIn = await cognitoSignIn(username, password)
    if (authOperation.current === operation) {
      setUser(signedIn)
      setIsLoading(false)
    }
  }, [])

  const signOut = useCallback(() => {
    authOperation.current += 1
    if (restoreOidcSession()) clearOidcSession()
    else cognitoSignOut()
    setUser(null)
  }, [])

  const value = useMemo<AuthContextValue>(
    () => ({
      user,
      isAuthenticated: user !== null,
      isLoading,
      signIn,
      signOut,
    }),
    [user, isLoading, signIn, signOut],
  )

  return <AuthContext.Provider value={value}>{children}</AuthContext.Provider>
}

// eslint-disable-next-line react-refresh/only-export-components
export function useAuth() {
  const context = useContext(AuthContext)
  if (context === undefined) {
    throw new Error('useAuth must be used within an AuthProvider')
  }
  return context
}
