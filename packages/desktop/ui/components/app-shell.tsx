"use client"

import { useEffect, useState, useCallback } from "react"
import { usePathname, useRouter } from "next/navigation"
import { Loader2 } from "lucide-react"
import { Sidebar } from "./sidebar"
import { SessionDropdown } from "./session-dropdown"
import {
  getWorkerStatus,
  getPTYSessions,
  createNewPTYSession,
  deletePTYSession,
  getSetupStatus,
  type PTYSessionRecord,
} from "@/lib/api"

export function AppShell({ children }: { children: React.ReactNode }) {
  const [workerRunning, setWorkerRunning] = useState(false)
  const [sessions, setSessions] = useState<PTYSessionRecord[]>([])
  const [activeSessionId, setActiveSessionId] = useState<string | null>(null)
  const [setupState, setSetupState] = useState<"checking" | "needed" | "ok">("checking")
  const pathname = usePathname()
  const router = useRouter()
  const isSetupRoute = pathname?.startsWith("/setup") ?? false

  // First-run setup check: block the main UI and route to /setup if the
  // desktop isn't provisioned with a valid worker token.
  useEffect(() => {
    let cancelled = false
    getSetupStatus()
      .then((res) => {
        if (cancelled) return
        if (res.setup_complete) {
          setSetupState("ok")
        } else {
          setSetupState("needed")
          if (!isSetupRoute) router.replace("/setup")
        }
      })
      .catch(() => {
        // On error (rare), assume ok so we don't trap the user.
        if (!cancelled) setSetupState("ok")
      })
    return () => {
      cancelled = true
    }
  }, [isSetupRoute, router])

  const refreshSessions = useCallback(async () => {
    try {
      const data = await getPTYSessions()
      setSessions(data.history)
      setActiveSessionId(data.active_session_id)
    } catch { /* ignore */ }
  }, [])

  useEffect(() => {
    if (setupState !== "ok") return
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
  }, [refreshSessions, setupState])

  const handleNewSession = async () => {
    await createNewPTYSession()
    refreshSessions()
  }

  const handleDeleteSession = async (id: string) => {
    await deletePTYSession(id)
    refreshSessions()
  }

  // While we're still checking, show a spinner so the main UI doesn't flash.
  if (setupState === "checking") {
    return (
      <div className="flex min-h-screen items-center justify-center bg-background">
        <Loader2 className="h-6 w-6 animate-spin text-muted-foreground" />
      </div>
    )
  }

  // On the /setup route (or if setup is needed), render the page without the
  // sidebar / top bar so the wizard is the only focus.
  if (isSetupRoute || setupState === "needed") {
    return <div className="min-h-screen bg-background">{children}</div>
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
