"use client"

import { useState, useEffect, useRef, useCallback } from "react"
import { AppShell } from "@/components/app-shell"
import { Play, Square, RotateCcw, Wifi, WifiOff } from "lucide-react"
import { cn } from "@/lib/utils"

// WebSocket URL for the real PTY terminal
const WS_URL = typeof window !== "undefined"
  ? `${window.location.protocol === "https:" ? "wss:" : "ws:"}//${window.location.host}/ws/pty`
  : "ws://localhost:18790/ws/pty"

export default function TerminalPage() {
  const [connected, setConnected] = useState(false)
  const [sessionAlive, setSessionAlive] = useState(false)
  const termRef = useRef<HTMLDivElement>(null)
  const wsRef = useRef<WebSocket | null>(null)
  const xtermRef = useRef<unknown>(null)
  const fitAddonRef = useRef<unknown>(null)

  const connectWs = useCallback(() => {
    if (wsRef.current?.readyState === WebSocket.OPEN) return

    const ws = new WebSocket(WS_URL)
    ws.binaryType = "arraybuffer"
    wsRef.current = ws

    ws.onopen = () => {
      setConnected(true)
    }

    ws.onmessage = (event) => {
      if (typeof event.data === "string") {
        // JSON control message
        try {
          const msg = JSON.parse(event.data)
          if (msg.type === "status") {
            setSessionAlive(msg.alive)
          }
        } catch { /* not JSON */ }
      } else {
        // Binary PTY output → write to xterm
        const term = xtermRef.current as { write: (data: Uint8Array) => void } | null
        if (term) {
          term.write(new Uint8Array(event.data))
        }
      }
    }

    ws.onclose = () => {
      setConnected(false)
      // Auto-reconnect after 3s
      setTimeout(connectWs, 3000)
    }

    ws.onerror = () => ws.close()
  }, [])

  // Initialize xterm.js
  useEffect(() => {
    if (!termRef.current) return

    let term: unknown
    let fitAddon: unknown

    const initTerm = async () => {
      const { Terminal } = await import("xterm")
      const { FitAddon } = await import("@xterm/addon-fit")
      const { WebLinksAddon } = await import("@xterm/addon-web-links")

      term = new Terminal({
        cursorBlink: true,
        fontSize: 13,
        fontFamily: "'Geist Mono', 'SF Mono', 'Menlo', monospace",
        theme: {
          background: "#0d1117",
          foreground: "#c9d1d9",
          cursor: "#58a6ff",
          selectionBackground: "#3b82f640",
          black: "#0d1117",
          red: "#f85149",
          green: "#3fb950",
          yellow: "#d29922",
          blue: "#58a6ff",
          magenta: "#bc8cff",
          cyan: "#39d2c0",
          white: "#c9d1d9",
          brightBlack: "#484f58",
          brightRed: "#f85149",
          brightGreen: "#3fb950",
          brightYellow: "#d29922",
          brightBlue: "#58a6ff",
          brightMagenta: "#bc8cff",
          brightCyan: "#39d2c0",
          brightWhite: "#f0f6fc",
        },
        allowProposedApi: true,
      })

      fitAddon = new FitAddon()
      const webLinksAddon = new WebLinksAddon()

      const t = term as { loadAddon: (a: unknown) => void; open: (e: HTMLElement) => void; onData: (cb: (data: string) => void) => void; onResize: (cb: (size: { cols: number; rows: number }) => void) => void }
      t.loadAddon(fitAddon)
      t.loadAddon(webLinksAddon)
      t.open(termRef.current!)

      const fa = fitAddon as { fit: () => void }
      fa.fit()

      xtermRef.current = term
      fitAddonRef.current = fitAddon

      // Send keystrokes to PTY via WebSocket
      t.onData((data: string) => {
        const ws = wsRef.current
        if (ws?.readyState === WebSocket.OPEN) {
          ws.send(JSON.stringify({ type: "input", data }))
        }
      })

      // Send resize events
      t.onResize(({ cols, rows }: { cols: number; rows: number }) => {
        const ws = wsRef.current
        if (ws?.readyState === WebSocket.OPEN) {
          ws.send(JSON.stringify({ type: "resize", cols, rows }))
        }
      })

      // Connect WebSocket after terminal is ready
      connectWs()
    }

    initTerm()

    // Handle window resize
    const handleResize = () => {
      const fa = fitAddonRef.current as { fit: () => void } | null
      if (fa) fa.fit()
    }
    window.addEventListener("resize", handleResize)

    return () => {
      window.removeEventListener("resize", handleResize)
      const t = term as { dispose: () => void } | undefined
      if (t) t.dispose()
      wsRef.current?.close()
    }
  }, [connectWs])

  const handleStart = async () => {
    const ws = wsRef.current
    if (ws?.readyState === WebSocket.OPEN) {
      ws.send(JSON.stringify({ type: "start" }))
    } else {
      await fetch("/api/pty/start", { method: "POST" })
      connectWs()
    }
  }

  const handleStop = () => {
    const ws = wsRef.current
    if (ws?.readyState === WebSocket.OPEN) {
      ws.send(JSON.stringify({ type: "stop" }))
    }
  }

  const handleRestart = async () => {
    await fetch("/api/pty/restart", { method: "POST" })
    // Clear terminal
    const term = xtermRef.current as { clear: () => void } | null
    if (term) term.clear()
    connectWs()
  }

  return (
    <AppShell>
      <div className="flex h-[calc(100vh-48px)] flex-col gap-4">
        {/* Toolbar */}
        <div className="flex items-center justify-between rounded-xl border border-border bg-card px-4 py-3">
          <div className="flex items-center gap-2">
            <button
              onClick={handleStart}
              className={cn(
                "flex items-center gap-1.5 rounded-lg px-3 py-1.5 text-sm font-medium transition-colors",
                sessionAlive
                  ? "bg-success/10 text-success"
                  : "bg-success text-success-foreground hover:bg-success/90"
              )}
              disabled={sessionAlive}
            >
              <Play className="h-4 w-4" />
              {sessionAlive ? "Running" : "Start Session"}
            </button>
            <button
              onClick={handleStop}
              className={cn(
                "flex items-center gap-1.5 rounded-lg border px-3 py-1.5 text-sm font-medium transition-colors",
                sessionAlive
                  ? "border-destructive text-destructive hover:bg-destructive/10"
                  : "border-border text-muted-foreground"
              )}
              disabled={!sessionAlive}
            >
              <Square className="h-4 w-4" />
              Stop
            </button>
            <button
              onClick={handleRestart}
              className="flex items-center gap-1.5 rounded-lg border border-border px-3 py-1.5 text-sm font-medium text-muted-foreground transition-colors hover:bg-secondary hover:text-foreground"
            >
              <RotateCcw className="h-4 w-4" />
              Restart
            </button>
          </div>
          <div className="flex items-center gap-2 text-sm">
            {connected ? (
              <Wifi className="h-4 w-4 text-success" />
            ) : (
              <WifiOff className="h-4 w-4 text-destructive" />
            )}
            <span className="text-xs text-muted-foreground">
              {connected
                ? sessionAlive
                  ? "Session active"
                  : "Click Start Session"
                : "Connecting..."}
            </span>
          </div>
        </div>

        {/* xterm.js Terminal */}
        <div className="flex-1 overflow-hidden rounded-xl border border-border bg-[#0d1117]">
          <div className="flex h-8 items-center gap-2 border-b border-[#21262d] px-4">
            <div className="h-3 w-3 rounded-full bg-[#ff5f57]" />
            <div className="h-3 w-3 rounded-full bg-[#febc2e]" />
            <div className="h-3 w-3 rounded-full bg-[#28c840]" />
            <span className="ml-2 text-xs text-[#8b949e]">claude --dangerously-skip-permissions</span>
          </div>
          <div
            ref={termRef}
            className="h-[calc(100%-32px)] w-full"
            style={{ padding: "4px" }}
          />
        </div>
      </div>
    </AppShell>
  )
}
