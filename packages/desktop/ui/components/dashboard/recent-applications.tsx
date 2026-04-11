import { cn } from "@/lib/utils"
import { Check, X, Loader2 } from "lucide-react"

interface ApplicationRow {
  company: string
  title?: string
  role?: string
  ats?: string
  platform?: string
  status: string
  applied_at?: string
  time?: string
  error?: string
}

function timeAgo(dateStr?: string): string {
  if (!dateStr) return ""
  const diff = Date.now() - new Date(dateStr).getTime()
  const mins = Math.floor(diff / 60000)
  if (mins < 1) return "now"
  if (mins < 60) return `${mins}m ago`
  const hours = Math.floor(mins / 60)
  if (hours < 24) return `${hours}h ago`
  return `${Math.floor(hours / 24)}d ago`
}

function StatusBadge({ status }: { status: string }) {
  return (
    <span
      className={cn(
        "inline-flex items-center gap-1 rounded-md px-2 py-0.5 text-xs font-medium",
        status === "submitted" && "bg-success/10 text-success",
        status === "failed" && "bg-destructive/10 text-destructive",
        status === "applying" && "bg-warning/10 text-warning"
      )}
    >
      {status === "submitted" && <Check className="h-3 w-3" />}
      {status === "failed" && <X className="h-3 w-3" />}
      {status === "applying" && <Loader2 className="h-3 w-3 animate-spin" />}
      {status === "submitted" && "Submitted"}
      {status === "failed" && "Failed"}
      {status === "applying" && "Applying"}
    </span>
  )
}

interface RecentApplicationsProps {
  applications?: ApplicationRow[]
}

export function RecentApplications({ applications: propApps }: RecentApplicationsProps) {
  const applications = propApps ?? []

  if (applications.length === 0) {
    return (
      <div className="flex h-32 items-center justify-center rounded-xl border border-border bg-card">
        <p className="text-sm text-muted-foreground">No applications yet. Connect your API token to see data.</p>
      </div>
    )
  }

  return (
    <div className="rounded-xl border border-border bg-card">
      <div className="border-b border-border px-5 py-4">
        <h3 className="text-sm font-medium text-card-foreground">
          Recent Applications
        </h3>
      </div>
      <div className="max-h-[400px] overflow-y-auto overflow-x-auto">
        <table className="w-full">
          <thead>
            <tr className="border-b border-border text-left text-xs text-muted-foreground">
              <th className="px-5 py-3 font-medium">Company</th>
              <th className="px-5 py-3 font-medium">Role</th>
              <th className="px-5 py-3 font-medium">Platform</th>
              <th className="px-5 py-3 font-medium">Status</th>
              <th className="px-5 py-3 font-medium">Applied</th>
            </tr>
          </thead>
          <tbody>
            {applications.map((app, i) => (
              <tr
                key={i}
                className="border-b border-border last:border-0 hover:bg-secondary/50"
              >
                <td className="px-5 py-3 text-sm font-medium text-card-foreground">
                  {app.company}
                </td>
                <td className="px-5 py-3 text-sm text-muted-foreground">
                  {app.title || app.role}
                </td>
                <td className="px-5 py-3">
                  <span className="rounded-md bg-secondary px-2 py-0.5 text-xs text-muted-foreground">
                    {app.ats || app.platform}
                  </span>
                </td>
                <td className="px-5 py-3">
                  <StatusBadge status={app.status} />
                </td>
                <td className="px-5 py-3 text-sm text-muted-foreground">
                  {app.time || timeAgo(app.applied_at)}
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </div>
  )
}
