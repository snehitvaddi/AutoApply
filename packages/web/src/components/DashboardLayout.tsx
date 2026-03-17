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
  { href: "/setup-complete", label: "Setup", icon: "\u2B73", exact: true },
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
        <div className="p-6 border-b flex items-center justify-between">
          <h1 className="text-xl font-bold text-brand-600">ApplyLoop</h1>
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
        {/* Mobile header */}
        <div className="md:hidden flex items-center p-4 border-b bg-white">
          <button onClick={() => setSidebarOpen(true)} className="text-gray-600 text-xl mr-3">
            &#x2630;
          </button>
          <h1 className="text-lg font-bold text-brand-600">ApplyLoop</h1>
        </div>
        <main className="flex-1 p-8 overflow-auto">{children}</main>
      </div>
    </div>
  );
}
