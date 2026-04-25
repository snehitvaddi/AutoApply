"use client"

import { useEffect, useState, useCallback } from "react"
import {
  getStats,
  getDailyBreakdown,
  getPlatformBreakdown,
  getRecentApplications,
  getWorkerStatus,
  type DashboardStats,
  type Application,
} from "@/lib/api"

export function useStats(pollInterval = 5000) {
  const [stats, setStats] = useState<DashboardStats | null>(null)
  const [daily, setDaily] = useState<{ date: string; submitted: number; failed: number }[]>([])
  const [platforms, setPlatforms] = useState<{ name: string; value: number }[]>([])
  const [recent, setRecent] = useState<Application[]>([])
  const [workerStatus, setWorkerStatus] = useState<{
    running: boolean;
    pid: number | null;
    uptime: number;
  } | null>(null)
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState<string | null>(null)

  const refresh = useCallback(async () => {
    try {
      const [statsRes, dailyRes, platRes, recentRes, workerRes] = await Promise.allSettled([
        getStats(),
        getDailyBreakdown(),
        getPlatformBreakdown(),
        getRecentApplications(10),
        getWorkerStatus(),
      ])
      if (statsRes.status === "fulfilled") setStats(statsRes.value.data)
      if (dailyRes.status === "fulfilled") setDaily(dailyRes.value.data)
      if (platRes.status === "fulfilled") setPlatforms(platRes.value.data)
      if (recentRes.status === "fulfilled") setRecent(recentRes.value.data)
      if (workerRes.status === "fulfilled") setWorkerStatus(workerRes.value)
      setError(null)
    } catch (e) {
      setError(e instanceof Error ? e.message : "Failed to fetch stats")
    } finally {
      setLoading(false)
    }
  }, [])

  useEffect(() => {
    refresh()
    const interval = setInterval(refresh, pollInterval)
    return () => clearInterval(interval)
  }, [refresh, pollInterval])

  return { stats, daily, platforms, recent, workerStatus, loading, error, refresh }
}
