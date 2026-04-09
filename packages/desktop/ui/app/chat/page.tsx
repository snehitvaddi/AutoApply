"use client"

import { useState, useRef, useEffect, useCallback } from "react"
import { AppShell } from "@/components/app-shell"
import { Send, Loader2, RotateCcw, Wifi, WifiOff } from "lucide-react"
import { cn } from "@/lib/utils"
import { useWebSocket } from "@/hooks/use-websocket"

interface Message {
  role: "user" | "assistant" | "system"
  content: string
  streaming?: boolean
}

function ChatBubble({ message }: { message: Message }) {
  const isUser = message.role === "user"
  const isSystem = message.role === "system"

  if (isSystem) {
    return (
      <div className="flex justify-center">
        <span className="text-xs text-muted-foreground">{message.content}</span>
      </div>
    )
  }

  return (
    <div className={cn("flex", isUser ? "justify-end" : "justify-start")}>
      <div
        className={cn(
          "max-w-[80%] rounded-2xl px-4 py-3",
          isUser
            ? "bg-primary text-primary-foreground"
            : "bg-card border border-border text-card-foreground"
        )}
      >
        <p className="whitespace-pre-wrap text-sm leading-relaxed">{message.content}</p>
        {message.streaming && (
          <Loader2 className="mt-1 h-3 w-3 animate-spin text-muted-foreground" />
        )}
      </div>
    </div>
  )
}

export default function ChatPage() {
  const [messages, setMessages] = useState<Message[]>([])
  const [input, setInput] = useState("")
  const [isThinking, setIsThinking] = useState(false)
  const [sessionAlive, setSessionAlive] = useState(false)
  const messagesEndRef = useRef<HTMLDivElement>(null)
  const streamingRef = useRef("")

  const onMessage = useCallback((data: unknown) => {
    const msg = data as { type: string; data: string; alive?: boolean; state?: string }

    if (msg.type === "session_status") {
      setSessionAlive(msg.alive ?? false)
    } else if (msg.type === "system") {
      setMessages((prev) => [...prev, { role: "system", content: msg.data }])
      setSessionAlive(true)
    } else if (msg.type === "session_ended") {
      setSessionAlive(false)
      setIsThinking(false)
      setMessages((prev) => [...prev, { role: "system", content: "Session ended. Send a message to restart." }])
    } else if (msg.type === "backfill") {
      // Backfill from persistent session buffer — show as assistant context
      setMessages((prev) => {
        // Avoid duplicating backfill on reconnect
        if (prev.length === 0 || prev[prev.length - 1]?.role !== "assistant" || !prev[prev.length - 1]?.content?.includes("[session history]")) {
          return [...prev, { role: "assistant", content: `[session history]\n${msg.data}` }]
        }
        const updated = [...prev]
        const last = updated[updated.length - 1]
        updated[updated.length - 1] = { ...last, content: last.content + "\n" + msg.data }
        return updated
      })
    } else if (msg.type === "backfill_done") {
      // Backfill complete
    } else if (msg.type === "status" && msg.data === "thinking") {
      setIsThinking(true)
      streamingRef.current = ""
      setMessages((prev) => [...prev, { role: "assistant", content: "", streaming: true }])
    } else if (msg.type === "stream") {
      setIsThinking(false)
      streamingRef.current += msg.data + "\n"
      setMessages((prev) => {
        const updated = [...prev]
        const last = updated[updated.length - 1]
        if (last?.role === "assistant" && last.streaming) {
          updated[updated.length - 1] = { ...last, content: streamingRef.current.trim() }
        } else {
          // No streaming message yet — create one
          return [...prev, { role: "assistant", content: msg.data, streaming: true }]
        }
        return updated
      })
    } else if (msg.type === "done") {
      setIsThinking(false)
      setMessages((prev) => {
        const updated = [...prev]
        const last = updated[updated.length - 1]
        if (last?.role === "assistant") {
          updated[updated.length - 1] = { ...last, content: msg.data, streaming: false }
        }
        return updated
      })
    } else if (msg.type === "error") {
      setIsThinking(false)
      setMessages((prev) => [...prev, { role: "system", content: `Error: ${msg.data}` }])
    }
  }, [])

  const { send, connected } = useWebSocket("/ws/chat", { onMessage })

  // Auto-scroll
  useEffect(() => {
    messagesEndRef.current?.scrollIntoView({ behavior: "smooth" })
  }, [messages])

  const handleSend = () => {
    const text = input.trim()
    if (!text || isThinking) return
    setMessages((prev) => [...prev, { role: "user", content: text }])
    send({ action: "message", message: text })
    setInput("")
  }

  const handleRestart = () => {
    send({ action: "restart" })
    setMessages((prev) => [...prev, { role: "system", content: "Restarting session..." }])
  }

  return (
    <AppShell>
      <div className="flex h-[calc(100vh-90px)] flex-col">
        {/* Connection indicator (small, non-intrusive) */}
        {!connected && (
          <div className="mb-2 rounded-lg bg-warning/10 px-3 py-1.5 text-center text-xs text-warning">
            Connecting to session...
          </div>
        )}

        {/* Chat messages */}
        <div className="flex-1 space-y-4 overflow-y-auto pb-4">
          {messages.length === 0 && (
            <div className="flex h-full items-center justify-center">
              <div className="text-center">
                <p className="text-lg font-medium text-muted-foreground">Ask ApplyLoop anything</p>
                <p className="mt-1 text-sm text-muted-foreground/70">
                  &quot;Apply to ML roles at YC companies&quot; &middot; &quot;Show my queue&quot; &middot; &quot;Skip defense companies&quot;
                </p>
              </div>
            </div>
          )}
          {messages.map((message, i) => (
            <ChatBubble key={i} message={message} />
          ))}
          <div ref={messagesEndRef} />
        </div>

        {/* Input area */}
        <div className="border-t border-border pt-4">
          <div className="flex items-center gap-2 rounded-xl border border-border bg-card p-2">
            <input
              type="text"
              value={input}
              onChange={(e) => setInput(e.target.value)}
              onKeyDown={(e) => e.key === "Enter" && !e.shiftKey && handleSend()}
              placeholder="Ask ApplyLoop anything..."
              className="flex-1 bg-transparent px-2 text-sm text-foreground placeholder:text-muted-foreground focus:outline-none"
              disabled={isThinking}
            />
            <button
              onClick={handleSend}
              disabled={isThinking || !input.trim()}
              className="flex h-9 w-9 items-center justify-center rounded-lg bg-primary text-primary-foreground transition-colors hover:bg-primary/90 disabled:opacity-50"
            >
              {isThinking ? (
                <Loader2 className="h-4 w-4 animate-spin" />
              ) : (
                <Send className="h-4 w-4" />
              )}
              <span className="sr-only">Send message</span>
            </button>
          </div>
        </div>
      </div>
    </AppShell>
  )
}
