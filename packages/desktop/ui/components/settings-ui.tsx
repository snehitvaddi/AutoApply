"use client"

/**
 * Settings UI primitives — <PageHeader>, <Section>, <FormRow>, <FieldLabel>,
 * <InlineHint>, <StatusBadge>, <InlineAction>, <SectionDivider>.
 *
 * Rationale for one file: every settings tab needs exactly this small set,
 * and they share typography + spacing tokens. Split by concern and import
 * once per tab. No shadcn replacement — just tightly composed helpers
 * that give every Settings screen the same hierarchy and breathing room.
 *
 * None of these change data flow. Every helper is presentational — the
 * tab continues to own state and API calls. Refactor targets (ProfilesTab,
 * Personal, Integrations, Worker & LLM, AI Import, Billing, Worker Token)
 * pass their existing inputs as children; we just give them a consistent
 * frame.
 */

import { type ReactNode, type HTMLAttributes } from "react"
import { cn } from "@/lib/utils"
import { Check, AlertCircle, Info } from "lucide-react"

// ── Page shell ───────────────────────────────────────────────────────

export function PageHeader({
  title, subtitle, actions, eyebrow,
}: {
  title: string
  subtitle?: string
  eyebrow?: string
  actions?: ReactNode
}) {
  return (
    <div className="flex items-start justify-between gap-4 pb-6 border-b border-border">
      <div className="min-w-0">
        {eyebrow && (
          <div className="text-[11px] font-medium uppercase tracking-wider text-muted-foreground mb-1">
            {eyebrow}
          </div>
        )}
        <h1 className="text-xl font-semibold tracking-tight text-foreground">
          {title}
        </h1>
        {subtitle && (
          <p className="text-sm text-muted-foreground mt-1 max-w-2xl">{subtitle}</p>
        )}
      </div>
      {actions && <div className="flex items-center gap-2 shrink-0">{actions}</div>}
    </div>
  )
}

// ── Section card ──────────────────────────────────────────────────────
// Consistent container for a grouped set of fields. Elevates visually
// above the page with border + subtle shadow, groups a title + optional
// description + content. Replaces the hand-rolled `rounded-xl border bg-card p-6`
// patterns scattered across ProfilesTab and settings/page.tsx.

export function Section({
  title, description, actions, children, className, tone = "default",
}: {
  title?: string
  description?: string
  actions?: ReactNode
  children: ReactNode
  className?: string
  tone?: "default" | "subtle" | "warning" | "danger"
}) {
  const toneClasses = {
    default: "border-border bg-card",
    subtle: "border-border bg-[var(--card-subtle)]",
    warning: "border-[var(--warning)]/30 bg-[var(--warning)]/5",
    danger: "border-[var(--destructive)]/30 bg-[var(--destructive-subtle)]",
  }[tone]

  return (
    <section
      className={cn(
        "rounded-lg border shadow-xs",
        toneClasses,
        className,
      )}
    >
      {(title || actions) && (
        <div className="flex items-start justify-between gap-4 px-5 py-4 border-b border-border/60">
          <div className="min-w-0">
            {title && (
              <h3 className="text-[15px] font-semibold text-foreground tracking-tight">
                {title}
              </h3>
            )}
            {description && (
              <p className="text-xs text-muted-foreground mt-1 max-w-xl leading-relaxed">
                {description}
              </p>
            )}
          </div>
          {actions && <div className="flex items-center gap-2 shrink-0">{actions}</div>}
        </div>
      )}
      <div className="p-5 space-y-4">{children}</div>
    </section>
  )
}

// ── Form row ──────────────────────────────────────────────────────────
// Consistent label + input + hint layout. Handles required marker, help
// text, error state, and optional trailing status (e.g. "Saved"). Does
// NOT own the actual input — caller renders any <input>/<select>/<textarea>
// etc. as children so data binding stays in the parent component.

export function FormRow({
  label, hint, required, error, status, children, orientation = "vertical", id,
}: {
  label?: string
  hint?: string
  required?: boolean
  error?: string
  status?: ReactNode
  children: ReactNode
  orientation?: "vertical" | "horizontal"
  id?: string
}) {
  if (orientation === "horizontal") {
    return (
      <div className="flex items-start gap-4">
        <div className="w-48 shrink-0 pt-1.5">
          {label && <FieldLabel htmlFor={id} required={required}>{label}</FieldLabel>}
          {hint && !error && (
            <p className="text-xs text-muted-foreground mt-1 leading-relaxed">{hint}</p>
          )}
        </div>
        <div className="flex-1 min-w-0">
          {children}
          {error && <p className="text-xs text-destructive mt-1.5">{error}</p>}
          {status && <div className="mt-1.5">{status}</div>}
        </div>
      </div>
    )
  }
  return (
    <div className="space-y-1.5">
      {(label || status) && (
        <div className="flex items-center justify-between gap-2">
          {label && <FieldLabel htmlFor={id} required={required}>{label}</FieldLabel>}
          {status && <div className="shrink-0">{status}</div>}
        </div>
      )}
      {children}
      {hint && !error && (
        <p className="text-xs text-muted-foreground leading-relaxed">{hint}</p>
      )}
      {error && <p className="text-xs text-destructive">{error}</p>}
    </div>
  )
}

// ── Field label ──────────────────────────────────────────────────────
// Tiny wrapper so every label gets the same weight/size/tracking and we
// render the required-asterisk consistently. Accepts htmlFor for a11y.

export function FieldLabel({
  htmlFor, required, children,
}: {
  htmlFor?: string
  required?: boolean
  children: ReactNode
}) {
  return (
    <label
      htmlFor={htmlFor}
      className="block text-[13px] font-medium text-foreground"
    >
      {children}
      {required && <span className="text-destructive ml-0.5">*</span>}
    </label>
  )
}

// ── Inline hint ──────────────────────────────────────────────────────
// Callout-style hint row for in-context help. Variants: info / warn / error.

export function InlineHint({
  children, variant = "info", className,
}: {
  children: ReactNode
  variant?: "info" | "warn" | "error"
  className?: string
}) {
  const variantClasses = {
    info: "bg-[var(--primary-subtle)] text-foreground border-primary/20",
    warn: "bg-[var(--warning)]/10 text-foreground border-[var(--warning)]/30",
    error: "bg-[var(--destructive-subtle)] text-foreground border-[var(--destructive)]/30",
  }[variant]
  const Icon = variant === "error" ? AlertCircle : variant === "warn" ? AlertCircle : Info
  return (
    <div
      className={cn(
        "flex items-start gap-2 rounded-md border px-3 py-2 text-xs leading-relaxed",
        variantClasses,
        className,
      )}
    >
      <Icon className="h-3.5 w-3.5 mt-0.5 shrink-0 opacity-80" />
      <div className="min-w-0 flex-1">{children}</div>
    </div>
  )
}

// ── Status badge ─────────────────────────────────────────────────────
// Compact saved/error/muted chip. Replaces scattered one-off status
// pills used across ProfilesTab (Saved ✓, Not set, etc.).

export function StatusBadge({
  children, variant = "neutral",
}: {
  children: ReactNode
  variant?: "neutral" | "success" | "warn" | "error"
}) {
  const variantClasses = {
    neutral: "bg-muted text-muted-foreground border-border",
    success: "bg-[var(--success-subtle)] text-[color:var(--success)] border-[var(--success)]/30",
    warn: "bg-[var(--warning)]/10 text-[color:var(--warning)] border-[var(--warning)]/30",
    error: "bg-[var(--destructive-subtle)] text-[color:var(--destructive)] border-[var(--destructive)]/30",
  }[variant]
  return (
    <span
      className={cn(
        "inline-flex items-center gap-1 rounded-md border px-1.5 py-0.5 text-[11px] font-medium",
        variantClasses,
      )}
    >
      {variant === "success" && <Check className="h-3 w-3" />}
      {children}
    </span>
  )
}

// ── Section divider ──────────────────────────────────────────────────
// Used inside a Section to separate sub-groups when a second nested
// Section would be too heavy.

export function SectionDivider({ label }: { label?: string }) {
  if (!label) return <div className="border-t border-border/60 my-2" />
  return (
    <div className="flex items-center gap-3 my-2">
      <div className="flex-1 border-t border-border/60" />
      <span className="text-[11px] font-medium uppercase tracking-wider text-muted-foreground">
        {label}
      </span>
      <div className="flex-1 border-t border-border/60" />
    </div>
  )
}

// ── Shared input class ───────────────────────────────────────────────
// Single source of truth for <input>/<select>/<textarea> styling. Import
// and spread via className on the caller's element to avoid owning the
// element itself (preserves data binding + refs in the parent).

export const fieldClass = cn(
  "w-full rounded-md border border-[var(--border-strong)] bg-background px-3 py-2",
  "text-[13px] text-foreground placeholder:text-muted-foreground",
  "shadow-xs transition-colors",
  "focus:outline-none focus:ring-2 focus:ring-primary/30 focus:border-primary",
  "disabled:opacity-60 disabled:cursor-not-allowed",
)

// ── Button class variants ────────────────────────────────────────────
// Reuse across tabs. Parent owns the <button>; we just give it consistent
// styling. Variants: primary / secondary / ghost / destructive.

export const buttonClass = {
  primary: cn(
    "inline-flex items-center justify-center gap-1.5 rounded-md",
    "bg-primary text-primary-foreground px-3.5 py-1.5 text-[13px] font-medium",
    "shadow-xs hover:bg-primary/90 active:bg-primary/80",
    "focus:outline-none focus:ring-2 focus:ring-primary/40 focus:ring-offset-2 focus:ring-offset-background",
    "disabled:opacity-50 disabled:cursor-not-allowed transition-colors",
  ),
  secondary: cn(
    "inline-flex items-center justify-center gap-1.5 rounded-md",
    "border border-border bg-card text-foreground px-3.5 py-1.5 text-[13px] font-medium",
    "hover:bg-secondary shadow-xs",
    "focus:outline-none focus:ring-2 focus:ring-primary/30",
    "disabled:opacity-50 disabled:cursor-not-allowed transition-colors",
  ),
  ghost: cn(
    "inline-flex items-center justify-center gap-1.5 rounded-md",
    "text-muted-foreground hover:text-foreground hover:bg-secondary px-2 py-1 text-[13px]",
    "focus:outline-none focus:ring-2 focus:ring-primary/30 transition-colors",
  ),
  destructive: cn(
    "inline-flex items-center justify-center gap-1.5 rounded-md",
    "text-muted-foreground hover:text-[color:var(--destructive)] hover:bg-[var(--destructive-subtle)]",
    "px-2 py-1 text-[13px] transition-colors",
    "focus:outline-none focus:ring-2 focus:ring-[var(--destructive)]/30",
  ),
}

// ── Inline action (add/remove row controls) ──────────────────────────
// Less visual weight than a proper button, for "+ Add", "+ Bullet", "×".

export function InlineAction({
  children, onClick, variant = "default", type = "button", ...props
}: {
  children: ReactNode
  onClick?: () => void
  variant?: "default" | "destructive"
} & Omit<HTMLAttributes<HTMLButtonElement>, "onClick"> & { type?: "button" | "submit" }) {
  return (
    <button
      type={type}
      onClick={onClick}
      className={variant === "destructive" ? buttonClass.destructive : buttonClass.ghost}
      {...props}
    >
      {children}
    </button>
  )
}
