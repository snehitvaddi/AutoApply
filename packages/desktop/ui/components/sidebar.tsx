"use client"

import Link from "next/link"
import { usePathname } from "next/navigation"
import {
  LayoutDashboard,
  Columns3,
  Terminal,
  MessageSquare,
  User,
  ClipboardList,
} from "lucide-react"
import { cn } from "@/lib/utils"

const navItems = [
  { href: "/", icon: LayoutDashboard, label: "Dashboard" },
  { href: "/pipeline", icon: Columns3, label: "Pipeline" },
  { href: "/jobs", icon: ClipboardList, label: "Jobs List" },
  { href: "/terminal", icon: Terminal, label: "Terminal" },
  { href: "/chat", icon: MessageSquare, label: "Chat" },
  { href: "/settings", icon: User, label: "Settings" },
]

interface SidebarProps {
  workerRunning?: boolean
}

export function Sidebar({ workerRunning }: SidebarProps) {
  const pathname = usePathname()

  return (
    <aside className="fixed left-0 top-0 z-40 flex h-screen w-16 flex-col border-r border-border bg-sidebar">
      {/* Logo */}
      <div className="flex h-16 items-center justify-center border-b border-border">
        <span className="bg-gradient-to-r from-primary to-[#60a5fa] bg-clip-text text-lg font-bold text-transparent">
          AL
        </span>
      </div>

      {/* Navigation */}
      <nav className="flex flex-1 flex-col items-center gap-2 py-4">
        {navItems.map((item) => {
          const isActive = pathname === item.href
          return (
            <Link
              key={item.href}
              href={item.href}
              className={cn(
                "group relative flex h-10 w-10 items-center justify-center rounded-lg transition-colors",
                isActive
                  ? "bg-primary/10 text-primary"
                  : "text-muted-foreground hover:bg-secondary hover:text-foreground"
              )}
            >
              <item.icon className="h-5 w-5" />
              <span className="sr-only">{item.label}</span>
              {/* Tooltip */}
              <span className="absolute left-full ml-2 hidden whitespace-nowrap rounded-md bg-popover px-2 py-1 text-xs text-popover-foreground shadow-md group-hover:block">
                {item.label}
              </span>
            </Link>
          )
        })}
      </nav>

      {/* Bottom section */}
      <div className="flex flex-col items-center gap-3 border-t border-border py-4">
        <div className="flex flex-col items-center gap-1">
          <div
            className={cn(
              "h-2.5 w-2.5 rounded-full",
              workerRunning ? "animate-pulse bg-success" : "bg-muted-foreground"
            )}
          />
          <span className="text-[10px] text-muted-foreground">
            {workerRunning ? "Active" : "Idle"}
          </span>
        </div>
      </div>
    </aside>
  )
}
