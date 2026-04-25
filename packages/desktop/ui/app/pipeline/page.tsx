"use client"

import { useEffect, useState, useCallback } from "react"
import { AppShell } from "@/components/app-shell"
import { KanbanColumn } from "@/components/pipeline/kanban-column"
import { KanbanCard } from "@/components/pipeline/kanban-card"
import { StatCard } from "@/components/dashboard/stat-card"
import { useStats } from "@/hooks/use-stats"
import {
  getPipeline,
  getCurrentlyApplying,
  getStuckJobs,
  resetStuckJobs,
  type PipelineData,
  type PipelineJob,
  type CurrentlyApplyingJob,
} from "@/lib/api"
import { Loader2, AlertTriangle, ExternalLink } from "lucide-react"

function timeAgo(dateStr?: string): string {
  if (!dateStr) return ""
  const diff = Date.now() - new Date(dateStr).getTime()
  const mins = Math.floor(diff / 60000)
  if (mins < 1) return "now"
  if (mins < 60) return `${mins}m ago`
  const hours = Math.floor(mins / 60)
  if (hours < 24) return `${hours}h ago`
  return `${Math.floor(hours / 24)}d ago`
}

function elapsedTime(dateStr?: string): string {
  if (!dateStr) return ""
  const mins = Math.floor((Date.now() - new Date(dateStr).getTime()) / 60000)
  if (mins < 1) return "just started"
  if (mins < 60) return `${mins}m elapsed`
  return `${Math.floor(mins / 60)}h ${mins % 60}m elapsed`
}

type ColumnVariant = "blue" | "amber" | "green" | "red"
type CardVariant = "default" | "success" | "failed" | "applying"

const columns: { key: keyof PipelineData; title: string; variant: ColumnVariant; cardVariant?: CardVariant }[] = [
  { key: "queued", title: "Queued", variant: "blue" },
  { key: "applying", title: "Applying", variant: "amber", cardVariant: "applying" },
  { key: "submitted", title: "Submitted", variant: "green", cardVariant: "success" },
  { key: "failed", title: "Failed", variant: "red", cardVariant: "failed" },
]

export default function PipelinePage() {
  const [pipeline, setPipeline] = useState<PipelineData | null>(null)
  const [current, setCurrent] = useState<CurrentlyApplyingJob | null>(null)
  const [stuckJobs, setStuckJobs] = useState<PipelineJob[]>([])
  const [loading, setLoading] = useState(true)
  const [resetting, setResetting] = useState(false)
  const { stats, loading: statsLoading, refresh: refreshStats } = useStats()

  const refresh = useCallback(async () => {
    try {
      const [pipelineRes, currentRes, stuckRes] = await Promise.allSettled([
        getPipeline(),
        getCurrentlyApplying(),
        getStuckJobs(),
      ])
      if (pipelineRes.status === "fulfilled" && pipelineRes.value.ok)
        setPipeline(pipelineRes.value.data)
      if (currentRes.status === "fulfilled" && currentRes.value.ok)
        setCurrent(currentRes.value.data)
      if (stuckRes.status === "fulfilled" && stuckRes.value.ok)
        setStuckJobs(stuckRes.value.data)
      // Keep stat cards in sync with the kanban on every poll cycle.
      refreshStats()
    } catch { /* ignore */ }
    finally { setLoading(false) }
  }, [refreshStats])

  useEffect(() => {
    refresh()
    const interval = setInterval(refresh, 5000)
    return () => clearInterval(interval)
  }, [refresh])

  const handleResetStuck = async () => {
    setResetting(true)
    try {
      await resetStuckJobs()
      await refresh()
    } finally {
      setResetting(false)
    }
  }

  return (
    <AppShell>
      <div className="space-y-4">
        <h1 className="text-xl font-semibold text-foreground">Pipeline</h1>

        {/* Stats Row */}
        <div className="grid gap-4 sm:grid-cols-2 lg:grid-cols-4">
          <StatCard
            title="Applied Today"
            value={statsLoading ? "—" : String(stats?.applied_today ?? 0)}
            badge={
              stats?.applied_today
                ? { text: `+${stats.applied_today}`, variant: "success" as const }
                : undefined
            }
          />
          <StatCard
            title="Total Applied"
            value={statsLoading ? "—" : String(stats?.total_applied ?? 0)}
          />
          <StatCard
            title="In Queue"
            value={statsLoading ? "—" : String(stats?.in_queue ?? 0)}
            pulseDot={(stats?.in_queue ?? 0) > 0}
          />
          <StatCard
            title="Success Rate"
            value={statsLoading ? "—" : `${stats?.success_rate ?? 0}%`}
            trend={(stats?.success_rate ?? 0) > 50 ? "up" : undefined}
          />
        </div>

        {/* Stuck Jobs Warning */}
        {stuckJobs.length > 0 && (
          <div className="flex items-center gap-3 rounded-xl border border-destructive/30 bg-destructive/5 p-4">
            <AlertTriangle className="h-5 w-5 flex-shrink-0 text-destructive" />
            <div className="flex-1">
              <p className="text-sm font-medium text-foreground">
                {stuckJobs.length} job{stuckJobs.length > 1 ? "s" : ""} stuck in &apos;applying&apos; for &gt;10 min
              </p>
              <p className="text-xs text-muted-foreground">
                {stuckJobs.map(j => j.company).join(", ")}
              </p>
            </div>
            <button
              onClick={handleResetStuck}
              disabled={resetting}
              className="flex items-center gap-1.5 rounded-lg bg-destructive/10 px-3 py-1.5 text-xs font-medium text-destructive transition-colors hover:bg-destructive/20 disabled:opacity-50"
            >
              {resetting ? <Loader2 className="h-3 w-3 animate-spin" /> : null}
              Reset to Queue
            </button>
          </div>
        )}

        {/* Currently Applying Hero Banner */}
        {current && (
          <div className="flex items-center gap-3 rounded-xl border border-warning/30 bg-warning/5 p-4">
            <Loader2 className="h-5 w-5 animate-spin text-warning" />
            <div className="flex-1">
              <p className="text-sm font-semibold text-foreground">
                Currently Applying: {current.company} — {current.title}
              </p>
              <p className="mt-0.5 text-xs text-muted-foreground">
                {current.ats}{current.location ? ` · ${current.location}` : ""} · {elapsedTime(current.updated_at)}
              </p>
            </div>
            {current.url && (
              <a
                href={current.url}
                target="_blank"
                rel="noopener noreferrer"
                className="flex items-center gap-1 text-xs text-primary hover:underline"
              >
                View Job <ExternalLink className="h-3 w-3" />
              </a>
            )}
          </div>
        )}

        {/* Kanban Columns */}
        {loading ? (
          <div className="flex items-center gap-2 text-muted-foreground">
            <Loader2 className="h-4 w-4 animate-spin" />
            Loading pipeline...
          </div>
        ) : (
          <div className="flex gap-4 overflow-x-auto pb-4">
            {columns.map((col) => {
              // The "queued" column merges both scouted-but-not-yet-queued jobs
              // and explicit queued jobs — they're both "waiting to apply".
              const jobs =
                col.key === "queued"
                  ? [...(pipeline?.queued ?? []), ...(pipeline?.discovered ?? [])]
                  : pipeline?.[col.key] ?? []
              return (
                <KanbanColumn
                  key={col.key}
                  title={col.title}
                  count={jobs.length}
                  variant={col.variant}
                >
                  {jobs.slice(0, 10).map((job: PipelineJob) => (
                    <KanbanCard
                      key={job.id}
                      jobId={job.id}
                      company={job.company}
                      role={job.title}
                      platform={job.ats}
                      posted={timeAgo(job.posted_at)}
                      variant={col.cardVariant}
                      url={job.url}
                      location={job.location}
                      error={job.error}
                      scoutedAt={job.scouted_at}
                      appliedAt={job.applied_at}
                      hasScreenshot={Boolean(job.screenshot)}
                      applyingMessage={
                        col.key === "applying"
                          ? `Filling form at ${job.ats}...`
                          : undefined
                      }
                    />
                  ))}
                  {jobs.length > 10 && (
                    <div className="px-3 py-2 text-center text-xs text-muted-foreground">
                      +{jobs.length - 10} more
                    </div>
                  )}
                </KanbanColumn>
              )
            })}
          </div>
        )}
      </div>
    </AppShell>
  )
}
