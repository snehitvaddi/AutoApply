"use client"

import { useEffect, useState, useCallback, useRef } from "react"
import { usePathname, useRouter } from "next/navigation"
import { Loader2, Key, AlertTriangle } from "lucide-react"
import { Sidebar } from "./sidebar"
import { SessionDropdown } from "./session-dropdown"
import {
  getWorkerStatus,
  getPTYSessions,
  createNewPTYSession,
  deletePTYSession,
  getSetupStatus,
  getAuthState,
  type PTYSessionRecord,
} from "@/lib/api"

export function AppShell({ children }: { children: React.ReactNode }) {
  const [workerRunning, setWorkerRunning] = useState(false)
  const [sessions, setSessions] = useState<PTYSessionRecord[]>([])
  const [activeSessionId, setActiveSessionId] = useState<string | null>(null)
  const [setupState, setSetupState] = useState<"checking" | "needed" | "ok">("checking")
  // Global auth-revoked banner. Polled every 15s from /api/auth/state.
  // Flips to "revoked" the moment the desktop proxy gets its first 401/403
  // from the cloud — which happens when admin reissues an activation code
  // (revoking the old worker token) or hits the Deactivate button. Before
  // this lived in app-shell, the banner only appeared on the dashboard /
  // home page; a user editing /settings or /jobs at that moment had no
  // indication their token was dead and no clear path to re-activate.
  const [authState, setAuthState] = useState<"ok" | "revoked" | "no_token" | null>(null)
  // Parallel signal piggybacked on the same /api/auth/state poll. When
  // profile_status === "missing", the cloud is reachable + the token is
  // valid, but no user_profiles row exists for the activated user_id.
  // Show an amber banner globally (every page) with the synced-as email
  // so the user can spot wrong-account activation from /jobs or /dashboard
  // without having to tab into /settings first.
  const [profileMissing, setProfileMissing] = useState<{ email?: string | null } | null>(null)
  const pathname = usePathname()
  const router = useRouter()
  const isSetupRoute = pathname?.startsWith("/setup") ?? false
  // /settings is also allowed during incomplete-setup mode so the wizard's
  // "Fill in profile" / "Upload resume" / "Set preferences" deep-links don't
  // trigger an instant bounce back to /setup. The settings page itself shows
  // a "return to wizard" banner when setup is not yet complete.
  const isAllowedDuringSetup =
    isSetupRoute || (pathname?.startsWith("/settings") ?? false)

  // First-run setup check: block the main UI and route to /setup if the
  // desktop isn't provisioned yet. Only redirects on FIRST check — once
  // setup passes, we NEVER redirect back to /setup even if a transient
  // failure occurs (gateway timeout, network blip, etc.). This prevents
  // yanking the user away from the terminal mid-session when they're
  // actively applying to jobs.
  //
  // The 15s poll still runs to update the sidebar status indicator, but
  // it only redirects if the user has NEVER had a successful setup in
  // this browser session.
  // Persist across app restarts via localStorage. If setup ever passed,
  // we NEVER redirect to /setup again — even after a reboot, gateway
  // crash, or browser refresh. The activation code is a ONE-TIME gate.
  const [everSetupOk, setEverSetupOk] = useState(() => {
    if (typeof window !== "undefined") {
      return localStorage.getItem("applyloop_setup_ok") === "true"
    }
    return false
  })
  // Track consecutive fetch failures so we don't spin forever when the
  // server is slow to start (pywebview opens before FastAPI is ready).
  const failCountRef = useRef(0)

  useEffect(() => {
    let cancelled = false
    const check = () => {
      getSetupStatus()
        .then((res) => {
          if (cancelled) return
          failCountRef.current = 0
          if (res.setup_complete) {
            setSetupState("ok")
            if (!everSetupOk) {
              setEverSetupOk(true)
              localStorage.setItem("applyloop_setup_ok", "true")
            }
          } else {
            // Only redirect to /setup if setup has NEVER passed —
            // not in this session, not in any previous session.
            // Once the activation code is entered and setup passes
            // once, the user should never see the activation screen
            // again, even if the gateway crashes or the server restarts.
            if (!everSetupOk) {
              setSetupState("needed")
              if (!isAllowedDuringSetup) router.replace("/setup")
            } else {
              // Previously activated → transient failure (e.g. token
              // briefly revoked, gateway hiccup). Keep the main UI
              // visible. Without this, setupState stayed at "checking"
              // forever and the user saw an eternal spinner.
              setSetupState("ok")
            }
          }
        })
        .catch(() => {
          if (cancelled) return
          failCountRef.current += 1
          // After 2 consecutive failures (server not ready / timeout):
          // - Previously activated → trust localStorage, show UI; server will catch up
          // - Never activated → route to /setup so user can activate
          // This prevents the spinner hanging forever when pywebview opens
          // before the FastAPI server has finished starting (~6s).
          if (failCountRef.current >= 2) {
            if (everSetupOk) {
              setSetupState("ok")
            } else {
              setSetupState("needed")
              if (!isAllowedDuringSetup) router.replace("/setup")
            }
          }
        })
    }
    check()
    const interval = setInterval(check, 15000)
    return () => {
      cancelled = true
      clearInterval(interval)
    }
  }, [isAllowedDuringSetup, router, everSetupOk])

  // Global auth-state poll. 15s cadence — fast enough to catch admin-driven
  // code reissues / deactivations within a normal user's attention window.
  useEffect(() => {
    let cancelled = false
    const check = () => {
      getAuthState()
        .then((res) => {
          if (cancelled) return
          if (res.status === "revoked") setAuthState("revoked")
          else if (res.status === "no_token") setAuthState("no_token")
          else setAuthState("ok")
          // Only flag profile-missing when auth itself is fine — otherwise
          // the auth banner takes precedence and the user shouldn't see
          // two warnings stacked.
          if (res.status === "ok" && res.profile_status === "missing") {
            setProfileMissing({ email: res.synced_as_email ?? null })
          } else {
            setProfileMissing(null)
          }
        })
        .catch(() => { /* transient — leave state */ })
    }
    check()
    const interval = setInterval(check, 15000)
    return () => { cancelled = true; clearInterval(interval) }
  }, [])

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
        {/* Global revoked-token banner. Visible on every page so a user
            editing /settings or /jobs when the admin reissues their
            activation code immediately sees the path back to working
            state. The button takes them to /setup which already has
            the activation form wired. */}
        {(authState === "revoked" || authState === "no_token") && (
          <div className="flex items-center justify-between gap-3 border-b border-red-300 bg-red-50 px-6 py-2.5 text-sm text-red-900 dark:border-red-700/50 dark:bg-red-950/30 dark:text-red-100">
            <div className="flex items-center gap-2">
              <Key className="h-4 w-4 flex-shrink-0" />
              <span>
                {authState === "revoked"
                  ? "Your access token was revoked or rotated by an admin. Re-activate with the new code to resume syncing."
                  : "No activation code on file. Activate now to start syncing with the cloud."}
              </span>
            </div>
            <button
              onClick={() => router.push("/setup")}
              className="rounded-md bg-red-200 px-3 py-1 text-xs font-medium text-red-900 hover:bg-red-300 dark:bg-red-800 dark:text-red-100 dark:hover:bg-red-700"
            >
              Re-activate
            </button>
          </div>
        )}
        {!authState ? null : authState === "ok" && profileMissing && (
          <div className="flex items-center justify-between gap-3 border-b border-amber-300 bg-amber-50 px-6 py-2.5 text-sm text-amber-900 dark:border-amber-700/50 dark:bg-amber-950/30 dark:text-amber-100">
            <div className="flex items-center gap-2">
              <AlertTriangle className="h-4 w-4 flex-shrink-0" />
              <span>
                Cloud reachable, but no profile data exists for this account
                {profileMissing.email ? <> (synced as <span className="font-mono">{profileMissing.email}</span>)</> : null}.
                If you filled your profile under a different account, ask the admin to reissue the activation code.
              </span>
            </div>
            <button
              onClick={() => router.push("/settings")}
              className="rounded-md bg-amber-200 px-3 py-1 text-xs font-medium text-amber-900 hover:bg-amber-300 dark:bg-amber-800 dark:text-amber-100 dark:hover:bg-amber-700"
            >
              Open Settings
            </button>
          </div>
        )}
        <div className="p-6">{children}</div>
      </main>
    </div>
  )
}
