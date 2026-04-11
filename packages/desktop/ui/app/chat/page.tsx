"use client"

import { useState, useRef, useEffect, useCallback } from "react"
import ReactMarkdown from "react-markdown"
import remarkGfm from "remark-gfm"
import { AppShell } from "@/components/app-shell"
import { Send, Loader2, Check, X, Clock, AlertTriangle, Zap, Smartphone } from "lucide-react"
import { cn } from "@/lib/utils"
import { useWebSocket } from "@/hooks/use-websocket"

// Lightweight Markdown renderer for chat bubbles.
// Keeps styling inline so we don't need a separate prose CSS dependency.
function MessageMarkdown({ children }: { children: string }) {
  return (
    <div className="[&>p]:my-0.5 [&>ul]:my-1 [&>ol]:my-1 [&>ul]:ml-4 [&>ol]:ml-4 [&>ul]:list-disc [&>ol]:list-decimal [&_code]:rounded [&_code]:bg-black/20 [&_code]:px-1 [&_code]:py-0.5 [&_code]:text-[0.9em] [&_code]:font-mono [&_pre]:mt-1 [&_pre]:mb-1 [&_pre]:rounded-md [&_pre]:bg-black/30 [&_pre]:p-2 [&_pre]:overflow-x-auto [&_pre>code]:bg-transparent [&_pre>code]:px-0 [&_pre>code]:py-0 [&_strong]:font-semibold [&_em]:italic [&_a]:text-primary [&_a]:underline [&_hr]:my-2 [&_hr]:border-border [&_h1]:text-base [&_h1]:font-semibold [&_h1]:mt-1 [&_h2]:text-sm [&_h2]:font-semibold [&_h2]:mt-1 [&_h3]:text-sm [&_h3]:font-semibold [&_h3]:mt-1 [&_li]:my-0 [&_blockquote]:border-l-2 [&_blockquote]:border-border [&_blockquote]:pl-2 [&_blockquote]:text-muted-foreground">
      <ReactMarkdown
        remarkPlugins={[remarkGfm]}
        components={{
          a: ({ ...props }) => (
            <a {...props} target="_blank" rel="noopener noreferrer" />
          ),
        }}
      >
        {children}
      </ReactMarkdown>
    </div>
  )
}

interface StatusEntry {
  id?: number
  company: string
  title: string
  ats: string
  status: string
  applied_at: string
}

interface ChatItem {
  type: "status" | "user" | "response" | "system" | "queue"
  content: string
  entries?: StatusEntry[]
  timestamp?: string
  viaTelegram?: boolean
}

function timeAgo(dateStr?: string): string {
  if (!dateStr) return ""
  const diff = Date.now() - new Date(dateStr).getTime()
  const mins = Math.floor(diff / 60000)
  if (mins < 1) return "just now"
  if (mins < 60) return `${mins}m ago`
  const hours = Math.floor(mins / 60)
  if (hours < 24) return `${hours}h ago`
  return `${Math.floor(hours / 24)}d ago`
}

function StatusCard({ entry }: { entry: StatusEntry }) {
  const isSubmitted = entry.status === "submitted"
  const isFailed = entry.status === "failed"
  const isQueued = entry.status === "queued" || entry.status === "scouted"

  return (
    <div
      className={cn(
        "flex items-center gap-3 rounded-lg px-3 py-2 text-xs",
        isSubmitted && "bg-success/5 text-success",
        isFailed && "bg-destructive/5 text-destructive",
        isQueued && "bg-primary/5 text-primary"
      )}
    >
      {isSubmitted && <Check className="h-3.5 w-3.5 flex-shrink-0" />}
      {isFailed && <X className="h-3.5 w-3.5 flex-shrink-0" />}
      {isQueued && <Clock className="h-3.5 w-3.5 flex-shrink-0" />}
      <div className="flex-1 min-w-0">
        <span className="font-medium">{entry.company}</span>
        <span className="text-muted-foreground"> — {entry.title}</span>
      </div>
      <span className="flex-shrink-0 text-muted-foreground">{timeAgo(entry.applied_at)}</span>
    </div>
  )
}

export default function ChatPage() {
  const [items, setItems] = useState<ChatItem[]>([])
  const [input, setInput] = useState("")
  const [isAsking, setIsAsking] = useState(false)
  const bottomRef = useRef<HTMLDivElement>(null)

  const onMessage = useCallback((data: unknown) => {
    const msg = data as {
      type: string
      data?: string
      entries?: StatusEntry[]
      count?: number
      from_bot?: boolean
      timestamp?: number
    }

    if (msg.type === "system") {
      setItems((prev) => [...prev, { type: "system", content: msg.data || "" }])
    } else if (msg.type === "activity" && msg.entries) {
      // Status feed — show new applications.
      // Sort oldest → newest so newest ends up at the bottom (messaging-app style).
      const sorted = [...msg.entries].sort((a, b) => {
        const ta = new Date(a.applied_at || 0).getTime()
        const tb = new Date(b.applied_at || 0).getTime()
        return ta - tb
      })
      setItems((prev) => [
        ...prev,
        { type: "status", content: "", entries: sorted, timestamp: new Date().toISOString() },
      ])
    } else if (msg.type === "telegram") {
      // Telegram traffic mirrored into the chat UI.
      // from_bot=false → incoming user message from phone
      // from_bot=true  → Claude's reply that was also sent to Telegram
      setItems((prev) => [
        ...prev,
        {
          type: msg.from_bot ? "response" : "user",
          content: msg.data || "",
          viaTelegram: true,
        },
      ])
    } else if (msg.type === "queue_update") {
      setItems((prev) => [
        ...prev,
        { type: "queue", content: msg.data || "" },
      ])
    } else if (msg.type === "session_idle") {
      setItems((prev) => [
        ...prev,
        { type: "system", content: `Session idle for ${msg.data}` },
      ])
    } else if (msg.type === "thinking") {
      setIsAsking(true)
    } else if (msg.type === "btw_response") {
      setIsAsking(false)
      setItems((prev) => [
        ...prev,
        { type: "response", content: msg.data || "" },
      ])
    } else if (msg.type === "stats") {
      // Could show stats card
    }
  }, [])

  const { send, connected } = useWebSocket("/ws/chat", { onMessage })

  useEffect(() => {
    bottomRef.current?.scrollIntoView({ behavior: "smooth" })
  }, [items])

  const handleSend = () => {
    const text = input.trim()
    if (!text) return
    setItems((prev) => [...prev, { type: "user", content: text }])
    send({ action: "message", message: text })
    setInput("")
  }

  return (
    <AppShell>
      <div className="flex h-[calc(100vh-90px)] flex-col">
        {!connected && (
          <div className="mb-2 rounded-lg bg-warning/10 px-3 py-1.5 text-center text-xs text-warning">
            Connecting...
          </div>
        )}

        {/* Chat feed */}
        <div className="flex-1 space-y-3 overflow-y-auto px-2 pb-4">
          {items.length === 0 && (
            <div className="flex h-full items-center justify-center">
              <div className="text-center">
                <Zap className="mx-auto h-8 w-8 text-muted-foreground/30" />
                <p className="mt-3 text-sm font-medium text-muted-foreground">ApplyLoop Activity</p>
                <p className="mt-1 text-xs text-muted-foreground/70">
                  Status updates appear here automatically.
                  <br />
                  Ask questions using the input below.
                </p>
              </div>
            </div>
          )}

          {items.map((item, i) => {
            if (item.type === "status" && item.entries) {
              return (
                <div key={i} className="space-y-1">
                  {item.entries.map((entry, j) => (
                    <StatusCard key={`${i}-${j}`} entry={entry} />
                  ))}
                </div>
              )
            }

            if (item.type === "queue") {
              return (
                <div key={i} className="flex items-center gap-2 rounded-lg bg-primary/5 px-3 py-2 text-xs text-primary">
                  <Clock className="h-3.5 w-3.5" />
                  {item.content}
                </div>
              )
            }

            if (item.type === "system") {
              return (
                <div key={i} className="flex items-center gap-2 rounded-lg bg-muted/30 px-3 py-2 text-xs text-muted-foreground">
                  <AlertTriangle className="h-3.5 w-3.5" />
                  {item.content}
                </div>
              )
            }

            if (item.type === "user") {
              return (
                <div key={i} className="flex flex-col items-end gap-0.5">
                  {item.viaTelegram && (
                    <div className="flex items-center gap-1 text-[10px] text-muted-foreground">
                      <Smartphone className="h-2.5 w-2.5" />
                      from Telegram
                    </div>
                  )}
                  <div className="max-w-[80%] rounded-2xl bg-primary px-4 py-2.5 text-sm text-primary-foreground">
                    <MessageMarkdown>{item.content}</MessageMarkdown>
                  </div>
                </div>
              )
            }

            if (item.type === "response") {
              return (
                <div key={i} className="flex flex-col items-start gap-0.5">
                  {item.viaTelegram && (
                    <div className="flex items-center gap-1 text-[10px] text-muted-foreground">
                      <Smartphone className="h-2.5 w-2.5" />
                      sent to Telegram
                    </div>
                  )}
                  <div className="max-w-[80%] rounded-2xl border border-border bg-card px-4 py-2.5 text-sm text-card-foreground">
                    <MessageMarkdown>{item.content}</MessageMarkdown>
                  </div>
                </div>
              )
            }

            return null
          })}

          {isAsking && (
            <div className="flex items-center gap-2 px-3 py-2 text-xs text-muted-foreground">
              <Loader2 className="h-3.5 w-3.5 animate-spin" />
              Asking Claude...
            </div>
          )}

          <div ref={bottomRef} />
        </div>

        {/* Input */}
        <div className="border-t border-border pt-3">
          <div className="flex items-center gap-2 rounded-xl border border-border bg-card p-2">
            <input
              type="text"
              value={input}
              onChange={(e) => setInput(e.target.value)}
              onKeyDown={(e) => e.key === "Enter" && !e.shiftKey && handleSend()}
              placeholder="Ask ApplyLoop anything..."
              className="flex-1 bg-transparent px-2 text-sm text-foreground placeholder:text-muted-foreground focus:outline-none"
            />
            <button
              onClick={handleSend}
              disabled={!input.trim() || isAsking}
              className="flex h-9 w-9 items-center justify-center rounded-lg bg-primary text-primary-foreground transition-colors hover:bg-primary/90 disabled:opacity-50"
            >
              {isAsking ? (
                <Loader2 className="h-4 w-4 animate-spin" />
              ) : (
                <Send className="h-4 w-4" />
              )}
            </button>
          </div>
        </div>
      </div>
    </AppShell>
  )
}
