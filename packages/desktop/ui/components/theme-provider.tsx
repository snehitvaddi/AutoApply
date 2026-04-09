'use client'

import * as React from 'react'

// Dark theme is set via CSS variables in globals.css — no runtime provider needed
export function ThemeProvider({ children }: { children: React.ReactNode }) {
  return <>{children}</>
}
