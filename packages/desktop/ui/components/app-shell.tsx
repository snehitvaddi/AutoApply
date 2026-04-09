"use client"

import { useEffect, useState } from "react"
import { Sidebar } from "./sidebar"
import { getWorkerStatus } from "@/lib/api"

export function AppShell({ children }: { children: React.ReactNode }) {
  const [workerRunning, setWorkerRunning] = useState(false)

  useEffect(() => {
    const check = async () => {
      try {
        const status = await getWorkerStatus()
        setWorkerRunning(status.running)
      } catch {
        setWorkerRunning(false)
      }
    }
    check()
    const interval = setInterval(check, 10000)
    return () => clearInterval(interval)
  }, [])

  return (
    <div className="min-h-screen bg-background">
      <Sidebar workerRunning={workerRunning} />
      <main className="ml-16 min-h-screen p-6">{children}</main>
    </div>
  )
}
