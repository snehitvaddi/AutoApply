"use client"

import { useEffect, useRef, useState, useCallback } from "react"

// Derive WebSocket URL from the current page origin (same host as FastAPI)
const WS_BASE = typeof window !== "undefined"
  ? `${window.location.protocol === "https:" ? "wss:" : "ws:"}//${window.location.host}`
  : "ws://localhost:18790"

interface UseWebSocketOptions {
  onMessage?: (data: unknown) => void
  autoReconnect?: boolean
  reconnectInterval?: number
}

export function useWebSocket(path: string, options: UseWebSocketOptions = {}) {
  const { onMessage, autoReconnect = true, reconnectInterval = 3000 } = options
  const wsRef = useRef<WebSocket | null>(null)
  const [connected, setConnected] = useState(false)
  const reconnectTimer = useRef<ReturnType<typeof setTimeout> | null>(null)

  const connect = useCallback(() => {
    if (wsRef.current?.readyState === WebSocket.OPEN) return

    const ws = new WebSocket(`${WS_BASE}${path}`)
    wsRef.current = ws

    ws.onopen = () => setConnected(true)

    ws.onmessage = (event) => {
      try {
        const data = JSON.parse(event.data)
        onMessage?.(data)
      } catch {
        onMessage?.(event.data)
      }
    }

    ws.onclose = () => {
      setConnected(false)
      if (autoReconnect) {
        reconnectTimer.current = setTimeout(connect, reconnectInterval)
      }
    }

    ws.onerror = () => ws.close()
  }, [path, onMessage, autoReconnect, reconnectInterval])

  useEffect(() => {
    connect()
    return () => {
      if (reconnectTimer.current) clearTimeout(reconnectTimer.current)
      wsRef.current?.close()
    }
  }, [connect])

  const send = useCallback((data: unknown) => {
    if (wsRef.current?.readyState === WebSocket.OPEN) {
      wsRef.current.send(JSON.stringify(data))
    }
  }, [])

  return { connected, send, ws: wsRef }
}
