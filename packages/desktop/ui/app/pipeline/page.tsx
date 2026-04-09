"use client"

import { useEffect, useState, useCallback } from "react"
import { AppShell } from "@/components/app-shell"
import { KanbanColumn } from "@/components/pipeline/kanban-column"
import { KanbanCard } from "@/components/pipeline/kanban-card"
import { getPipeline, type PipelineData, type PipelineJob } from "@/lib/api"
import { Loader2 } from "lucide-react"

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

type ColumnVariant = "gray" | "blue" | "amber" | "green" | "red"
type CardVariant = "default" | "success" | "failed" | "applying"

const columns: { key: keyof PipelineData; title: string; variant: ColumnVariant; cardVariant?: CardVariant }[] = [
  { key: "discovered", title: "Discovered", variant: "gray" },
  { key: "queued", title: "Queued", variant: "blue" },
  { key: "applying", title: "Applying", variant: "amber", cardVariant: "applying" },
  { key: "submitted", title: "Submitted", variant: "green", cardVariant: "success" },
  { key: "failed", title: "Failed", variant: "red", cardVariant: "failed" },
]

export default function PipelinePage() {
  const [pipeline, setPipeline] = useState<PipelineData | null>(null)
  const [loading, setLoading] = useState(true)

  const refresh = useCallback(async () => {
    try {
      const res = await getPipeline()
      if (res.ok) setPipeline(res.data)
    } catch { /* ignore */ }
    finally { setLoading(false) }
  }, [])

  useEffect(() => {
    refresh()
    const interval = setInterval(refresh, 10000)
    return () => clearInterval(interval)
  }, [refresh])

  return (
    <AppShell>
      <div className="space-y-4">
        <h1 className="text-xl font-semibold text-foreground">Pipeline</h1>
        {loading ? (
          <div className="flex items-center gap-2 text-muted-foreground">
            <Loader2 className="h-4 w-4 animate-spin" />
            Loading pipeline...
          </div>
        ) : (
          <div className="flex gap-4 overflow-x-auto pb-4">
            {columns.map((col) => {
              const jobs = pipeline?.[col.key] ?? []
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
                      company={job.company}
                      role={job.title}
                      platform={job.ats}
                      posted={timeAgo(job.posted_at)}
                      variant={col.cardVariant}
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
