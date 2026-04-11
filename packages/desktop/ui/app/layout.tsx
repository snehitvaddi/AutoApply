import type { Metadata } from 'next'
import './globals.css'
import { ThemeProvider } from '@/components/theme-provider'

export const metadata: Metadata = {
  title: 'ApplyLoop - Automated Job Application Tracker',
  description: 'Track and automate your job applications with AI-powered insights',
}

// Inline script that runs BEFORE React hydrates — reads the saved theme from
// localStorage and sets the .dark class on <html> so there's no light-mode flash.
const themeInitScript = `
(function(){
  try {
    var stored = localStorage.getItem('applyloop-theme');
    var theme = (stored === 'light' || stored === 'dark') ? stored : 'dark';
    if (theme === 'dark') document.documentElement.classList.add('dark');
  } catch (e) {
    document.documentElement.classList.add('dark');
  }
})();
`

export default function RootLayout({
  children,
}: Readonly<{
  children: React.ReactNode
}>) {
  return (
    <html lang="en">
      <head>
        <script dangerouslySetInnerHTML={{ __html: themeInitScript }} />
      </head>
      <body className="font-sans antialiased">
        <ThemeProvider>{children}</ThemeProvider>
      </body>
    </html>
  )
}
