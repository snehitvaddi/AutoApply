"use client"

import { useEffect, useState, useCallback } from "react"
import { Sidebar } from "./sidebar"
import { SessionDropdown } from "./session-dropdown"
import {
  getWorkerStatus,
  getPTYSessions,
  createNewPTYSession,
  deletePTYSession,
  type PTYSessionRecord,
} from "@/lib/api"

export function AppShell({ children }: { children: React.ReactNode }) {
  const [workerRunning, setWorkerRunning] = useState(false)
  const [sessions, setSessions] = useState<PTYSessionRecord[]>([])
  const [activeSessionId, setActiveSessionId] = useState<string | null>(null)

  const refreshSessions = useCallback(async () => {
    try {
      const data = await getPTYSessions()
      setSessions(data.history)
      setActiveSessionId(data.active_session_id)
    } catch { /* ignore */ }
  }, [])

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
    refreshSessions()
    const interval = setInterval(() => { check(); refreshSessions() }, 10000)
    return () => clearInterval(interval)
  }, [refreshSessions])

  const handleNewSession = async () => {
    await createNewPTYSession()
    refreshSessions()
  }

  const handleDeleteSession = async (id: string) => {
    await deletePTYSession(id)
    refreshSessions()
  }

  return (
    <div className="min-h-screen bg-background">
      <Sidebar workerRunning={workerRunning} />
      <main className="ml-16 min-h-screen">
        {/* Global top bar with session dropdown */}
        <div className="flex items-center justify-end border-b border-border px-6 py-2">
          <SessionDropdown
            sessions={sessions}
            activeSessionId={activeSessionId}
            onNewSession={handleNewSession}
            onDeleteSession={handleDeleteSession}
          />
        </div>
        <div className="p-6">{children}</div>
      </main>
    </div>
  )
}
