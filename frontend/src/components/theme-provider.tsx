import { createContext, useContext, useEffect, useMemo, useState } from 'react'

type Theme = 'dark' | 'light' | 'system'

type ThemeProviderProps = {
  children: React.ReactNode
  defaultTheme?: Theme
  storageKey?: string
}

type ThemeProviderState = {
  theme: Theme
  resolvedTheme: Exclude<Theme, 'system'>
  setTheme: (theme: Theme) => void
}

const initialState: ThemeProviderState = {
  theme: 'system',
  resolvedTheme: 'light',
  setTheme: () => null,
}

const ThemeProviderContext = createContext<ThemeProviderState>(initialState)

export function ThemeProvider({
  children,
  defaultTheme = 'system',
  storageKey = 'aurinara.ui.theme',
  ...props
}: ThemeProviderProps) {
  const [theme, setTheme] = useState<Theme>(() => {
    try {
      const stored = localStorage.getItem(storageKey)
      return stored === 'light' || stored === 'dark' || stored === 'system' ? stored : defaultTheme
    } catch {
      return defaultTheme
    }
  })
  const [systemDark, setSystemDark] = useState(() => window.matchMedia?.('(prefers-color-scheme: dark)').matches ?? false)
  const resolvedTheme = theme === 'system' ? (systemDark ? 'dark' : 'light') : theme

  useEffect(() => {
    const query = window.matchMedia?.('(prefers-color-scheme: dark)')
    const update = () => setSystemDark(query?.matches ?? false)
    query?.addEventListener?.('change', update)
    return () => query?.removeEventListener?.('change', update)
  }, [])

  useEffect(() => {
    const root = window.document.documentElement
    root.classList.toggle('light', resolvedTheme === 'light')
    root.classList.toggle('dark', resolvedTheme === 'dark')
    root.dataset.theme = resolvedTheme
    root.dataset.themeMode = theme
  }, [resolvedTheme, theme])

  const value = useMemo(() => ({
    theme,
    resolvedTheme,
    setTheme: (next: Theme) => {
      try { localStorage.setItem(storageKey, next) } catch { /* storage is optional */ }
      setTheme(next)
    },
  }), [resolvedTheme, storageKey, theme])

  return (
    <ThemeProviderContext.Provider {...props} value={value}>
      {children}
    </ThemeProviderContext.Provider>
  )
}

// eslint-disable-next-line react-refresh/only-export-components
export function useTheme() {
  const context = useContext(ThemeProviderContext)
  if (context === undefined) {
    throw new Error('useTheme must be used within a ThemeProvider')
  }
  return context
}
