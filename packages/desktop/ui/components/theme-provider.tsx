'use client'

import * as React from 'react'

type Theme = 'light' | 'dark'

interface ThemeContextValue {
  theme: Theme
  toggle: () => void
  setTheme: (t: Theme) => void
}

const ThemeContext = React.createContext<ThemeContextValue | undefined>(undefined)

const STORAGE_KEY = 'applyloop-theme'

function getInitialTheme(): Theme {
  if (typeof window === 'undefined') return 'dark'
  const stored = localStorage.getItem(STORAGE_KEY)
  if (stored === 'light' || stored === 'dark') return stored
  return 'dark' // default matches previous behavior
}

export function ThemeProvider({ children }: { children: React.ReactNode }) {
  const [theme, setThemeState] = React.useState<Theme>('dark')

  // Read saved theme on mount
  React.useEffect(() => {
    setThemeState(getInitialTheme())
  }, [])

  // Apply theme class to <html>
  React.useEffect(() => {
    const root = document.documentElement
    if (theme === 'dark') {
      root.classList.add('dark')
    } else {
      root.classList.remove('dark')
    }
    try {
      localStorage.setItem(STORAGE_KEY, theme)
    } catch {
      /* ignore */
    }
  }, [theme])

  const setTheme = React.useCallback((t: Theme) => setThemeState(t), [])
  const toggle = React.useCallback(
    () => setThemeState((t) => (t === 'dark' ? 'light' : 'dark')),
    []
  )

  return (
    <ThemeContext.Provider value={{ theme, toggle, setTheme }}>
      {children}
    </ThemeContext.Provider>
  )
}

export function useTheme(): ThemeContextValue {
  const ctx = React.useContext(ThemeContext)
  if (!ctx) {
    // Fallback for SSR / pre-mount — return a no-op so components don't crash
    return { theme: 'dark', toggle: () => {}, setTheme: () => {} }
  }
  return ctx
}
