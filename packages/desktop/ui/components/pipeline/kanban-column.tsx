import { cn } from "@/lib/utils"

interface KanbanColumnProps {
  title: string
  count: number
  variant: "gray" | "blue" | "amber" | "green" | "red"
  children: React.ReactNode
}

const variantStyles = {
  gray: "bg-muted/50 text-muted-foreground",
  blue: "bg-primary/10 text-primary",
  amber: "bg-warning/10 text-warning",
  green: "bg-success/10 text-success",
  red: "bg-destructive/10 text-destructive",
}

export function KanbanColumn({ title, count, variant, children }: KanbanColumnProps) {
  return (
    <div className="flex min-w-[240px] max-w-[360px] flex-1 flex-col rounded-xl bg-card">
      <div className="flex items-center justify-between border-b border-border px-3 py-3">
        <span className={cn("rounded-md px-2 py-0.5 text-xs font-medium", variantStyles[variant])}>
          {title}
        </span>
        <span className="text-xs text-muted-foreground">{count}</span>
      </div>
      <div className="flex flex-col gap-2 p-2">{children}</div>
    </div>
  )
}
