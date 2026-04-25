"use client";

import Link from "next/link";
import { usePathname, useRouter } from "next/navigation";
import { useState, useEffect } from "react";
import { createBrowserClient } from "@supabase/ssr";

const supabase = createBrowserClient(
  process.env.NEXT_PUBLIC_SUPABASE_URL!,
  process.env.NEXT_PUBLIC_SUPABASE_ANON_KEY!
);

const NAV_ITEMS = [
  { href: "/dashboard", label: "Overview", icon: "\u2302", exact: true },
  { href: "/dashboard/jobs", label: "Jobs", icon: "\u2609", exact: false },
  { href: "/dashboard/applications", label: "Applications", icon: "\u2611", exact: false },
  { href: "/dashboard/settings", label: "Settings", icon: "\u2699", exact: false },
  // NB: /dashboard/setup (not /setup-complete) so it inherits DashboardLayout
  // and the sidebar stays visible. /setup-complete is still the post-signup
  // full-bleed landing page; both render the shared SetupCard component.
  { href: "/dashboard/setup", label: "Setup", icon: "\u2B73", exact: true },
];

export default function DashboardLayout({ children }: { children: React.ReactNode }) {
  const pathname = usePathname();
  const router = useRouter();
  const [sidebarOpen, setSidebarOpen] = useState(false);
  const [userEmail, setUserEmail] = useState("");
  const [isAdmin, setIsAdmin] = useState(false);

  useEffect(() => {
    supabase.auth.getUser().then(({ data: { user } }) => {
      if (user) {
        setUserEmail(user.email || "");
        supabase.from("users").select("is_admin").eq("id", user.id).single()
          .then(({ data }) => { if (data?.is_admin) setIsAdmin(true); });
      }
    });
  }, []);

  async function handleSignOut() {
    await supabase.auth.signOut();
    router.push("/auth/login");
  }

  function isActive(href: string, exact: boolean) {
    return exact ? pathname === href : pathname.startsWith(href);
  }

  return (
    <div className="min-h-screen flex">
      {/* Mobile overlay */}
      {sidebarOpen && (
        <div className="fixed inset-0 bg-black/30 z-40 md:hidden" onClick={() => setSidebarOpen(false)} />
      )}

      {/* Sidebar */}
      <aside className={`
        fixed md:static inset-y-0 left-0 z-50 w-64 bg-white border-r flex flex-col
        transform transition-transform md:translate-x-0
        ${sidebarOpen ? "translate-x-0" : "-translate-x-full"}
      `}>
        {/* Brand header — matches the desktop app sidebar, the favicon,
            the OG card, and the macOS Dock icon. Blue gradient rounded
            square + "AL" monogram + wordmark. One visual identity across
            every ApplyLoop surface. */}
        <div className="p-5 border-b flex items-center justify-between">
          <Link href="/dashboard" className="flex items-center gap-2.5 group">
            <div
              className="w-9 h-9 rounded-xl flex items-center justify-center shadow-sm group-hover:shadow-md transition-shadow"
              style={{ background: "linear-gradient(135deg, #6366f1 0%, #4f46e5 100%)" }}
            >
              <span className="text-white font-bold text-[12px] tracking-tight">AL</span>
            </div>
            <h1 className="text-xl font-bold text-gray-900">ApplyLoop</h1>
          </Link>
          <button className="md:hidden text-gray-400" onClick={() => setSidebarOpen(false)}>
            &#x2715;
          </button>
        </div>
        <nav className="flex-1 p-4 space-y-1">
          {NAV_ITEMS.map(({ href, label, icon, exact }) => (
            <Link
              key={href}
              href={href}
              onClick={() => setSidebarOpen(false)}
              className={`flex items-center gap-3 px-3 py-2 rounded-lg text-sm font-medium ${
                isActive(href, exact)
                  ? "bg-brand-50 text-brand-700"
                  : "text-gray-600 hover:bg-gray-50"
              }`}
            >
              <span className="w-6 h-6 flex items-center justify-center text-base">{icon}</span>
              {label}
            </Link>
          ))}
          {isAdmin && (
            <Link
              href="/admin"
              onClick={() => setSidebarOpen(false)}
              className={`flex items-center gap-3 px-3 py-2 rounded-lg text-sm font-medium ${
                pathname.startsWith("/admin")
                  ? "bg-brand-50 text-brand-700"
                  : "text-gray-600 hover:bg-gray-50"
              }`}
            >
              <span className="w-6 h-6 flex items-center justify-center text-base">&#x2630;</span>
              Admin
            </Link>
          )}
        </nav>
        <div className="p-4 border-t">
          <p className="text-xs text-gray-500 truncate mb-2">{userEmail}</p>
          <button
            onClick={handleSignOut}
            className="w-full text-left text-xs text-red-500 hover:text-red-700"
          >
            Sign out
          </button>
        </div>
      </aside>

      {/* Main content */}
      <div className="flex-1 flex flex-col min-w-0">
        {/* Mobile header — same brand mark as the desktop sidebar */}
        <div className="md:hidden flex items-center p-4 border-b bg-white gap-3">
          <button onClick={() => setSidebarOpen(true)} className="text-gray-600 text-xl">
            &#x2630;
          </button>
          <div
            className="w-7 h-7 rounded-lg flex items-center justify-center"
            style={{ background: "linear-gradient(135deg, #6366f1 0%, #4f46e5 100%)" }}
          >
            <span className="text-white font-bold text-[10px] tracking-tight">AL</span>
          </div>
          <h1 className="text-lg font-bold text-gray-900">ApplyLoop</h1>
        </div>
        <main className="flex-1 p-8 overflow-auto">{children}</main>
      </div>
    </div>
  );
}
