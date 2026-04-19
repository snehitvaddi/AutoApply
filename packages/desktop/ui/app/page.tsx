"use client"

import { useState, useEffect, useCallback } from "react"
import Link from "next/link"
import { AppShell } from "@/components/app-shell"
import { StatCard } from "@/components/dashboard/stat-card"
import { ApplicationsChart } from "@/components/dashboard/applications-chart"
import { PlatformChart } from "@/components/dashboard/platform-chart"
import { RecentApplications } from "@/components/dashboard/recent-applications"
import { useStats } from "@/hooks/use-stats"
import {
  getAuthState,
  getCurrentlyApplying,
  focusBrowser,
  getHeartbeat,
  type CurrentlyApplyingJob,
} from "@/lib/api"
import { Key, AlertTriangle, ArrowRight, Loader2, ExternalLink, Settings } from "lucide-react"

// Banner state reflects /api/auth/state, which is the desktop server's
// real view of whether the saved worker token still authenticates against
// the remote ApplyLoop API. `/api/auth/status` is unreliable for this —
// it returns authenticated:true whenever the token file exists on disk,
// swallowing 401s from the upstream proxy.
type AuthBanner = null | "no_token" | "revoked"

// Worker heartbeat banner — reflects the worker's self-reported state.
// "awaiting_setup" means the worker refused to boot because the user
// hasn't finished Settings (target_titles missing, no resume, etc.).
// Without this the dashboard shows a sea of zeros and the user has no
// idea why nothing is happening — audit-flagged #1 abandonment risk.
type HeartbeatBanner = null | { action: string; details: string }

function elapsedTime(dateStr?: string): string {
  if (!dateStr) return ""
  const mins = Math.floor((Date.now() - new Date(dateStr).getTime()) / 60000)
  if (mins < 1) return "just started"
  if (mins < 60) return `${mins}m elapsed`
  return `${Math.floor(mins / 60)}h ${mins % 60}m elapsed`
}

export default function DashboardPage() {
  const { stats, daily, platforms, recent, loading, error } = useStats()
  const [authBanner, setAuthBanner] = useState<AuthBanner>(null)
  const [heartbeatBanner, setHeartbeatBanner] = useState<HeartbeatBanner>(null)
  // Until the first heartbeat fetch returns, we don't know whether to show
  // a setup banner or not. If the user is brand-new and the worker is
  // silent, the dashboard would look deceptively empty for up to 15s.
  // Render a neutral "checking worker state" placeholder instead.
  const [heartbeatChecked, setHeartbeatChecked] = useState(false)
  // First-application celebration. Tracks the applied_today value at
  // mount so we can fire a toast the first time it increments during
  // this session. Prevents the user from missing their first successful
  // application — previously the only signal was a stats counter ticking.
  const [firstMountAppliedToday, setFirstMountAppliedToday] = useState<number | null>(null)
  const [celebrated, setCelebrated] = useState(false)
  const [showCelebration, setShowCelebration] = useState(false)
  const [current, setCurrent] = useState<CurrentlyApplyingJob | null>(null)

  useEffect(() => {
    // Poll /auth/state rather than /auth/status — the status endpoint
    // returns authenticated:true whenever a token file exists on disk,
    // even if every upstream call is 401'ing. /auth/state is flipped to
    // "revoked" the first time the desktop proxy actually sees a 401/403.
    const check = () => {
      getAuthState()
        .then((res) => {
          if (res.status === "no_token") setAuthBanner("no_token")
          else if (res.status === "revoked") setAuthBanner("revoked")
          else setAuthBanner(null)
        })
        .catch(() => {
          // Transient fetch error — don't flip the banner state so we
          // don't flash a misleading warning on every network blip.
        })
    }
    check()
    const interval = setInterval(check, 15000)
    return () => clearInterval(interval)
  }, [])

  // Poll worker heartbeat every 15s to catch "awaiting_setup" (worker
  // refused to boot due to missing target_titles / resume / etc.) and
  // surface it as a Finish-Setup banner. The dashboard's stat cards are
  // all zero in this state; without a banner the user has no idea why.
  useEffect(() => {
    const check = () => {
      getHeartbeat()
        .then((res) => {
          const act = res?.data?.last_action || ""
          const setupStates = ["awaiting_setup", "awaiting_preferences", "awaiting_resume"]
          if (setupStates.includes(act)) {
            setHeartbeatBanner({ action: act, details: res?.data?.details || "" })
          } else {
            setHeartbeatBanner(null)
          }
          setHeartbeatChecked(true)
        })
        .catch(() => {
          // Transient — leave banner as-is but flip checked so we don't
          // show the "checking" skeleton forever if the endpoint is down.
          setHeartbeatChecked(true)
        })
    }
    check()
    const interval = setInterval(check, 15000)
    return () => clearInterval(interval)
  }, [])

  const refreshCurrent = useCallback(async () => {
    try {
      const res = await getCurrentlyApplying()
      if (res.ok) setCurrent(res.data)
    } catch { /* ignore */ }
  }, [])

  useEffect(() => {
    refreshCurrent()
    const interval = setInterval(refreshCurrent, 5000)
    return () => clearInterval(interval)
  }, [refreshCurrent])

  // Capture the baseline applied_today count on first stats load, then
  // fire a celebration toast the first time that number increments.
  useEffect(() => {
    if (loading || stats?.applied_today == null) return
    if (firstMountAppliedToday === null) {
      setFirstMountAppliedToday(stats.applied_today)
      return
    }
    if (!celebrated && stats.applied_today > firstMountAppliedToday) {
      setCelebrated(true)
      setShowCelebration(true)
      window.setTimeout(() => setShowCelebration(false), 6000)
    }
  }, [loading, stats?.applied_today, firstMountAppliedToday, celebrated])

  const handleFocusBrowser = async () => {
    try {
      const res = await focusBrowser()
      if (!res.ok && current?.url) {
        window.open(current.url, "_blank")
      }
    } catch {
      if (current?.url) window.open(current.url, "_blank")
    }
  }

  return (
    <AppShell>
      <div className="space-y-6">
        {/* Auth banner — revoked token takes priority so the user never
            sees an innocuous "token required" message while stats silently
            zero out. app-shell also bounces to /setup on revoked state;
            this banner is the fallback for the brief interval before the
            redirect fires (and for users who race the check). */}
        {authBanner === "revoked" && (
          <Link
            href="/setup/"
            className="flex items-center gap-3 rounded-xl border border-destructive/30 bg-destructive/5 p-4 transition-colors hover:bg-destructive/10"
          >
            <AlertTriangle className="h-5 w-5 text-destructive" />
            <div className="flex-1">
              <p className="text-sm font-medium text-foreground">API Token Revoked</p>
              <p className="text-xs text-muted-foreground">
                Your worker token is no longer valid. Re-activate with a fresh code.
              </p>
            </div>
            <ArrowRight className="h-4 w-4 text-muted-foreground" />
          </Link>
        )}
        {authBanner === "no_token" && (
          <Link
            href="/setup/"
            className="flex items-center gap-3 rounded-xl border border-warning/30 bg-warning/5 p-4 transition-colors hover:bg-warning/10"
          >
            <Key className="h-5 w-5 text-warning" />
            <div className="flex-1">
              <p className="text-sm font-medium text-foreground">API Token Required</p>
              <p className="text-xs text-muted-foreground">
                Redeem an activation code to connect this desktop to your ApplyLoop account.
              </p>
            </div>
            <ArrowRight className="h-4 w-4 text-muted-foreground" />
          </Link>
        )}

        {/* Empty-state welcome card — brand-new user with no heartbeat
            banner, no applications yet, no currently-applying job. Shows
            a 3-step checklist so they're not staring at an empty
            dashboard wondering what to do. Hidden as soon as they have
            any apps or the worker starts running. */}
        {!authBanner && heartbeatChecked && !heartbeatBanner && !current &&
         !loading && (stats?.total_applied ?? 0) === 0 && (
          <div className="rounded-xl border border-primary/30 bg-primary/5 p-5">
            <h3 className="text-sm font-semibold text-foreground mb-2">
              Welcome to ApplyLoop 👋
            </h3>
            <p className="text-xs text-muted-foreground mb-3">
              You&apos;re all set up. Finish these three steps and the worker
              will start applying on your behalf — usually within a few minutes.
            </p>
            <ol className="space-y-2 text-sm">
              <li className="flex items-start gap-2">
                <span className="flex h-5 w-5 flex-shrink-0 items-center justify-center rounded-full bg-primary/20 text-xs font-medium text-primary">1</span>
                <Link href="/settings/" className="flex-1 text-foreground hover:underline">
                  Open Settings → Profiles → add at least one target title
                </Link>
              </li>
              <li className="flex items-start gap-2">
                <span className="flex h-5 w-5 flex-shrink-0 items-center justify-center rounded-full bg-primary/20 text-xs font-medium text-primary">2</span>
                <Link href="/settings/" className="flex-1 text-foreground hover:underline">
                  Settings → Resumes → upload your PDF
                </Link>
              </li>
              <li className="flex items-start gap-2">
                <span className="flex h-5 w-5 flex-shrink-0 items-center justify-center rounded-full bg-primary/20 text-xs font-medium text-primary">3</span>
                <Link href="/settings/" className="flex-1 text-foreground hover:underline">
                  Settings → API Keys → add Gmail app password + Telegram bot
                </Link>
              </li>
            </ol>
          </div>
        )}

        {/* Celebration toast — fires once per session when applied_today
            first increments past the value observed at mount. Auto-
            dismisses after 6 seconds. */}
        {showCelebration && (
          <div className="flex items-center gap-3 rounded-xl border border-success/30 bg-success/5 p-4">
            <div className="text-2xl">🎉</div>
            <div className="flex-1">
              <p className="text-sm font-medium text-foreground">Application submitted</p>
              <p className="text-xs text-muted-foreground">
                The worker just submitted a new application. Details in Recent Applications below.
              </p>
            </div>
            <button
              onClick={() => setShowCelebration(false)}
              className="text-xs text-muted-foreground hover:text-foreground"
            >
              Dismiss
            </button>
          </div>
        )}

        {/* Neutral placeholder shown before the first heartbeat fetch
            resolves. Prevents a new user from staring at zero stats with
            no explanation for up to 15s on slow networks. */}
        {!authBanner && !heartbeatChecked && (
          <div className="flex items-center gap-3 rounded-xl border border-border bg-muted/30 p-4">
            <Loader2 className="h-5 w-5 animate-spin text-muted-foreground" />
            <p className="text-sm text-muted-foreground">Checking worker state…</p>
          </div>
        )}

        {/* Setup-incomplete banner — worker is alive but refusing to apply
            because required data is missing. Replaces the blank-dashboard
            abandonment risk: instead of zero stats with no explanation,
            the user sees exactly which step to finish + a direct link. */}
        {!authBanner && heartbeatChecked && heartbeatBanner && (
          <Link
            href="/settings/"
            className="flex items-center gap-3 rounded-xl border border-warning/30 bg-warning/5 p-4 transition-colors hover:bg-warning/10"
          >
            <Settings className="h-5 w-5 text-warning" />
            <div className="flex-1">
              <p className="text-sm font-medium text-foreground">
                {heartbeatBanner.action === "awaiting_resume"
                  ? "Upload a resume to start applying"
                  : heartbeatBanner.action === "awaiting_preferences"
                  ? "Set your target roles to start scouting"
                  : "Finish setup to start the worker"}
              </p>
              <p className="text-xs text-muted-foreground">
                {heartbeatBanner.details || "The worker is waiting for setup to be completed."}
              </p>
            </div>
            <ArrowRight className="h-4 w-4 text-muted-foreground" />
          </Link>
        )}

        {/* Stats Row */}
        <div className="grid gap-4 sm:grid-cols-2 lg:grid-cols-4">
          <StatCard
            title="Applied Today"
            value={loading ? "—" : String(stats?.applied_today ?? 0)}
            subtitle={
              (stats?.applying_now ?? 0) > 0
                ? `${stats?.applying_now} applying now`
                : undefined
            }
          />
          <StatCard
            title="Total Applied"
            value={loading ? "—" : String(stats?.total_applied ?? 0)}
          />
          <StatCard
            title="In Queue"
            value={loading ? "—" : String(stats?.in_queue ?? 0)}
            pulseDot={(stats?.in_queue ?? 0) > 0}
            subtitle={
              stats?.last_scout_min_ago != null
                ? `Last scout: ${
                    stats.last_scout_min_ago < 1
                      ? "just now"
                      : `${Math.round(stats.last_scout_min_ago)}m ago`
                  }`
                : undefined
            }
          />
          <StatCard
            title="Success Rate"
            value={loading ? "—" : `${stats?.success_rate ?? 0}%`}
            trend={(stats?.success_rate ?? 0) > 50 ? "up" : undefined}
          />
        </div>

        {/* Charts Row */}
        <div className="grid gap-4 lg:grid-cols-[1.5fr_1fr]">
          <ApplicationsChart data={daily} />
          <PlatformChart data={platforms} />
        </div>

        {/* Currently Applying banner (click to focus live browser) */}
        {current && (
          <button
            onClick={handleFocusBrowser}
            className="flex w-full items-center gap-3 rounded-xl border border-warning/30 bg-warning/5 p-4 text-left transition-colors hover:bg-warning/10"
          >
            <Loader2 className="h-5 w-5 flex-shrink-0 animate-spin text-warning" />
            <div className="flex-1 min-w-0">
              <p className="truncate text-sm font-semibold text-foreground">
                Currently Applying: {current.company} — {current.title}
              </p>
              <p className="mt-0.5 truncate text-xs text-muted-foreground">
                {current.ats}
                {current.location ? ` · ${current.location}` : ""}
                {" · "}
                {elapsedTime(current.updated_at)}
              </p>
            </div>
            <div className="flex items-center gap-1 text-xs text-primary">
              Open browser <ExternalLink className="h-3 w-3" />
            </div>
          </button>
        )}

        {/* Recent Applications */}
        <RecentApplications applications={recent} />
      </div>
    </AppShell>
  )
}
