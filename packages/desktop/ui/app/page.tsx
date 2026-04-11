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
  type CurrentlyApplyingJob,
} from "@/lib/api"
import { Key, AlertTriangle, ArrowRight, Loader2, ExternalLink } from "lucide-react"

// Banner state reflects /api/auth/state, which is the desktop server's
// real view of whether the saved worker token still authenticates against
// the remote ApplyLoop API. `/api/auth/status` is unreliable for this —
// it returns authenticated:true whenever the token file exists on disk,
// swallowing 401s from the upstream proxy.
type AuthBanner = null | "no_token" | "revoked"

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

        {/* Stats Row */}
        <div className="grid gap-4 sm:grid-cols-2 lg:grid-cols-4">
          <StatCard
            title="Applied Today"
            value={loading ? "—" : String(stats?.applied_today ?? 0)}
            badge={
              stats?.applied_today
                ? { text: `+${stats.applied_today}`, variant: "success" as const }
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
