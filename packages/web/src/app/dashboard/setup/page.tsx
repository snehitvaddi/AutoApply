import { SetupCard } from "@/components/SetupCard";

/**
 * In-dashboard Setup tab. Inherits the DashboardLayout automatically via
 * the nested layout at `packages/web/src/app/dashboard/layout.tsx`, so the
 * sidebar + header stay visible — same chrome as /dashboard/settings.
 *
 * This is what the "Setup" link in the sidebar points to (after commit
 * `2d4e2a8` → new). Returning users can re-open it any time to copy their
 * activation code or reinstall the desktop app.
 *
 * The body is the shared <SetupCard /> component (also rendered full-bleed
 * at /setup-complete after signup).
 */
export default function DashboardSetupPage() {
  return (
    <div className="max-w-3xl">
      <h1 className="text-2xl font-bold mb-6">Setup</h1>
      <SetupCard variant="inline" />
    </div>
  );
}
