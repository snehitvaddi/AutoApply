"use client"

import { useState, useEffect, useRef, useCallback } from "react"
import { AppShell } from "@/components/app-shell"
import { Play, Square, RotateCcw, Wifi, WifiOff } from "lucide-react"
import { cn } from "@/lib/utils"
import type { Terminal as XTerm } from "xterm"
import type { FitAddon as XFitAddon } from "@xterm/addon-fit"
import "xterm/css/xterm.css"

const WS_URL = typeof window !== "undefined"
  ? `${window.location.protocol === "https:" ? "wss:" : "ws:"}//${window.location.host}/ws/pty`
  : "ws://localhost:18790/ws/pty"

export default function TerminalPage() {
  const [connected, setConnected] = useState(false)
  const [sessionAlive, setSessionAlive] = useState(false)
  const [initError, setInitError] = useState<string | null>(null)
  const [termEl, setTermEl] = useState<HTMLDivElement | null>(null)
  const wsRef = useRef<WebSocket | null>(null)
  const xtermRef = useRef<XTerm | null>(null)
  const fitAddonRef = useRef<XFitAddon | null>(null)
  const pendingWritesRef = useRef<Uint8Array[]>([])

  const connectWs = useCallback(() => {
    if (wsRef.current?.readyState === WebSocket.OPEN) return

    const ws = new WebSocket(WS_URL)
    ws.binaryType = "arraybuffer"
    wsRef.current = ws

    ws.onopen = () => setConnected(true)

    ws.onmessage = (event) => {
      if (typeof event.data === "string") {
        try {
          const msg = JSON.parse(event.data)
          if (msg.type === "status") setSessionAlive(msg.alive)
        } catch { /* not JSON */ }
      } else {
        const bytes = new Uint8Array(event.data)
        const term = xtermRef.current
        if (term) {
          term.write(bytes)
        } else {
          pendingWritesRef.current.push(bytes)
        }
      }
    }

    ws.onclose = () => {
      setConnected(false)
      setTimeout(connectWs, 3000)
    }

    ws.onerror = () => ws.close()
  }, [])

  useEffect(() => {
    connectWs()
    return () => {
      wsRef.current?.close()
    }
  }, [connectWs])

  useEffect(() => {
    if (!termEl) return

    let term: XTerm | null = null
    let fitAddon: XFitAddon | null = null
    let disposed = false

    const handleResize = () => {
      try { fitAddonRef.current?.fit() } catch { /* ignore */ }
    }
    window.addEventListener("resize", handleResize)
    const ro = new ResizeObserver(handleResize)
    ro.observe(termEl)

    const initTerm = async () => {
      try {
        const xtermMod = await import("xterm")
        const fitMod = await import("@xterm/addon-fit")
        const linksMod = await import("@xterm/addon-web-links")

        const TerminalCtor =
          (xtermMod as { Terminal?: new (opts: unknown) => XTerm }).Terminal ??
          (xtermMod as { default?: { Terminal?: new (opts: unknown) => XTerm } }).default?.Terminal
        const FitAddonCtor =
          (fitMod as { FitAddon?: new () => XFitAddon }).FitAddon ??
          (fitMod as { default?: { FitAddon?: new () => XFitAddon } }).default?.FitAddon
        const WebLinksAddonCtor =
          (linksMod as { WebLinksAddon?: new () => unknown }).WebLinksAddon ??
          (linksMod as { default?: { WebLinksAddon?: new () => unknown } }).default?.WebLinksAddon

        if (!TerminalCtor) throw new Error("xterm: Terminal export missing")
        if (!FitAddonCtor) throw new Error("@xterm/addon-fit: FitAddon export missing")
        if (disposed) return

        term = new TerminalCtor({
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

        fitAddon = new FitAddonCtor()
        term.loadAddon(fitAddon as unknown as Parameters<XTerm["loadAddon"]>[0])
        if (WebLinksAddonCtor) {
          term.loadAddon(new WebLinksAddonCtor() as unknown as Parameters<XTerm["loadAddon"]>[0])
        }
        term.open(termEl)

        requestAnimationFrame(() => {
          try { fitAddon?.fit() } catch (e) { console.error("[terminal] fit failed", e) }
        })

        xtermRef.current = term
        fitAddonRef.current = fitAddon

        if (pendingWritesRef.current.length > 0) {
          for (const chunk of pendingWritesRef.current) term.write(chunk)
          pendingWritesRef.current = []
        }

        term.onData((data: string) => {
          const ws = wsRef.current
          if (ws?.readyState === WebSocket.OPEN) {
            ws.send(JSON.stringify({ type: "input", data }))
          }
        })

        term.onResize(({ cols, rows }: { cols: number; rows: number }) => {
          const ws = wsRef.current
          if (ws?.readyState === WebSocket.OPEN) {
            ws.send(JSON.stringify({ type: "resize", cols, rows }))
          }
        })
      } catch (err) {
        const msg = err instanceof Error ? err.message : String(err)
        console.error("[terminal] xterm init failed", err)
        setInitError(msg)
      }
    }

    initTerm()

    return () => {
      disposed = true
      window.removeEventListener("resize", handleResize)
      ro.disconnect()
      try { term?.dispose() } catch { /* ignore */ }
      xtermRef.current = null
      fitAddonRef.current = null
    }
  }, [termEl])

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
    xtermRef.current?.clear()
    connectWs()
  }

  return (
    <AppShell>
      <div className="flex h-[calc(100vh-48px)] flex-col gap-4">
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
            {initError ? (
              <span className="text-xs text-destructive">xterm error: {initError}</span>
            ) : connected ? (
              <Wifi className="h-4 w-4 text-success" />
            ) : (
              <WifiOff className="h-4 w-4 text-destructive" />
            )}
            {!initError && (
              <span className="text-xs text-muted-foreground">
                {connected
                  ? sessionAlive
                    ? "Session active"
                    : "Click Start Session"
                  : "Connecting..."}
              </span>
            )}
          </div>
        </div>

        <div className="flex-1 overflow-hidden rounded-xl border border-border bg-[#0d1117]">
          <div className="flex h-8 items-center gap-2 border-b border-[#21262d] px-4">
            <div className="h-3 w-3 rounded-full bg-[#ff5f57]" />
            <div className="h-3 w-3 rounded-full bg-[#febc2e]" />
            <div className="h-3 w-3 rounded-full bg-[#28c840]" />
            <span className="ml-2 text-xs text-[#8b949e]">claude --dangerously-skip-permissions</span>
          </div>
          <div
            ref={setTermEl}
            className="h-[calc(100%-32px)] w-full"
            style={{ padding: "4px" }}
          />
        </div>
      </div>
    </AppShell>
  )
}
