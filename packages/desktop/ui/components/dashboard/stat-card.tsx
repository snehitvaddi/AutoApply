import { cn } from "@/lib/utils"
import { ArrowUp } from "lucide-react"

interface StatCardProps {
  title: string
  value: string
  badge?: {
    text: string
    variant: "success" | "warning" | "info"
  }
  trend?: "up" | "down"
  pulseDot?: boolean
  subtitle?: string
}

export function StatCard({ title, value, badge, trend, pulseDot, subtitle }: StatCardProps) {
  return (
    <div className="rounded-xl border border-border bg-card p-5">
      <p className="text-sm text-muted-foreground">{title}</p>
      <div className="mt-2 flex items-center gap-3">
        <span className="text-3xl font-semibold text-card-foreground">{value}</span>
        {badge && (
          <span
            className={cn(
              "rounded-md px-2 py-0.5 text-xs font-medium",
              badge.variant === "success" && "bg-success/10 text-success",
              badge.variant === "warning" && "bg-warning/10 text-warning",
              badge.variant === "info" && "bg-primary/10 text-primary"
            )}
          >
            {badge.text}
          </span>
        )}
        {pulseDot && (
          <span className="h-2 w-2 animate-pulse rounded-full bg-primary" />
        )}
        {trend === "up" && (
          <ArrowUp className="h-4 w-4 text-success" />
        )}
      </div>
      {subtitle && (
        <p className="mt-1 text-xs text-muted-foreground">{subtitle}</p>
      )}
    </div>
  )
}
