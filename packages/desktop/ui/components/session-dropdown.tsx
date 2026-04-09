"use client"

import { useState } from "react"
import { cn } from "@/lib/utils"
import { ChevronDown, Plus, Trash2, Circle } from "lucide-react"
import type { PTYSessionRecord } from "@/lib/api"

function formatDuration(seconds: number): string {
  const h = Math.floor(seconds / 3600)
  const m = Math.floor((seconds % 3600) / 60)
  if (h > 0) return `${h}h ${m}m`
  if (m > 0) return `${m}m`
  return `${Math.floor(seconds)}s`
}

interface SessionDropdownProps {
  sessions: PTYSessionRecord[]
  activeSessionId: string | null
  onNewSession: () => void
  onDeleteSession: (id: string) => void
}

export function SessionDropdown({
  sessions,
  activeSessionId,
  onNewSession,
  onDeleteSession,
}: SessionDropdownProps) {
  const [open, setOpen] = useState(false)

  return (
    <div className="relative">
      <button
        onClick={() => setOpen(!open)}
        className="flex items-center gap-2 rounded-lg border border-border bg-background px-3 py-1.5 text-xs font-medium text-muted-foreground transition-colors hover:bg-secondary hover:text-foreground"
      >
        {activeSessionId ? (
          <>
            <Circle className="h-2 w-2 fill-success text-success" />
            <span>Session {activeSessionId}</span>
          </>
        ) : (
          <span>No active session</span>
        )}
        <ChevronDown className={cn("h-3 w-3 transition-transform", open && "rotate-180")} />
      </button>

      {open && (
        <>
          <div className="fixed inset-0 z-40" onClick={() => setOpen(false)} />
          <div className="absolute right-0 top-full z-50 mt-1 w-72 rounded-xl border border-border bg-card shadow-xl">
            <div className="border-b border-border px-3 py-2">
              <p className="text-[10px] font-medium uppercase tracking-wider text-muted-foreground">
                Sessions ({sessions.length})
              </p>
            </div>

            <div className="max-h-48 overflow-y-auto">
              {sessions.length === 0 && (
                <div className="px-3 py-4 text-center text-xs text-muted-foreground">
                  No sessions yet
                </div>
              )}
              {sessions.map((s) => {
                const isActive = s.session_id === activeSessionId
                return (
                  <div
                    key={s.session_id}
                    className={cn(
                      "flex items-center justify-between px-3 py-2 text-xs transition-colors hover:bg-secondary/50",
                      isActive && "bg-primary/5"
                    )}
                  >
                    <div className="flex items-center gap-2">
                      <Circle
                        className={cn(
                          "h-2 w-2",
                          isActive ? "fill-success text-success" : "fill-muted-foreground text-muted-foreground"
                        )}
                      />
                      <div>
                        <span className="font-medium text-card-foreground">{s.session_id}</span>
                        <span className="ml-2 text-muted-foreground">{formatDuration(s.duration)}</span>
                      </div>
                    </div>
                    <button
                      onClick={(e) => {
                        e.stopPropagation()
                        if (isActive) {
                          if (confirm("Delete active session? A new one will be created.")) {
                            onDeleteSession(s.session_id)
                          }
                        } else {
                          onDeleteSession(s.session_id)
                        }
                      }}
                      className="rounded p-1 text-muted-foreground transition-colors hover:bg-destructive/10 hover:text-destructive"
                    >
                      <Trash2 className="h-3 w-3" />
                    </button>
                  </div>
                )
              })}
            </div>

            <div className="border-t border-border">
              <button
                onClick={() => { onNewSession(); setOpen(false) }}
                className="flex w-full items-center gap-2 px-3 py-2.5 text-xs font-medium text-primary transition-colors hover:bg-primary/5"
              >
                <Plus className="h-3.5 w-3.5" />
                New Session
              </button>
            </div>
          </div>
        </>
      )}
    </div>
  )
}
