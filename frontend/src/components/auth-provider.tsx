import {
  createContext,
  useCallback,
  useContext,
  useEffect,
  useMemo,
  useState,
} from 'react'
import {
  type AuthUser,
  restoreSession,
  signIn as cognitoSignIn,
  signOut as cognitoSignOut,
} from '@/lib/cognito'
import { onAuthChange } from '@/lib/auth'

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

  // Restore any existing Cognito session on first load.
  useEffect(() => {
    let active = true
    restoreSession()
      .then((restored) => {
        if (active) setUser(restored)
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
      if (!token) setUser(null)
    })
  }, [])

  const signIn = useCallback(async (username: string, password: string) => {
    const signedIn = await cognitoSignIn(username, password)
    setUser(signedIn)
  }, [])

  const signOut = useCallback(() => {
    cognitoSignOut()
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
