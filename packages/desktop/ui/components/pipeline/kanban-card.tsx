import { cn } from "@/lib/utils"
import { Loader2 } from "lucide-react"

interface KanbanCardProps {
  company: string
  role: string
  platform: string
  posted: string
  variant?: "default" | "success" | "failed" | "applying"
  applyingMessage?: string
}

export function KanbanCard({
  company,
  role,
  platform,
  posted,
  variant = "default",
  applyingMessage,
}: KanbanCardProps) {
  return (
    <div
      className={cn(
        "rounded-lg border border-border bg-background p-3 transition-shadow hover:shadow-md",
        variant === "success" && "border-l-2 border-l-success",
        variant === "failed" && "border-l-2 border-l-destructive",
        variant === "applying" && "border-l-2 border-l-warning"
      )}
    >
      <p className="text-sm font-medium text-foreground">{company}</p>
      <p className="mt-0.5 text-xs text-muted-foreground">{role}</p>
      <div className="mt-2 flex items-center justify-between">
        {platform ? (
          <span className="rounded-md bg-secondary px-1.5 py-0.5 text-[10px] text-muted-foreground">
            {platform}
          </span>
        ) : <span />}
        <span className="text-[10px] text-muted-foreground">{posted}</span>
      </div>
      {variant === "applying" && applyingMessage && (
        <div className="mt-2 flex items-center gap-1.5 text-[10px] text-warning">
          <Loader2 className="h-3 w-3 animate-spin" />
          {applyingMessage}
        </div>
      )}
    </div>
  )
}
