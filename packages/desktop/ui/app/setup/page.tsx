"use client"

/**
 * First-run setup wizard.
 *
 * Shown automatically when the desktop server reports setup_complete=false.
 * User enters their activation code (AL-XXXX-XXXX) → we POST to /api/setup/activate
 * on the local server, which redeems with the cloud, saves the worker token,
 * downloads the default resume, and stashes profile.json. On success we redirect
 * to the main dashboard.
 */
import { useState, useEffect, useCallback } from "react"
import { useRouter } from "next/navigation"
import { Loader2, CheckCircle2, AlertTriangle, KeyRound } from "lucide-react"
import { activateWithCode, getSetupStatus } from "@/lib/api"

const CODE_PATTERN = /^AL-[A-Z0-9]{4}-[A-Z0-9]{4}$/

function formatCodeInput(raw: string): string {
  // Uppercase, strip anything that isn't alnum-or-dash.
  const cleaned = raw.toUpperCase().replace(/[^A-Z0-9-]/g, "")
  // Strip all dashes so we can re-insert them at the right spots.
  const compact = cleaned.replace(/-/g, "")
  // Prefix AL if the user didn't type it.
  let body = compact
  if (body.startsWith("AL")) body = body.slice(2)
  const seg1 = body.slice(0, 4)
  const seg2 = body.slice(4, 8)
  if (!seg1) return "AL-"
  if (!seg2) return `AL-${seg1}`
  return `AL-${seg1}-${seg2}`
}

export default function SetupPage() {
  const router = useRouter()
  const [code, setCode] = useState("AL-")
  const [loading, setLoading] = useState(false)
  const [checking, setChecking] = useState(true)
  const [error, setError] = useState<string | null>(null)
  const [success, setSuccess] = useState<{ email?: string | null; name?: string | null } | null>(
    null
  )

  // If we're already provisioned, bounce straight to the dashboard.
  useEffect(() => {
    let cancelled = false
    getSetupStatus()
      .then((res) => {
        if (cancelled) return
        if (res.setup_complete) {
          router.replace("/")
          return
        }
        setChecking(false)
      })
      .catch(() => {
        if (!cancelled) setChecking(false)
      })
    return () => {
      cancelled = true
    }
  }, [router])

  const onSubmit = useCallback(
    async (e?: React.FormEvent) => {
      if (e) e.preventDefault()
      setError(null)
      setLoading(true)
      try {
        const res = await activateWithCode(code)
        if (res.ok) {
          setSuccess(res.user || null)
          setTimeout(() => router.replace("/"), 1800)
        } else {
          setError(res.suggestion || res.message || "Activation failed — try again.")
        }
      } catch (err) {
        setError(
          `Can't reach the ApplyLoop server: ${err instanceof Error ? err.message : String(err)}`
        )
      } finally {
        setLoading(false)
      }
    },
    [code, router]
  )

  const isValid = CODE_PATTERN.test(code)

  if (checking) {
    return (
      <div className="flex min-h-screen items-center justify-center bg-background">
        <Loader2 className="h-6 w-6 animate-spin text-muted-foreground" />
      </div>
    )
  }

  if (success) {
    return (
      <div className="flex min-h-screen items-center justify-center bg-background p-6">
        <div className="w-full max-w-md rounded-xl border border-border bg-card p-8 text-center shadow-lg">
          <div className="mx-auto flex h-16 w-16 items-center justify-center rounded-full bg-success/10">
            <CheckCircle2 className="h-8 w-8 text-success" />
          </div>
          <h1 className="mt-4 text-xl font-semibold text-foreground">
            Welcome{success.name ? `, ${success.name}` : ""}!
          </h1>
          <p className="mt-2 text-sm text-muted-foreground">
            Activation successful. Loading your dashboard...
          </p>
        </div>
      </div>
    )
  }

  return (
    <div className="flex min-h-screen items-center justify-center bg-background p-6">
      <div className="w-full max-w-md rounded-xl border border-border bg-card p-8 shadow-lg">
        {/* Logo */}
        <div className="mb-6 flex items-center justify-center">
          <span className="bg-gradient-to-r from-primary to-[#60a5fa] bg-clip-text text-3xl font-bold text-transparent">
            ApplyLoop
          </span>
        </div>

        <div className="mb-6 flex items-start gap-3 rounded-lg border border-border bg-secondary/30 p-3">
          <KeyRound className="h-4 w-4 flex-shrink-0 text-primary" />
          <div className="text-xs text-muted-foreground">
            <p className="font-medium text-foreground">Welcome! One-time setup</p>
            <p className="mt-0.5">
              Paste the activation code the admin sent you on Telegram or email.
            </p>
          </div>
        </div>

        <form onSubmit={onSubmit} className="space-y-4">
          <div>
            <label className="mb-1 block text-xs font-medium text-muted-foreground">
              Activation code
            </label>
            <input
              value={code}
              onChange={(e) => setCode(formatCodeInput(e.target.value))}
              placeholder="AL-XXXX-XXXX"
              autoFocus
              spellCheck={false}
              autoComplete="off"
              className="w-full rounded-lg border border-border bg-background px-4 py-3 text-center font-mono text-lg tracking-widest text-foreground shadow-sm transition-colors focus:border-primary focus:outline-none focus:ring-2 focus:ring-primary/20"
            />
          </div>

          {error && (
            <div className="flex items-start gap-2 rounded-lg border border-destructive/30 bg-destructive/5 p-3 text-xs text-destructive">
              <AlertTriangle className="h-4 w-4 flex-shrink-0" />
              <span>{error}</span>
            </div>
          )}

          <button
            type="submit"
            disabled={!isValid || loading}
            className="flex w-full items-center justify-center gap-2 rounded-lg bg-primary px-4 py-3 text-sm font-medium text-primary-foreground transition-colors hover:bg-primary/90 disabled:cursor-not-allowed disabled:opacity-50"
          >
            {loading ? (
              <>
                <Loader2 className="h-4 w-4 animate-spin" />
                Activating...
              </>
            ) : (
              "Activate"
            )}
          </button>
        </form>

        <p className="mt-6 text-center text-xs text-muted-foreground">
          Don&apos;t have a code?{" "}
          <a
            href="https://applyloop.vercel.app/dashboard"
            target="_blank"
            rel="noopener noreferrer"
            className="text-primary hover:underline"
          >
            Check your dashboard
          </a>{" "}
          or ask the admin.
        </p>
      </div>
    </div>
  )
}
