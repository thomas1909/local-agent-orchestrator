"use client"

import { useEffect, useState } from "react"
import { api, type HealthResponse } from "@/lib/api"

export function useHealth(intervalMs = 30_000) {
  const [health, setHealth] = useState<HealthResponse | null>(null)
  const [offline, setOffline] = useState(false)

  useEffect(() => {
    let mounted = true
    async function check() {
      try {
        const h = await api.health()
        if (mounted) { setHealth(h); setOffline(false) }
      } catch {
        if (mounted) setOffline(true)
      }
    }
    check()
    const id = setInterval(check, intervalMs)
    return () => { mounted = false; clearInterval(id) }
  }, [intervalMs])

  return { health, offline }
}
