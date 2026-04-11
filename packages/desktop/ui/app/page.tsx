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
  checkAuth,
  getCurrentlyApplying,
  focusBrowser,
  type CurrentlyApplyingJob,
} from "@/lib/api"
import { Key, ArrowRight, Loader2, ExternalLink } from "lucide-react"

function elapsedTime(dateStr?: string): string {
  if (!dateStr) return ""
  const mins = Math.floor((Date.now() - new Date(dateStr).getTime()) / 60000)
  if (mins < 1) return "just started"
  if (mins < 60) return `${mins}m elapsed`
  return `${Math.floor(mins / 60)}h ${mins % 60}m elapsed`
}

export default function DashboardPage() {
  const { stats, daily, platforms, recent, loading, error } = useStats()
  const [needsToken, setNeedsToken] = useState(false)
  const [current, setCurrent] = useState<CurrentlyApplyingJob | null>(null)

  useEffect(() => {
    checkAuth().then((res) => {
      if (!res.authenticated) setNeedsToken(true)
    }).catch(() => setNeedsToken(true))
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
        {/* Setup banner */}
        {needsToken && (
          <Link
            href="/settings/"
            className="flex items-center gap-3 rounded-xl border border-warning/30 bg-warning/5 p-4 transition-colors hover:bg-warning/10"
          >
            <Key className="h-5 w-5 text-warning" />
            <div className="flex-1">
              <p className="text-sm font-medium text-foreground">API Token Required</p>
              <p className="text-xs text-muted-foreground">
                Go to Settings &rarr; API Token to connect to your ApplyLoop account. All data will load once connected.
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
