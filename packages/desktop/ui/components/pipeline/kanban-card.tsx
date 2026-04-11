"use client"

import { useState } from "react"
import { cn } from "@/lib/utils"
import { Loader2, ExternalLink, Image as ImageIcon, X } from "lucide-react"

interface KanbanCardProps {
  jobId?: string | number
  company: string
  role: string
  platform: string
  posted: string
  variant?: "default" | "success" | "failed" | "applying"
  applyingMessage?: string
  url?: string
  location?: string
  error?: string
  scoutedAt?: string
  appliedAt?: string
  hasScreenshot?: boolean
}

function formatTimestamp(dateStr?: string): string {
  if (!dateStr) return ""
  const dt = new Date(dateStr)
  return dt.toLocaleDateString("en-US", {
    month: "short",
    day: "numeric",
    hour: "numeric",
    minute: "2-digit",
  })
}

export function KanbanCard({
  jobId,
  company,
  role,
  platform,
  posted,
  variant = "default",
  applyingMessage,
  url,
  location,
  error,
  scoutedAt,
  appliedAt,
  hasScreenshot,
}: KanbanCardProps) {
  const [expanded, setExpanded] = useState(false)
  const [lightboxOpen, setLightboxOpen] = useState(false)

  const screenshotUrl = jobId != null ? `/api/screenshots/${jobId}` : null

  return (
    <>
      <div
        onClick={() => setExpanded(!expanded)}
        className={cn(
          "cursor-pointer rounded-lg border border-border bg-background p-3 transition-shadow hover:shadow-md",
          variant === "success" && "border-l-2 border-l-success",
          variant === "failed" && "border-l-2 border-l-destructive",
          variant === "applying" && "border-l-2 border-l-warning"
        )}
      >
        <p className="text-sm font-medium text-foreground">{company}</p>
        <p className="mt-0.5 text-xs text-muted-foreground">{role}</p>
        <div className="mt-2 flex items-center justify-between">
          {platform ? (
            <span className="rounded-md bg-secondary px-1.5 py-0.5 text-[10px] text-muted-foreground">
              {platform}
            </span>
          ) : <span />}
          <span className="text-[10px] text-muted-foreground">{posted}</span>
        </div>
        {variant === "applying" && applyingMessage && (
          <div className="mt-2 flex items-center gap-1.5 text-[10px] text-warning">
            <Loader2 className="h-3 w-3 animate-spin" />
            {applyingMessage}
          </div>
        )}

        {/* Screenshot thumbnail — only on submitted/failed cards */}
        {hasScreenshot && screenshotUrl && (variant === "success" || variant === "failed") && (
          <div
            onClick={(e) => {
              e.stopPropagation()
              setLightboxOpen(true)
            }}
            className="mt-2 overflow-hidden rounded-md border border-border bg-muted/30 transition-opacity hover:opacity-90"
            title="Click to expand"
          >
            <img
              src={screenshotUrl}
              alt="Application screenshot"
              loading="lazy"
              className="h-24 w-full object-cover object-top"
              onError={(e) => {
                // Hide the whole thumbnail container if the image fails
                (e.currentTarget.parentElement as HTMLElement).style.display = "none"
              }}
            />
          </div>
        )}

        {/* Expanded details */}
        {expanded && (
          <div className="mt-2 space-y-1 border-t border-border pt-2 text-[11px] text-muted-foreground">
            {location && <p>{location}</p>}
            {url && (
              <a
                href={url}
                target="_blank"
                rel="noopener noreferrer"
                onClick={(e) => e.stopPropagation()}
                className="flex items-center gap-1 text-primary hover:underline"
              >
                <ExternalLink className="h-3 w-3" />
                <span className="truncate">{url}</span>
              </a>
            )}
            {error && (
              <p className="text-destructive">{error}</p>
            )}
            {scoutedAt && <p>Scouted: {formatTimestamp(scoutedAt)}</p>}
            {appliedAt && <p>Applied: {formatTimestamp(appliedAt)}</p>}
            {hasScreenshot && screenshotUrl && (
              <button
                onClick={(e) => {
                  e.stopPropagation()
                  setLightboxOpen(true)
                }}
                className="flex items-center gap-1 text-primary hover:underline"
              >
                <ImageIcon className="h-3 w-3" />
                View full screenshot
              </button>
            )}
          </div>
        )}
      </div>

      {/* Lightbox modal */}
      {lightboxOpen && screenshotUrl && (
        <div
          onClick={() => setLightboxOpen(false)}
          className="fixed inset-0 z-50 flex items-center justify-center bg-black/90 p-8 backdrop-blur-sm"
        >
          <button
            onClick={() => setLightboxOpen(false)}
            className="absolute right-4 top-4 rounded-full bg-white/10 p-2 text-white transition-colors hover:bg-white/20"
            aria-label="Close"
          >
            <X className="h-5 w-5" />
          </button>
          <div className="max-h-full max-w-full overflow-auto">
            <img
              src={screenshotUrl}
              alt={`${company} — ${role} application screenshot`}
              className="max-h-[90vh] max-w-[90vw] rounded-lg border border-white/20 shadow-2xl"
              onClick={(e) => e.stopPropagation()}
            />
          </div>
          <div className="absolute bottom-4 left-1/2 -translate-x-1/2 rounded-lg bg-black/60 px-4 py-2 text-sm text-white">
            <span className="font-medium">{company}</span>
            <span className="text-white/70"> — {role}</span>
          </div>
        </div>
      )}
    </>
  )
}
