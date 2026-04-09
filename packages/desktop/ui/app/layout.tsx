import type { Metadata } from 'next'
import './globals.css'

export const metadata: Metadata = {
  title: 'ApplyLoop - Automated Job Application Tracker',
  description: 'Track and automate your job applications with AI-powered insights',
}

export default function RootLayout({
  children,
}: Readonly<{
  children: React.ReactNode
}>) {
  return (
    <html lang="en">
      <body className="font-sans antialiased">
        {children}
      </body>
    </html>
  )
}
