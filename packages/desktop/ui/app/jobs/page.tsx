"use client"

import { useState, useEffect, useCallback, useRef } from "react"
import { AppShell } from "@/components/app-shell"
import { getRecentApplications, getPipeline, getStats, deleteFromQueue, clearQueue, type Application, type PipelineJob } from "@/lib/api"
import { cn } from "@/lib/utils"
import { Check, X, Clock, Loader2, Filter, Trash2, XCircle } from "lucide-react"

function timeAgo(dateStr?: string): string {
  if (!dateStr) return ""
  const diff = Date.now() - new Date(dateStr).getTime()
  const mins = Math.floor(diff / 60000)
  if (mins < 1) return "now"
  if (mins < 60) return `${mins}m ago`
  const hours = Math.floor(mins / 60)
  if (hours < 24) return `${hours}h ago`
  const days = Math.floor(hours / 24)
  if (days < 7) return `${days}d ago`
  return new Date(dateStr).toLocaleDateString("en-US", { month: "short", day: "numeric" })
}

function formatDate(dateStr?: string): string {
  if (!dateStr) return ""
  // Date-only strings (e.g. "2026-04-07") have no time component — just show the date
  const hasTime = dateStr.includes("T") || dateStr.includes(" ")
  if (hasTime) {
    return new Date(dateStr).toLocaleDateString("en-US", {
      month: "short",
      day: "numeric",
      hour: "numeric",
      minute: "2-digit",
    })
  }
  // Date-only: parse parts manually to avoid timezone shift from Date constructor
  const [year, month, day] = dateStr.split("-").map(Number)
  const dt = new Date(year, month - 1, day)
  return dt.toLocaleDateString("en-US", { month: "short", day: "numeric" })
}

function StatusBadge({ status }: { status: string }) {
  return (
    <span
      className={cn(
        "inline-flex items-center gap-1 rounded-md px-2 py-0.5 text-xs font-medium",
        status === "submitted" && "bg-success/10 text-success",
        status === "failed" && "bg-destructive/10 text-destructive",
        status === "queued" && "bg-primary/10 text-primary",
        status === "skipped" && "bg-muted/50 text-muted-foreground"
      )}
    >
      {status === "submitted" && <Check className="h-3 w-3" />}
      {status === "failed" && <X className="h-3 w-3" />}
      {status === "queued" && <Clock className="h-3 w-3" />}
      {status === "submitted" && "Applied"}
      {status === "failed" && "Failed"}
      {status === "queued" && "In Queue"}
      {status === "skipped" && "Skipped"}
    </span>
  )
}

type FilterType = "all" | "submitted" | "failed"

export default function JobsListPage() {
  const [applied, setApplied] = useState<Application[]>([])
  const [queued, setQueued] = useState<Application[]>([])
  const [totalApplied, setTotalApplied] = useState(0)
  const [totalQueue, setTotalQueue] = useState(0)
  const [loading, setLoading] = useState(true)
  const [filter, setFilter] = useState<FilterType>("all")
  const appliedEndRef = useRef<HTMLDivElement>(null)

  const refresh = useCallback(async () => {
    try {
      const [recentRes, pipelineRes, statsRes] = await Promise.allSettled([
        getRecentApplications(2000),
        getPipeline(),
        getStats(),
      ])

      if (recentRes.status === "fulfilled" && recentRes.value.ok) {
        const all = recentRes.value.data
        // Split into applied (submitted+failed) and queued
        const appliedJobs = all.filter(
          (j: Application) => j.status === "submitted" || j.status === "failed"
        )
        // Ascending: oldest at top, newest at bottom
        appliedJobs.reverse()
        setApplied(appliedJobs)
      }

      if (pipelineRes.status === "fulfilled" && pipelineRes.value.ok) {
        const p = pipelineRes.value.data
        // Queue: next-to-apply at top, newest scouted at bottom
        const queuedJobs = [...(p.queued || []), ...(p.discovered || [])].map(
          (j: PipelineJob) => ({
            id: typeof j.id === "number" ? j.id : undefined,
            company: j.company,
            title: j.title,
            ats: j.ats,
            status: "queued" as const,
            applied_at: j.posted_at,
          })
        )
        setQueued(queuedJobs)
        setTotalQueue(queuedJobs.length)
      }

      if (statsRes.status === "fulfilled" && statsRes.value.ok) {
        setTotalApplied(statsRes.value.data.total_applied || 0)
        setTotalQueue((prev: number) => statsRes.value.data.in_queue || prev)
      }
    } catch {
      /* ignore */
    } finally {
      setLoading(false)
    }
  }, [])

  useEffect(() => {
    refresh()
    const interval = setInterval(refresh, 15000)
    return () => clearInterval(interval)
  }, [refresh])

  // Auto-scroll applied list to bottom (newest)
  useEffect(() => {
    appliedEndRef.current?.scrollIntoView({ behavior: "smooth" })
  }, [applied])

  const filteredApplied =
    filter === "all"
      ? applied
      : applied.filter((j) => j.status === filter)

  return (
    <AppShell>
      <div className="flex h-[calc(100vh-48px)] flex-col gap-4">
        {/* Header */}
        <div className="flex items-center justify-between">
          <div>
            <h1 className="text-xl font-semibold text-foreground">Jobs List</h1>
            <p className="mt-0.5 text-sm text-muted-foreground">
              {totalApplied || applied.length} applied &middot; {totalQueue || queued.length} in queue
            </p>
          </div>

          {/* Filter */}
          <div className="flex items-center gap-1 rounded-lg border border-border bg-card p-1">
            <Filter className="ml-2 h-3.5 w-3.5 text-muted-foreground" />
            {(["all", "submitted", "failed"] as FilterType[]).map((f) => (
              <button
                key={f}
                onClick={() => setFilter(f)}
                className={cn(
                  "rounded-md px-3 py-1 text-xs font-medium transition-colors",
                  filter === f
                    ? "bg-primary/10 text-primary"
                    : "text-muted-foreground hover:text-foreground"
                )}
              >
                {f === "all" ? "All" : f === "submitted" ? "Applied" : "Failed"}
              </button>
            ))}
          </div>
        </div>

        {loading ? (
          <div className="flex items-center gap-2 text-muted-foreground">
            <Loader2 className="h-4 w-4 animate-spin" /> Loading jobs...
          </div>
        ) : (
          /* Split view: Applied (left) | Queue (right) */
          <div className="grid flex-1 gap-4 overflow-hidden lg:grid-cols-2">
            {/* LEFT: Applied — oldest top, newest bottom, auto-scroll to bottom */}
            <div className="flex flex-col overflow-hidden rounded-xl border border-border bg-card">
              <div className="flex items-center justify-between border-b border-border px-4 py-3">
                <div className="flex items-center gap-2">
                  <Check className="h-4 w-4 text-success" />
                  <span className="text-sm font-medium text-card-foreground">
                    Applied ({filteredApplied.length})
                  </span>
                </div>
                <span className="text-[10px] text-muted-foreground">oldest ↑ newest ↓</span>
              </div>
              <div className="flex-1 overflow-y-auto">
                {filteredApplied.length === 0 ? (
                  <div className="flex h-full items-center justify-center p-8">
                    <p className="text-sm text-muted-foreground">No applications yet</p>
                  </div>
                ) : (
                  <table className="w-full">
                    <thead className="sticky top-0 bg-card z-10">
                      <tr className="border-b border-border">
                        <th className="px-4 py-2 text-left text-xs font-medium text-muted-foreground">Company / Role</th>
                        <th className="hidden px-4 py-2 text-left text-xs font-medium text-muted-foreground sm:table-cell">Platform</th>
                        <th className="px-4 py-2 text-left text-xs font-medium text-muted-foreground">Status</th>
                        <th className="px-4 py-2 text-right text-xs font-medium text-muted-foreground">Date</th>
                      </tr>
                    </thead>
                    <tbody>
                      {filteredApplied.map((job, i) => (
                        <tr
                          key={i}
                          className="border-b border-border last:border-0 hover:bg-secondary/30"
                        >
                          <td className="px-4 py-2.5">
                            <p className="text-sm font-medium text-card-foreground">
                              {job.company}
                            </p>
                            <p className="text-xs text-muted-foreground">{job.title}</p>
                          </td>
                          <td className="hidden px-4 py-2.5 sm:table-cell">
                            {job.ats && job.ats !== "Unknown" && (
                              <span className="rounded-md bg-secondary px-1.5 py-0.5 text-[10px] text-muted-foreground">
                                {job.ats}
                              </span>
                            )}
                          </td>
                          <td className="px-4 py-2.5">
                            <StatusBadge status={job.status} />
                          </td>
                          <td className="px-4 py-2.5 text-right text-xs text-muted-foreground">
                            {formatDate(job.applied_at)}
                          </td>
                        </tr>
                      ))}
                    </tbody>
                  </table>
                )}
                <div ref={appliedEndRef} />
              </div>
            </div>

            {/* RIGHT: Queue — next-to-apply at top, newest scouted at bottom */}
            <div className="flex flex-col overflow-hidden rounded-xl border border-border bg-card">
              <div className="flex items-center justify-between border-b border-border px-4 py-3">
                <div className="flex items-center gap-2">
                  <Clock className="h-4 w-4 text-primary" />
                  <span className="text-sm font-medium text-card-foreground">
                    Queue ({queued.length})
                  </span>
                </div>
                <div className="flex items-center gap-2">
                  <span className="text-[10px] text-muted-foreground">newest ↑</span>
                  {queued.length > 0 && (
                    <button
                      onClick={async () => {
                        if (confirm(`Clear all ${queued.length} jobs from the queue?`)) {
                          await clearQueue()
                          setQueued([])
                          refresh()
                        }
                      }}
                      className="flex items-center gap-1 rounded-md px-2 py-0.5 text-[10px] font-medium text-destructive transition-colors hover:bg-destructive/10"
                    >
                      <XCircle className="h-3 w-3" />
                      Clear All
                    </button>
                  )}
                </div>
              </div>
              <div className="flex-1 overflow-y-auto">
                {queued.length === 0 ? (
                  <div className="flex h-full items-center justify-center p-8">
                    <p className="text-sm text-muted-foreground">Queue is empty</p>
                  </div>
                ) : (
                  <table className="w-full">
                    <thead className="sticky top-0 bg-card z-10">
                      <tr className="border-b border-border">
                        <th className="px-4 py-2 text-left text-xs font-medium text-muted-foreground">Company / Role</th>
                        <th className="hidden px-4 py-2 text-left text-xs font-medium text-muted-foreground sm:table-cell">Platform</th>
                        <th className="px-4 py-2 text-left text-xs font-medium text-muted-foreground">Status</th>
                        <th className="px-4 py-2 text-right text-xs font-medium text-muted-foreground">Added</th>
                        <th className="px-2 py-2 text-xs font-medium text-muted-foreground"></th>
                      </tr>
                    </thead>
                    <tbody>
                      {queued.map((job, i) => (
                        <tr
                          key={i}
                          className={cn(
                            "border-b border-border last:border-0 hover:bg-secondary/30",
                            i === 0 && "bg-primary/5"
                          )}
                        >
                          <td className="px-4 py-2.5">
                            <div className="flex items-center gap-2">
                              {i === 0 && (
                                <span className="flex h-5 w-5 items-center justify-center rounded-full bg-primary/10 text-[10px] font-bold text-primary">
                                  1
                                </span>
                              )}
                              <div>
                                <p className="text-sm font-medium text-card-foreground">
                                  {job.company}
                                </p>
                                <p className="text-xs text-muted-foreground">{job.title}</p>
                              </div>
                            </div>
                          </td>
                          <td className="hidden px-4 py-2.5 sm:table-cell">
                            {job.ats && job.ats !== "Unknown" && (
                              <span className="rounded-md bg-secondary px-1.5 py-0.5 text-[10px] text-muted-foreground">
                                {job.ats}
                              </span>
                            )}
                          </td>
                          <td className="px-4 py-2.5">
                            <StatusBadge status="queued" />
                          </td>
                          <td className="px-4 py-2.5 text-right text-xs text-muted-foreground">
                            {timeAgo(job.applied_at)}
                          </td>
                          <td className="px-2 py-2.5">
                            <button
                              onClick={async () => {
                                const jobWithId = job as Application & { id?: number }
                                if (jobWithId.id) {
                                  await deleteFromQueue(jobWithId.id)
                                }
                                setQueued((prev) => prev.filter((_, idx) => idx !== i))
                              }}
                              className="rounded-md p-1 text-muted-foreground transition-colors hover:bg-destructive/10 hover:text-destructive"
                              title="Remove from queue"
                            >
                              <Trash2 className="h-3.5 w-3.5" />
                            </button>
                          </td>
                        </tr>
                      ))}
                    </tbody>
                  </table>
                )}
              </div>
            </div>
          </div>
        )}
      </div>
    </AppShell>
  )
}
