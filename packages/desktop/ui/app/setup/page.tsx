"use client"

/**
 * First-run + ongoing setup wizard.
 *
 * v1.0.4: checklist-based. Calls /api/setup/status, which returns the
 * full preflight response (8 checks). Renders one row per check with
 * inline fix buttons:
 *   - Cloud data rows (profile/resume/preferences) → deep-link to
 *     Settings tabs via ?tab= query param
 *   - Local binary rows (claude_cli/openclaw_cli) → POST /api/setup/
 *     install-tool to kick off a background brew/npm install,
 *     streams the log, flips green on success
 *   - Token row → the existing activation-code input (shown full-width
 *     on the first step before everything else)
 *   - openclaw_gateway row → opens openclaw.com/pricing in the user's
 *     default browser
 *   - git row is optional and shown dimmed
 *
 * The page polls /api/setup/status every 3 seconds so when the user
 * completes a step in another tab (or finishes a background install)
 * the row auto-flips to green without manual refresh.
 *
 * The "Start ApplyLoop" button at the bottom is disabled until every
 * non-optional check is green. Click routes to / (dashboard).
 */
import { useState, useEffect, useCallback, useRef } from "react"
import { useRouter } from "next/navigation"
import {
  Loader2, CheckCircle2, XCircle, AlertTriangle, KeyRound, Rocket,
  Download, ExternalLink, User, FileText, Target, Terminal, Zap, Package,
} from "lucide-react"
import {
  activateWithCode, getSetupStatus, installTool, getInstallProgress,
  startBootstrap, getBootstrapStatus,
  type PreflightCheck, type SetupStatus, type InstallProgress,
  type BootstrapState,
} from "@/lib/api"

const CODE_PATTERN = /^AL-[A-Z0-9]{4}-[A-Z0-9]{4}$/

function formatCodeInput(raw: string): string {
  const cleaned = raw.toUpperCase().replace(/[^A-Z0-9-]/g, "")
  const compact = cleaned.replace(/-/g, "")
  let body = compact
  if (body.startsWith("AL")) body = body.slice(2)
  const seg1 = body.slice(0, 4)
  const seg2 = body.slice(4, 8)
  if (!seg1) return "AL-"
  if (!seg2) return `AL-${seg1}`
  return `AL-${seg1}-${seg2}`
}

// Icon per check id — keeps the checklist visually scannable.
const CHECK_ICONS: Record<string, typeof User> = {
  token: KeyRound,
  profile: User,
  resume: FileText,
  preferences: Target,
  claude_cli: Terminal,
  openclaw_cli: Package,
  openclaw_gateway: Zap,
  git: Download,
}

export default function SetupPage() {
  const router = useRouter()

  // Activation code state (shown on Step 1 only when no token yet)
  const [code, setCode] = useState("AL-")
  const [activating, setActivating] = useState(false)
  const [activationError, setActivationError] = useState<string | null>(null)
  const [activationSuccess, setActivationSuccess] = useState<{
    email?: string | null
    name?: string | null
  } | null>(null)

  // Full preflight state
  const [status, setStatus] = useState<SetupStatus | null>(null)
  const [checking, setChecking] = useState(true)

  // Per-tool install progress (keyed by tool name) — recovery path when
  // a single row's "Install" button is clicked manually after the
  // bootstrap chain finishes.
  const [installing, setInstalling] = useState<Record<string, InstallProgress>>({})
  const installTimersRef = useRef<Record<string, ReturnType<typeof setInterval>>>({})

  // Auto-install bootstrap state — kicks off after activation succeeds.
  // While running (or while needs_brew_terminal is true), the wizard
  // renders a single full-screen overlay instead of the per-row
  // checklist, so the user sees one progress view, not five.
  const [bootstrap, setBootstrap] = useState<BootstrapState | null>(null)
  const bootstrapPollRef = useRef<ReturnType<typeof setInterval> | null>(null)

  const pollBootstrapOnce = useCallback(async () => {
    try {
      const s = await getBootstrapStatus()
      setBootstrap(s)
      if (!s.running && !s.needs_brew_terminal) {
        if (bootstrapPollRef.current) {
          clearInterval(bootstrapPollRef.current)
          bootstrapPollRef.current = null
        }
        // Once the chain finishes, refresh the full preflight so the
        // per-row checklist reflects the new green state.
        setTimeout(() => loadStatusRef.current?.(), 500)
      }
    } catch {
      /* transient error — keep polling */
    }
  }, [])
  // Use a ref so the bootstrap poller can call the latest loadStatus
  // without recreating the callback every render.
  const loadStatusRef = useRef<(() => Promise<void>) | null>(null)

  const loadStatus = useCallback(async () => {
    try {
      const res = await getSetupStatus()
      setStatus(res)
    } catch {
      /* ignore transient errors */
    } finally {
      setChecking(false)
    }
  }, [])
  // Keep the ref in sync so the bootstrap poller (which doesn't re-run
  // on each loadStatus identity change) always calls the live version.
  useEffect(() => {
    loadStatusRef.current = loadStatus
  }, [loadStatus])

  const kickOffBootstrap = useCallback(async () => {
    try {
      const res = await startBootstrap()
      // nothing_to_do means the user already has every tool — skip the
      // overlay entirely so the checklist renders unobstructed.
      if (res.nothing_to_do) {
        return
      }
      // Begin polling — the overlay shows up the first time we see
      // running=true. Tear down on completion in pollBootstrapOnce.
      pollBootstrapOnce()
      if (bootstrapPollRef.current) clearInterval(bootstrapPollRef.current)
      bootstrapPollRef.current = setInterval(pollBootstrapOnce, 1000)
    } catch {
      /* transient — user can manually click per-row install as a fallback */
    }
  }, [pollBootstrapOnce])

  // Initial fetch + poll every 3s so checks auto-refresh as the user
  // completes steps elsewhere (Settings edits, background installs).
  useEffect(() => {
    loadStatus()
    const interval = setInterval(loadStatus, 3000)
    return () => clearInterval(interval)
  }, [loadStatus])

  // Clean up install progress pollers on unmount
  useEffect(() => {
    return () => {
      Object.values(installTimersRef.current).forEach((t) => clearInterval(t))
      if (bootstrapPollRef.current) clearInterval(bootstrapPollRef.current)
    }
  }, [])

  // On mount, peek at bootstrap state — if a previous session left a
  // chain running (user closed the window before it finished), resume
  // polling so the overlay reappears instead of dumping the user into
  // a half-installed checklist.
  useEffect(() => {
    let cancelled = false
    getBootstrapStatus()
      .then((s) => {
        if (cancelled) return
        if (s.running || s.needs_brew_terminal) {
          setBootstrap(s)
          if (bootstrapPollRef.current) clearInterval(bootstrapPollRef.current)
          bootstrapPollRef.current = setInterval(pollBootstrapOnce, 1000)
        }
      })
      .catch(() => { /* ignore */ })
    return () => { cancelled = true }
  }, [pollBootstrapOnce])

  // ── Activation code flow ──────────────────────────────────────────

  const onActivate = useCallback(async (e?: React.FormEvent) => {
    if (e) e.preventDefault()
    setActivationError(null)
    setActivating(true)
    try {
      const res = await activateWithCode(code)
      if (res.ok) {
        setActivationSuccess(res.user || null)
        // Let the checklist poll pick up the new token state on next tick
        setTimeout(loadStatus, 500)
        // Auto-bootstrap: install brew → node → openclaw + claude in
        // dependency order. The wizard renders an overlay while the
        // chain runs so the user doesn't have to click each install
        // button manually. Per Pujith's feedback after v1.0.6.
        kickOffBootstrap()
      } else {
        setActivationError(
          res.suggestion || res.message || "Activation failed — try again."
        )
      }
    } catch (err) {
      setActivationError(
        `Can't reach the ApplyLoop server: ${
          err instanceof Error ? err.message : String(err)
        }`
      )
    } finally {
      setActivating(false)
    }
  }, [code, loadStatus])

  // ── Install flow ──────────────────────────────────────────────────

  const startInstall = useCallback(async (tool: "claude" | "openclaw" | "git" | "brew") => {
    setInstalling((prev) => ({
      ...prev,
      [tool]: { ok: true, running: true, exit_code: null, last_lines: [], started: true },
    }))
    try {
      const res = await installTool(tool)
      if (!res.ok) {
        setInstalling((prev) => ({
          ...prev,
          [tool]: {
            ok: false, running: false, exit_code: 1,
            last_lines: [res.error || "install failed to start"],
            started: true,
          },
        }))
        return
      }
      // Poll install progress every 500ms until it stops running
      const poll = async () => {
        try {
          const p = await getInstallProgress(tool)
          setInstalling((prev) => ({ ...prev, [tool]: p }))
          if (!p.running) {
            clearInterval(installTimersRef.current[tool])
            delete installTimersRef.current[tool]
            // Refresh the overall status so the row flips green
            setTimeout(loadStatus, 500)
          }
        } catch {
          /* ignore transient errors */
        }
      }
      installTimersRef.current[tool] = setInterval(poll, 500)
      poll()
    } catch (err) {
      setInstalling((prev) => ({
        ...prev,
        [tool]: {
          ok: false, running: false, exit_code: 1,
          last_lines: [err instanceof Error ? err.message : String(err)],
          started: true,
        },
      }))
    }
  }, [loadStatus])

  // ── Derived state ─────────────────────────────────────────────────

  // Filter out checks the backend explicitly marked hidden — used today
  // for the OpenClaw Pro row when openclaw CLI isn't installed yet
  // (otherwise users see two consecutive rows about the same missing
  // tool, which Pujith found confusing on v1.0.6).
  const checks = (status?.checks || []).filter((c) => !c.hidden)
  const tokenCheck = checks.find((c) => c.id === "token")
  const hasToken = tokenCheck?.ok === true
  const otherChecks = checks.filter((c) => c.id !== "token")
  const blockingFailed = checks.filter((c) => !c.ok && !c.optional && c.id !== "token")
  const allReady = status?.setup_complete === true

  const goToSettings = (tab: string) => {
    router.push(`/settings?tab=${tab}`)
  }

  // ── Render ────────────────────────────────────────────────────────

  if (checking && !status) {
    return (
      <div className="flex min-h-screen items-center justify-center bg-background">
        <Loader2 className="h-6 w-6 animate-spin text-muted-foreground" />
      </div>
    )
  }

  // Bootstrap takes over the page while it's running. Once it finishes
  // (or short-circuits to nothing_to_do), we fall through to the normal
  // checklist render and the user finishes setup the usual way.
  if (bootstrap && (bootstrap.running || bootstrap.needs_brew_terminal)) {
    return <BootstrapOverlay state={bootstrap} />
  }

  return (
    <div className="flex min-h-screen items-center justify-center bg-background p-6">
      <div className="w-full max-w-2xl rounded-xl border border-border bg-card p-8 shadow-lg">
        {/* Logo */}
        <div className="mb-6 flex items-center justify-center">
          <span className="bg-gradient-to-r from-primary to-[#60a5fa] bg-clip-text text-3xl font-bold text-transparent">
            ApplyLoop
          </span>
        </div>

        {/* Step 1: Activation (full-width, shown when no token) */}
        {!hasToken && !activationSuccess && (
          <>
            <div className="mb-6 flex items-start gap-3 rounded-lg border border-border bg-secondary/30 p-3">
              <KeyRound className="h-4 w-4 flex-shrink-0 text-primary" />
              <div className="text-xs text-muted-foreground">
                <p className="font-medium text-foreground">Step 1 of 2 — Activate</p>
                <p className="mt-0.5">
                  Paste the activation code the admin sent you on Telegram or email.
                  We&apos;ll check the rest of your setup after that.
                </p>
              </div>
            </div>

            <form onSubmit={onActivate} className="space-y-4">
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

              {activationError && (
                <div className="flex items-start gap-2 rounded-lg border border-destructive/30 bg-destructive/5 p-3 text-xs text-destructive">
                  <AlertTriangle className="h-4 w-4 flex-shrink-0" />
                  <span>{activationError}</span>
                </div>
              )}

              <button
                type="submit"
                disabled={!CODE_PATTERN.test(code) || activating}
                className="flex w-full items-center justify-center gap-2 rounded-lg bg-primary px-4 py-3 text-sm font-medium text-primary-foreground transition-colors hover:bg-primary/90 disabled:cursor-not-allowed disabled:opacity-50"
              >
                {activating ? (
                  <>
                    <Loader2 className="h-4 w-4 animate-spin" />
                    Activating...
                  </>
                ) : (
                  "Activate"
                )}
              </button>
            </form>

            {/* Show the checklist below even when no token, so the user
                sees what's coming next. Local binaries can be installed
                in parallel with activation. */}
            <div className="mt-8 border-t border-border pt-6">
              <p className="mb-3 text-xs font-medium text-muted-foreground">
                Step 2 — these will be checked after activation
              </p>
              <ChecklistRows
                checks={otherChecks}
                installing={installing}
                onFix={(check) => handleFix(check, { goToSettings, startInstall })}
                disabled={true}
              />
            </div>
          </>
        )}

        {/* Activation just succeeded — brief celebration before the
            checklist re-renders with the token check flipped green */}
        {activationSuccess && !allReady && (
          <div className="mb-6 rounded-lg border border-success/30 bg-success/5 p-4">
            <div className="flex items-center gap-3">
              <CheckCircle2 className="h-5 w-5 text-success" />
              <div>
                <p className="text-sm font-semibold text-foreground">
                  Activated{activationSuccess.name ? `, ${activationSuccess.name}` : ""}!
                </p>
                <p className="text-xs text-muted-foreground">
                  Checking the rest of your setup...
                </p>
              </div>
            </div>
          </div>
        )}

        {/* Step 2: Full checklist (shown once token is present) */}
        {hasToken && (
          <>
            <div className="mb-6 flex items-start gap-3 rounded-lg border border-border bg-secondary/30 p-3">
              <Rocket className="h-4 w-4 flex-shrink-0 text-primary" />
              <div className="text-xs text-muted-foreground">
                <p className="font-medium text-foreground">Setup checklist</p>
                <p className="mt-0.5">
                  The apply loop will start automatically once every item below
                  is green. Rows refresh every 3 seconds.
                </p>
              </div>
            </div>

            <ChecklistRows
              checks={otherChecks}
              installing={installing}
              onFix={(check) => handleFix(check, { goToSettings, startInstall })}
            />

            {/* Bottom action row */}
            <div className="mt-8 flex items-center justify-between gap-3 border-t border-border pt-6">
              <div className="text-xs text-muted-foreground">
                {allReady ? (
                  <span className="text-success">
                    All set — you&apos;re ready to launch.
                  </span>
                ) : (
                  <span>
                    {blockingFailed.length} item{blockingFailed.length === 1 ? "" : "s"} remaining
                  </span>
                )}
              </div>
              <button
                onClick={() => router.push("/")}
                disabled={!allReady}
                className="flex items-center gap-2 rounded-lg bg-primary px-5 py-2.5 text-sm font-medium text-primary-foreground transition-colors hover:bg-primary/90 disabled:cursor-not-allowed disabled:opacity-40"
              >
                <Rocket className="h-4 w-4" />
                Start ApplyLoop
              </button>
            </div>
          </>
        )}
      </div>
    </div>
  )
}

// ── Bootstrap overlay ───────────────────────────────────────────────
//
// Single full-screen view that takes over /setup while the post-
// activation install chain is running. Shows a vertical stepper of the
// planned tools, a spinner on the current step, a checkmark on
// completed ones, and a tail of the live install log. If brew is
// missing, the chain spawns Terminal.app via osascript and shows a
// banner instructing the user to enter their password there — the
// wizard polls and resumes automatically once brew lands on PATH.

const BOOTSTRAP_LABELS: Record<string, string> = {
  brew: "Homebrew (package manager)",
  node: "Node.js + npm",
  openclaw: "OpenClaw CLI",
  claude: "Claude Code CLI",
}

function BootstrapOverlay({ state }: { state: BootstrapState }) {
  const completed = new Set(state.completed)
  return (
    <div className="flex min-h-screen items-center justify-center bg-background p-6">
      <div className="w-full max-w-2xl rounded-xl border border-border bg-card p-8 shadow-lg">
        <div className="mb-6 flex items-center justify-center">
          <span className="bg-gradient-to-r from-primary to-[#60a5fa] bg-clip-text text-3xl font-bold text-transparent">
            ApplyLoop
          </span>
        </div>

        <div className="mb-4 text-center">
          <h2 className="text-lg font-semibold text-foreground">
            Setting up your machine
          </h2>
          <p className="mt-1 text-sm text-muted-foreground">
            Installing the tools ApplyLoop needs to apply to jobs on your behalf.
            This is a one-time setup — usually under 5 minutes.
          </p>
        </div>

        {state.needs_brew_terminal && (
          <div className="mb-4 flex items-start gap-3 rounded-lg border border-amber-300 bg-amber-50 p-3 text-sm text-amber-900 dark:border-amber-700/50 dark:bg-amber-950/30 dark:text-amber-100">
            <Terminal className="h-4 w-4 flex-shrink-0 mt-0.5" />
            <div>
              <p className="font-medium">Terminal opened — please enter your password</p>
              <p className="mt-0.5 text-xs">
                Homebrew installation needs admin permission. Find the Terminal
                window we just opened, type your Mac password when prompted,
                and we&apos;ll continue automatically once it&apos;s done.
              </p>
            </div>
          </div>
        )}

        <ol className="mb-6 space-y-2.5">
          {state.plan.map((tool) => {
            const isDone = completed.has(tool)
            const isCurrent = state.current === tool
            return (
              <li key={tool} className="flex items-center gap-3 rounded-lg border border-border bg-secondary/20 p-3">
                <span className="flex h-6 w-6 items-center justify-center">
                  {isDone ? (
                    <CheckCircle2 className="h-5 w-5 text-emerald-500" />
                  ) : isCurrent ? (
                    <Loader2 className="h-5 w-5 animate-spin text-primary" />
                  ) : (
                    <span className="h-2.5 w-2.5 rounded-full border border-muted-foreground/50" />
                  )}
                </span>
                <span className={isCurrent ? "text-sm font-medium text-foreground" : "text-sm text-muted-foreground"}>
                  {BOOTSTRAP_LABELS[tool] || tool}
                </span>
              </li>
            )
          })}
        </ol>

        {state.failed && (
          <div className="mb-4 flex items-start gap-3 rounded-lg border border-destructive/50 bg-destructive/10 p-3 text-sm text-destructive">
            <XCircle className="h-4 w-4 flex-shrink-0 mt-0.5" />
            <div>
              <p className="font-medium">Failed during {BOOTSTRAP_LABELS[state.failed] || state.failed}</p>
              <p className="mt-0.5 text-xs opacity-90">
                Check the log below for details. You can manually install
                the missing tool and reload this page to continue.
              </p>
            </div>
          </div>
        )}

        {state.log_tail.length > 0 && (
          <div>
            <p className="mb-1.5 text-xs font-medium text-muted-foreground">Install log</p>
            <pre className="max-h-48 overflow-auto rounded-lg border border-border bg-secondary/30 p-3 text-[11px] leading-relaxed text-muted-foreground">
              {state.log_tail.join("\n")}
            </pre>
          </div>
        )}
      </div>
    </div>
  )
}

// ── Checklist row component ─────────────────────────────────────────

function ChecklistRows({
  checks,
  installing,
  onFix,
  disabled,
}: {
  checks: PreflightCheck[]
  installing: Record<string, InstallProgress>
  onFix: (check: PreflightCheck) => void
  disabled?: boolean
}) {
  return (
    <ul className="space-y-2">
      {checks.map((check) => {
        const Icon = CHECK_ICONS[check.id] || FileText
        const install = installing[check.id === "claude_cli" ? "claude" : check.id === "openclaw_cli" ? "openclaw" : check.id]
        const installRunning = install?.running === true
        return (
          <li
            key={check.id}
            className={`rounded-lg border p-3 transition-colors ${
              check.ok
                ? "border-success/30 bg-success/5"
                : check.optional
                ? "border-border bg-background opacity-60"
                : "border-border bg-background"
            }`}
          >
            <div className="flex items-center gap-3">
              {check.ok ? (
                <CheckCircle2 className="h-5 w-5 flex-shrink-0 text-success" />
              ) : check.optional ? (
                <AlertTriangle className="h-5 w-5 flex-shrink-0 text-muted-foreground" />
              ) : (
                <XCircle className="h-5 w-5 flex-shrink-0 text-muted-foreground" />
              )}
              <Icon className="h-4 w-4 flex-shrink-0 text-muted-foreground" />
              <div className="min-w-0 flex-1">
                <p className="truncate text-sm font-medium text-foreground">
                  {check.label}
                  {check.optional && (
                    <span className="ml-2 text-[10px] uppercase tracking-wider text-muted-foreground">
                      optional
                    </span>
                  )}
                </p>
                <p className="truncate text-xs text-muted-foreground" title={check.detail}>
                  {check.detail}
                </p>
              </div>
              {!check.ok && !disabled && check.remediation && (
                <FixButton
                  check={check}
                  running={installRunning}
                  onClick={() => onFix(check)}
                />
              )}
            </div>
            {/* Streaming install log — visible while a subprocess is
                running, collapses after success/failure. */}
            {install && (install.running || install.exit_code !== null) && (
              <div className="mt-2 ml-11">
                <pre className="max-h-32 overflow-auto rounded bg-gray-900 p-2 text-[10px] text-green-400 font-mono whitespace-pre-wrap">
{install.last_lines.slice(-8).join("\n") || (install.running ? "starting..." : "")}
                </pre>
                {!install.running && install.exit_code === 0 && (
                  <p className="mt-1 text-[10px] text-success">Install complete.</p>
                )}
                {!install.running && install.exit_code !== 0 && install.exit_code !== null && (
                  <p className="mt-1 text-[10px] text-destructive">
                    Install failed (exit {install.exit_code}). Check log above.
                  </p>
                )}
              </div>
            )}
          </li>
        )
      })}
    </ul>
  )
}

function FixButton({
  check,
  running,
  onClick,
}: {
  check: PreflightCheck
  running: boolean
  onClick: () => void
}) {
  if (running) {
    return (
      <span className="flex items-center gap-1.5 rounded-md border border-border bg-background px-3 py-1.5 text-xs font-medium text-muted-foreground">
        <Loader2 className="h-3 w-3 animate-spin" />
        Installing...
      </span>
    )
  }
  const r = check.remediation
  if (!r) return null

  let label: React.ReactNode = "Fix"
  if (r.type === "install") label = <><Download className="h-3 w-3" /> Install</>
  else if (r.type === "link") label = <><ExternalLink className="h-3 w-3" /> Subscribe</>
  else if (r.type === "route") label = "Fix →"

  return (
    <button
      onClick={onClick}
      className="flex items-center gap-1.5 rounded-md bg-primary px-3 py-1.5 text-xs font-medium text-primary-foreground transition-colors hover:bg-primary/90"
    >
      {label}
    </button>
  )
}

// ── Dispatch a "fix" click to the right side-effect ─────────────────

function handleFix(
  check: PreflightCheck,
  handlers: {
    goToSettings: (tab: string) => void
    startInstall: (tool: "claude" | "openclaw" | "git" | "brew") => void
  }
) {
  const r = check.remediation
  if (!r) return

  if (r.type === "route") {
    // /settings?tab=ai / /settings?tab=resume / /settings?tab=preferences
    const match = r.target.match(/tab=(\w+)/)
    if (match) {
      handlers.goToSettings(match[1])
    } else {
      // Direct path
      window.location.href = r.target
    }
  } else if (r.type === "install") {
    // Map check id → install tool name (they differ: claude_cli → claude)
    const toolMap: Record<string, "claude" | "openclaw" | "git" | "brew"> = {
      claude_cli: "claude",
      openclaw_cli: "openclaw",
      git: "git",
    }
    const tool = toolMap[check.id]
    if (tool) handlers.startInstall(tool)
  } else if (r.type === "link") {
    // Open in default browser via window.open
    window.open(r.target, "_blank", "noopener,noreferrer")
  }
}
